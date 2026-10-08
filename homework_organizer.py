#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
子命令：
  scan    扫描目录、列出文件（大小 / 修改时间），支持按扩展名过滤
示例：
  python homework_organizer.py scan   ./作业 --ext .pdf .docx
"""
import argparse
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

# CLI 入口

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="organizer", description="作业文件批量整理工具")
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    sub = p.add_subparsers(dest="command", required=True, metavar="命令")

    s = sub.add_parser("scan", help="扫描并列出文件（大小 / 修改时间）")
    s.add_argument("path", help="要扫描的目录")
    s.add_argument("--ext", nargs="*", default=None, help="只显示这些扩展名，如 --ext .pdf")
    s.set_defaults(func=cmd_scan)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)     # 根据子命令分发到对应的 cmd_xxx 函数


if __name__ == "__main__":
    sys.exit(main())
