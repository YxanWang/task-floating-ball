"""Dock reveal animations finish at their anchor and yield to user actions."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QEnterEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

from task_ball.appearance import Appearance, save_appearance
from task_ball.docking import placement_for
from task_ball.storage import AppPaths, load_position, new_task, save_tasks
from task_ball.window import TaskFloatingBall


class DockRevealTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="task-ball-reveal-")
        self.paths = AppPaths.from_directory(self.directory.name)
        save_appearance(self.paths.config, Appearance("amber", 40, True))
        save_tasks(self.paths.tasks, [new_task("reveal lifecycle fixture")])
        self.window = TaskFloatingBall(paths=self.paths)
        self.bounds = self.app.primaryScreen().availableGeometry().getRect()
        self.screens = mock.patch.object(self.window, "_dock_screens", return_value=[self.bounds])
        self.pointer = mock.patch.object(self.window, "_dock_pointer_inside", return_value=True)
        self.screens.start()
        self.pointer.start()
        self.addCleanup(self.screens.stop)
        self.addCleanup(self.pointer.stop)
        self.window.show()
        self.window.ball.set_reduced_motion(False)
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.directory.cleanup()

    def compact(self, side="left"):
        self.window._stop_dock_reveal(snap=True)
        left, top, _, _ = self.bounds
        target = placement_for(side, self.bounds, (left + 180, top + 180),
                               self.window.appearance.size, padding=4)
        self.window._dock_target = target
        self.window.move(QPoint(*target.anchor))
        self.window._motion_position = QPointF(*target.anchor)
        self.window._drag_target = QPointF(*target.anchor)
        # Showing the previous panel may focus its input; finish that interaction
        # before staging a different edge, rather than bypassing its focus guard.
        self.window.panel.input.clearFocus()
        self.window._dock_compact(force=True)
        self.app.processEvents()
        self.assertTrue(self.window._dock_collapsed)
        self.assertFalse(self.window.panel.isVisible())
        return target

    def reveal_in_progress(self, side="left"):
        target = self.compact(side)
        self.window._dock_reveal()
        self.assertIsNotNone(self.window._dock_reveal_anim)
        self.assertTrue(self.window._dock_transitioning)
        self.assertFalse(self.window.panel.isVisible())
        return target

    def test_hover_waits_for_reveal_before_opening_panel(self):
        target = self.compact()
        handle = self.window.dock_handle
        center = QPointF(handle.rect().center())
        QApplication.sendEvent(handle, QEnterEvent(
            center, center, QPointF(handle.mapToGlobal(center.toPoint()))))
        self.app.processEvents()
        self.assertTrue(self.window._dock_hover_timer.isActive())
        self.assertIsNone(self.window._dock_reveal_anim)
        QTest.qWait(self.window._dock_hover_timer.interval() + 25)
        animation = self.window._dock_reveal_anim
        self.assertIsNotNone(animation)
        self.assertEqual(animation.duration(), 140)
        self.assertNotEqual(self.window.pos(), QPoint(*target.anchor))
        self.assertFalse(self.window._expanded)
        self.assertFalse(self.window.panel.isVisible())
        QTest.qWait(170)
        self.assertIsNone(self.window._dock_reveal_anim)
        self.assertFalse(self.window._dock_transitioning)
        self.assertEqual(self.window.pos(), QPoint(*target.anchor))
        self.assertTrue(self.window._expanded)
        self.assertTrue(self.window.panel.isVisible())
        QTest.qWait(230)
        self.assertEqual(self.window.panel.geometry(), self.window._panel_geometry()[0])

    def test_all_four_revealed_edges_leave_four_pixels_for_large_ball(self):
        self.window.set_appearance(Appearance("ocean", 80, True))
        for side in ("left", "right", "top", "bottom"):
            with self.subTest(side=side):
                target = self.reveal_in_progress(side)
                QTest.qWait(180)
                self.assertIsNone(self.window._dock_reveal_anim)
                self.assertEqual(self.window.pos(), QPoint(*target.anchor))
                left, top, width, height = self.bounds
                gap = {
                    "left": self.window.x() - left,
                    "right": left + width - self.window.x() - self.window.width(),
                    "top": self.window.y() - top,
                    "bottom": top + height - self.window.y() - self.window.height(),
                }[side]
                self.assertEqual(gap, 4)
                self.assertTrue(self.window.panel.isVisible())

    def test_reduced_motion_reveals_and_expands_without_animation(self):
        target = self.compact()
        self.window.ball.set_reduced_motion(True)
        self.window._dock_reveal()
        self.assertIsNone(self.window._dock_reveal_anim)
        self.assertFalse(self.window._dock_transitioning)
        self.assertEqual(self.window.pos(), QPoint(*target.anchor))
        self.assertTrue(self.window._expanded)
        self.assertTrue(self.window.panel.isVisible())

    def test_drag_during_reveal_cancels_old_endpoint_and_panel_callback(self):
        target = self.reveal_in_progress()
        QTest.qWait(30)
        ball = self.window.ball
        center = ball.rect().center()
        destination = center + QPoint(200, 30)
        QTest.mousePress(ball, Qt.MouseButton.LeftButton, pos=center)
        QTest.mouseMove(ball, destination)
        self.assertTrue(self.window._dragging)
        self.assertIsNone(self.window._dock_reveal_anim)
        self.assertIsNone(self.window._dock_target)
        QTest.qWait(180)
        self.assertFalse(self.window._expanded)
        self.assertFalse(self.window.panel.isVisible())
        self.assertNotEqual(self.window.pos(), QPoint(*target.anchor))
        QTest.mouseRelease(ball, Qt.MouseButton.LeftButton, pos=destination)
        QTest.qWait(350)
        expected = self.window._drag_target.toPoint()
        self.assertIsNone(self.window._dock_target)
        self.assertEqual(self.window.pos(), expected)
        QTest.qWait(180)
        self.assertEqual(self.window.pos(), expected)
        self.assertFalse(self.window.panel.isVisible())

    def test_settings_interrupt_and_size_change_cannot_restore_old_anchor(self):
        old_target = self.reveal_in_progress()
        QTest.qWait(30)
        self.window._show_appearance_settings()
        self.assertIsNone(self.window._dock_reveal_anim)
        self.assertEqual(self.window.pos(), QPoint(*old_target.anchor))
        self.assertTrue(self.window._appearance_dialog.isVisible())
        self.window.set_appearance(Appearance("moon", 64, False, 65))
        expected = QPoint(*self.window._dock_target.anchor)
        self.assertNotEqual(expected, QPoint(*old_target.anchor))
        QTest.qWait(250)
        self.assertEqual(self.window.pos(), expected)
        self.assertFalse(self.window._expanded)
        self.assertFalse(self.window.panel.isVisible())
        self.assertTrue(self.window._appearance_dialog.isVisible())

    def test_context_menu_interrupt_cancels_late_panel_open(self):
        target = self.reveal_in_progress()
        QTest.qWait(30)
        test = self

        class ObservedMenu(QMenu):
            def exec(self, position):
                test.assertTrue(test.window._menu_open)
                test.assertIsNone(test.window._dock_reveal_anim)
                test.assertEqual(test.window.pos(), QPoint(*target.anchor))
                QTest.qWait(180)
                test.assertFalse(test.window.panel.isVisible())
                return None

        with mock.patch("task_ball.window.QMenu", ObservedMenu):
            self.window._show_context_menu(self.window.pos())
        self.assertFalse(self.window._menu_open)
        self.assertFalse(self.window._expanded)
        self.assertFalse(self.window.panel.isVisible())

    def test_undocking_during_reveal_has_no_delayed_expand(self):
        target = self.reveal_in_progress()
        QTest.qWait(30)
        self.window._undock()
        self.assertIsNone(self.window._dock_reveal_anim)
        self.assertIsNone(self.window._dock_target)
        self.assertEqual(self.window.pos(), QPoint(*target.anchor))
        QTest.qWait(220)
        self.assertEqual(self.window.pos(), QPoint(*target.anchor))
        self.assertFalse(self.window._expanded)
        self.assertFalse(self.window.panel.isVisible())

    def test_saving_reveal_start_and_midpoint_uses_final_visible_anchor(self):
        target = self.reveal_in_progress()
        self.assertFalse(QRect(*self.bounds).contains(self.window.geometry()))
        self.window._save_config()
        self.assertEqual(load_position(self.paths.config), target.anchor)
        QTest.qWait(40)
        self.assertNotEqual(self.window.pos(), QPoint(*target.anchor))
        self.window._save_config()
        self.assertEqual(load_position(self.paths.config), target.anchor)

    def test_closing_during_reveal_stops_all_delayed_visuals_and_saves_anchor(self):
        target = self.reveal_in_progress()
        QTest.qWait(30)
        self.window.close()
        self.assertIsNone(self.window._dock_reveal_anim)
        self.assertEqual(load_position(self.paths.config), target.anchor)
        QTest.qWait(220)
        self.assertFalse(self.window.isVisible())
        self.assertFalse(self.window.panel.isVisible())
        effects = self.window.ball.effects
        self.assertTrue(effects is None or not effects.isVisible())
        self.assertFalse(self.window.ball._timer.isActive())


if __name__ == "__main__":
    unittest.main()
