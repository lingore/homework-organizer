"""需求 1：扫描目录并列出文件（大小 / 修改时间，支持扩展名过滤）。"""
import stat
import sys
from pathlib import Path

from .utils import LOG_FILE, ext_of, human_readable_size, human_time, norm_ext_token


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
