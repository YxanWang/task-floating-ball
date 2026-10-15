"""External task updates preserve editor lifecycle and the external document."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from task_ball.storage import AppPaths, load_tasks, new_task, save_tasks
from task_ball.window import TaskFloatingBall


class ExternalRefreshEditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="task-ball-refresh-")
        self.paths = AppPaths.from_directory(self.directory.name)
        self.initial = [new_task("first task"), new_task("second task")]
        save_tasks(self.paths.tasks, self.initial)
        self.window = TaskFloatingBall(paths=self.paths)
        self.window.show()
        self.window.set_pinned(True)
        QTest.qWait(250)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.directory.cleanup()

    def begin_first_edit(self):
        row = self.window._row_map[self.initial[0]["id"]]
        row._start_edit()
        row._editor.setText("uncommitted local change")
        self.assertEqual(self.window._editing_count, 1)
        return row

    def external_document(self, tasks):
        # Retain distinct bytes so an unintended GUI write is detectable.
        raw = json.dumps(tasks, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8-sig")
        self.paths.tasks.write_bytes(raw)
        self.window._reload_external()
        return raw

    def test_removing_edited_row_releases_editing_state_without_writing_back(self):
        self.begin_first_edit()
        external = [self.initial[1]]
        raw = self.external_document(external)
        QTest.qWait(250)
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        self.assertEqual(self.window._editing_count, 0)
        self.assertNotIn(self.initial[0]["id"], self.window._row_map)
        self.assertEqual(self.window.tasks, external)
        self.assertEqual(load_tasks(self.paths.tasks), external)
        self.assertEqual(self.paths.tasks.read_bytes(), raw)

    def test_refreshing_same_id_keeps_editor_active_until_cancelled(self):
        row = self.begin_first_edit()
        editor = row._editor
        external = [dict(self.initial[0], text="external replacement"), self.initial[1]]
        raw = self.external_document(external)

        self.assertIs(self.window._row_map[self.initial[0]["id"]], row)
        self.assertIs(row._editor, editor)
        self.assertEqual(self.window._editing_count, 1)
        self.assertEqual(editor.text(), "uncommitted local change")
        row.cancel_edit()
        self.assertIsNone(row._editor)
        self.assertEqual(self.window._editing_count, 0)
        self.assertEqual(self.window.tasks, external)
        self.assertEqual(self.paths.tasks.read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
