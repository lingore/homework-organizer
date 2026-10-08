#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
子命令：
  scan    扫描目录、列出文件（大小 / 修改时间），支持按扩展名过滤
  rename  按规则批量改名（先打印预览，确认后才执行，自动处理重名冲突）
  archive 按学期 / 类别把文件移动到子目录，并生成整理报告
  report  查看整理报告（处理 / 跳过统计）
  undo    撤销上一次操作
示例：
  python homework_organizer.py scan   ./作业 --ext .pdf .docx
  python homework_organizer.py rename ./作业 --fields 3,1
  python homework_organizer.py archive ./作业 --by semester
"""
import argparse
import json
import os
import shutil
import stat       # cmd_scan 用 stat.S_ISREG 判断普通文件
import sys
from datetime import datetime
from pathlib import Path

# 让 Windows 控制台也以 UTF-8 读写，避免中文乱码
for _stream in (sys.stdout, sys.stderr, sys.stdin):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

# 整理日志文件名
LOG_FILE = ".organizer_log.json"

VERSION = "1.0.0"

# ============================================================
# 通用工具函数
# ============================================================

def human_readable_size(n) -> str:
    """
    将字节数转换为可读大小。
    """
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"

def human_time(ts: float) -> str:
    """
    把时间戳转成 'YYYY-MM-DD HH:MM:SS'，方便使用者阅读。
    """
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

def ext_of(name: str) -> str:
    """
    取文件扩展名（小写、带点），如 '.PDF' → '.pdf'；无扩展名返回 ''。
    '.gitignore' 这类隐藏文件同样会被视为无扩展名，返回 ''。
    """
    return Path(name).suffix.lower()

def norm_ext_token(token: str) -> str:
    """
    把用户传入的扩展名过滤项统一成小写带点：'pdf'/'.pdf'/'.PDF' → '.pdf'。
    """
    token = (token or "").strip().lower()
    if not token:
        return ""
    return token if token.startswith(".") else "." + token

def match_ext(name: str, exts) -> bool:
    """
    判断文件名是否命中扩展名过滤列表；exts 为空表示不过滤。
    """
    if not exts:
        return True
    wanted = {norm_ext_token(e) for e in exts}   # 把过滤项也统一成 '.pdf' 形式
    return ext_of(name) in wanted

def fname_key(name: str) -> str:
    """
    统一小写后比较。
    """
    return name.lower()

def iter_files(root: Path) -> list[Path]:
    """
    列出目录下所有普通文件（跳过日志文件），按文件名排序保证输出稳定。
    排序依据为字符串。
    """
    files = [p for p in root.iterdir() if p.is_file() and p.name != LOG_FILE]
    return sorted(files, key=lambda p: p.name)

def confirm(prompt: str) -> bool:
    """
    打印提示并用 input() 等待用户输入；输入 y / yes 才返回 True。
    直接回车、输入其他字符、EOF、Ctrl+C 均视为 False。
    """
    try:
        answer = input(f"{prompt} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        # 非交互环境（无输入）或 Ctrl+C 时，默认视为「不确认」，保证安全
        answer = ""
    return answer in ("y", "yes")

# ============================================================
# 整理日志（供 report / undo 使用）
# ============================================================

def _now_str() -> str:
    """
    当前时间字符串（日志时间戳 / 报告时间共用）。
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _backup_bad_log(fp: Path) -> None:
    """
    把损坏的日志改名备份，避免 append_log 覆盖后丢失历史。
    """
    try:
        fp.replace(fp.with_name(f"{fp.name}.bad-{_now_str().replace(':', '-')}"))
    except OSError:
        pass


def load_log(root: Path) -> list[dict]:
    """
    读取整理日志；日志不存在或损坏时返回空列表，绝不因日志问题崩溃。
    """
    fp = root / LOG_FILE
    if not fp.is_file():
        return []
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        # 手工编辑后的日志可能有缺字段的条目，过滤掉，保证 report/undo 不崩
        return [op for op in data if isinstance(op, dict) and isinstance(op.get("items"), list)]
    except (OSError, ValueError):      # UnicodeDecodeError / JSONDecodeError 都是 ValueError
        _backup_bad_log(fp)            # 损坏时不静默覆盖：先改名备份
        return []


