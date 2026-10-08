"""撤销上一次操作：按日志把文件移回原位，绝不覆盖。"""
import shutil
import sys
from pathlib import Path

from .journal import load_log, save_log
from .utils import confirm


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
