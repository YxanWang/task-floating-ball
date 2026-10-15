"""CLI behavior with injected paths, without opening the GUI or real app data."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
from task_ball.cli import run_cli
from task_ball.storage import AppPaths, load_tasks, save_tasks


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="task-ball-cli-")
        self.addCleanup(self.directory.cleanup)
        self.paths = AppPaths.from_directory(self.directory.name)

    def run_command(self, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            code = run_cli(["task_floating_ball.py", *args], self.paths)
        return code, output.getvalue()

    def test_empty_list_and_add_join_arguments(self):
        self.assertEqual(self.run_command("list"), (0, "(暂无任务)\n"))
        self.assertEqual(self.run_command("add", "  中文", "task  "),
                         (0, "已添加: 中文 task\n"))
        self.assertEqual(self.run_command("list"), (0, "1. 中文 task\n"))
        self.assertEqual(load_tasks(self.paths.tasks)[0]["text"], "中文 task")

    def test_delete_uses_current_display_order_and_preserves_remaining_fields(self):
        initial = [{"id": "a", "text": "第一项", "tag": "保留"},
                   {"id": "b", "text": "第二项"},
                   {"id": "c", "text": "第三项"}]
        save_tasks(self.paths.tasks, initial)
        self.assertEqual(self.run_command("list"),
                         (0, "1. 第一项\n2. 第二项\n3. 第三项\n"))
        self.assertEqual(self.run_command("del", "2"), (0, "已删除: 第二项\n"))
        self.assertEqual(load_tasks(self.paths.tasks), [initial[0], initial[2]])
        self.assertEqual(self.run_command("list"), (0, "1. 第一项\n2. 第三项\n"))
        self.assertEqual(self.run_command("del", "2"), (0, "已删除: 第三项\n"))
        self.assertEqual(load_tasks(self.paths.tasks), [initial[0]])

    def test_invalid_commands_do_not_change_tasks(self):
        initial = [{"id": "a", "text": "留着"}]
        save_tasks(self.paths.tasks, initial)
        raw = self.paths.tasks.read_bytes()
        cases = [
            (("add",), "用法: python task_floating_ball.py add <任务内容>\n"),
            (("add", "  "), "用法: python task_floating_ball.py add <任务内容>\n"),
            (("del",), "用法: python task_floating_ball.py del <序号>\n"),
            (("del", "bad"), "用法: python task_floating_ball.py del <序号>\n"),
            (("del", "0"), "序号超出范围，共 1 条（先 list 查看）\n"),
            (("del", "-1"), "序号超出范围，共 1 条（先 list 查看）\n"),
            (("del", "2"), "序号超出范围，共 1 条（先 list 查看）\n"),
            (("unknown",), "未知命令: unknown\n"),
        ]
        for args, output in cases:
            with self.subTest(args=args):
                self.assertEqual(self.run_command(*args), (1, output))
                self.assertEqual(self.paths.tasks.read_bytes(), raw)

    def test_help_and_missing_command_return_without_creating_data(self):
        for argument in ("-h", "--help"):
            with self.subTest(argument=argument):
                code, output = self.run_command(argument)
                self.assertEqual(code, 0)
                self.assertIn("用法:", output)
        code, output = self.run_command()
        self.assertEqual(code, 1)
        self.assertIn("用法:", output)
        self.assertFalse(self.paths.tasks.exists())

    def test_import_does_not_load_qt(self):
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; from task_ball.cli import run_cli; "
             "assert not any(name.startswith('PySide6') for name in sys.modules)"],
            cwd=PROJECT_DIR, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
