"""需求 2：按规则批量改名（先预览确认，重名冲突绝不覆盖）。"""
import os
import sys
from pathlib import Path

from .journal import append_log
from .report import build_report
from .utils import LOG_FILE, confirm, fname_key, iter_files, match_ext


def parse_fields(spec: str) -> list:
    """把 '3,1' 解析成从 0 开始的字段序号列表，如 [2, 0]。"""
    tokens = [t.strip() for t in (spec or "").split(",") if t.strip()]
    if not tokens:                          # 空串、全空（如 ",,"）都直接报错
        raise SystemExit("[错误] --fields 至少需要一个字段序号")
    idx = []
    for token in tokens:
        try:
            num = int(token)
        except ValueError:
            raise SystemExit(f"[错误] --fields 只能是正整数序号，收到：{token!r}")
        if num < 1:
            raise SystemExit(f"[错误] --fields 只能是正整数序号，收到：{token!r}")
        idx.append(num - 1)
    return idx


def new_name_from_fields(name: str, idx: list, sep: str) -> str:
    """
    字段重排：把 '学号_姓名_作业名.pdf' 按 idx 重排成 '作业名_学号.pdf'。

    例：name='2023001_张三_线性代数.pdf', sep='_', idx=[2,0]
        → 主名 '2023001_张三_线性代数'.split('_') = ['2023001','张三','线性代数']
        → 取第 3、第 1 段 → '线性代数_2023001'，再拼回扩展名 '.pdf'
    """
    p = Path(name)
    parts = p.stem.split(sep)                    # 只对「去掉扩展名的主名」切分
    if any(i < 0 or i >= len(parts) for i in idx):
        raise ValueError(f"字段序号越界（'{name}' 只有 {len(parts)} 段）")
    return sep.join(parts[i] for i in idx) + p.suffix   # 重排后拼回原扩展名


def plan_rename(root: Path, files, idx: list, sep: str) -> list:
    """
    计算改名计划（不动文件）。返回 [{from,to,status,reason}]。

    防重名 / 防覆盖的关键：
      1) 先把目录里「所有现有文件名」+ 日志文件登记进 occupied 占用集合；
      2) 每确定一个新名字，也立刻加入 occupied；
      3) 后续任何文件的新名字一旦撞进 occupied，就跳过、绝不覆盖。
    同时防止撞上已有文件以及两个源文件改出同一个名字的情况。
    """
    def skip(src, reason: str, to: str = "") -> None:
        plans.append({"from": src.name, "to": to, "status": "skipped", "reason": reason})

    occupied = {fname_key(p.name) for p in iter_files(root)}  # 现有文件全登记为占用
    occupied.add(fname_key(LOG_FILE))             # 日志文件本身也不许被覆盖
    plans = []
    for src in files:                              # files 已按名字排序，保证结果稳定
        try:
            new_name = new_name_from_fields(src.name, idx, sep)
        except ValueError as e:                    # 规则不匹配（如字段越界）→ 跳过
            skip(src, str(e))
            continue
        key = fname_key(new_name)                  # 只算一次，复用
        if key == fname_key(src.name):             # 新名 = 原名
            skip(src, "新名字与原名字相同", new_name)
            continue
        if key in occupied:                        # 重名冲突则跳过
            skip(src, f"重名冲突：{new_name}", new_name)
            continue
        occupied.add(key)                          # 登记新名，防止后续再撞
        plans.append({"from": src.name, "to": new_name,
                      "status": "renamed", "reason": ""})
    return plans


def apply_rename(root: Path, plans: list) -> None:
    """
    执行改名（就地更新 plans）：成功的保持 'renamed'，失败的改为 'skipped' 并带原因。
    调用方按 plans 的最终状态写日志，undo 才不会去还原未发生的改名。
    """
    for p in plans:
        if p["status"] != "renamed":
            continue
        try:
            os.replace(root / p["from"], root / p["to"])
        except OSError as e:
            p["status"] = "skipped"
            p["reason"] = f"改名失败：{e}"


def cmd_rename(args) -> int:
    """
    批量改名：学号_姓名_作业名 → 作业名_学号（默认 --fields 3,1）。
    """
    root = Path(args.path).expanduser()
    if not root.is_dir():
        print(f"[错误] 目录不存在：{root}", file=sys.stderr)
        return 1
    if not args.split:
        print("[错误] --split 不能为空字符串", file=sys.stderr)
        return 1

    exts = [e for tok in (args.ext or []) for e in tok.replace(",", " ").split() if e.strip()]
    files = [f for f in iter_files(root) if match_ext(f.name, exts)]
    idx = parse_fields(args.fields)
    plans = plan_rename(root, files, idx, args.split)

    # ---- 1) 打印预览（先打印，绝不直接改） ----
    renamed = [p for p in plans if p["status"] == "renamed"]
    skipped = [p for p in plans if p["status"] == "skipped"]
    lines = []
    if renamed:
        lines.append("将要改名的文件：")
        lines += [f"  {p['from']}  →  {p['to']}" for p in renamed]
    if skipped:
        lines.append("\n将跳过的文件：")
        lines += [f"  {p['from']}  ({p['reason']})" for p in skipped]
    if lines:
        print("\n".join(lines))
    if not renamed:
        print("没有需要改名的文件。")
        return 0

    # ---- 2) input() 等待确认 ----
    if not confirm("确认执行以上改名？"):
        print("已取消，未做任何修改。")
        return 0

    # ---- 3) 确认后才执行，并写入日志 ----
    apply_rename(root, plans)
    items = [
        {"action": "rename", "status": "done", "from": p["from"], "to": p["to"]}
        if p["status"] == "renamed" else
        {"action": "rename", "status": "skipped", "from": p["from"],
         "to": "", "reason": p["reason"]}
        for p in plans
    ]
    append_log(root, "rename", items)     # 记录日志，undo 才能还原
    print()
    print(build_report("rename", root, items))
    return 0
