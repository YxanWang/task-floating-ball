"""Exercise widget signals without a main window or persistent application data."""

import os
from pathlib import Path
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from task_ball.settings import ROW_LABEL_W
from task_ball.widgets import Ball, PanelWindow, TaskRow


class WidgetSignalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def show_widget(self, widget):
        self.widgets.append(widget)
        widget.show()
        self.app.processEvents()
        return widget

    def make_row(self):
        row = self.show_widget(TaskRow(
            {"id": "example", "text": "original task"}, ROW_LABEL_W))
        return row

    def begin_edit(self, row):
        QTest.mouseDClick(row.label, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertIsNotNone(row._editor)
        return row._editor

    def test_double_click_and_return_emit_one_edit_lifecycle(self):
        row = self.make_row()
        started = QSignalSpy(row.editingStarted)
        finished = QSignalSpy(row.editingFinished)
        edited = QSignalSpy(row.edited)
        deleted = QSignalSpy(row.deleted)

        editor = self.begin_edit(row)
        QTest.keyClicks(editor, "updated task")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.app.processEvents()

        self.assertEqual(started.count(), 1)
        self.assertEqual(finished.count(), 1)
        self.assertEqual(edited.count(), 1)
        self.assertEqual(edited.at(0), ["example", "updated task"])
        self.assertEqual(deleted.count(), 0)
        self.assertIsNone(row._editor)

    def test_escape_finishes_once_without_saving_or_deleting(self):
        row = self.make_row()
        started = QSignalSpy(row.editingStarted)
        finished = QSignalSpy(row.editingFinished)
        edited = QSignalSpy(row.edited)
        deleted = QSignalSpy(row.deleted)

        editor = self.begin_edit(row)
        QTest.keyClicks(editor, "discarded change")
        QTest.keyClick(editor, Qt.Key.Key_Escape)
        self.app.processEvents()

        self.assertEqual(started.count(), 1)
        self.assertEqual(finished.count(), 1)
        self.assertEqual(edited.count(), 0)
        self.assertEqual(deleted.count(), 0)
        self.assertEqual(row.task["text"], "original task")
        self.assertIsNone(row._editor)

    def test_empty_edit_emits_deletion_once(self):
        row = self.make_row()
        finished = QSignalSpy(row.editingFinished)
        deleted = QSignalSpy(row.deleted)
        edited = QSignalSpy(row.edited)

        editor = self.begin_edit(row)
        QTest.keyClick(editor, Qt.Key.Key_Backspace)
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.app.processEvents()

        self.assertEqual(finished.count(), 1)
        self.assertEqual(deleted.count(), 1)
        self.assertEqual(deleted.at(0), ["example"])
        self.assertEqual(edited.count(), 0)

    def test_delete_button_emits_task_id_without_main_window(self):
        row = self.make_row()
        deleted = QSignalSpy(row.deleted)

        QTest.mouseClick(row.delb, Qt.MouseButton.LeftButton)

        self.assertEqual(deleted.count(), 1)
        self.assertEqual(deleted.at(0), ["example"])

    def test_panel_return_requests_submission_without_owning_data(self):
        panel = self.show_widget(PanelWindow())
        submitted = QSignalSpy(panel.submitted)

        QTest.keyClicks(panel.input, "new task")
        QTest.keyClick(panel.input, Qt.Key.Key_Return)

        self.assertEqual(submitted.count(), 1)
        self.assertEqual(panel.input.text(), "new task")

    def test_ball_click_does_not_start_drag(self):
        ball = self.show_widget(Ball())
        clicked = QSignalSpy(ball.clicked)
        started = QSignalSpy(ball.dragStarted)
        finished = QSignalSpy(ball.dragFinished)

        QTest.mouseClick(ball, Qt.MouseButton.LeftButton,
                         pos=ball.rect().center())

        self.assertEqual(clicked.count(), 1)
        self.assertEqual(started.count(), 0)
        self.assertEqual(finished.count(), 0)

    def test_ball_drag_emits_motion_without_main_window(self):
        ball = self.show_widget(Ball())
        clicked = QSignalSpy(ball.clicked)
        started = QSignalSpy(ball.dragStarted)
        moved = QSignalSpy(ball.dragMoved)
        finished = QSignalSpy(ball.dragFinished)
        origin = ball.rect().center()
        target = origin + QPoint(12, 7)

        QTest.mousePress(ball, Qt.MouseButton.LeftButton, pos=origin)
        QTest.mouseMove(ball, target)
        QTest.mouseRelease(ball, Qt.MouseButton.LeftButton, pos=target)

        self.assertEqual(started.count(), 1)
        self.assertEqual(moved.count(), 1)
        self.assertEqual(moved.at(0), [QPoint(12, 7)])
        self.assertEqual(finished.count(), 1)
        self.assertEqual(clicked.count(), 0)


if __name__ == "__main__":
    unittest.main()
