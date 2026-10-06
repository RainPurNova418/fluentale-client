"""
通用工具：日志、路径、配置读写、平台检测、U 盘标识
"""
import sys
import os
import json

try:
    from colorama import Fore, Style, init
    init(autoreset=True)
    HAS_COLORAMA = True
except ImportError:
    HAS_COLORAMA = False

    class Fore:
        RED = ''
        GREEN = ''
        YELLOW = ''
        BLUE = ''
        CYAN = ''
        MAGENTA = ''
        WHITE = ''
        RESET = ''

    class Style:
        BRIGHT = ''
        DIM = ''
        NORMAL = ''
        RESET_ALL = ''

def _safe_print(msg: str):
    """console=False 打包时 sys.stdout 为 None，避免崩溃"""
    if sys.stdout is not None:
        print(msg)

def log_info(msg: str):
    if HAS_COLORAMA:
        _safe_print(f"{Fore.CYAN}[INFO] {msg}{Style.RESET_ALL}")
    else:
        _safe_print(f"[INFO] {msg}")

def log_success(msg: str):
    if HAS_COLORAMA:
        _safe_print(f"{Fore.GREEN}[SUCCESS] {msg}{Style.RESET_ALL}")
    else:
        _safe_print(f"[SUCCESS] {msg}")

def log_warning(msg: str):
    if HAS_COLORAMA:
        _safe_print(f"{Fore.YELLOW}[WARNING] {msg}{Style.RESET_ALL}")
    else:
        _safe_print(f"[WARNING] {msg}")

def log_error(msg: str):
    if HAS_COLORAMA:
        _safe_print(f"{Fore.RED}[ERROR] {msg}{Style.RESET_ALL}")
    else:
        _safe_print(f"[ERROR] {msg}")

def log_debug(msg: str):
    if HAS_COLORAMA:
        _safe_print(f"{Fore.MAGENTA}[DEBUG] {msg}{Style.RESET_ALL}")
    else:
        _safe_print(f"[DEBUG] {msg}")

def log(msg: str, level: str = "INFO"):
    """
    统一日志入口。
    支持级别: INFO, SUCCESS, WARNING, ERROR, DEBUG (不区分大小写)
    """
    level = level.upper()
    if level == "INFO":
        log_info(msg)
    elif level == "SUCCESS":
        log_success(msg)
    elif level == "WARNING":
        log_warning(msg)
    elif level == "ERROR":
        log_error(msg)
    elif level == "DEBUG":
        log_debug(msg)
    else:
        _safe_print(msg)

def resource_path(rel_path: str) -> str:
    """资源路径：开发时基于当前文件，打包后基于 _MEIPASS"""
    if hasattr(sys, "_MEIPASS"):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, rel_path)

def get_config_dir() -> str:
    """项目根目录下的 config/ 目录，不存在则创建"""
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "config")
    os.makedirs(path, exist_ok=True)
    return path

def get_user_settings_path() -> str:
    """config/UserSettings.json 的完整路径"""
    return os.path.join(get_config_dir(), "UserSettings.json")

def _config_paths():
    """
    返回 (只读资源路径, 可写用户路径)。
    开发时两者相同；打包后资源在 _MEIPASS，可写在 exe 旁边。
    """
    resource = resource_path("config/config.json")
    if hasattr(sys, "_MEIPASS"):
        exe_dir = os.path.dirname(sys.executable)
        writable = os.path.join(exe_dir, "config", "config.json")
    else:
        writable = resource
    return resource, writable

