"""Storage contract checks; all file access uses isolated temporary folders."""

from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from task_ball import storage


class TaskParsingTests(unittest.TestCase):
    def test_filters_invalid_rows_and_keeps_first_duplicate_and_extra_fields(self):
        first = {"id": "a", "text": " 首条 ", "source": {"script": True}}
        second = {"id": "b", "text": "第二条", "priority": 2}
        rows = [
            first, {"id": "a", "text": "重复"}, None, 1, "任务",
            {"text": "没有 ID"}, {"id": "", "text": "空 ID"},
            {"id": "  ", "text": "空白 ID"}, {"id": 3, "text": "数字 ID"},
            {"id": "c"}, {"id": "c", "text": " "},
            {"id": "c", "text": 12}, second,
        ]
        raw = json.dumps(rows, ensure_ascii=False).encode("utf-8-sig")
        self.assertEqual(storage.parse_tasks(raw), [first, second])

    def test_malformed_documents_raise_value_error(self):
        for raw in (b"", b"{", b"{}", b"null", b'"list"', b"\xff"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                storage.parse_tasks(raw)

    def test_new_task_preserves_text_and_has_short_hex_id(self):
        task = storage.new_task(" 中文任务 ")
        self.assertEqual(task["text"], " 中文任务 ")
        self.assertRegex(task["id"], r"^[0-9a-f]{8}$")


class StorageFileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="task-ball-storage-")
        self.addCleanup(self.directory.cleanup)
        self.paths = storage.AppPaths.from_directory(self.directory.name)

    def test_paths_are_normalized_and_immutable(self):
        paths = storage.AppPaths.from_directory(self.paths.directory / "." / "child" / "..")
        self.assertEqual(paths, self.paths)
        self.assertEqual(paths.tasks, paths.directory / "tasks.json")
        self.assertEqual(paths.config, paths.directory / "config.json")
        with self.assertRaises(FrozenInstanceError):
            paths.directory = Path("elsewhere")

    def test_default_paths_support_source_and_frozen_executable(self):
        with mock.patch.object(storage.sys, "frozen", False, create=True):
            self.assertEqual(storage.default_paths().directory,
                             Path(storage.__file__).resolve().parents[1])
        executable = self.paths.directory / "任务悬浮球.exe"
        with mock.patch.object(storage.sys, "frozen", True, create=True), \
                mock.patch.object(storage.sys, "executable", str(executable)):
            self.assertEqual(storage.default_paths(), self.paths)

    def test_missing_and_invalid_files_load_as_empty(self):
        self.assertEqual(storage.raw_bytes(self.paths.tasks), b"")
        self.assertEqual(storage.load_tasks(self.paths.tasks), [])
        for raw in (b"broken", b"{}", b"\xff"):
            with self.subTest(raw=raw):
                self.paths.tasks.write_bytes(raw)
                self.assertEqual(storage.load_tasks(self.paths.tasks), [])

    def test_temporarily_unreadable_file_is_safe_for_file_watchers(self):
        with mock.patch.object(Path, "read_bytes", side_effect=PermissionError("busy")):
            self.assertEqual(storage.raw_bytes(self.paths.tasks), b"")
            self.assertEqual(storage.load_tasks(self.paths.tasks), [])

    def test_task_round_trip_replaces_target_without_leaving_temporary_file(self):
        first = [{"id": "a", "text": "中文", "tag": "保留"}]
        storage.save_tasks(self.paths.tasks, first)
        self.assertEqual(storage.load_tasks(self.paths.tasks), first)
        self.assertIn("中文", self.paths.tasks.read_text(encoding="utf-8"))
        replacement = [{"id": "b", "text": "替换"}]
        storage.save_tasks(str(self.paths.tasks), replacement)
        self.assertEqual(storage.load_tasks(self.paths.tasks), replacement)
        self.assertFalse(self.paths.tasks.with_suffix(".json.tmp").exists())

    def test_position_round_trip_and_invalid_inputs(self):
        self.assertIsNone(storage.load_position(self.paths.config))
        storage.save_position(self.paths.config, -128, 920)
        self.assertEqual(storage.load_position(self.paths.config), (-128, 920))
        self.assertFalse(self.paths.config.with_suffix(".json.tmp").exists())
        self.paths.config.write_text('{"x": "40", "y": 80}', encoding="utf-8-sig")
        self.assertEqual(storage.load_position(self.paths.config), (40, 80))
        for raw in (b"bad", b"[]", b"null", b'{"x": 1}',
                    b'{"x": "bad", "y": 2}', b'{"x": null, "y": 2}'):
            with self.subTest(raw=raw):
                self.paths.config.write_bytes(raw)
                self.assertIsNone(storage.load_position(self.paths.config))


if __name__ == "__main__":
    unittest.main()
