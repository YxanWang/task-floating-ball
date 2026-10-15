"""Edge compaction preserves normal ball coordinates, input and task data."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QCursor, QEnterEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

from task_ball.appearance import Appearance, load_appearance
from task_ball.docking import placement_for
from task_ball.storage import AppPaths, load_position, new_task, save_tasks
from task_ball.window import TaskFloatingBall


class WindowDockingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="task-ball-docking-")
        self.paths = AppPaths.from_directory(self.directory.name)
        self.tasks = [new_task("first docking task"), new_task("second docking task")]
        save_tasks(self.paths.tasks, self.tasks)
        self.original_tasks = self.paths.tasks.read_bytes()
        self.window = TaskFloatingBall(paths=self.paths)
        screen = self.app.primaryScreen().availableGeometry()
        self.bounds = screen.getRect()
        self.screen_patch = mock.patch.object(self.window, "_dock_screens", return_value=[self.bounds])
        self.pointer_patch = mock.patch.object(self.window, "_dock_pointer_inside", return_value=False)
        self.screen_patch.start()
        self.pointer_patch.start()
        self.addCleanup(self.screen_patch.stop)
        self.addCleanup(self.pointer_patch.stop)
        self.window.show()
        self.window.ball.set_reduced_motion(False)
        self.window.move(screen.left() + 170, screen.top() + 180)
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.directory.cleanup()

    def padding(self):
        return self.window._dock_padding()

    def dock_fixture(self, side="left", *, compact=True):
        """Stage a dock placement; drag/release discovery has its own test."""
        # A previous reveal gives the input focus. Close that fixture's panel
        # through its normal path before staging another unrelated placement.
        self.window._undock()
        self.window.panel.input.clearFocus()
        self.window._collapse()
        self.window._stop_panel_anims()
        self.window.panel.hide()
        self.assertFalse(self.window._expanded)
        left, top, _, _ = self.bounds
        target = placement_for(side, self.bounds, (left + 150, top + 180),
                               self.window.appearance.size, padding=self.padding())
        self.window._dock_target = target
        self.window.move(QPoint(*target.anchor))
        self.window._drag_target = QPointF(*target.anchor)
        self.window._motion_position = QPointF(*target.anchor)
        if compact:
            self.window._dock_compact(force=True)
            self.assertTrue(self.window._dock_collapsed, {
                "input_focus": self.window.panel.input.hasFocus(),
                "expanded": self.window._expanded, "blocked": self.window._dock_blocked(),
                "motion_active": self.window._motion_timer.isActive(),
                "reveal_active": self.window._dock_reveal_anim is not None,
            })
        self.app.processEvents()
        if compact:
            self.assertTrue(self.window._dock_collapsed)
        return target

    def assert_task_identity(self):
        self.assertEqual(self.paths.tasks.read_bytes(), self.original_tasks)
        self.assertEqual(self.window.tasks, self.tasks)
        self.assertEqual(self.window.ball.scene.task_ids, tuple(task["id"] for task in self.tasks))

    def drag_widget(self, widget, delta):
        center = widget.rect().center()
        destination = center + delta
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=center)
        QTest.mouseMove(widget, destination, delay=0)
        self.assertTrue(self.window._dragging)
        clamped_target = self.window._drag_target.toPoint()
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=destination)
        QTest.qWait(700)
        return clamped_target

    def enter_handle(self):
        handle = self.window.dock_handle
        center = handle.rect().center()
        event = QEnterEvent(QPointF(center), QPointF(center),
                            QPointF(handle.mapToGlobal(center)))
        # The production queue checks the cursor is genuinely over the handle.
        # Keep that structural input deterministic without moving the user's mouse.
        with mock.patch.object(QCursor, "pos", return_value=handle.mapToGlobal(center)):
            QApplication.sendEvent(handle, event)
            self.app.processEvents()

    def test_drag_release_near_edge_snaps_compacts_and_saves_ball_anchor(self):
        left, top, _, _ = self.bounds
        desired = QPoint(left + self.padding() + 7, top + 200)
        self.drag_widget(self.window.ball, desired - self.window.pos())
        target = self.window._dock_target
        self.assertIsNotNone(target)
        self.assertEqual(target.side, "left")
        self.assertTrue(self.window._dock_collapsed)
        self.assertTrue(self.window.dock_handle.isVisible())
        self.assertFalse(self.window.ball.isVisible())
        self.assertFalse(self.window.ball.effects.isVisible())
        self.assertFalse(self.window.ball._timer.isActive())
        self.assertEqual(self.window.dock_handle.mapToGlobal(QPoint()),
                         QPoint(*target.handle_rect[:2]))
        self.assertEqual((self.window.dock_handle.width(), self.window.dock_handle.height()),
                         target.handle_rect[2:])
        self.assertEqual(load_position(self.paths.config), target.anchor)
        self.assertNotEqual(load_position(self.paths.config),
                            tuple(target.handle_rect[:2]))
        self.assert_task_identity()

    def test_collapse_timer_cannot_compact_before_drag_motion_settles(self):
        left, top, _, _ = self.bounds
        self.window._start_drag()
        self.window._drag_move(QPoint(left + self.padding() - self.window.x(),
                                      top + 220 - self.window.y()))
        self.window._after_drag()
        self.assertTrue(self.window._motion_timer.isActive())
        self.assertIsNotNone(self.window._dock_target)
        self.window._collapse()
        self.app.processEvents()
        self.assertFalse(self.window._dock_collapsed)
        self.assertEqual(self.window.width(), self.window.appearance.size)
        QTest.qWait(700)
        self.assertTrue(self.window._dock_collapsed)
        self.assertEqual(self.window.geometry().getRect(), self.window._dock_target.handle_rect)
        self.assertFalse(self.window._motion_timer.isActive())
        self.assert_task_identity()

    def test_handle_hover_waits_before_revealing_ball_effects_and_panel(self):
        self.dock_fixture()
        with mock.patch.object(self.window, "_dock_pointer_inside", return_value=True):
            self.enter_handle()
            self.assertTrue(self.window._dock_collapsed)
            self.assertTrue(self.window._dock_hover_timer.isActive())
            QTest.qWait(self.window._dock_hover_timer.interval() + 180)
            self.assertFalse(self.window._dock_collapsed)
            self.assertFalse(self.window.dock_handle.isVisible())
            self.assertTrue(self.window.ball.isVisible())
            self.assertTrue(self.window.ball.effects.isVisible())
            self.assertTrue(self.window.ball._timer.isActive())
            self.assertEqual((self.window.width(), self.window.height()),
                             (self.window.appearance.size,) * 2)
            self.assertTrue(self.window._expanded)
            self.assertTrue(self.window.panel.isVisible())
        self.assert_task_identity()

    def test_leaving_handle_cancels_pending_reveal(self):
        self.dock_fixture()
        with mock.patch.object(self.window, "_dock_pointer_inside", return_value=True):
            self.enter_handle()
            self.assertTrue(self.window._dock_hover_timer.isActive())
        QApplication.sendEvent(self.window.dock_handle, QEvent(QEvent.Type.Leave))
        QApplication.sendEvent(self.window, QEvent(QEvent.Type.Leave))
        QTest.qWait(self.window._dock_hover_timer.interval() + 30)
        self.assertTrue(self.window._dock_collapsed)
        self.assertTrue(self.window.dock_handle.isVisible())
        self.assertFalse(self.window.ball.isVisible())
        self.assertFalse(self.window._dock_hover_timer.isActive())

    def test_pressing_handle_keeps_drag_capture_past_hover_delay(self):
        self.dock_fixture()
        handle = self.window.dock_handle
        center = handle.rect().center()
        with mock.patch.object(self.window, "_dock_pointer_inside", return_value=True):
            self.enter_handle()
            QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=center)
            QTest.qWait(self.window._dock_hover_timer.interval() + 30)
            self.assertTrue(self.window._dock_collapsed)
            self.assertTrue(handle.is_pressed())
            destination = center + QPoint(220, 0)
            QTest.mouseMove(handle, destination)
            self.assertTrue(self.window._dragging)
            QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=destination)
        QTest.qWait(700)
        self.assertFalse(self.window._dock_collapsed)
        self.assertIsNone(self.window._dock_target)
        self.assertTrue(self.window.ball.isVisible())
        self.assertFalse(handle.is_pressed())
        self.assert_task_identity()

    def test_context_menu_cancels_pending_hover_reveal(self):
        self.dock_fixture()
        with mock.patch.object(self.window, "_dock_pointer_inside", return_value=True):
            self.enter_handle()
            self.assertTrue(self.window._dock_hover_timer.isActive())

            def inspect_open_menu(_position):
                self.assertTrue(self.window._menu_open)
                self.assertFalse(self.window._dock_hover_timer.isActive())
                self.window._queue_dock_reveal()
                QTest.qWait(self.window._dock_hover_timer.interval() + 30)
                self.assertFalse(self.window._dock_hover_timer.isActive())
                self.assertTrue(self.window._dock_collapsed)

            class ObservedMenu(QMenu):
                def exec(self, position):
                    return inspect_open_menu(position)

            with mock.patch("task_ball.window.QMenu", ObservedMenu):
                self.window._show_context_menu(self.window.pos())
        self.assertFalse(self.window._menu_open)
        self.assert_task_identity()

    def test_leaving_expanded_panel_compacts_after_collapse_animation(self):
        self.dock_fixture()
        with mock.patch.object(self.window, "_dock_pointer_inside", return_value=True):
            self.window._dock_reveal()
            QTest.qWait(180)
            self.assertTrue(self.window._expanded)
        self.window.panel.input.clearFocus()
        with mock.patch.object(QApplication, "widgetAt", return_value=None):
            self.window._maybe_collapse()
            self.assertFalse(self.window._dock_collapsed)
            QTest.qWait(400)
        self.assertTrue(self.window._dock_collapsed)
        self.assertFalse(self.window.panel.isVisible())
        self.assertFalse(self.window.ball._timer.isActive())
        self.assert_task_identity()

    def test_pin_menu_and_editing_guards_prevent_compaction(self):
        self.dock_fixture(compact=False)
        for attribute, value in (("_pinned", True), ("_menu_open", True), ("_editing_count", 1)):
            with self.subTest(attribute=attribute):
                with mock.patch.object(self.window, attribute, value):
                    self.window._dock_compact()
                    self.assertFalse(self.window._dock_collapsed)
                    self.assertTrue(self.window.ball.isVisible())
                # Removing only that blocker makes the same placement compact.
                self.window._dock_compact()
                self.assertTrue(self.window._dock_collapsed)
                self.window._dock_reveal(expand=False)

    def test_open_settings_prevents_compaction_until_dialog_closes(self):
        self.dock_fixture()
        self.window._show_appearance_settings()
        dialog = self.window._appearance_dialog
        self.assertTrue(dialog.isVisible())
        self.window._dock_compact()
        self.assertFalse(self.window._dock_collapsed)
        self.assertTrue(self.window.ball.isVisible())
        dialog.close_button.click()
        self.window._dock_compact()
        self.assertTrue(self.window._dock_collapsed)
        self.assert_task_identity()

    def test_editing_task_blocks_outside_collapse_without_committing_draft(self):
        self.dock_fixture()
        with mock.patch.object(self.window, "_dock_pointer_inside", return_value=True):
            self.window._dock_reveal()
            QTest.qWait(180)
        row = self.window._row_map[self.tasks[0]["id"]]
        row._start_edit()
        editor = row._editor
        editor.setText("uncommitted docking draft")
        try:
            with mock.patch.object(QApplication, "widgetAt", return_value=None):
                self.window._maybe_collapse()
                QTest.qWait(200)
            self.assertFalse(self.window._dock_collapsed)
            self.assertTrue(self.window.panel.isVisible())
            self.assertIs(row._editor, editor)
            self.assertEqual(editor.text(), "uncommitted docking draft")
            self.assert_task_identity()
        finally:
            row.cancel_edit()
        self.window.panel.input.clearFocus()
        with mock.patch.object(QApplication, "widgetAt", return_value=None):
            self.window._maybe_collapse()
            QTest.qWait(400)
        self.assertTrue(self.window._dock_collapsed)
        self.assert_task_identity()

    def test_compact_appearance_changes_preserve_handle_center_and_normal_anchor(self):
        for side in ("left", "right", "top", "bottom"):
            with self.subTest(side=side):
                self.window._dock_reveal(expand=False)
                target = self.dock_fixture(side)
                x, y, width, height = target.handle_rect
                center = (2 * x + width, 2 * y + height)
                for appearance in (Appearance("moon", 80, False, 30),
                                   Appearance("ocean", 54, True, 65),
                                   Appearance("amber", 40, True)):
                    self.window.set_appearance(appearance)
                    self.app.processEvents()
                    updated = self.window._dock_target
                    nx, ny, nw, nh = updated.handle_rect
                    self.assertEqual(updated.side, side)
                    self.assertEqual((2 * nx + nw, 2 * ny + nh), center)
                    self.assertTrue(self.window._dock_collapsed)
                    self.assertTrue(self.window.dock_handle.isVisible())
                    self.assertEqual(self.window.dock_handle.theme, appearance.theme)
                    self.assertAlmostEqual(self.window.windowOpacity(), appearance.opacity / 100,
                                           delta=1/255)
                    self.assertFalse(self.window.ball.isVisible())
                    self.assertFalse(self.window.ball._timer.isActive())
                    self.assertEqual(load_position(self.paths.config), updated.anchor)
                    self.assertEqual(load_appearance(self.paths.config), appearance)
                    self.assert_task_identity()

    def test_reveal_keeps_core_four_pixels_from_every_edge_for_all_sizes_and_ships(self):
        for side in ("left", "right", "top", "bottom"):
            for size in (40, 80):
                for show_ships in (False, True):
                    with self.subTest(side=side, size=size, show_ships=show_ships):
                        self.window._undock()
                        self.window.set_appearance(Appearance("amber", size, show_ships))
                        target = self.dock_fixture(side)
                        hx, hy, hw, hh = target.handle_rect
                        with mock.patch.object(self.window, "_dock_pointer_inside", return_value=True):
                            self.window._dock_reveal()
                            self.assertIsNotNone(self.window._dock_reveal_anim)
                            self.assertTrue(self.window._dock_transitioning)
                            self.assertFalse(self.window.panel.isVisible())
                            QTest.qWait(180)
                            self.assertIsNone(self.window._dock_reveal_anim)
                            self.assertFalse(self.window._dock_transitioning)
                            self.assertTrue(self.window._expanded)
                            self.assertTrue(self.window.panel.isVisible())
                        x, y, width, height = self.bounds
                        gap = {"left": self.window.x() - x,
                               "right": x + width - self.window.x() - size,
                               "top": self.window.y() - y,
                               "bottom": y + height - self.window.y() - size}[side]
                        self.assertEqual(gap, 4)
                        if side in ("left", "right"):
                            self.assertEqual(2 * self.window.y() + size, 2 * hy + hh)
                        else:
                            self.assertEqual(2 * self.window.x() + size, 2 * hx + hw)
                        self.assertEqual(self.window.pos(), QPoint(*target.anchor))
                        self.assert_task_identity()

    def test_normal_drag_clamp_still_captures_edge_with_every_size_and_ships_setting(self):
        left, top, _, _ = self.bounds
        for size in (40, 80):
            for show_ships in (False, True):
                with self.subTest(size=size, show_ships=show_ships):
                    self.window._undock()
                    self.window.set_appearance(Appearance("amber", size, show_ships))
                    self.window.move(left + 170, top + 180)
                    desired = QPoint(left, top + 240)
                    clamped = self.drag_widget(self.window.ball, desired - self.window.pos())
                    # The free ball retains its ordinary visual padding. Edge
                    # capture must bridge that distance to the tighter dock.
                    self.assertGreater(clamped.x() - left, 4)
                    self.assertIsNotNone(self.window._dock_target)
                    self.assertEqual(self.window._dock_target.side, "left")
                    self.assertTrue(self.window._dock_collapsed)
                    self.window._dock_reveal(expand=False)
                    self.assertEqual(self.window.x() - left, 4)
                    self.assert_task_identity()

    def test_dragging_handle_or_revealed_ball_into_desktop_cancels_docking(self):
        for source in ("handle", "ball"):
            with self.subTest(source=source):
                self.dock_fixture()
                if source == "ball":
                    self.window._dock_reveal(expand=False)
                    widget = self.window.ball
                else:
                    widget = self.window.dock_handle
                self.drag_widget(widget, QPoint(150, 25))
                self.assertIsNone(self.window._dock_target)
                self.assertFalse(self.window._dock_collapsed)
                self.assertFalse(self.window.dock_handle.isVisible())
                self.assertTrue(self.window.ball.isVisible())
                self.assertTrue(self.window.ball.effects.isVisible())
                self.assertTrue(self.window.ball._timer.isActive())
                self.assertEqual(load_position(self.paths.config),
                                 (self.window.x(), self.window.y()))
                self.assert_task_identity()

    def test_toggling_ships_at_docked_corner_keeps_ball_and_handle_in_place(self):
        left, top, _, _ = self.bounds
        self.window.set_appearance(Appearance("ocean", 80, True))
        target = placement_for("left", self.bounds, (left, top), 80, padding=4)
        self.window._dock_target = target
        self.window.move(QPoint(*target.anchor))
        self.window.panel.input.clearFocus()
        self.window._dock_compact(force=True)
        for show_ships in (False, True, False):
            self.window.set_appearance(Appearance("ocean", 80, show_ships))
            self.assertEqual(self.window._dock_target.anchor, target.anchor)
            self.assertEqual(self.window._dock_target.handle_rect, target.handle_rect)
            self.assertTrue(self.window._dock_collapsed)
        self.assert_task_identity()

    def test_drag_release_at_shared_monitor_seam_does_not_dock(self):
        left, top, width, height = self.bounds
        adjacent = (left + width, top, width, height)
        desired = QPoint(left + width - self.window.width() - self.padding() - 7,
                         top + 200)
        with mock.patch.object(self.window, "_dock_screens", return_value=[self.bounds, adjacent]):
            self.drag_widget(self.window.ball, desired - self.window.pos())
        self.assertIsNone(self.window._dock_target)
        self.assertFalse(self.window._dock_collapsed)
        self.assertTrue(self.window.ball.isVisible())
        self.assert_task_identity()

    def test_release_in_monitor_gap_returns_to_real_work_area(self):
        screens = [(0, 0, 1920, 1080), (-1280, 200, 1280, 1024)]
        self.window._drag_target = QPointF(-500, 80)
        self.window._motion_position = QPointF(-500, 80)
        with mock.patch.object(self.window, "_dock_screens", return_value=screens):
            self.window._after_drag()
            QTest.qWait(700)
        target = self.window._dock_target
        self.assertIsNotNone(target)
        self.assertEqual(target.side, "top")
        self.assertTrue(QRect(*screens[1]).contains(
            QRect(*target.anchor, self.window.appearance.size, self.window.appearance.size)))
        self.assertTrue(self.window._dock_collapsed)
        self.assert_task_identity()

    def test_resizing_exposed_segment_into_monitor_seam_undocks(self):
        left, top, _, _ = self.bounds
        bounds = (left, top, 800, 600)
        screens = [bounds, (left + 800, top + 50, 800, 600)]
        self.window.set_appearance(Appearance("ocean", 40, True))
        target = placement_for("right", bounds, (left, top), 40,
                               padding=self.padding())
        self.window._dock_target = target
        self.window.move(QPoint(*target.anchor))
        self.window._dock_compact(force=True)
        with mock.patch.object(self.window, "_dock_screens", return_value=screens):
            self.window.set_appearance(Appearance("ocean", 80, True))
        self.assertIsNone(self.window._dock_target)
        self.assertFalse(self.window._dock_collapsed)
        self.assertTrue(self.window.ball.isVisible())
        self.assertFalse(self.window.dock_handle.isVisible())
        self.assertTrue(QRect(*bounds).contains(self.window.geometry()))
        self.assert_task_identity()


if __name__ == "__main__":
    unittest.main()
