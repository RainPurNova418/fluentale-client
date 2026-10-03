# plugins/devtest/_runner.py
# coding: utf-8
"""
在后台线程运行 devtest 脚本，实时捕获 stdout / stderr。
"""
import io
import runpy
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal


_HERE = Path(__file__).resolve().parent


class _LineEmitter(io.TextIOBase):
    """把 write() 拆成逐行信号发出去"""

    def __init__(self, signal):
        super().__init__()
        self._signal = signal
        self._buf = ""

    def write(self, s):
        if not s:
            return 0
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._signal.emit(line)
        return len(s)

    def flush(self):
        pass

    def flush_pending(self):
        if self._buf:
            self._signal.emit(self._buf)
            self._buf = ""


class ScriptRunner(QThread):
    line = Signal(str)          # 一行输出
    finished = Signal(int)      # 退出码

    def __init__(self, module: str, parent=None):
        super().__init__(parent)
        self.module = module

    def run(self):
        script = _HERE / f"{self.module}.py"
        if not script.exists():
            self.line.emit(f"[错误] 脚本不存在: {script}")
            self.finished.emit(1)
            return

        old_stdout = sys.stdout
        old_stderr = sys.stderr
        emitter = _LineEmitter(self.line)

        sys.stdout = emitter
        sys.stderr = emitter

        code = 0
        try:
            self.line.emit(f"$ python {self.module}.py")
            self.line.emit("─" * 64)
            runpy.run_path(str(script), run_name="__main__")
            self.line.emit("─" * 64)
            self.line.emit("[完成]")
        except SystemExit as e:
            c = e.code
            code = c if isinstance(c, int) else (0 if c is None else 1)
            self.line.emit(f"[退出] code={code}")
        except Exception:
            self.line.emit("[异常]")
            self.line.emit(traceback.format_exc())
            code = 1
        finally:
            emitter.flush_pending()
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        self.finished.emit(code)