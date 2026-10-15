"""Application bootstrap; task CLI commands do not import Qt."""
import ctypes
import hashlib
import sys

from .cli import run_cli
from .settings import APP_ID, APP_NAME, APP_VERSION
from .single_instance import SingleInstance
from .storage import AppPaths, default_paths


def main(argv=None, *, paths: AppPaths | None = None, instance_id=None,
         window_factory=None) -> int:
    arguments = list(sys.argv if argv is None else argv)
    paths = paths or default_paths()
    verification_dir = None
    instance_id = instance_id or APP_ID
    if len(arguments) > 1:
        if arguments[1] == "--verify":
            if len(arguments) != 3:
                return 2
            paths = AppPaths.from_directory(arguments[2])
            paths.directory.mkdir(parents=True, exist_ok=True)
            verification_dir = paths.directory
            directory_id = hashlib.sha256(
                str(paths.directory).casefold().encode("utf-8")).hexdigest()[:16]
            instance_id += ".Verify." + directory_id
        else:
            return run_cli(arguments, paths)

    if sys.platform != "win32":
        print("桌面界面目前仅支持 Windows。", file=sys.stderr)
        return 1

    # Set Windows application identity and DPI before constructing QApplication.
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except OSError:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except OSError:
        pass

    from PySide6.QtWidgets import QApplication
    from .window import TaskFloatingBall

    app = QApplication(arguments)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    instance = SingleInstance(instance_id, APP_NAME)
    if not instance.acquire():
        instance.activate_existing()
        return 0
    try:
        factory = window_factory or TaskFloatingBall
        window = factory(paths=paths)
        window.show()
        if verification_dir is not None:
            from .verification import start_verification
            start_verification(app, window, verification_dir)
        return app.exec()
    finally:
        instance.close()
