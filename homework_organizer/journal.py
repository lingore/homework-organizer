"""整理日志：读取、原子写入、追加记录（供 report / undo 使用）。"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from .utils import LOG_FILE


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
