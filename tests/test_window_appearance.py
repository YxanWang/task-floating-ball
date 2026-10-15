"""Appearance, task identity and delayed dragging use isolated app data."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from task_ball.appearance import Appearance, load_appearance
from task_ball.storage import AppPaths, new_task, save_tasks
from task_ball.window import TaskFloatingBall


class WindowAppearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="task-ball-appearance-window-")
        self.paths = AppPaths.from_directory(self.directory.name)
        self.tasks = [new_task("one"), new_task("two")]
        save_tasks(self.paths.tasks, self.tasks)
        self.window = TaskFloatingBall(paths=self.paths)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.directory.cleanup()

    def test_live_appearance_preserves_center_tasks_and_persists(self):
        self.window.move(200, 200)
        original_center = self.window.geometry().center()
        original_tasks = self.paths.tasks.read_bytes()
        for appearance in (Appearance("ocean", 80, False),
                           Appearance("moon", 54, True),
                           Appearance("amber", 40, True)):
            self.window.set_appearance(appearance)
            self.app.processEvents()
            self.assertEqual(self.window.width(), appearance.size)
            self.assertEqual(self.window.ball.width(), appearance.size)
            self.assertEqual(self.window.geometry().center(), original_center)
            self.assertEqual(load_appearance(self.paths.config), appearance)
            self.assertEqual(self.paths.tasks.read_bytes(), original_tasks)
            self.assertEqual(self.window.ball.scene.task_ids,
                             tuple(task["id"] for task in self.tasks))

    def test_position_save_keeps_appearance_after_dialog_close(self):
        selected = Appearance("moon", 80, False)
        self.window.set_appearance(selected)
        self.window.set_pinned(True)
        self.window._show_appearance_settings()
        dialog = self.window._appearance_dialog
        self.assertTrue(dialog.isVisible())
        dialog.done_button.click()
        self.app.processEvents()
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.window.ball.effects.isVisible())
        self.assertTrue(self.window._expanded)
        self.window.move(250, 180)
        self.window._save_config()
        self.assertEqual(load_appearance(self.paths.config), selected)
        config = json.loads(self.paths.config.read_text(encoding="utf-8"))
        self.assertEqual((config["x"], config["y"]), (250, 180))

    def test_drag_follows_then_settles_at_target(self):
        self.window.ball.set_reduced_motion(False)
        self.window.move(200, 200)
        self.window._start_drag()
        self.window._drag_move(QPoint(120, 35))
        self.assertEqual(self.window.pos(), QPoint(200, 200))
        self.window._advance_motion()
        self.assertNotEqual(self.window.pos(), QPoint(320, 235))
        self.window._after_drag()
        QTest.qWait(650)
        self.assertEqual(self.window.pos(), QPoint(320, 235))
        self.assertFalse(self.window._motion_timer.isActive())

    def test_panel_geometry_uses_new_ball_size(self):
        self.window.set_appearance(Appearance("ocean", 80, True))
        screen = self.app.primaryScreen().availableGeometry()
        self.window.move(screen.left() + 100, screen.top() + 100)
        rectangle, mirrored = self.window._panel_geometry()
        self.assertFalse(mirrored)
        self.assertEqual(rectangle.left(), self.window.x() + 80 + 10 + 28)
        self.assertLessEqual(rectangle.bottom(), screen.bottom())

    def test_opacity_reaches_all_floating_surfaces_and_restores_on_startup(self):
        original_tasks = self.paths.tasks.read_bytes()
        self.window._show_appearance_settings()
        dialog = self.window._appearance_dialog
        for percent in (30, 65, 100):
            dialog.opacity_slider.setValue(percent)
            self.app.processEvents()
            for surface in (self.window, self.window.panel, self.window.ball.effects):
                self.assertAlmostEqual(surface.windowOpacity(), percent / 100, delta=1/255)
            self.assertEqual(dialog.windowOpacity(), 1)
            self.assertEqual(self.window.appearance.opacity, percent)
            self.assertEqual(load_appearance(self.paths.config).opacity, percent)
            self.assertEqual(self.paths.tasks.read_bytes(), original_tasks)
        dialog.opacity_slider.setValue(65)
        other = TaskFloatingBall(paths=self.paths)
        try:
            self.assertEqual(other.appearance.opacity, 65)
            for surface in (other, other.panel, other.ball.effects):
                self.assertAlmostEqual(surface.windowOpacity(), .65, delta=1/255)
        finally:
            other.close()
            other.deleteLater()


if __name__ == "__main__":
    unittest.main()
