"""Validated floating-ball preferences, independent of the GUI toolkit."""

from dataclasses import asdict, dataclass
from pathlib import Path

from .storage import load_config_dict, save_config_merge


THEMES = ("ocean", "moon", "amber")


@dataclass(frozen=True)
class Appearance:
    theme: str = "amber"
    size: int = 40
    show_ships: bool = True
    opacity: int = 100

    def __post_init__(self):
        if not isinstance(self.theme, str) or self.theme not in THEMES:
            object.__setattr__(self, "theme", "amber")
        if type(self.size) is not int or not 40 <= self.size <= 80 or self.size % 2:
            object.__setattr__(self, "size", 40)
        if type(self.show_ships) is not bool:
            object.__setattr__(self, "show_ships", True)
        if type(self.opacity) is not int or not 30 <= self.opacity <= 100:
            object.__setattr__(self, "opacity", 100)


def load_appearance(path: str | Path) -> Appearance:
    values = load_config_dict(path).get("appearance")
    if not isinstance(values, dict):
        return Appearance()
    return Appearance(
        theme=values.get("theme", "amber"),
        size=values.get("size", 40),
        show_ships=values.get("show_ships", True),
        opacity=values.get("opacity", 100),
    )


def save_appearance(path: str | Path, appearance: Appearance) -> None:
    save_config_merge(path, {"appearance": asdict(appearance)})
