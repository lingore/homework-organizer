"""整理报告：报告文本生成与 report 子命令。"""
import sys
from pathlib import Path

from .journal import _now_str, load_log


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
