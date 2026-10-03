# app_state.py
# coding: utf-8
"""
全局应用状态。

用 sys.modules 保证整个进程内只有一个实例，
即使插件被 importlib 用不同模块名加载，也能拿到同一份。
"""
import sys
from PySide6.QtCore import QObject, Signal


class AppState(QObject):
    readerTopicChanged = Signal(object)

    def __init__(self):
        super().__init__()
        self._current_reader_topic = None
        self._current_reader_window = None

    @property
    def current_reader_topic(self):
        return self._current_reader_topic

    @property
    def current_reader_window(self):
        return self._current_reader_window

    def set_reader_topic(self, topic, window):
        self._current_reader_topic = topic
        self._current_reader_window = window
        self.readerTopicChanged.emit(topic)

    def clear_reader_topic(self, window=None):
        if window is None or self._current_reader_window is window:
            self._current_reader_topic = None
            self._current_reader_window = None
            self.readerTopicChanged.emit(None)


# ── 单例：整个进程只此一份 ──
_KEY = "_fluentale_app_state_singleton"
if _KEY not in sys.modules:
    sys.modules[_KEY] = AppState()

app_state = sys.modules[_KEY]