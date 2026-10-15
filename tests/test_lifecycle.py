"""Exercise the real GUI event loop and mutex lifecycle in isolated processes."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid


PROJECT_DIR = Path(__file__).resolve().parents[1]


WORKER = r"""
import json
import os
from pathlib import Path
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("TASK_FLOATING_BALL_AUTOPIN", None)
sys.path.insert(0, sys.argv[1])
from task_ball.app import main
from task_ball.window import TaskFloatingBall
from task_ball.single_instance import SingleInstance
from task_ball.storage import AppPaths
from PySide6.QtCore import QTimer, Qt

app_id = sys.argv[2]
paths = AppPaths.from_directory(sys.argv[3])
case = sys.argv[4]
sys.argv = [sys.argv[0]]
original_window = TaskFloatingBall
events = []
errors = []


class LifecycleWindow(original_window):
    def __init__(self, paths):
        super().__init__(paths=paths)
        QTimer.singleShot(0, self.observe_shown)

    def observe_shown(self):
        events.append({"event": "shown", "ball_visible": self.isVisible(),
                       "tool_window": self.windowType() == Qt.WindowType.Tool})
        if case == "expanded":
            self.set_pinned(True)
        QTimer.singleShot(100, self.close_via_window)

    def close_via_window(self):
        events.append({"event": "close_requested", "ball_visible": self.isVisible(),
                       "panel_visible": self.panel.isVisible()})
        self.close()
        events.append({"event": "close_returned", "ball_visible": self.isVisible(),
                       "panel_visible": self.panel.isVisible()})


def record_exception(exc_type, value, traceback):
    errors.append(str(value))
    sys.__excepthook__(exc_type, value, traceback)


sys.excepthook = record_exception
# No app.quit timer: main must return through the application's own close path.
result = main([sys.argv[0]], paths=paths, instance_id=app_id, window_factory=LifecycleWindow)
events.append({"event": "main_returned", "result": result})
guard = SingleInstance(app_id, "isolated lifecycle test")
try:
    mutex_available = guard.acquire()
finally:
    guard.close()
print(json.dumps({"events": events, "errors": errors,
                  "mutex_available": mutex_available}), flush=True)
"""


@unittest.skipUnless(sys.platform == "win32", "requires Windows named mutexes")
class ApplicationLifecycleTests(unittest.TestCase):
    def run_main_and_close(self, case, app_id, directory):
        environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        try:
            result = subprocess.run(
                [sys.executable, "-u", "-c", WORKER, str(PROJECT_DIR),
                 app_id, str(directory), case],
                cwd=str(PROJECT_DIR),
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
            )
        except subprocess.TimeoutExpired as error:
            self.fail(
                "main() did not return after closing the %s tool window; "
                "the isolated worker was terminated after 10 seconds. "
                "stdout=%r stderr=%r" % (case, error.stdout, error.stderr)
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.strip(), result.stderr)
        payload = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(payload["errors"], [], result.stderr)
        events = payload["events"]
        self.assertEqual([event["event"] for event in events],
                         ["shown", "close_requested", "close_returned", "main_returned"])
        self.assertTrue(events[0]["ball_visible"])
        self.assertTrue(events[0]["tool_window"])
        self.assertTrue(events[1]["ball_visible"])
        self.assertEqual(events[1]["panel_visible"], case == "expanded")
        self.assertFalse(events[2]["ball_visible"])
        self.assertFalse(events[2]["panel_visible"])
        self.assertEqual(events[3]["result"], 0)
        self.assertTrue(payload["mutex_available"], payload)
        return payload

    def test_close_collapsed_ball_returns_main_and_releases_mutex(self):
        with tempfile.TemporaryDirectory(prefix="task-ball-lifecycle-") as directory:
            self.run_main_and_close(
                "collapsed", "TaskFloatingBall.Lifecycle." + uuid.uuid4().hex, directory
            )

    def test_close_expanded_ball_returns_main_and_releases_mutex(self):
        with tempfile.TemporaryDirectory(prefix="task-ball-lifecycle-") as directory:
            self.run_main_and_close(
                "expanded", "TaskFloatingBall.Lifecycle." + uuid.uuid4().hex, directory
            )

    def test_normal_exit_allows_same_application_id_to_show_again(self):
        app_id = "TaskFloatingBall.Lifecycle." + uuid.uuid4().hex
        with tempfile.TemporaryDirectory(prefix="task-ball-lifecycle-") as directory:
            self.run_main_and_close("collapsed", app_id, directory)
            self.run_main_and_close("expanded", app_id, directory)


if __name__ == "__main__":
    unittest.main()
