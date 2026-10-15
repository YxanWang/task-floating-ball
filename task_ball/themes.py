"""Shared UI colors and local widget styles, without importing Qt."""

from dataclasses import dataclass


@dataclass(frozen=True)
class UiPalette:
    name: str
    surface: str
    surface_alpha: int
    border: str
    border_alpha: int
    text: str
    muted: str
    accent: str
    accent_text: str
    input: str
    input_hover: str
    focus: str
    row_hover: str
    divider: str
    danger: str
    button_hover: str
    scroll_handle: str


_PALETTES = {
    "ocean": UiPalette(
        name="ocean", surface="#112D38", surface_alpha=238,
        border="#507F8D", border_alpha=85,
        text="#E6F4F2", muted="#93B6BB", accent="#75D4CF", accent_text="#102E35",
        input="#1C414D", input_hover="#244D58", focus="#78C9C7",
        row_hover="rgba(117,212,207,0.09)", divider="rgba(117,212,207,0.18)",
        danger="#F28D91", button_hover="#91E0DC", scroll_handle="#668F98",
    ),
    "moon": UiPalette(
        name="moon", surface="#F0F5F5", surface_alpha=245,
        border="#A6BDC6", border_alpha=150,
        text="#28434E", muted="#4B6773", accent="#456F7D", accent_text="#FFFFFF",
        input="#DFE9EC", input_hover="#D7E4E8", focus="#648E9B",
        row_hover="rgba(70,109,125,0.08)", divider="rgba(70,109,125,0.20)",
        danger="#AC3D4B", button_hover="#365E6D", scroll_handle="#8CA8B4",
    ),
    "amber": UiPalette(
        name="amber", surface="#342B24", surface_alpha=241,
        border="#A88759", border_alpha=90,
        text="#F5E8D1", muted="#BBA88B", accent="#DCB97E", accent_text="#35291E",
        input="#483B2D", input_hover="#554631", focus="#C6A372",
        row_hover="rgba(218,183,128,0.09)", divider="rgba(218,183,128,0.19)",
        danger="#EF9D8F", button_hover="#E6C795", scroll_handle="#9A815D",
    ),
}


def palette(theme: str) -> UiPalette:
    if not isinstance(theme, str):
        return _PALETTES["amber"]
    return _PALETTES.get(theme, _PALETTES["amber"])


def panel_qss(theme: str) -> str:
    p = palette(theme)
    return f"""
        QLabel {{ color: {p.text}; background: transparent; }}
        QLabel#hint, QLabel#head-title {{ color: {p.muted}; background: transparent; }}
        QLabel#head-count {{ color: {p.accent}; background: transparent; }}
        QScrollArea {{ background: transparent; border: none; }}
        QLineEdit {{ color: {p.text}; background: {p.input};
            border: 1px solid transparent; border-radius: 10px; padding: 7px 12px;
            placeholder-text-color: {p.muted};
            selection-background-color: {p.accent}; selection-color: {p.accent_text}; }}
        QLineEdit:hover {{ background: {p.input_hover}; }}
        QLineEdit:focus {{ background: {p.input_hover}; border-color: {p.focus}; }}
        QScrollBar:vertical {{ background: transparent; width: 4px; margin: 2px; }}
        QScrollBar::handle:vertical {{ background: {p.scroll_handle};
            border-radius: 2px; min-height: 30px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: transparent; }}
    """


def row_qss(theme: str, hover: bool) -> str:
    p = palette(theme)
    background = p.row_hover if hover else "transparent"
    delete_color = p.muted if hover else "transparent"
    return f"""
        QFrame {{ background: {background}; border-radius: 10px; }}
        QLabel {{ color: {p.text}; background: transparent; }}
        QLineEdit {{ color: {p.text}; background: {p.input_hover};
            border: 1px solid {p.focus}; border-radius: 8px; padding: 2px 6px;
            placeholder-text-color: {p.muted};
            selection-background-color: {p.accent}; selection-color: {p.accent_text}; }}
        QToolButton#del {{ color: {delete_color}; background: transparent;
            border: none; font-size: 13px; }}
        QToolButton#del:hover {{ color: {p.danger}; }}
    """


def dialog_qss(theme: str) -> str:
    p = palette(theme)
    return f"""
        QDialog {{ background: transparent; color: {p.text}; }}
        QWidget#appearanceTitleBar {{ background: transparent; }}
        QLabel, QCheckBox {{ color: {p.text}; background: transparent; }}
        QSlider::groove:horizontal {{ height: 4px; background: {p.scroll_handle};
            border-radius: 2px; }}
        QSlider::sub-page:horizontal {{ background: {p.accent}; border-radius: 2px; }}
        QSlider::handle:horizontal {{ width: 14px; margin: -5px 0;
            background: {p.accent}; border: 1px solid {p.focus}; border-radius: 7px; }}
        QCheckBox {{ spacing: 8px; }}
        QCheckBox:disabled, QLabel:disabled {{ color: {p.muted}; }}
        QPushButton {{ color: {p.accent_text}; background: {p.accent};
            border: 1px solid transparent; border-radius: 6px; padding: 7px 20px; }}
        QPushButton:hover {{ background: {p.button_hover}; }}
        QPushButton:focus {{ border-color: {p.focus}; }}
        QPushButton:disabled {{ color: {p.muted}; background: {p.input}; }}
        QPushButton[themeOption="true"] {{ color: {p.text}; background: {p.input};
            border: 1px solid transparent; border-radius: 8px; padding: 6px 8px; }}
        QPushButton[themeOption="true"]:hover {{ background: {p.input_hover}; }}
        QPushButton[themeOption="true"]:checked {{ color: {p.accent_text};
            background: {p.accent}; border-color: {p.accent}; }}
        QPushButton[themeOption="true"]:checked:hover {{ background: {p.button_hover}; }}
        QPushButton[themeOption="true"]:focus {{ border-color: {p.focus}; }}
        QPushButton#appearanceCloseButton {{ color: {p.muted}; background: transparent;
            border: 1px solid transparent; border-radius: 8px; padding: 0; font-size: 20px; }}
        QPushButton#appearanceCloseButton:hover {{ color: {p.text}; background: {p.input}; }}
        QPushButton#appearanceCloseButton:focus {{ border-color: {p.focus}; }}
    """


def menu_qss(theme: str) -> str:
    p = palette(theme)
    return f"""
        QMenu {{ color: {p.text}; background: {p.surface};
            border: 1px solid {p.border}; border-radius: 7px; padding: 5px; }}
        QMenu::item {{ color: {p.text}; background: transparent;
            padding: 6px 22px 6px 12px; border-radius: 4px; }}
        QMenu::item:selected {{ color: {p.accent_text}; background: {p.accent}; }}
        QMenu::item:disabled {{ color: {p.muted}; }}
        QMenu::separator {{ height: 1px; background: {p.divider}; margin: 4px 7px; }}
    """
