"""Exercise permanent deletion through real widgets with isolated task files."""

import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from task_ball import window as module
from task_ball.storage import AppPaths


class PermanentDeletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="task-ball-delete-")
        self.paths = AppPaths.from_directory(self.directory.name)
        self.initial = [module.new_task(text) for text in ("first", "second", "third")]
        module.save_tasks(self.paths.tasks, self.initial)
        self.window = module.TaskFloatingBall(paths=self.paths)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.directory.cleanup()

    def assert_persisted(self, expected):
        self.assertEqual(self.window.tasks, expected)
        self.assertEqual(module.load_tasks(self.paths.tasks), expected)

    def test_delete_button_keeps_other_ids_order_and_persistence(self):
        task = self.initial[1]
        self.window._row_map[task["id"]].delb.click()
        self.assert_persisted([self.initial[0], self.initial[2]])
        self.assertNotIn(task["id"], self.window._row_map)
        self.assertEqual(self.window.ball._count, 2)
        self.assertTrue(self.window.panel.hint.isHidden())

    def test_clearing_inline_editor_permanently_deletes_task(self):
        row = self.window._row_map[self.initial[1]["id"]]
        row._start_edit()
        row._editor.clear()
        QTest.keyClick(row._editor, Qt.Key.Key_Return)
        self.assert_persisted([self.initial[0], self.initial[2]])
        self.assertEqual(self.window._editing_count, 0)
        self.assertNotIn(self.initial[1]["id"], self.window._row_map)

    def test_delete_all_then_add_with_return(self):
        for task in self.initial:
            self.window._row_map[task["id"]].delb.click()
        self.assert_persisted([])
        self.assertFalse(self.window.panel.hint.isHidden())
        self.assertTrue(self.window.panel.scroll.isHidden())
        self.assertEqual(self.window.ball._count, 0)
        self.assertEqual(self.window._panel_h(), 10 + 22 + 6 + 34 + 10)

        self.window.panel.input.setText("replacement task")
        QTest.keyClick(self.window.panel.input, Qt.Key.Key_Return)
        self.assertEqual(len(self.window.tasks), 1)
        added = self.window.tasks[0]
        self.assertEqual(added["text"], "replacement task")
        self.assertNotIn(added["id"], {task["id"] for task in self.initial})
        self.assertIn(added["id"], self.window._row_map)
        self.assertTrue(self.window.panel.hint.isHidden())
        self.assertFalse(self.window.panel.scroll.isHidden())
        self.assertEqual(self.window.ball._count, 1)
        self.assertEqual(self.window.panel.input.text(), "")
        self.assert_persisted([added])

    def test_undo_controls_and_history_are_absent(self):
        self.window._row_map[self.initial[0]["id"]].delb.click()
        for name in ("undo_bar", "undo_button", "undo_hint"):
            self.assertFalse(hasattr(self.window.panel, name), name)
        self.assertFalse(hasattr(self.window, "_undo_stack"))
        self.assertFalse(hasattr(self.window, "_undo_delete"))

    def test_external_reload_does_not_restore_deleted_task(self):
        self.window._row_map[self.initial[1]["id"]].delb.click()
        added = module.new_task("external task")
        external = [self.initial[0], self.initial[2], added]
        module.save_tasks(self.paths.tasks, external)
        self.window._reload_external()
        self.assert_persisted(external)
        self.assertNotIn(self.initial[1]["id"], self.window._row_map)

    def test_delete_and_add_keep_bottom_aligned_panel_inside_screen(self):
        screen = self.app.primaryScreen().availableGeometry()
        self.window.move(screen.left() + 30, screen.bottom() - self.window.height() + 1)
        self.window.show()
        self.app.processEvents()
        geometry, mirrored = self.window._panel_geometry()
        self.window._panel_mirrored = mirrored
        self.window._expanded = True
        self.window._pinned = True
        self.window.panel.setFixedSize(geometry.size())
        self.window.panel.move(geometry.topLeft())
        self.window.panel.show()
        self.app.processEvents()

        for task in self.initial:
            self.window._row_map[task["id"]].delb.click()
            QTest.qWait(250)
            self.assertLessEqual(self.window.panel.geometry().bottom(), screen.bottom())
            self.assertGreaterEqual(self.window.panel.geometry().top(), screen.top())
        self.assertTrue(self.window.panel.hint.isVisible())
        self.assertEqual(self.window.panel.height(), self.window._panel_h())
        self.window.panel.input.setText("new task after empty list")
        QTest.keyClick(self.window.panel.input, Qt.Key.Key_Return)
        QTest.qWait(250)
        self.assertLessEqual(self.window.panel.geometry().bottom(), screen.bottom())
        self.assertGreaterEqual(self.window.panel.geometry().top(), screen.top())
        self.assertEqual(self.window.panel.height(), self.window._panel_h())
        self.assertTrue(self.window.panel.input.isVisible())
        self.assertEqual(self.window.ball._count, 1)


if __name__ == "__main__":
    unittest.main()