def save_log(root: Path, ops: list[dict]) -> None:
    """
    把日志原子写回磁盘：先写临时文件再 os.replace，避免写一半损坏。
    """
    fp = root / LOG_FILE
    tmp = fp.with_name(fp.name + ".tmp")
    tmp.write_text(json.dumps(ops, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    os.replace(tmp, fp)                # 同卷原子替换


def append_log(root: Path, command: str, items: list[dict]) -> None:
    """
    向日志追加一条操作记录；日志写入失败只告警，不影响主流程。
    """
    ops = load_log(root)
    ops.append({
        "time": _now_str(),
        "command": command,
        "items": items,
    })
    try:
        save_log(root, ops)
    except OSError as e:
        print(f"[警告] 日志写入失败，report/undo 将不可用：{e}", file=sys.stderr)


def build_report(command: str, root: Path, items: list[dict], when: str = "") -> str:
    """
    根据一次操作的结果生成报告文本（成功 / 跳过数量 + 跳过原因）。
    """
    counts = {"done": 0, "skipped": 0, "other": 0}
    skipped = []
    for i in items:
        st = i.get("status")
        counts[st if st in counts else "other"] += 1
        if st == "skipped":
            skipped.append(i)
    sep = "=" * 56
    lines = [
        sep,
        "整理报告",
        sep,
        f"操作 : {command}",
        f"时间 : {when or _now_str()}",
        f"目录 : {root}",
        "-" * 56,
        f"成功 : {counts['done']} 个",
        f"跳过 : {counts['skipped']} 个",
    ]
    if counts["other"]:
        lines.append(f"其他 : {counts['other']} 个")
    lines.append(f"合计 : {len(items)} 个")
    if skipped:
        lines.append("跳过原因：")
        for i in skipped:
            lines.append(f"  - {i['from']}：{i['reason']}")
    lines.append(sep)
    return "\n".join(lines)

# 需求 1：扫描并列出

def cmd_scan(args) -> int:
    """
    扫描目录，列出文件（名称 / 大小 / 修改时间），支持 --ext 扩展名过滤。
    """
    root = Path(args.path).expanduser()          # 支持 ~ 展开到家目录
    if not root.is_dir():                        # 路径检查：目录不存在则报错返回
        print(f"[错误] 目录不存在：{root}", file=sys.stderr)
        return 1
    # 扩展名统一成 '.pdf' 形式再比较；逗号 / 空格两种写法都支持
    wanted = {norm_ext_token(e)
              for tok in (args.ext or []) for e in tok.replace(",", " ").split()
              if e.strip()}
    rows, total, bad = [], 0, 0
    try:
        entries = sorted(root.iterdir(), key=lambda p: p.name.lower())
    except OSError as e:                         # 目录本身不可读
        print(f"[错误] 无法读取目录：{e}", file=sys.stderr)
        return 1
    for f in entries:
        if f.name == LOG_FILE or (wanted and ext_of(f.name) not in wanted):
            continue
        try:
            st = f.stat()
        except OSError:                          # 权限不足 / 文件刚被删,记数跳过
            bad += 1
            continue
        if not stat.S_ISREG(st.st_mode):         # 用已取到的 stat 判断，省一次系统调用
            continue
        rows.append((f.name, human_readable_size(st.st_size), human_time(st.st_mtime)))
        total += st.st_size
    # 收集输出、一次打印：文件多时减少 print 调用开销
    out = [f"扫描文件夹: {root}"]
    if args.ext:
        out.append(f"扩展名过滤: {' '.join(args.ext)}")
    out.append(f"符合条件: {len(rows)} 个文件")
    out.append("-" * 70)
    out += [f"  {name}  |  {size:>10}  |  {mtime}" for name, size, mtime in rows]
    out.append("-" * 70)
    if not rows:
        out.append("  (没有符合条件的文件)")
    if bad:
        out.append(f"  （另有 {bad} 个文件因权限等原因无法读取）")
    out.append(f"总计 {human_readable_size(total)}")
    print("\n".join(out))
    return 0

# 需求 2：批量改名

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

# 需求 3：归档、报告、撤销

def semester_of(ts: float) -> str:
    """按修改时间推断学期：1-6 月为春、7-12 月为秋，如 '2024-春'。"""
    dt = datetime.fromtimestamp(ts)
    return f"{dt.year}-{'春' if dt.month <= 6 else '秋'}"


def parse_keyword_map(text: str) -> dict:
    """解析 '关键词=目录;关键词2=目录2'，如 '数学=Math;英语=English'。"""
    mapping = {}
    for part in (text or "").split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise SystemExit(f"[错误] --keyword-map 格式应为 '关键词=目录;...'，收到：{part!r}")
        key, val = part.split("=", 1)
        key, val = key.strip(), val.strip()
        if key and val:
            mapping[key] = val
    if not mapping:
        raise SystemExit("[错误] --keyword-map 为空。")
    return mapping


def safe_folder(name: str) -> bool:
    """目录名合法性校验：拒绝 '..' 与路径分隔符，防止路径遍历攻击。"""
    return bool(name) and name not in (".", "..") and "/" not in name and "\\" not in name


def classify(p: Path, by: str, kw_map: dict) -> str:
    """根据归档依据返回子目录名；无法归类时返回空字符串 ''。"""
    if by == "ext":
        return ext_of(p.name).lstrip(".") or "无扩展名"   # 按扩展名：pdf → 'pdf'
    if by == "semester":
        try:
            return semester_of(p.stat().st_mtime)         # 按修改时间：'2025-春'
        except OSError:                                   # 文件刚被删 / 不可读 → 视为无法归类
            return ""
    if by == "keyword":
        low = p.name.lower()
        for keyword, folder in kw_map.items():            # 按文件名关键词：先命中先归类
            if keyword.lower() in low:
                return folder
        return ""                                          # 无关键词命中 → 无法归类
    return ""


def plan_archive(root: Path, files, by: str, kw_map: dict) -> list:
    """计算归档计划（只计划，不动文件），并对每个子目录做重名检测。"""
    occupied = {}          # 子目录名 -> 该目录下已存在的文件名集合
    plans = []
    for src in files:
        folder = classify(src, by, kw_map)
        if not folder or not safe_folder(folder):          # 无法归类 / 非法目录名 → 跳过
            reason = "无法确定类别" if not folder else f"非法目录名：{folder}"
            plans.append({"from": src.name, "to": "", "status": "skipped",
                          "reason": reason})
            continue

        target_dir = root / folder
        # 首次处理某个子目录时，把它里面已有的文件名登记为占用（防覆盖），
        # 之后直接复用缓存，避免同一个子目录被反复扫描
        names = occupied.get(folder)
        if names is None:
            names = ({fname_key(p.name) for p in target_dir.iterdir() if p.is_file()}
                     if target_dir.is_dir() else set())
            occupied[folder] = names

        if fname_key(src.name) in names:                   # 目标目录里已有同名文件 → 跳过
            plans.append({"from": src.name, "to": f"{folder}/{src.name}",
                          "status": "skipped",
                          "reason": f"重名冲突：{folder}/{src.name}"})
            continue
        names.add(fname_key(src.name))                     # 登记，防止同目录内再撞
        plans.append({"from": src.name, "to": f"{folder}/{src.name}",
                      "status": "moved", "reason": ""})
    return plans


def cmd_archive(args) -> int:
    """按类别 / 学期 / 扩展名把文件移动到子目录，并生成整理报告。"""
    root = Path(args.path).expanduser()
    if not root.is_dir():
        print(f"[错误] 目录不存在：{root}", file=sys.stderr)
        return 1

    kw_map = parse_keyword_map(args.keyword_map) if args.by == "keyword" else {}
    files = iter_files(root)
    plans = plan_archive(root, files, args.by, kw_map)

    # ---- 1) 打印预览 ----
    moved = [p for p in plans if p["status"] == "moved"]
    skipped = [p for p in plans if p["status"] == "skipped"]
    if moved:
        print("将要移动的文件：")
        for p in moved:
            print(f"  {p['from']}  →  {p['to']}")
    if skipped:
        print("\n将跳过的文件：")
        for p in skipped:
            print(f"  {p['from']}  ({p['reason']})")
    if not moved:
        print("没有需要归档的文件。")
        return 0

    # ---- 2) input() 等待确认 ----
    if not confirm("确认执行以上归档？"):
        print("已取消，未做任何修改。")
        return 0

    # ---- 3) 执行移动，逐个捕获异常（单个失败不中断整体） ----
    failed = {}
    for p in moved:
        dst = root / p["to"]
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)   # 先确保子目录存在
            shutil.move(str(root / p["from"]), str(dst))    # 移动文件
        except OSError as e:                                # 权限等错误 → 记为失败
            failed[p["from"]] = str(e)

    # 把「实际结果」写进日志：成功→done，失败/跳过→skipped（带原因）
    items = []
    for p in plans:
        if p["status"] == "moved":
            if p["from"] in failed:
                items.append({"action": "move", "status": "skipped",
                              "from": p["from"], "to": p["to"],
                              "reason": f"移动失败：{failed[p['from']]}"})
            else:
                items.append({"action": "move", "status": "done",
                              "from": p["from"], "to": p["to"]})
        else:
            items.append({"action": "move", "status": "skipped",
                          "from": p["from"], "to": "", "reason": p["reason"]})

    append_log(root, "archive", items)
    print()
    print(build_report("archive", root, items))      # 生成整理报告
    return 0


def cmd_report(args) -> int:
    """查看整理报告（默认最近一次，--all 显示全部）。"""
    root = Path(args.path).expanduser()
    if not root.is_dir():
        print(f"[错误] 目录不存在：{root}", file=sys.stderr)
        return 1
    ops = load_log(root)
    if not ops:
        print("没有整理记录(该目录下还没执行过 rename / archive)。")
        return 0
    selected = ops if args.all else ops[-1:]         # 默认只显示最近一次
    for op in selected:
        print(build_report(op["command"], root, op["items"], op.get("time", "")))
    return 0


def cmd_undo(args) -> int:
    """撤销上次操作：读取日志里最近一次操作，把每个 done 条目反向移动回去。"""
    root = Path(args.path).expanduser()
    if not root.is_dir():
        print(f"[错误] 目录不存在：{root}", file=sys.stderr)
        return 1
    ops = load_log(root)
    if not ops:
        print("没有可撤销的操作。")
        return 0

    op = ops[-1]                                      # 最近一次操作
    done = [i for i in op["items"] if i["status"] == "done"]
    if not done:
        print(f"上次操作「{op['command']}」没有实际改动，已从日志移除。")
        try:
            save_log(root, ops[:-1])
        except OSError as e:
            print(f"[警告] 日志写入失败：{e}", file=sys.stderr)
        return 0

    # ---- 打印将撤销的动作 ----
    print(f"将撤销操作「{op['command']}」（{op.get('time', '')}）：")
    for i in done:
        print(f"  {i['to']}  ←  {i['from']}")         # to 是现在位置，from 是原来位置

    if not confirm("确认撤销？"):
        print("已取消。")
        return 0

    # ---- 反向移动：把文件从 'to' 移回 'from' ----
    restored, failed = 0, []
    for i in done:
        src = root / i["to"]                          # 文件现在所在位置
        dst = root / i["from"]                        # 文件原来位置
        if not src.exists():                          # 文件已经不在 → 无法撤销
            failed.append((i, "源文件已不存在（可能已被手动移动）"))
            continue
        dst.parent.mkdir(parents=True, exist_ok=True) # 确保原目录存在
        if dst.exists():                              # 原位已有文件 → 绝不覆盖
            failed.append((i, "目标位置已存在（避免覆盖，跳过）"))
            continue
        try:
            shutil.move(str(src), str(dst))           # 移回原位
            restored += 1
        except OSError as e:                          # 权限等错误兜底
            failed.append((i, f"移动失败：{e}"))

    # 注：撤销只把文件移回原位，不删除遗留的空子目录
    if failed:                                         # 有未还原的：保留这些条目，下次 undo 可重试
        op["items"] = [i for i, _ in failed]
        try:
            save_log(root, ops)
        except OSError as e:
            print(f"[警告] 日志写入失败：{e}", file=sys.stderr)
        print(f"\n撤销部分完成：还原 {restored} 个，{len(failed)} 个未还原"
              f"（已保留在日志中，可再次 undo 重试）。")
    else:                                              # 全部还原 → 移除这条日志
        try:
            save_log(root, ops[:-1])
        except OSError as e:
            print(f"[警告] 日志写入失败：{e}", file=sys.stderr)
        print(f"\n撤销完成：还原 {restored} 个。")
    for i, reason in failed:
        print(f"  - 未还原 {i['to']}：{reason}")
    return 0

# CLI 入口

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="organizer", description="作业文件批量整理工具")
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    sub = p.add_subparsers(dest="command", required=True, metavar="命令")

    s = sub.add_parser("scan", help="扫描并列出文件（大小 / 修改时间）")
    s.add_argument("path", help="要扫描的目录")
    s.add_argument("--ext", nargs="*", default=None, help="只显示这些扩展名，如 --ext .pdf")
    s.set_defaults(func=cmd_scan)

    r = sub.add_parser("rename", help="批量改名（先预览，input 确认后执行）")
    r.add_argument("path", help="要处理的目录")
    r.add_argument("--split", default="_", help="字段分隔符（默认 _）")
    r.add_argument("--fields", default="3,1", help="保留字段序号，如 3,1（默认 3,1）")
    r.add_argument("--ext", nargs="*", default=None, help="只处理这些扩展名")
    r.set_defaults(func=cmd_rename)

    a = sub.add_parser("archive", help="按类别 / 学期 / 扩展名归档到子目录")
    a.add_argument("path", help="要处理的目录")
    a.add_argument("--by", choices=["ext", "semester", "keyword"], default="ext",
                   help="归档依据（默认 ext）")
    a.add_argument("--keyword-map", help="--by keyword 时：'关键词=目录;...'")
    a.set_defaults(func=cmd_archive)

    rep = sub.add_parser("report", help="查看整理报告")
    rep.add_argument("path", help="要查看的目录")
    rep.add_argument("--all", action="store_true", help="显示全部历史记录（默认最近一次）")
    rep.set_defaults(func=cmd_report)

    u = sub.add_parser("undo", help="撤销上次操作")
    u.add_argument("path", help="要处理的目录")
    u.set_defaults(func=cmd_undo)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)     # 根据子命令分发到对应的 cmd_xxx 函数


if __name__ == "__main__":
    sys.exit(main())