def get_json_info(key: str = None, default=None):
    """
    读取 config/config.json 的某个字段。

    优先读可写文件（exe 旁边），不存在时回退到资源文件（_MEIPASS）。
    """
    if key is None:
        return "You need a key to open door, right?"

    resource_p, writable_p = _config_paths()

    for path in (writable_p, resource_p):
        if not os.path.exists(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8') as temp:
                text = json.load(temp)
        except json.JSONDecodeError as e:
            msg = (f"[JSONDecodeError] 配置文件 JSON 格式错误:\n"
                   f"  path={path}\n"
                   f"  line={e.lineno}, col={e.colno}, pos={e.pos}\n"
                   f"  msg={e.msg}")
            if default is None:
                log_error(msg)
            continue
        except PermissionError as e:
            if default is None:
                log_error(f"[PermissionError] 无权限读取文件:\n  path={path}\n  {e}")
            continue
        except OSError as e:
            if default is None:
                log_error(f"[OSError] 读取失败:\n  path={path}\n  {e}")
            continue

        if not isinstance(text, dict):
            if default is None:
                log_error(f"[TypeError] 配置文件顶层结构应为 dict, "
                          f"实际为 {type(text).__name__}\n  path={path}")
            continue

        if key in text:
            return text[key]

    if default is not None:
        return default

    resource_p, writable_p = _config_paths()
    return (f"[KeyError] 键 {key!r} 不存在\n"
            f"  已查找: {writable_p}\n"
            f"  已查找: {resource_p}")

def set_json_info(key: str, value) -> bool:
    """
    写入 config/config.json 的某个字段。

    只写可写文件（开发时=项目根目录，打包后=exe 旁边）。
    写入前会先读现有内容，尽量保留其他字段。
    """
    resource_p, writable_p = _config_paths()

    data = {}
    for path in (writable_p, resource_p):
        if not os.path.exists(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data = loaded
                break
        except (json.JSONDecodeError, OSError):
            continue

    data[key] = value

    try:
        os.makedirs(os.path.dirname(writable_p), exist_ok=True)
        with open(writable_p, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        return True
    except PermissionError as e:
        log_error(f"[set_json_info] 无权限写入:\n  path={writable_p}\n  {e}")
        return False
    except OSError as e:
        log_error(f"[set_json_info] 写入失败:\n  path={writable_p}\n  {e}")
        return False

def get_version():
    return get_json_info("version", default="0.0.0")

def is_windows() -> bool:
    return sys.platform.startswith("win")

def get_windows_build() -> int:
    if not is_windows():
        return 0
    try:
        return sys.getwindowsversion().build
    except Exception:
        return 0

def is_win11() -> bool:
    return get_windows_build() >= 22000

def is_win10() -> bool:
    build = get_windows_build()
    return 10240 <= build < 22000

def supports_mica() -> bool:
    return is_win11()

def list_removable_drives() -> list:
    if not is_windows():
        return []
    import ctypes

    DRIVE_REMOVABLE = 2
    drives = []
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for i in range(26):
        if bitmask & (1 << i):
            letter = chr(ord('A') + i)
            root = f"{letter}:\\"
            drive_type = ctypes.windll.kernel32.GetDriveTypeW(root)
            if drive_type == DRIVE_REMOVABLE:
                drives.append(root)
    return drives

def get_volume_serial(drive: str) -> int:
    if not is_windows():
        return 0
    import ctypes
    from ctypes import wintypes

    serial = wintypes.DWORD()
    ok = ctypes.windll.kernel32.GetVolumeInformationW(
        drive,
        None, 0,
        ctypes.byref(serial),
        None, None,
        None, 0,
    )
    return serial.value if ok else 0

def get_volume_label(drive: str) -> str:
    if not is_windows():
        return ""
    import ctypes

    buf = ctypes.create_unicode_buffer(261)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(
        drive,
        buf, 261,
        None, None, None,
        None, 0,
    )
    return buf.value if ok else ""

def get_usb_id(drive: str) -> str:
    """卷序列号 + 卷标 → SHA256 前 32 字符，很简陋的U盘登录。"""
    import hashlib
    serial = get_volume_serial(drive)
    label = get_volume_label(drive)
    if not serial:
        return ""
    raw = f"{serial}:{label}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]

if __name__ == "__main__":
    print(get_version())