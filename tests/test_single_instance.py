"""Exercise actual Windows mutexes using isolated names and Python processes."""

from pathlib import Path
import queue
import subprocess
import sys
import threading
import unittest
from unittest import mock
import uuid


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
from task_ball.single_instance import SingleInstance


WORKER = r"""
import os
import sys
sys.path.insert(0, sys.argv[1])
from task_ball.single_instance import SingleInstance

guard = SingleInstance(sys.argv[2], "isolated mutex test")
print("ready", flush=True)
sys.stdin.readline()
acquired = guard.acquire()
print("acquired" if acquired else "duplicate", flush=True)
if acquired:
    command = sys.stdin.readline().strip()
    if command == "crash":
        os._exit(0)  # Deliberately bypass close()/destructors.
guard.close()
"""


class Worker:
    def __init__(self, test, app_id):
        self.process = subprocess.Popen(
            [sys.executable, "-u", "-c", WORKER, str(PROJECT_DIR), app_id],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        self.lines = queue.Queue()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        test.addCleanup(self.cleanup)
        test.assertEqual(self.receive(), "ready")

    def _read(self):
        for line in self.process.stdout:
            self.lines.put(line.strip())
        self.lines.put(None)

    def receive(self):
        try:
            line = self.lines.get(timeout=15)
        except queue.Empty:
            raise AssertionError("mutex worker did not respond within 15 seconds")
        if line is None:
            self.process.wait(timeout=5)
            raise AssertionError("mutex worker exited: " + self.process.stderr.read())
        return line

    def send(self, command):
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()

    def finish(self, command="release"):
        self.send(command)
        code = self.process.wait(timeout=10)
        if code != 0:
            raise AssertionError("mutex worker failed: " + self.process.stderr.read())

    def cleanup(self):
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=10)
        self.reader.join(timeout=5)
        self.process.stdin.close()
        self.process.stdout.close()
        self.process.stderr.close()


@unittest.skipUnless(sys.platform == "win32", "requires Windows named mutexes")
class SingleInstanceTests(unittest.TestCase):
    def setUp(self):
        self.app_id = "TaskFloatingBall.Test." + uuid.uuid4().hex

    def test_two_independent_processes_allow_one_instance(self):
        first = Worker(self, self.app_id)
        first.send("go")
        self.assertEqual(first.receive(), "acquired")
        second = Worker(self, self.app_id)
        second.send("go")
        self.assertEqual(second.receive(), "duplicate")
        self.assertEqual(second.process.wait(timeout=10), 0)
        first.finish()

    def test_process_exit_releases_mutex_without_cleanup(self):
        first = Worker(self, self.app_id)
        first.send("go")
        self.assertEqual(first.receive(), "acquired")
        first.finish("crash")
        replacement = Worker(self, self.app_id)
        replacement.send("go")
        self.assertEqual(replacement.receive(), "acquired")
        replacement.finish()

    def test_simultaneous_start_allows_exactly_one_instance(self):
        workers = [Worker(self, self.app_id) for _ in range(6)]
        for worker in workers:
            worker.send("go")
        results = [worker.receive() for worker in workers]
        self.assertEqual(results.count("acquired"), 1, results)
        self.assertEqual(results.count("duplicate"), len(workers) - 1, results)
        for worker, result in zip(workers, results):
            if result == "acquired":
                worker.finish()
            else:
                self.assertEqual(worker.process.wait(timeout=10), 0)

    def test_close_and_acquire_are_idempotent_and_allow_restart(self):
        first = SingleInstance(self.app_id, "isolated mutex test")
        second = SingleInstance(self.app_id, "isolated mutex test")
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        self.assertTrue(first.acquire())
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())
        first.close()
        first.close()
        self.assertTrue(second.acquire())

    def test_app_ids_are_isolated(self):
        first = SingleInstance(self.app_id, "isolated mutex test")
        second = SingleInstance(self.app_id + ".Other", "isolated mutex test")
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        self.assertTrue(first.acquire())
        self.assertTrue(second.acquire())

    def test_activation_skips_hidden_panel_without_calling_real_windows(self):
        guard = SingleInstance(self.app_id, "任务悬浮球")
        self.addCleanup(guard.close)
        user32 = mock.MagicMock()
        # Both windows share the application title; the task panel is hidden.
        user32.IsWindowVisible.side_effect = lambda hwnd: hwnd == 200
        user32.GetWindowTextLengthW.return_value = len("任务悬浮球")

        def read_title(_hwnd, buffer, _length):
            buffer.value = "任务悬浮球"
            return len(buffer.value)

        def enumerate_windows(callback, lparam):
            for hwnd in (100, 200):
                if not callback(hwnd, lparam):
                    return False
            return True

        user32.GetWindowTextW.side_effect = read_title
        user32.EnumWindows.side_effect = enumerate_windows
        user32.IsIconic.return_value = False
        user32.SetForegroundWindow.return_value = True
        with mock.patch("task_ball.single_instance.ctypes.WinDLL", return_value=user32):
            self.assertTrue(guard.activate_existing())
        user32.SetForegroundWindow.assert_called_once_with(200)
        user32.ShowWindow.assert_not_called()


if __name__ == "__main__":
    unittest.main()
