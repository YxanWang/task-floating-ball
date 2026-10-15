"""Appearance persistence and modeless controls use isolated configuration."""

from dataclasses import FrozenInstanceError
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QComboBox

from task_ball.appearance import Appearance, load_appearance, save_appearance
from task_ball.appearance_dialog import AppearanceDialog
from task_ball.storage import load_position, save_position


class AppearancePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="task-ball-appearance-")
        self.addCleanup(self.directory.cleanup)
        self.config = Path(self.directory.name) / "config.json"

    def test_defaults_and_legacy_position_configuration(self):
        self.assertEqual(load_appearance(self.config), Appearance("amber", 40, True))
        save_position(self.config, -100, 200)
        self.assertEqual(load_appearance(self.config), Appearance())
        self.assertEqual(load_position(self.config), (-100, 200))
        for raw in (b"broken", b"[]", b"null", b'{"appearance": []}',
                    b'{"appearance": null}'):
            with self.subTest(raw=raw):
                self.config.write_bytes(raw)
                self.assertEqual(load_appearance(self.config), Appearance())

    def test_strict_field_validation_and_immutable_values(self):
        for value in (True, False, 39, 41, 81, 48.0, "48", None):
            with self.subTest(size=value):
                self.assertEqual(Appearance(size=value).size, 40)
        for value in (None, "unknown", "AMBER", [], 1):
            with self.subTest(theme=value):
                self.assertEqual(Appearance(theme=value).theme, "amber")
        for value in (0, 1, "false", [], None):
            with self.subTest(show_ships=value):
                self.assertTrue(Appearance(show_ships=value).show_ships)
        for size in range(40, 81, 2):
            self.assertEqual(Appearance(size=size).size, size)
        for theme in ("ocean", "moon", "amber"):
            self.assertEqual(Appearance(theme, 80, False), Appearance(theme, 80, False))
        with self.assertRaises(FrozenInstanceError):
            Appearance().size = 60

    def test_invalid_config_fields_fall_back_independently(self):
        self.config.write_text(json.dumps({"appearance": {
            "theme": "moon", "size": True, "show_ships": False,
        }}), encoding="utf-8-sig")
        self.assertEqual(load_appearance(self.config), Appearance("moon", 40, False))

    def test_opacity_defaults_preserve_legacy_three_argument_construction(self):
        self.assertEqual(Appearance("moon", 54, False).opacity, 100)
        self.config.write_text(json.dumps({"appearance": {
            "theme": "ocean", "size": 64, "show_ships": False,
        }}), encoding="utf-8-sig")
        self.assertEqual(load_appearance(self.config), Appearance("ocean", 64, False, 100))

    def test_opacity_accepts_only_integer_percentages_between_30_and_100(self):
        for value in range(30, 101):
            with self.subTest(opacity=value):
                self.assertEqual(Appearance(opacity=value).opacity, value)
        for value in (True, False, 0, 29, 101, 60.0, "60", None, [], {}):
            with self.subTest(invalid_opacity=value):
                self.assertEqual(Appearance(opacity=value).opacity, 100)
                self.config.write_text(json.dumps({"appearance": {
                    "theme": "moon", "size": 48, "show_ships": False, "opacity": value,
                }}), encoding="utf-8")
                self.assertEqual(load_appearance(self.config), Appearance("moon", 48, False, 100))
        with self.assertRaises(FrozenInstanceError):
            Appearance().opacity = 60

    def test_opacity_round_trip_preserves_position_and_other_settings(self):
        self.config.write_text(json.dumps({
            "x": -120, "y": 345, "extra": {"setting": "保留"},
        }), encoding="utf-8-sig")
        appearance = Appearance("amber", 80, True, 65)
        save_appearance(self.config, appearance)
        self.assertEqual(load_appearance(self.config), appearance)
        self.assertEqual(load_position(self.config), (-120, 345))
        save_position(self.config, 456, -78)
        self.assertEqual(load_appearance(self.config), appearance)
        data = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertEqual(data["appearance"]["opacity"], 65)
        self.assertEqual(data["extra"], {"setting": "保留"})
        self.assertEqual((data["x"], data["y"]), (456, -78))

    def test_position_and_appearance_saves_preserve_each_other_and_unknown_keys(self):
        self.config.write_text(json.dumps({
            "x": 11, "y": -22, "extra": {"setting": "保留"},
        }), encoding="utf-8-sig")
        appearance = Appearance("ocean", 64, False)
        save_appearance(self.config, appearance)
        self.assertEqual(load_position(self.config), (11, -22))
        self.assertEqual(load_appearance(self.config), appearance)
        save_position(self.config, -500, 700)
        self.assertEqual(load_appearance(self.config), appearance)
        self.assertEqual(load_position(self.config), (-500, 700))
        data = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertEqual(data["extra"], {"setting": "保留"})
        self.assertFalse(self.config.with_suffix(".json.tmp").exists())

    def test_preferences_and_cli_import_without_qt(self):
        result = subprocess.run(
            [sys.executable, "-c", "import sys; import task_ball.appearance; "
             "import task_ball.cli; "
             "assert not any(name.startswith('PySide6') for name in sys.modules)"],
            cwd=PROJECT_DIR, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class AppearanceDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dialog = AppearanceDialog(appearance=Appearance())
        self.spy = QSignalSpy(self.dialog.appearanceChanged)

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_loading_preferences_does_not_emit_changes(self):
        for theme in ("moon", "ocean", "amber"):
            with self.subTest(theme=theme):
                appearance = Appearance(theme, 76, False)
                self.dialog.set_appearance(appearance)
                self.assertEqual(self.dialog.appearance(), appearance)
                self.assertEqual([name for name, button in self.dialog.theme_buttons.items()
                                  if button.isChecked()], [theme])
                self.assertEqual(self.dialog.theme, theme)
                self.assertEqual(self.dialog.size_slider.value(), 76)
                self.assertEqual(self.dialog.size_value.text(), "76 px")
                self.assertFalse(self.dialog.ships_checkbox.isChecked())
        self.assertEqual(self.spy.count(), 0)

    def test_controls_emit_live_valid_preferences_once_per_change(self):
        self.dialog.show()
        self.app.processEvents()
        button = self.dialog.theme_buttons["ocean"]
        QTest.mouseClick(button, Qt.MouseButton.LeftButton, pos=button.rect().center())
        self.assertEqual(self.spy.count(), 1)
        self.assertEqual(self.spy.at(0), [Appearance("ocean", 40, True)])
        self.dialog.size_slider.setValue(62)
        self.assertEqual(self.spy.count(), 2)
        self.assertEqual(self.spy.at(1), [Appearance("ocean", 62, True)])
        self.dialog.ships_checkbox.setChecked(False)
        self.assertEqual(self.spy.count(), 3)
        self.assertEqual(self.spy.at(2), [Appearance("ocean", 62, False)])
        self.dialog.size_slider.setValue(63)
        self.assertEqual(self.dialog.size_slider.value(), 62)
        self.assertEqual(self.spy.count(), 3)

    def test_theme_buttons_are_exclusive_and_reclick_does_not_emit_changes(self):
        self.dialog.show()
        self.app.processEvents()
        self.assertEqual(set(self.dialog.theme_buttons), {"ocean", "moon", "amber"})
        self.assertFalse(self.dialog.findChildren(QComboBox))
        self.assertTrue(all(button.isCheckable() for button in self.dialog.theme_buttons.values()))
        for count, theme in enumerate(("ocean", "moon", "amber"), 1):
            with self.subTest(theme=theme):
                button = self.dialog.theme_buttons[theme]
                QTest.mouseClick(button, Qt.MouseButton.LeftButton, pos=button.rect().center())
                self.assertEqual([name for name, control in self.dialog.theme_buttons.items()
                                  if control.isChecked()], [theme])
                self.assertEqual(self.dialog.theme, theme)
                self.assertEqual(self.dialog.appearance(), Appearance(theme, 40, True))
                self.assertEqual(self.spy.count(), count)
                QTest.mouseClick(button, Qt.MouseButton.LeftButton, pos=button.rect().center())
                self.assertTrue(button.isChecked())
                self.assertEqual(self.spy.count(), count)

    def test_custom_title_bar_close_keeps_preferences_without_emitting(self):
        self.dialog.show()
        self.app.processEvents()
        self.assertTrue(self.dialog.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.assertTrue(self.dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.assertTrue(self.dialog.title_bar.isVisible())
        self.assertTrue(self.dialog.close_button.isVisible())
        expected = Appearance("moon", 64, False)
        self.dialog.set_appearance(expected)
        self.assertEqual(self.spy.count(), 0)
        QTest.mouseClick(self.dialog.close_button, Qt.MouseButton.LeftButton,
                         pos=self.dialog.close_button.rect().center())
        self.assertFalse(self.dialog.isVisible())
        self.assertEqual(self.dialog.appearance(), expected)
        self.assertEqual(self.spy.count(), 0)

    def test_done_closes_modeless_dialog_without_resetting_or_emitting(self):
        self.dialog.show()
        self.app.processEvents()
        self.assertFalse(self.dialog.isModal())
        self.assertEqual(self.dialog.windowTitle(), "外观设置")
        self.assertTrue(self.dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.dialog.size_slider.setValue(80)
        QTest.mouseClick(self.dialog.done_button, Qt.MouseButton.LeftButton)
        self.assertFalse(self.dialog.isVisible())
        self.assertEqual(self.dialog.appearance(), Appearance("amber", 80, True))
        self.assertEqual(self.spy.count(), 1)


if __name__ == "__main__":
    unittest.main()
