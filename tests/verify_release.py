"""Run the packaged Windows GUI, including duplicate launch and a full restart."""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import traceback


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def wait_for_ready(path, process, previous_pid=None):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.get("pid") != previous_pid:
                    return payload
            except (OSError, ValueError):
                pass
        if process.poll() is not None:
            raise AssertionError("GUI exited before its ready signal: %s" % process.returncode)
        time.sleep(0.05)
    raise AssertionError("Packaged GUI did not become ready within 20 seconds")


def is_process_alive(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        result = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(result)):
            raise ctypes.WinError(ctypes.get_last_error())
        return result.value == 259
    finally:
        kernel.CloseHandle(handle)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    exe = args.exe.resolve(strict=True)
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    work = output / "isolated-data"
    work.mkdir()
    if (exe.parent / "config.json").is_file():
        shutil.copy2(exe.parent / "config.json", work / "config.json")
    (work / "wait-for-go").write_text("hold until duplicate startup has been checked", encoding="utf-8")
    original = {name: file_hash(exe.parent / name) for name in ("tasks.json", "config.json")}
    environment = os.environ.copy()
    for variable in ("QT_QPA_PLATFORM", "QT_QPA_PLATFORM_PLUGIN_PATH", "QT_PLUGIN_PATH",
                     "QML_IMPORT_PATH", "PYTHONHOME", "PYTHONPATH", "TASK_FLOATING_BALL_AUTOPIN"):
        environment.pop(variable, None)
    command = [str(exe), "--verify", str(work)]
    processes = []
    summary = {"ok": False, "executable": str(exe), "sha256": file_hash(exe), "runs": []}
    try:
        first = subprocess.Popen(command, env=environment, cwd=str(exe.parent))
        processes.append(first)
        ready = wait_for_ready(work / "ready.json", first)
        assert ready.get("frozen") is True, ready
        assert ready.get("platform") == "windows", ready
        duplicate = subprocess.Popen(command, env=environment, cwd=str(exe.parent))
        processes.append(duplicate)
        assert duplicate.wait(timeout=15) == 0
        assert first.poll() is None, "Duplicate launch stopped the first GUI"
        assert is_process_alive(ready["pid"]), "First GUI disappeared during duplicate startup"
        summary["duplicate_launch_exit_code"] = duplicate.returncode
        (work / "go").write_text("run verification", encoding="utf-8")
        # Native rendering and real appearance controls add four dialog cycles.
        assert first.wait(timeout=60) == 0
        assert not is_process_alive(ready["pid"]), "GUI process stayed alive after close"
        report = json.loads((work / "report.json").read_text(encoding="utf-8"))
        assert report.get("ok") is True, report
        summary["runs"].append({"ready": ready, "exit_code": first.returncode, "report": report})
        shutil.copy2(work / "screenshot.png", output / "first-run.png")

        second = subprocess.Popen(command, env=environment, cwd=str(exe.parent))
        processes.append(second)
        restarted = wait_for_ready(work / "ready.json", second, ready["pid"])
        assert restarted.get("frozen") is True and restarted.get("platform") == "windows", restarted
        assert restarted.get("appearance") == report.get("final_appearance"), {
            "expected": report.get("final_appearance"),
            "restored": restarted.get("appearance"),
        }
        summary["appearance_restored_on_restart"] = True
        assert second.wait(timeout=60) == 0
        assert not is_process_alive(restarted["pid"]), "Restarted GUI stayed alive after close"
        report = json.loads((work / "report.json").read_text(encoding="utf-8"))
        assert report.get("ok") is True, report
        summary["runs"].append({"ready": restarted, "exit_code": second.returncode, "report": report})
        shutil.copy2(work / "screenshot.png", output / "second-run.png")
        assert original == {name: file_hash(exe.parent / name) for name in original}, "User data changed"
        summary["original_data_unchanged"] = True
        summary["both_gui_processes_exited"] = True
        summary["ok"] = True
    except Exception:
        summary["error"] = traceback.format_exc()
        raise
    finally:
        for process in processes:
            if process.poll() is None:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
                process.wait(timeout=10)
        (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "report": str(output / "summary.json"), "runs": len(summary["runs"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
