"""命令行入口：注册 5 个子命令并分发执行。"""
import argparse
import sys

from . import __version__
from .archive import cmd_archive
from .rename import cmd_rename
from .report import cmd_report
from .scan import cmd_scan
from .undo import cmd_undo


def _setup_console() -> None:
    """让 Windows 控制台也以 UTF-8 读写，避免中文乱码。"""
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="organizer", description="作业文件批量整理工具")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
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
    _setup_console()                                  # 输出编码先设好，再解析参数
    args = build_parser().parse_args(argv)
    return args.func(args)                            # 根据子命令分发到对应 cmd_xxx
