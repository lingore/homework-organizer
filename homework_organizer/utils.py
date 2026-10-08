"""通用工具函数：大小 / 时间格式化、扩展名匹配、文件枚举、交互确认。"""
from datetime import datetime
from pathlib import Path

# 整理日志文件名（放在被整理目录下，记录每次操作，供 report / undo 使用）
LOG_FILE = ".organizer_log.json"


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
