"""A small modeless editor for floating-ball appearance preferences."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPalette, QPen, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton,
    QSlider, QVBoxLayout, QWidget,
)

from .appearance import Appearance
from .themes import palette as ui_palette, dialog_qss
from .widgets import themed_qpalette


class AppearanceTitleBar(QWidget):
    """Use the operating system's move loop while keeping the title in-theme."""

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
        super().mousePressEvent(event)


class AppearanceDialog(QDialog):
    appearanceChanged = Signal(object)

    def __init__(self, parent=None, appearance: Appearance | None = None):
        super().__init__(parent)
        self.setWindowTitle("外观设置")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(False)
        self.setMinimumWidth(300)
        font = QFont("Microsoft YaHei UI")
        font.setPointSize(10)
        self.setFont(font)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(12)

        self.title_bar = AppearanceTitleBar()
        self.title_bar.setObjectName("appearanceTitleBar")
        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(8)
        self.title_label = QLabel("外观设置")
        self.title_label.setObjectName("appearanceTitle")
        title_font = QFont(font)
        title_font.setPointSize(11)
        title_font.setWeight(QFont.Weight.Medium)
        self.title_label.setFont(title_font)
        title_layout.addWidget(self.title_label)
        title_layout.addStretch(1)
        self.close_button = QPushButton("×")
        self.close_button.setObjectName("appearanceCloseButton")
        self.close_button.setAccessibleName("关闭")
        self.close_button.setToolTip("关闭")
        self.close_button.setAutoDefault(False)
        self.close_button.setFixedSize(32, 32)
        self.close_button.clicked.connect(self.close)
        title_layout.addWidget(self.close_button)
        layout.addWidget(self.title_bar)

        theme_row = QHBoxLayout()
        theme_row.setSpacing(5)
        self.theme_group = QButtonGroup(self)
        self.theme_group.setExclusive(True)
        self.theme_buttons = {}
        for label, theme in (("深海", "ocean"), ("月白", "moon"), ("琥珀", "amber")):
            button = QPushButton(label)
            button.setObjectName(f"theme{theme.title()}Button")
            button.setAccessibleName(label)
            button.setProperty("themeOption", True)
            button.setProperty("themeName", theme)
            button.setCheckable(True)
            button.setAutoDefault(False)
            button.setMinimumHeight(34)
            self.theme_group.addButton(button)
            self.theme_buttons[theme] = button
            theme_row.addWidget(button, 1)
        layout.addLayout(theme_row)

        size_header = QHBoxLayout()
        size_header.addWidget(QLabel("球体大小"))
        size_header.addStretch(1)
        self.size_value = QLabel()
        self.size_value.setAlignment(Qt.AlignmentFlag.AlignRight)
        size_header.addWidget(self.size_value)
        layout.addLayout(size_header)

        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setObjectName("sizeSlider")
        self.size_slider.setRange(40, 80)
        self.size_slider.setSingleStep(2)
        self.size_slider.setPageStep(2)
        self.size_slider.setMinimumHeight(22)
        layout.addWidget(self.size_slider)

        opacity_header = QHBoxLayout()
        opacity_label = QLabel("透明度")
        opacity_header.addWidget(opacity_label)
        opacity_header.addStretch(1)
        self.opacity_value = QLabel()
        self.opacity_value.setObjectName("opacityValue")
        self.opacity_value.setAlignment(Qt.AlignmentFlag.AlignRight)
        opacity_header.addWidget(self.opacity_value)
        layout.addLayout(opacity_header)

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setObjectName("opacitySlider")
        self.opacity_slider.setAccessibleName("透明度")
        self.opacity_slider.setToolTip("数值越低越透明，100% 为完全不透明")
        self.opacity_slider.setRange(30, 100)
        self.opacity_slider.setSingleStep(1)
        self.opacity_slider.setPageStep(5)
        self.opacity_slider.setMinimumHeight(22)
        opacity_label.setBuddy(self.opacity_slider)
        layout.addWidget(self.opacity_slider)

        self.ships_checkbox = QCheckBox("显示任务光点")
        self.ships_checkbox.setObjectName("showShipsCheck")

        buttons = QHBoxLayout()
        buttons.addWidget(self.ships_checkbox)
        buttons.addStretch(1)
        self.done_button = QPushButton("完成")
        self.done_button.setObjectName("doneButton")
        self.done_button.setAutoDefault(False)
        self.done_button.clicked.connect(self.close)
        buttons.addWidget(self.done_button)
        layout.addLayout(buttons)

        self.theme_group.buttonClicked.connect(self._controls_changed)
        self.size_slider.valueChanged.connect(self._size_changed)
        self.opacity_slider.valueChanged.connect(self._opacity_changed)
        self.ships_checkbox.toggled.connect(self._controls_changed)
        self._close_shortcut = QShortcut(QKeySequence("Alt+F4"), self)
        self._close_shortcut.activated.connect(self.close)
        self.set_appearance(appearance or Appearance())

    def appearance(self) -> Appearance:
        return self._appearance

    def set_appearance(self, appearance: Appearance) -> None:
        """Load preferences without emitting changes or writing configuration."""
        controls = (*self.theme_buttons.values(), self.theme_group,
                    self.size_slider, self.opacity_slider, self.ships_checkbox)
        previous = [control.blockSignals(True) for control in controls]
        try:
            self._appearance = appearance
            self.theme_buttons[appearance.theme].setChecked(True)
            self.size_slider.setValue(appearance.size)
            self.size_value.setText(f"{appearance.size} px")
            self.opacity_slider.setValue(appearance.opacity)
            self.opacity_value.setText(f"{appearance.opacity}%")
            self.ships_checkbox.setChecked(appearance.show_ships)
            self._apply_theme(appearance.theme)
        finally:
            for control, was_blocked in zip(controls, previous):
                control.blockSignals(was_blocked)

    def _size_changed(self, value):
        # Mouse movement can produce odd values despite QSlider's keyboard step.
        size = value - value % 2
        if size != value:
            was_blocked = self.size_slider.blockSignals(True)
            self.size_slider.setValue(size)
            self.size_slider.blockSignals(was_blocked)
        self.size_value.setText(f"{size} px")
        self._controls_changed()

    def _opacity_changed(self, value):
        self.opacity_value.setText(f"{value}%")
        self._controls_changed()

    def _apply_theme(self, theme):
        semantic = ui_palette(theme)
        name = semantic.name
        if getattr(self, "theme", None) == name:
            return
        focused = self.focusWidget()
        had_focus = focused is not None and focused.hasFocus()
        self.theme = name
        colors = themed_qpalette(name)
        self.setPalette(colors)
        self.setStyleSheet(dialog_qss(name))
        for control in (self.size_slider, self.opacity_slider, self.ships_checkbox,
                        self.size_value, self.opacity_value, self.title_label):
            control.setPalette(colors)
        button_colors = QPalette(colors)
        button_colors.setColor(QPalette.ColorRole.Button, QColor(semantic.accent))
        button_colors.setColor(QPalette.ColorRole.ButtonText, QColor(semantic.accent_text))
        button_colors.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button,
                               QColor(semantic.input))
        button_colors.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText,
                               QColor(semantic.muted))
        self.done_button.setPalette(button_colors)
        self.done_button.ensurePolished()
        self.done_button.update()
        for button in self.theme_buttons.values():
            option_colors = QPalette(colors)
            option_colors.setColor(QPalette.ColorRole.Button,
                                   QColor(semantic.accent if button.isChecked() else semantic.input))
            option_colors.setColor(QPalette.ColorRole.ButtonText,
                                   QColor(semantic.accent_text if button.isChecked() else semantic.text))
            button.setPalette(option_colors)
            button.ensurePolished()
        close_colors = QPalette(colors)
        close_colors.setColor(QPalette.ColorRole.ButtonText, QColor(semantic.muted))
        self.close_button.setPalette(close_colors)
        self.update()
        if had_focus and not focused.hasFocus():
            focused.setFocus(Qt.FocusReason.OtherFocusReason)

    def _controls_changed(self, *_):
        checked = self.theme_group.checkedButton()
        appearance = Appearance(
            theme=checked.property("themeName") if checked is not None else "amber",
            size=self.size_slider.value(),
            show_ships=self.ships_checkbox.isChecked(),
            opacity=self.opacity_slider.value(),
        )
        if appearance != self._appearance:
            self._appearance = appearance
            self._apply_theme(appearance.theme)
            self.appearanceChanged.emit(appearance)

    def paintEvent(self, event):
        colors = ui_palette(self.theme)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(colors.surface))
        border = QColor(colors.border)
        border.setAlpha(colors.border_alpha)
        painter.setPen(QPen(border, 1))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 14, 14)
        painter.end()
        super().paintEvent(event)
