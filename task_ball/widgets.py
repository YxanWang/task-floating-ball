# -*- coding: utf-8 -*-
"""Reusable Qt widgets for the floating task ball.

Widgets expose signals for application actions and keep no references to the
main window or persistent task storage.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QColor, QPainter, QPen, QFont, QFontMetrics, QPalette,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QFrame,
    QToolButton, QScrollArea,
)

from .settings import APP_NAME, ROW_W, ROW_H, HEAD_H
from .themes import palette as ui_palette, panel_qss, row_qss


from .water_ball import WaterBall as Ball


def themed_qpalette(theme):
    """Keep native control painting consistent with the same semantic colors."""
    colors = ui_palette(theme)
    result = QPalette()
    roles = {
        QPalette.ColorRole.Window: colors.surface,
        QPalette.ColorRole.WindowText: colors.text,
        QPalette.ColorRole.Base: colors.input,
        QPalette.ColorRole.AlternateBase: colors.input_hover,
        QPalette.ColorRole.Text: colors.text,
        QPalette.ColorRole.Button: colors.input,
        QPalette.ColorRole.ButtonText: colors.text,
        QPalette.ColorRole.Highlight: colors.accent,
        QPalette.ColorRole.HighlightedText: colors.accent_text,
        QPalette.ColorRole.PlaceholderText: colors.muted,
        QPalette.ColorRole.ToolTipBase: colors.surface,
        QPalette.ColorRole.ToolTipText: colors.text,
        QPalette.ColorRole.Link: colors.accent,
        QPalette.ColorRole.Accent: colors.accent,
        QPalette.ColorRole.Light: colors.border,
    }
    for role, value in roles.items():
        result.setColor(role, QColor(value))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText):
        result.setColor(QPalette.ColorGroup.Disabled, role, QColor(colors.muted))
    return result


class ClickableLabel(QLabel):
    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, e):
        self.doubleClicked.emit()


class Editor(QLineEdit):
    """行内编辑框：Esc 取消，回车/失焦提交。"""

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self._cancel = True
            self.editingFinished.emit()
            return
        super().keyPressEvent(e)


class TaskRow(QFrame):
    """单条任务行：文字（双击编辑）+ 悬停出现删除按钮。"""

    deleted = Signal(str)
    edited = Signal(str, str)
    editingStarted = Signal()
    editingFinished = Signal()

    def __init__(self, task, label_w, theme="amber"):
        super().__init__()
        self.theme = ui_palette(theme).name
        self.setPalette(themed_qpalette(self.theme))
        self.task = task
        self._editor = None
        self._hovering = False

        h = QHBoxLayout(self)
        h.setContentsMargins(12, 0, 4, 0)
        h.setSpacing(6)

        self.label = ClickableLabel()
        self.label.setFixedWidth(label_w)
        self.label.setCursor(Qt.CursorShape.IBeamCursor)
        fm = QFontMetrics(self.label.font())
        text = str(task["text"])
        self.label.setText(fm.elidedText(text, Qt.TextElideMode.ElideRight, label_w))
        self.label.setToolTip(text)
        self.label.doubleClicked.connect(self._start_edit)

        self.delb = QToolButton()
        self.delb.setObjectName("del")
        self.delb.setText("✕")
        self.delb.setFixedSize(22, 22)
        self.delb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delb.clicked.connect(lambda *_: self.deleted.emit(self.task["id"]))
        # 删除按钮永远占位：非悬停时只是颜色透明（不是 setVisible）。
        # 若用显隐切换，布局会把 label 居中到 x=26，悬停又跳回 x=12，
        # 文字左右漂移（实机反馈的"乱飘"）。常驻占位则布局永不变化。

        h.addWidget(self.label, 1)
        h.addWidget(self.delb)
        self.setFixedSize(ROW_W, ROW_H - 2)   # 锁死行尺寸：任何布局重算都改不动
        self.refresh(task)

    def refresh(self, task):
        """同步行内容（行内编辑/外部 CLI 刷新后由 rebuild 调用）。"""
        self.task = task
        text = str(task["text"])
        fm = QFontMetrics(self.label.font())
        self.label.setText(fm.elidedText(
            text, Qt.TextElideMode.ElideRight, self.label.width()))
        self.label.setToolTip(text)
        self._apply_style(self._hovering)

    def _apply_style(self, hover):
        self.setStyleSheet(row_qss(self.theme, hover))

    def set_theme(self, theme):
        """Recolor the existing row and editor without committing its input."""
        self.theme = ui_palette(theme).name
        editor = self._editor
        if editor is not None:
            text, cursor = editor.text(), editor.cursorPosition()
            selection, selected = editor.selectionStart(), editor.selectedText()
            focused = editor.hasFocus()
            blocked = editor.blockSignals(True)
        try:
            self.setPalette(themed_qpalette(self.theme))
            self._apply_style(self._hovering)
            if editor is not None:
                editor.setPalette(themed_qpalette(self.theme))
                editor.setStyleSheet(row_qss(self.theme, self._hovering))
                if editor.text() != text:
                    editor.setText(text)
                if selection >= 0:
                    if cursor == selection:
                        editor.setSelection(selection + len(selected), -len(selected))
                    else:
                        editor.setSelection(selection, len(selected))
                else:
                    editor.setCursorPosition(cursor)
                if focused and not editor.hasFocus():
                    editor.setFocus(Qt.FocusReason.OtherFocusReason)
        finally:
            if editor is not None:
                editor.blockSignals(blocked)

    def enterEvent(self, e):
        self._hovering = True
        self._apply_style(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hovering = False
        self._apply_style(False)
        super().leaveEvent(e)

    def _start_edit(self):
        if self._editor is not None:
            return
        self.editingStarted.emit()
        self.label.setVisible(False)
        ed = Editor(str(self.task["text"]))
        ed.setPalette(themed_qpalette(self.theme))
        ed.setStyleSheet(row_qss(self.theme, self._hovering))
        ed._cancel = False
        ed.editingFinished.connect(self._commit_edit)
        self._editor = ed
        self.layout().insertWidget(0, ed, 1)
        ed.setFocus()
        ed.selectAll()

    def cancel_edit(self):
        """End an editing session when its row is removed externally."""
        if self._editor is not None:
            self._editor._cancel = True
            self._commit_edit()

    def _commit_edit(self):
        ed = self._editor
        if ed is None:
            return
        self._editor = None
        self.editingFinished.emit()
        text = str(self.task["text"]) if ed._cancel else ed.text().strip()
        ed.deleteLater()
        self.label.setVisible(True)
        if not ed._cancel:
            if text:
                if text != self.task["text"]:
                    self.edited.emit(self.task["id"], text)
            else:
                self.deleted.emit(self.task["id"])


class PanelWindow(QFrame):
    """独立面板窗口：背景由 paintEvent 手绘（QSS 背景在顶层透明窗上
    渲染不可靠，实机踩坑：背景丢失只剩子控件悬浮）。"""

    entered = Signal()
    left = Signal()
    submitted = Signal()

    def __init__(self, theme="amber"):
        super().__init__()
        self.theme = ui_palette(theme).name
        self._colors = ui_palette(self.theme)
        self.setObjectName("panel")
        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFont(QFont("Microsoft YaHei UI", 10))

        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(6)

        # 标题区：应用名称 + 未完成数 + 底部发丝分割线（有任务时才显示）
        self.head = QWidget()
        hv = QVBoxLayout(self.head)
        hv.setContentsMargins(4, 0, 4, 0)
        hv.setSpacing(5)
        hh = QHBoxLayout()
        hh.setContentsMargins(0, 0, 0, 0)
        hh.setSpacing(0)
        self.head_title = QLabel(APP_NAME)
        self.head_title.setObjectName("head-title")
        tf = QFont("Microsoft YaHei UI")
        tf.setPointSize(9)
        tf.setBold(True)
        tf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.5)
        self.head_title.setFont(tf)
        self.head_count = QLabel("0")
        self.head_count.setObjectName("head-count")
        cf = QFont()
        cf.setFamilies(["Segoe UI Variable Display", "Segoe UI"])
        cf.setPointSize(9)
        cf.setBold(True)
        self.head_count.setFont(cf)
        hh.addWidget(self.head_title)
        hh.addStretch(1)
        hh.addWidget(self.head_count)
        hv.addLayout(hh)
        self.head_rule = QFrame()
        self.head_rule.setFixedHeight(1)
        hv.addWidget(self.head_rule)
        self.head.setFixedHeight(HEAD_H)
        v.addWidget(self.head)

        self.hint = QLabel("暂无任务 · 在下方输入后回车")
        self.hint.setObjectName("hint")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setFixedHeight(22)
        v.addWidget(self.hint)

        self.scroll = QScrollArea()
        self.scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # 视口必须显式透明，否则会以默认灰底盖住手绘卡片
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.viewport().setStyleSheet("background: transparent;")
        v.addWidget(self.scroll, 1)

        self.host = QWidget()
        self.host.setFixedHeight(1)
        self.scroll.setWidget(self.host)

        self.input = QLineEdit()
        self.input.setPlaceholderText("添加任务，回车确认")
        self.input.setClearButtonEnabled(True)
        self.input.setFixedHeight(34)
        self.input.returnPressed.connect(self.submitted)
        v.addWidget(self.input)
        self.hide()
        self.set_theme(theme)

    def set_theme(self, theme):
        self._colors = ui_palette(theme)
        self.theme = self._colors.name
        self.setPalette(themed_qpalette(self.theme))
        self.setStyleSheet(panel_qss(self.theme))
        self.head_rule.setStyleSheet(
            f"QFrame{{background:{self._colors.divider};border:none;}}")
        self.input.setPalette(themed_qpalette(self.theme))
        self.update()

    def paintEvent(self, e):
        # Keep the translucent top-level surface in QPainter, with static alpha.
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        surface = QColor(self._colors.surface)
        surface.setAlpha(self._colors.surface_alpha)
        border = QColor(self._colors.border)
        border.setAlpha(self._colors.border_alpha)
        p.setBrush(surface)
        p.setPen(QPen(border, 1))
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 14, 14)
        super().paintEvent(e)

    def enterEvent(self, e):
        self.entered.emit()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.left.emit()
        super().leaveEvent(e)
