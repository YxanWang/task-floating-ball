"""Exercise the actual native context-menu path using isolated task storage."""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


PROJECT_DIR = Path(__file__).resolve().parents[1]

WORKER = r"""
import ctypes
from ctypes import wintypes
import json
import os
import sys
import tempfile

os.environ.pop("QT_QPA_PLATFORM", None)
os.environ.pop("TASK_FLOATING_BALL_AUTOPIN", None)
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu
from task_ball.storage import AppPaths, load_config_dict, save_position
from task_ball.window import TaskFloatingBall

mode = sys.argv[2]
app = QApplication([])
app.setQuitOnLastWindowClosed(False)
user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.IsWindowVisible.argtypes = (wintypes.HWND,)
user32.IsWindowVisible.restype = wintypes.BOOL
events = []
errors = []
sys.excepthook = lambda kind, value, trace: errors.append(repr(value))


class ObservedWindow(TaskFloatingBall):
    def _show_appearance_settings(self):
        popup = app.activePopupWidget()
        events.append({"event": "appearance_slot_entered", "menu_flag": self._menu_open,
                       "active_popup": type(popup).__name__ if popup else None})
        super()._show_appearance_settings()


with tempfile.TemporaryDirectory(prefix="task-ball-native-menu-") as directory:
    paths = AppPaths.from_directory(directory)
    save_position(paths.config, 120, 160)
    window = ObservedWindow(paths=paths)
    window.setWindowTitle("TaskBall isolated menu test")

    class ContextObserver(QObject):
        def eventFilter(self, watched, event):
            if event.type() == QEvent.Type.ContextMenu:
                events.append({"event": "context_delivery",
                               "target": "ball" if watched is window.ball else "window"})
            return False

    observer = ContextObserver()
    window.installEventFilter(observer)
    window.ball.installEventFilter(observer)
    window.show()

    def select_action():
        popup = app.activePopupWidget()
        events.append({"event": "menu_open", "type": type(popup).__name__,
                       "visible": bool(popup and popup.isVisible())})
        if not isinstance(popup, QMenu):
            QTimer.singleShot(0, inspect_dialog)
            return
        if mode == "mouse":
            action = next(action for action in popup.actions()
                          if action.text().startswith("外观设置"))
            QTest.mouseClick(popup, Qt.MouseButton.LeftButton,
                             pos=popup.actionGeometry(action).center())
        else:
            QTest.keyClick(popup, Qt.Key.Key_Down)
            QTest.keyClick(popup, Qt.Key.Key_Down)
            events.append({"event": "keyboard_selection",
                           "active": popup.activeAction().text()})
            QTest.keyClick(popup, Qt.Key.Key_Return)
        events.append({"event": "action_selected", "mode": mode})
        QTimer.singleShot(300, inspect_dialog)

    def inspect_dialog():
        dialog = window._appearance_dialog
        popup = app.activePopupWidget()
        events.append({"event": "dialog_after_menu", "created": dialog is not None,
                       "visible": bool(dialog and dialog.isVisible()),
                       "native_visible": bool(dialog and user32.IsWindowVisible(int(dialog.winId()))),
                       "enabled": bool(dialog and dialog.isEnabled()),
                       "active": bool(dialog and dialog.isActiveWindow()),
                       "active_popup": type(popup).__name__ if popup else None,
                       "active_window": app.activeWindow().windowTitle()
                                        if app.activeWindow() else None,
                       "menu_flag": window._menu_open,
                       "controls_enabled": [control.isEnabled() for control in
                           (*dialog.theme_buttons.values(), dialog.size_slider, dialog.opacity_slider,
                            dialog.ships_checkbox, dialog.done_button,
                            dialog.close_button)] if dialog else []})
        if dialog is not None:
            dialog.size_slider.setFocus()
            QTest.keyClick(dialog.size_slider, Qt.Key.Key_Right)
            events.append({"event": "settings_changed", "size": window.appearance.size,
                           "stored": load_config_dict(paths.config).get("appearance")})
            QTest.mouseClick(dialog.done_button, Qt.MouseButton.LeftButton)
            events.append({"event": "done_clicked", "visible": dialog.isVisible(),
                           "ball_visible": window.isVisible()})
        window.close()

    def open_menu():
        QTimer.singleShot(150, select_action)
        point = window.ball.rect().center()
        event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point,
                                 window.ball.mapToGlobal(point))
        QApplication.sendEvent(window.ball, event)
        events.append({"event": "context_returned", "accepted": event.isAccepted(),
                       "menu_flag": window._menu_open})

    def watchdog():
        events.append({"event": "watchdog"})
        popup = app.activePopupWidget()
        if popup:
            popup.close()
        window.close()

    QTimer.singleShot(400, open_menu)
    QTimer.singleShot(5000, watchdog)
    app.exec()
    print(json.dumps({"events": events, "errors": errors}, ensure_ascii=True), flush=True)
"""


@unittest.skipUnless(sys.platform == "win32", "requires the native Windows Qt plugin")
@unittest.skipIf(os.environ.get("TASK_FLOATING_BALL_SKIP_NATIVE_TESTS") == "1",
                 "requires an interactive Windows desktop; run locally")
class NativeContextMenuTests(unittest.TestCase):
    def exercise_menu(self, mode):
        environment = dict(os.environ)
        environment.pop("QT_QPA_PLATFORM", None)
        result = subprocess.run(
            [sys.executable, "-u", "-c", WORKER, str(PROJECT_DIR), mode],
            cwd=PROJECT_DIR, env=environment, capture_output=True,
            text=True, encoding="utf-8", timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(payload["errors"], [], payload)
        events = payload["events"]
        self.assertFalse(any(item["event"] == "watchdog" for item in events), payload)
        deliveries = [item for item in events if item["event"] == "context_delivery"]
        self.assertEqual(deliveries, [{"event": "context_delivery", "target": "ball"}])
        opening = next(item for item in events if item["event"] == "appearance_slot_entered")
        self.assertFalse(opening["menu_flag"], payload)
        self.assertIsNone(opening["active_popup"], payload)
        dialog = next(item for item in events if item["event"] == "dialog_after_menu")
        # Foreground activation is controlled by Windows and the user's focus.
        # Retain it in diagnostics while requiring actual native visibility.
        for name in ("created", "visible", "native_visible", "enabled"):
            self.assertTrue(dialog[name], payload)
        self.assertEqual(dialog["controls_enabled"], [True] * 8, payload)
        self.assertIsNone(dialog["active_popup"], payload)
        self.assertFalse(dialog["menu_flag"], payload)
        changed = next(item for item in events if item["event"] == "settings_changed")
        self.assertEqual(changed["size"], 42, payload)
        self.assertEqual(changed["stored"]["size"], 42, payload)
        done = next(item for item in events if item["event"] == "done_clicked")
        self.assertFalse(done["visible"], payload)
        self.assertTrue(done["ball_visible"], payload)
        return payload

    def test_mouse_menu_selection_opens_usable_appearance_dialog(self):
        self.exercise_menu("mouse")

    def test_keyboard_menu_selection_opens_usable_appearance_dialog(self):
        self.exercise_menu("keyboard")


if __name__ == "__main__":
    unittest.main()
