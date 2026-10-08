"""需求 3：按学期 / 类别归档到子目录，并生成整理报告。"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

from .journal import append_log
from .report import build_report
from .utils import confirm, ext_of, fname_key, iter_files


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
