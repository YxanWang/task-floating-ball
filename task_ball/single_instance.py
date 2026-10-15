"""Windows GUI single-instance guard without touching application data files."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9


class SingleInstance:
    """Keep a session-local named mutex alive for the GUI process lifetime.

    The mutex is deliberately not owned by a thread: its existence, and the
    retained kernel handle, identify the running instance. Windows closes that
    handle even when the process terminates without Python cleanup.
    """

    def __init__(self, app_id: str, window_title: str):
        if not isinstance(app_id, str) or not app_id or any(
            char in app_id for char in ("\\", "/", "\0")
        ):
            raise ValueError("app_id must be a nonempty name without slashes or NUL")
        if sys.platform != "win32":
            raise OSError("SingleInstance requires Windows")

        self._name = "Local\\" + app_id
        self._window_title = window_title
        self._handle = None
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateMutexW.argtypes = (
            ctypes.c_void_p,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        )
        self._kernel32.CreateMutexW.restype = wintypes.HANDLE
        self._kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self._kernel32.CloseHandle.restype = wintypes.BOOL

    def acquire(self) -> bool:
        """Return True for this instance, False while another instance lives.

        Unexpected Windows errors raise OSError instead of silently starting an
        unprotected GUI. Calling acquire again on a held guard is harmless.
        """
        if self._handle is not None:
            return True

        ctypes.set_last_error(0)
        handle = self._kernel32.CreateMutexW(None, False, self._name)
        error = ctypes.get_last_error()
        if not handle:
            raise ctypes.WinError(error)
        if error == ERROR_ALREADY_EXISTS:
            # Retaining this extra handle would keep the named object alive
            # after the original GUI exits, preventing a subsequent restart.
            if not self._kernel32.CloseHandle(handle):
                raise ctypes.WinError(ctypes.get_last_error())
            return False
        self._handle = handle
        return True

    def activate_existing(self) -> bool:
        """Best-effort activation; Windows may refuse foreground permission."""
        if not self._window_title:
            return False
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            enum_callback_type = ctypes.WINFUNCTYPE(
                wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
            )
            user32.EnumWindows.argtypes = (enum_callback_type, wintypes.LPARAM)
            user32.EnumWindows.restype = wintypes.BOOL
            user32.IsWindowVisible.argtypes = (wintypes.HWND,)
            user32.IsWindowVisible.restype = wintypes.BOOL
            user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
            user32.GetWindowTextLengthW.restype = ctypes.c_int
            user32.GetWindowTextW.argtypes = (
                wintypes.HWND, wintypes.LPWSTR, ctypes.c_int
            )
            user32.GetWindowTextW.restype = ctypes.c_int
            user32.IsIconic.argtypes = (wintypes.HWND,)
            user32.IsIconic.restype = wintypes.BOOL
            user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
            user32.ShowWindow.restype = wintypes.BOOL
            user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
            user32.SetForegroundWindow.restype = wintypes.BOOL
            matching_windows = []

            @enum_callback_type
            def find_visible_window(hwnd, _lparam):
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length:
                    title = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, title, length + 1)
                    if title.value == self._window_title:
                        matching_windows.append(hwnd)
                        return False
                return True

            # The hidden task panel has the same title as the visible ball.
            # Enumerate visible windows so a duplicate launch cannot reveal it.
            user32.EnumWindows(find_visible_window, 0)
            if not matching_windows:
                return False
            hwnd = matching_windows[0]
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, SW_RESTORE)
            return bool(user32.SetForegroundWindow(hwnd))
        except OSError:
            return False

    def close(self) -> None:
        """Release the retained handle; safe to call more than once."""
        handle = self._handle
        if handle is None:
            return
        if not self._kernel32.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())
        self._handle = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            # Interpreter teardown and process exit already close OS handles.
            pass
