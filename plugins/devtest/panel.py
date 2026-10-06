from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import (
    ListWidget, TextEdit, TitleLabel, CaptionLabel,
    PrimaryPushButton, PushButton,
)

from plugins._default.login import _FluentDialog
from . import SCRIPTS
from ._runner import ScriptRunner


class DevTestPanel(_FluentDialog):

    def __init__(self, parent=None):
        super().__init__("功能及状态测试", parent)
        self._runner = None
        self.setMinimumSize(900, 600)
        self.resize(1000, 680)

        for btn in (getattr(self, "yesButton", None),
                    getattr(self, "cancelButton", None)):
            if btn is not None:
                btn.hide()

        self.addContent(TitleLabel("功能及状态测试", self))
        desc = CaptionLabel(
            "开发者专用。选中左侧条目后点击「运行」，输出会实时显示在右侧。",
            self,
        )
        desc.setWordWrap(True)
        self.addContent(desc)

        body = QWidget(self)
        bodyLayout = QHBoxLayout(body)
        bodyLayout.setContentsMargins(0, 0, 0, 0)
        bodyLayout.setSpacing(12)

        self.scriptList = ListWidget(body)
        self.scriptList.setFixedWidth(260)
        for s in SCRIPTS:
            self.scriptList.addItem(s.name)
        self.scriptList.currentRowChanged.connect(self._on_script_changed)
        bodyLayout.addWidget(self.scriptList)

        right = QWidget(body)
        rightLayout = QVBoxLayout(right)
        rightLayout.setContentsMargins(0, 0, 0, 0)
        rightLayout.setSpacing(6)

        self.descLabel = CaptionLabel("", right)
        self.descLabel.setWordWrap(True)
        rightLayout.addWidget(self.descLabel)

        self.outputView = TextEdit(right)
        self.outputView.setReadOnly(True)
        font = QFont("Consolas")
        font.setPointSize(9)
        self.outputView.setFont(font)
        rightLayout.addWidget(self.outputView, 1)

        bodyLayout.addWidget(right, 1)
        self.addContent(body)

        btnRow = QWidget(self)
        btnLayout = QHBoxLayout(btnRow)
        btnLayout.setContentsMargins(0, 0, 0, 0)
        btnLayout.setSpacing(8)

        self.runBtn = PrimaryPushButton("运行", btnRow)
        self.runBtn.clicked.connect(self._on_run)
        self.clearBtn = PushButton("清空输出", btnRow)
        self.clearBtn.clicked.connect(self.outputView.clear)
        self.closeBtn = PushButton("关闭", btnRow)
        self.closeBtn.clicked.connect(self.close)

        btnLayout.addWidget(self.runBtn)
        btnLayout.addWidget(self.clearBtn)
        btnLayout.addStretch(1)
        btnLayout.addWidget(self.closeBtn)

        self.addContent(btnRow)

        if SCRIPTS:
            self.scriptList.setCurrentRow(0)

    def _on_script_changed(self, row):
        if row < 0 or row >= len(SCRIPTS):
            return
        self.descLabel.setText(SCRIPTS[row].desc)

    def _on_run(self):
        if self._runner is not None and self._runner.isRunning():
            return
        row = self.scriptList.currentRow()
        if row < 0:
            return
        s = SCRIPTS[row]

        self.outputView.clear()
        self.runBtn.setEnabled(False)
        self.runBtn.setText("运行中…")

        self._runner = ScriptRunner(s.module, self)
        self._runner.line.connect(self._on_line)
        self._runner.finished.connect(self._on_finished)
        self._runner.start()

    def _on_line(self, text):
        self.outputView.append(text)
        sb = self.outputView.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_finished(self, code):
        self.runBtn.setEnabled(True)
        self.runBtn.setText("运行")
        self._runner = None