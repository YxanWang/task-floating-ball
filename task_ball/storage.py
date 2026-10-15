"""Task and position files shared by the GUI and command line."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
import uuid


@dataclass(frozen=True)
class AppPaths:
    directory: Path
    tasks: Path
    config: Path

    @classmethod
    def from_directory(cls, path: str | Path) -> "AppPaths":
        directory = Path(path).expanduser().resolve()
        return cls(directory, directory / "tasks.json", directory / "config.json")


def default_paths() -> AppPaths:
    """Keep portable app data beside the executable or source entry point."""
    if getattr(sys, "frozen", False):
        directory = Path(sys.executable).parent
    else:
        directory = Path(__file__).resolve().parent.parent
    return AppPaths.from_directory(directory)


def raw_bytes(path: str | Path) -> bytes:
    try:
        return Path(path).read_bytes()
    except OSError:
        return b""


def parse_tasks(raw: bytes) -> list[dict]:
    """Reject malformed documents and skip malformed or repeated task rows."""
    data = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError("任务文件的顶层必须是列表")

    tasks = []
    seen_ids = set()
    for task in data:
        if not isinstance(task, dict):
            continue
        task_id, text = task.get("id"), task.get("text")
        if not isinstance(task_id, str) or not task_id.strip():
            continue
        if not isinstance(text, str) or not text.strip():
            continue
        if task_id in seen_ids:
            continue
        seen_ids.add(task_id)
        tasks.append(task)
    return tasks


def load_tasks(path: str | Path) -> list[dict]:
    """A missing or invalid task file starts with an empty list."""
    try:
        return parse_tasks(raw_bytes(path))
    except (OSError, ValueError):
        return []


def _save_json(path: str | Path, value, *, indent: int | None = None) -> None:
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=indent)
    os.replace(temporary, path)


def save_tasks(path: str | Path, tasks: list[dict]) -> None:
    _save_json(path, tasks, indent=2)


def new_task(text: str) -> dict:
    return {"id": uuid.uuid4().hex[:8], "text": text}


def load_position(path: str | Path) -> tuple[int, int] | None:
    try:
        config = json.loads(raw_bytes(path).decode("utf-8-sig"))
        return int(config["x"]), int(config["y"])
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return None


def save_position(path: str | Path, x: int, y: int) -> None:
    save_config_merge(path, {"x": x, "y": y})


def load_config_dict(path: str | Path) -> dict:
    """Read portable settings, accepting old position-only configuration files."""
    try:
        config = json.loads(raw_bytes(path).decode("utf-8-sig"))
    except ValueError:
        return {}
    return config if isinstance(config, dict) else {}


def save_config_merge(path: str | Path, values: dict) -> None:
    """Replace selected settings while preserving other configuration keys."""
    config = load_config_dict(path)
    config.update(values)
    _save_json(path, config)
