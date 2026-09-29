import sys
import os
import traceback
from toolmethods import log

def show_error(title: str, message: str, exit_after: bool = False):
    log(f"{title}\n{message}","ERROR")
    if exit_after:
        traceback.print_exc()

    try:
        from qfluentwidgets import InfoBar, InfoBarPosition
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app and app.activeWindow():
            InfoBar.error(title, message, app.activeWindow(), InfoBarPosition.TOP_RIGHT, 3000)
            if exit_after:
                sys.exit(1)
            return
    except Exception:
        pass

    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance() or QApplication([])
        QMessageBox.critical(None, title, message)
        if exit_after:
            sys.exit(1)
        return
    except Exception:
        pass

    try:
        from win10toast import ToastNotifier
        ToastNotifier().show_toast(title, message, duration=5)
        if exit_after:
            sys.exit(1)
        return
    except Exception:
        pass

    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        if exit_after:
            sys.exit(1)
        return
    except Exception:
        pass

    if exit_after:
        sys.exit(1)


# ========== 依赖检查 ==========
try:
    from PySide6.QtCore import *
    from PySide6.QtGui import *
    from PySide6.QtWidgets import *
except ImportError as e:
    show_error("关键依赖缺失", f"PySide6 未安装: {e}", exit_after=True)

try:
    from qfluentwidgets import *
    from qfluentwidgets import setTheme
    from qfluentwidgets.common.config import qconfig
except ImportError as e:
    show_error("依赖缺失", f"qfluentwidgets 未安装: {e}", exit_after=True)

try:
    from tqdm import tqdm
except ImportError:
    show_error("提示", "tqdm 未安装，进度条功能不可用", exit_after=False)


# ========== 全局异常钩子 ==========
def global_exception_hook(exc_type, exc_value, exc_tb):
    error_msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
    show_error("未捕获异常", error_msg, exit_after=True)


sys.excepthook = global_exception_hook


# ========== 启动应用 ==========
from window_plugin import MainWindowPlugin


if __name__ == "__main__":
    log("有app", "DEBUG")
    app = QApplication(sys.argv)

    # ── 加载客户端配置 ──
    try:
        from plugins._default.settings import cfg
        log("配置已加载", "DEBUG")
    except ImportError as e:
        log(f"cfg 导入失败: {e}", "ERROR")
        raise

    # ── 应用保存的主题和颜色 ──
    setTheme(cfg.themeMode.value)
    print("=====================")
    log(f"主题已应用: mode={cfg.themeMode.value}, "
        f"color={cfg.themeColor.value.name()}", "DEBUG")

    main_window = MainWindowPlugin()
    sys.exit(app.exec())