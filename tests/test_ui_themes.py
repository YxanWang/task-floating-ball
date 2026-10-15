"""Theme changes reach live widgets without replacing task editors or data."""

import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from task_ball.appearance import Appearance, load_appearance, save_appearance
from task_ball.storage import AppPaths, new_task, save_tasks
from task_ball.themes import palette
from task_ball.window import TaskFloatingBall


THEMES = ("amber", "ocean", "moon")


def contrast_ratio(foreground, background):
    """WCAG relative luminance for the actual opaque semantic color roles."""
    def luminance(color):
        channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4
                  for value in channels]
        return sum(value * weight for value, weight in zip(linear, (.2126, .7152, .0722)))

    lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (lighter + .05) / (darker + .05)


class LiveThemeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="task-ball-themes-")
        self.paths = AppPaths.from_directory(self.directory.name)
        self.initial = [new_task("existing first task"), new_task("existing second task")]
        save_tasks(self.paths.tasks, self.initial)
        self.windows = []

    def tearDown(self):
        for window in reversed(self.windows):
            window.close()
            window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.directory.cleanup()

    def make_window(self):
        window = TaskFloatingBall(paths=self.paths)
        self.windows.append(window)
        window.show()
        window.set_pinned(True)
        self.app.processEvents()
        return window

    def assert_text_color(self, widget, role, expected):
        widget.ensurePolished()
        self.assertEqual(widget.palette().color(role).name(), QColor(expected).name())

    def test_each_theme_updates_ball_panel_existing_new_rows_and_dialog(self):
        window = self.make_window()
        original_row = window._row_map[self.initial[0]["id"]]
        panel_samples = []
        for theme in THEMES:
            with self.subTest(theme=theme):
                colors = palette(theme)
                appearance = Appearance(theme, 48, True)
                window.set_appearance(appearance)
                self.app.processEvents()
                self.assertEqual(window.ball.scene.theme, theme)
                self.assertEqual(window.panel.theme, theme)
                self.assertIs(window._row_map[self.initial[0]["id"]], original_row)
                for row in window._row_map.values():
                    self.assertEqual(row.theme, theme)
                    self.assert_text_color(row.label, QPalette.ColorRole.WindowText, colors.text)
                self.assert_text_color(window.panel.input, QPalette.ColorRole.Text, colors.text)
                self.assert_text_color(window.panel.head_title,
                                       QPalette.ColorRole.WindowText, colors.muted)
                panel_image = window.panel.grab().toImage()
                panel_samples.append(panel_image.pixelColor(5, panel_image.height() // 2).rgba())

                window._show_appearance_settings()
                self.app.processEvents()
                dialog = window._appearance_dialog
                self.assertEqual(dialog.theme, theme)
                self.assertEqual(dialog.appearance(), appearance)
                self.assertEqual([name for name, button in dialog.theme_buttons.items()
                                  if button.isChecked()], [theme])
                self.assert_text_color(dialog.ships_checkbox,
                                       QPalette.ColorRole.WindowText, colors.text)
                self.assert_text_color(dialog.done_button,
                                       QPalette.ColorRole.ButtonText, colors.accent_text)
                dialog.close()
                self.app.processEvents()

                window.panel.input.setText("new task for " + theme)
                window._add_from_input()
                new_row = window._row_map[window.tasks[-1]["id"]]
                self.assertEqual(new_row.theme, theme)
                self.assert_text_color(new_row.label, QPalette.ColorRole.WindowText, colors.text)
        # The panel is hand-painted, so a changed theme field/QSS alone is not
        # sufficient: a pixel away from all children must actually change too.
        self.assertEqual(len(set(panel_samples)), len(THEMES))

    def test_theme_changes_keep_active_editor_selection_and_task_file(self):
        window = self.make_window()
        window.set_appearance(Appearance("amber", 48, True))
        row = window._row_map[self.initial[0]["id"]]
        row._start_edit()
        editor = row._editor
        editor.setText("uncommitted theme editing draft")
        editor.setSelection(5, 11)
        before = (editor.text(), editor.selectedText(), editor.selectionStart(), editor.cursorPosition())
        raw_tasks = self.paths.tasks.read_bytes()
        try:
            for theme in THEMES:
                with self.subTest(theme=theme):
                    window.set_appearance(Appearance(theme, 48, True))
                    self.app.processEvents()
                    self.assertIs(window._row_map[self.initial[0]["id"]], row)
                    self.assertIs(row._editor, editor)
                    self.assertEqual((editor.text(), editor.selectedText(), editor.selectionStart(),
                                      editor.cursorPosition()), before)
                    self.assertEqual(window._editing_count, 1)
                    self.assertEqual(window.tasks, self.initial)
                    self.assertEqual(self.paths.tasks.read_bytes(), raw_tasks)
                    self.assert_text_color(editor, QPalette.ColorRole.Text, palette(theme).text)
        finally:
            row.cancel_edit()

    def test_saved_preferences_style_panel_rows_and_dialog_on_startup(self):
        raw_tasks = self.paths.tasks.read_bytes()
        for theme in THEMES:
            with self.subTest(theme=theme):
                expected = Appearance(theme, 64, False)
                save_appearance(self.paths.config, expected)
                window = self.make_window()
                self.assertEqual(window.appearance, expected)
                self.assertEqual(load_appearance(self.paths.config), expected)
                self.assertEqual(window.ball.scene.theme, theme)
                self.assertEqual(window.panel.theme, theme)
                self.assertTrue(all(row.theme == theme for row in window._row_map.values()))
                self.assert_text_color(window.panel.input,
                                       QPalette.ColorRole.Text, palette(theme).text)
                window._show_appearance_settings()
                self.app.processEvents()
                self.assertEqual(window._appearance_dialog.theme, theme)
                self.assertEqual(window._appearance_dialog.appearance(), expected)
                self.assertEqual([name for name, button in window._appearance_dialog.theme_buttons.items()
                                  if button.isChecked()], [theme])
                self.assertEqual(self.paths.tasks.read_bytes(), raw_tasks)
                window.close()

    def test_moon_text_roles_keep_at_least_4_5_contrast(self):
        colors = palette("moon")
        pairs = [(foreground, background)
                 for foreground in ("text", "muted")
                 for background in ("surface", "input", "input_hover")]
        pairs += [("accent_text", "accent"), ("accent_text", "button_hover")]
        for foreground, background in pairs:
            with self.subTest(foreground=foreground, background=background):
                self.assertGreaterEqual(contrast_ratio(getattr(colors, foreground),
                                                      getattr(colors, background)), 4.5)


if __name__ == "__main__":
    unittest.main()
