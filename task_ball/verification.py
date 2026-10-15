"""Opt-in verification of the visible, packaged Windows application.

The caller supplies an isolated data directory. After resetting that test
fixture, task operations use the actual widgets; this module never substitutes
an offscreen Qt platform or quits QApplication itself.
"""

import ctypes
from ctypes import wintypes
from dataclasses import asdict
import json
import os
import sys
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtTest import QTest

from .appearance import Appearance, load_appearance
from .appearance_dialog import AppearanceDialog


def start_verification(app, window, output_dir):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "ok": False,
        "checks": [],
        "platform": app.platformName(),
        "executable": sys.executable,
        "frozen": bool(getattr(sys, "frozen", False)),
        "pid": os.getpid(),
        "exit_path": "not requested",
    }
    state = {"finished": False, "started": False}

    def write_json(name, value):
        # A filesystem watcher also watches this directory. Atomic writes keep
        # external verification from observing a partly written report.
        target = output / name
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, target)

    def save_report():
        write_json("report.json", report)

    def check(name, condition, detail=None):
        item = {"name": name, "ok": bool(condition)}
        if detail is not None:
            item["detail"] = json.loads(json.dumps(detail, ensure_ascii=False))
        report["checks"].append(item)
        if not condition:
            raise AssertionError(name + (": " + str(detail) if detail else ""))

    def persisted():
        return json.loads((output / "tasks.json").read_text(encoding="utf-8"))

    def check_tasks(name, expected):
        actual = persisted()
        check(name, window.tasks == expected and actual == expected,
              {"expected": expected, "memory": window.tasks, "disk": actual})

    def appearance_state():
        return asdict(window.appearance)

    def check_ships(name):
        scene = window.ball.scene
        expected = tuple(task["id"] for task in window.tasks)
        actual_ids = tuple(scene.task_ids)
        ship_ids = tuple(scene.ships)
        check(name, actual_ids == expected and len(ship_ids) == len(expected)
              and set(ship_ids) == set(expected),
              {"tasks": list(expected), "scene": list(actual_ids),
               "ships": list(ship_ids)})

    def click(widget):
        QTest.mouseMove(widget, widget.rect().center())
        QTest.qWait(60)
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton,
                         pos=widget.rect().center())
        QTest.qWait(400)

    def capture(name="screenshot.png"):
        # The visible water and satellites live in a separate input-transparent
        # overlay; the small hit-target window itself is almost transparent.
        effects = getattr(window.ball, "effects", None)
        ball = effects.grab() if effects is not None else window.grab()
        panel = window.panel.grab()
        # Use the widget renders rather than including the user's desktop.
        # Normalizing DPR preserves every captured pixel on mixed-DPI desktops.
        ball.setDevicePixelRatio(1)
        panel.setDevicePixelRatio(1)
        image = QPixmap(ball.width() + panel.width() + 72,
                        max(panel.height(), ball.height()) + 64)
        image.fill(QColor("#E9EEF5"))
        painter = QPainter(image)
        painter.drawPixmap(24, 32, ball)
        painter.drawPixmap(ball.width() + 48, 32, panel)
        painter.end()
        return image.save(str(output / name))

    def check_native_overlay():
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        get_style = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
        get_style.argtypes = (wintypes.HWND, ctypes.c_int)
        get_style.restype = ctypes.c_ssize_t
        user32.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        user32.GetClientRect.restype = wintypes.BOOL
        user32.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
        user32.ClientToScreen.restype = wintypes.BOOL
        user32.WindowFromPoint.argtypes = (wintypes.POINT,)
        user32.WindowFromPoint.restype = wintypes.HWND
        user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        user32.GetAncestor.restype = wintypes.HWND
        user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        user32.GetWindowRect.restype = wintypes.BOOL

        effects = window.ball.effects
        effects_id, window_id = int(effects.winId()), int(window.winId())
        style = get_style(effects_id, -20)  # GWL_EXSTYLE
        expected_style = 0x20 | 0x08000000  # WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
        check("overlay_native_transparent_and_noactivate",
              style & expected_style == expected_style,
              {"extended_style": hex(style), "overlay_hwnd": effects_id})

        rect = wintypes.RECT()
        if not user32.GetClientRect(window_id, ctypes.byref(rect)):
            raise ctypes.WinError(ctypes.get_last_error())
        center = wintypes.POINT((rect.right - rect.left) // 2,
                               (rect.bottom - rect.top) // 2)
        if not user32.ClientToScreen(window_id, ctypes.byref(center)):
            raise ctypes.WinError(ctypes.get_last_error())
        hit = user32.WindowFromPoint(center)
        root = user32.GetAncestor(hit, 2) if hit else None  # GA_ROOT
        check("overlay_passes_native_hit_test_to_ball", root == window_id,
              {"hit_hwnd": hit, "root_hwnd": root, "ball_hwnd": window_id,
               "opacity": window.appearance.opacity})

        core, halo = wintypes.RECT(), wintypes.RECT()
        if not user32.GetWindowRect(window_id, ctypes.byref(core)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not user32.GetWindowRect(effects_id, ctypes.byref(halo)):
            raise ctypes.WinError(ctypes.get_last_error())
        halo_point = wintypes.POINT((halo.left + core.left) // 2, center.y)
        halo_hit = user32.WindowFromPoint(halo_point)
        check("overlay_halo_passes_native_hit_test_to_desktop",
              halo.left < core.left and halo_hit != effects_id,
              {"halo_hit_hwnd": halo_hit, "overlay_hwnd": effects_id})

    def exercise_drag():
        tasks_before = [dict(task) for task in window.tasks]
        ball = window.ball
        origin = window.pos()
        center = ball.rect().center()
        destination = center + QPoint(-84, 18)
        QTest.mousePress(ball, Qt.MouseButton.LeftButton, pos=center)
        try:
            QTest.mouseMove(ball, destination, delay=0)
            target = window._drag_target.toPoint()
            check("widget_drag_starts_and_updates_target",
                  window._dragging and target != origin,
                  {"origin": [origin.x(), origin.y()],
                   "target": [target.x(), target.y()]})
            check("widget_drag_has_delayed_following", window.pos() != target,
                  {"position": [window.x(), window.y()],
                   "target": [target.x(), target.y()]})
            QTest.qWait(60)
            check("drag_stretch_screenshot_saved",
                  ball.effects.grab().save(str(output / "drag-stretch.png")))
        finally:
            QTest.mouseRelease(ball, Qt.MouseButton.LeftButton, pos=destination)
        QTest.qWait(700)
        check("widget_drag_settles_at_target",
              not window._dragging and window.pos() == target
              and not window._motion_timer.isActive(),
              {"position": [window.x(), window.y()],
               "target": [target.x(), target.y()]})
        check_tasks("widget_drag_keeps_tasks", tasks_before)
        check_ships("widget_drag_keeps_ship_ids")
        check("widget_drag_restores_pinned_panel",
              window._pinned and window._expanded and window.panel.isVisible())
        check("drag_settled_screenshot_saved",
              ball.effects.grab().save(str(output / "drag-settled.png")))

    def exercise_appearance():
        from PySide6.QtGui import QContextMenuEvent
        from PySide6.QtGui import QPalette
        from PySide6.QtWidgets import QApplication, QMenu
        from .themes import palette

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.IsWindowVisible.argtypes = (wintypes.HWND,)
        user32.IsWindowVisible.restype = wintypes.BOOL

        tasks_before = [dict(task) for task in window.tasks]
        task_bytes_before = (output / "tasks.json").read_bytes()
        # Include the previous 48 px size and both ends of the new size range.
        # Nondefault final size and opacity make the harness prove restoration.
        cases = (Appearance("ocean", 80, False, 30), Appearance("moon", 48, True, 65),
                 Appearance("amber", 40, True, 100), Appearance("amber", 80, True, 65))
        for case_index, expected in enumerate(cases, 1):
            label = f"{expected.theme}_{expected.size}_{expected.show_ships}_opacity{expected.opacity}"
            previous_opacity = window.appearance.opacity
            callback_errors = []
            selection = {"clicked": False}

            def choose_appearance_action():
                try:
                    popup = QApplication.activePopupWidget()
                    if not isinstance(popup, QMenu):
                        raise AssertionError("The ball context menu did not open.")
                    actions = [action for action in popup.actions()
                               if action.text().replace("&", "").startswith("外观设置")]
                    if len(actions) != 1:
                        raise AssertionError("The appearance menu action is missing or ambiguous.")
                    action_rect = popup.actionGeometry(actions[0])
                    if action_rect.isEmpty():
                        raise AssertionError("The appearance menu action has no visible geometry.")
                    QTest.mouseMove(popup, action_rect.center())
                    QTest.mouseClick(popup, Qt.MouseButton.LeftButton,
                                     pos=action_rect.center())
                    selection["clicked"] = True
                except Exception:
                    callback_errors.append(traceback.format_exc())
                    popup = QApplication.activePopupWidget()
                    if isinstance(popup, QMenu):
                        popup.close()

            def close_stuck_menu():
                popup = QApplication.activePopupWidget()
                if isinstance(popup, QMenu):
                    callback_errors.append("The context menu stayed open after clicking its action.")
                    popup.close()

            # QMenu.exec starts a nested loop. Select its real action while that
            # loop runs, then allow deferred popup cleanup and dialog creation.
            menu_guard = QTimer(window)
            menu_guard.setSingleShot(True)
            menu_guard.timeout.connect(close_stuck_menu)
            menu_guard.start(2000)
            QTimer.singleShot(80, choose_appearance_action)
            center = window.ball.rect().center()
            event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, center,
                                      window.ball.mapToGlobal(center))
            try:
                QApplication.sendEvent(window.ball, event)
            finally:
                menu_guard.stop()
                menu_guard.deleteLater()
            QTest.qWait(250)
            check("context_menu_appearance_action_was_clicked",
                  selection["clicked"] and not callback_errors, callback_errors)
            dialog = window._appearance_dialog
            check("appearance_dialog_is_visible", isinstance(dialog, AppearanceDialog)
                  and dialog.isVisible())
            check("appearance_dialog_is_native_visible",
                  bool(user32.IsWindowVisible(int(dialog.winId()))))
            check("appearance_dialog_opens_after_menu_cleanup",
                  not window._menu_open and QApplication.activePopupWidget() is None)
            available = dialog.screen().availableGeometry()
            geometry = dialog.frameGeometry()
            check("appearance_dialog_is_inside_available_screen",
                  available.contains(geometry),
                  {"available": [available.x(), available.y(), available.width(), available.height()],
                   "dialog": [geometry.x(), geometry.y(), geometry.width(), geometry.height()]})
            check("appearance_dialog_open_screenshot_saved",
                  dialog.grab().save(str(output / f"appearance-dialog-open-{case_index:02d}.png")))
            check("appearance_dialog_loads_current_preferences",
                  dialog.appearance() == window.appearance)

            theme_button = dialog.theme_buttons.get(expected.theme)
            check("appearance_theme_control_has_requested_theme",
                  theme_button is not None and theme_button.isVisible() and theme_button.isEnabled())
            QTest.mouseClick(theme_button, Qt.MouseButton.LeftButton,
                             pos=theme_button.rect().center())
            slider = dialog.size_slider
            slider.setFocus()
            QTest.keyClick(slider, Qt.Key.Key_Home)
            for _ in range((expected.size - slider.minimum()) // slider.singleStep()):
                QTest.keyClick(slider, Qt.Key.Key_Right)
            if dialog.ships_checkbox.isChecked() != expected.show_ships:
                dialog.ships_checkbox.setFocus()
                QTest.keyClick(dialog.ships_checkbox, Qt.Key.Key_Space)
            check("appearance_other_controls_keep_opacity_" + label,
                  window.appearance.opacity == previous_opacity
                  and dialog.opacity_slider.value() == previous_opacity)
            opacity_slider = dialog.opacity_slider
            check("appearance_opacity_control_has_full_range", opacity_slider.minimum() == 30
                  and opacity_slider.maximum() == 100)
            opacity_slider.setFocus()
            QTest.keyClick(opacity_slider, Qt.Key.Key_End if expected.opacity == 100
                           else Qt.Key.Key_Home)
            if expected.opacity != 100:
                for _ in range((expected.opacity - opacity_slider.minimum()) // opacity_slider.singleStep()):
                    QTest.keyClick(opacity_slider, Qt.Key.Key_Right)
            QTest.qWait(250)
            colors = palette(expected.theme)
            effects = window.ball.effects
            opacity_values = {"root": window.windowOpacity(), "panel": window.panel.windowOpacity(),
                              "effects": effects.windowOpacity() if effects is not None else None,
                              "settings": dialog.windowOpacity()}
            check("appearance_opacity_reaches_three_surfaces_" + label,
                  all(opacity_values[name] is not None
                      and abs(opacity_values[name] - expected.opacity / 100) <= 1 / 255 + 1e-6
                      for name in ("root", "panel", "effects"))
                  and abs(opacity_values["settings"] - 1.0) < 1e-6
                  and dialog.opacity_slider.value() == expected.opacity
                  and dialog.opacity_value.text() == f"{expected.opacity}%", opacity_values)
            check("appearance_theme_buttons_are_exclusive_" + label,
                  [name for name, button in dialog.theme_buttons.items() if button.isChecked()]
                  == [expected.theme]
                  and all(button.isCheckable() for button in dialog.theme_buttons.values()))
            check("appearance_theme_reaches_panel_rows_and_dialog_" + label,
                  window.panel.theme == expected.theme
                  and dialog.theme == expected.theme
                  and all(row.theme == expected.theme for row in window._row_map.values()),
                  {"panel": window.panel.theme, "dialog": dialog.theme,
                   "rows": [row.theme for row in window._row_map.values()]})
            check("appearance_theme_reaches_widget_text_colors_" + label,
                  window.panel.input.palette().color(QPalette.ColorRole.Text).name()
                  == QColor(colors.text).name()
                  and all(row.label.palette().color(QPalette.ColorRole.WindowText).name()
                          == QColor(colors.text).name() for row in window._row_map.values())
                  and dialog.ships_checkbox.palette().color(QPalette.ColorRole.WindowText).name()
                  == QColor(colors.text).name()
                  and dialog.done_button.palette().color(QPalette.ColorRole.ButtonText).name()
                  == QColor(colors.accent_text).name())
            check("appearance_dialog_stays_native_visible_after_theme_" + label,
                  dialog.isVisible() and bool(user32.IsWindowVisible(int(dialog.winId()))))
            check("appearance_dialog_applied_theme_screenshot_saved_" + label,
                  dialog.grab().save(str(output / ("appearance-dialog-applied-" + label + ".png"))))
            click(dialog.done_button)

            actual_config = json.loads((output / "config.json").read_text(encoding="utf-8"))
            check("appearance_controls_apply_" + label,
                  window.appearance == expected and dialog.appearance() == expected
                  and not dialog.isVisible()
                  and window.width() == window.height() == expected.size
                  and window.ball.width() == window.ball.height() == expected.size
                  and window.ball.scene.theme == expected.theme
                  and window.ball.scene.size == expected.size
                  and window.ball.scene.show_ships == expected.show_ships,
                  {"expected": asdict(expected), "actual": appearance_state()})
            check("appearance_preferences_are_persisted_" + label,
                  actual_config.get("appearance") == asdict(expected)
                  and load_appearance(output / "config.json") == expected,
                  actual_config.get("appearance"))
            check_tasks("appearance_changes_keep_tasks_" + label, tasks_before)
            check("appearance_changes_keep_task_file_bytes_" + label,
                  (output / "tasks.json").read_bytes() == task_bytes_before)
            check_ships("appearance_changes_keep_ship_ids_" + label)
            check("appearance_preview_is_saved_" + label,
                  capture("appearance-" + label + ".png"))
            # QWidget-directed clicks alone cannot detect a layered input plane
            # becoming natively click-through when its alpha is scaled down.
            check_native_overlay()
        report["final_appearance"] = appearance_state()

    def exercise_docking():
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QContextMenuEvent, QCursor
        from PySide6.QtWidgets import QApplication, QMenu
        from .docking import find_dock, placement_for
        from .storage import load_position

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.IsWindowVisible.argtypes = (wintypes.HWND,)
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        user32.GetClientRect.restype = wintypes.BOOL
        user32.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
        user32.ClientToScreen.restype = wintypes.BOOL
        user32.WindowFromPoint.argtypes = (wintypes.POINT,)
        user32.WindowFromPoint.restype = wintypes.HWND
        user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        user32.GetAncestor.restype = wintypes.HWND
        user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        user32.GetWindowRect.restype = wintypes.BOOL

        saved_position = QPoint(window.pos())
        saved_cursor = QCursor.pos()
        saved_pinned, saved_expanded = window._pinned, window._expanded
        original_tasks = (output / "tasks.json").read_bytes()
        expected_tasks = [dict(task) for task in window.tasks]
        screens = window._dock_screens()
        size = window.appearance.size

        def wait_for(name, predicate, timeout=1800):
            deadline = time.monotonic() + timeout / 1000
            while time.monotonic() < deadline and not predicate():
                QTest.qWait(20)
            check(name, predicate())

        def move_pointer(position):
            # Move the actual native cursor: the production hover/corridor
            # logic must run, rather than calling reveal/collapse slots.
            QCursor.setPos(position)
            QTest.qWait(35)

        def screenshot_widget(widget, name):
            rendered = widget.grab()
            rendered.setDevicePixelRatio(1)
            image = QPixmap(rendered.width() + 48, rendered.height() + 48)
            image.fill(QColor("#E9EEF5"))
            painter = QPainter(image)
            painter.drawPixmap(24, 24, rendered)
            painter.end()
            return image.save(str(output / name))

        def check_compact(side):
            target = window._dock_target
            native_rect = wintypes.RECT()
            native_rect_ok = bool(user32.GetWindowRect(int(window.winId()), ctypes.byref(native_rect)))
            handle_origin = window.dock_handle.mapToGlobal(QPoint())
            pointer = QCursor.pos()
            details = {
                "geometry": list(window.geometry().getRect()),
                "frame_geometry": list(window.frameGeometry().getRect()),
                "expected": list(target.handle_rect) if target is not None else None,
                "anchor": list(target.anchor) if target is not None else None,
                "handle_geometry": list(window.dock_handle.geometry().getRect()),
                "handle_origin": [handle_origin.x(), handle_origin.y()],
                "native_rect": [native_rect.left, native_rect.top, native_rect.right, native_rect.bottom]
                               if native_rect_ok else None,
                "native_visible": bool(user32.IsWindowVisible(int(window.winId()))),
                "collapsed": window._dock_collapsed, "transitioning": window._dock_transitioning,
                "reveal_animation": window._dock_reveal_anim is not None,
                "dragging": window._dragging, "from_handle": window._drag_from_handle,
                "motion_timer": window._motion_timer.isActive(),
                "hover_timer": window._dock_hover_timer.isActive(),
                "compact_timer": window._dock_compact_timer.isActive(),
                "watch_timer": window._dock_watch_timer.isActive(),
                "pointer": [pointer.x(), pointer.y()],
            }
            check("dock_" + side + "_has_compact_geometry",
                  target is not None and target.side == side and window._dock_collapsed
                  and window.geometry().getRect() == target.handle_rect
                  and window.dock_handle.isVisible()
                  and window.dock_handle.mapToGlobal(QPoint()) == QPoint(*target.handle_rect[:2]),
                  details)
            effects = window.ball.effects
            check("dock_" + side + "_stops_hidden_water_effects",
                  not window.ball.isVisible() and not window.panel.isVisible()
                  and not window.ball._timer.isActive()
                  and (effects is None or (not effects.isVisible()
                       and not user32.IsWindowVisible(int(effects.winId())))))
            check("dock_" + side + "_persists_normal_ball_anchor",
                  load_position(output / "config.json") == target.anchor
                  and target.anchor != target.handle_rect[:2],
                  {"stored": load_position(output / "config.json"), "anchor": target.anchor})

            hwnd = int(window.winId())
            rect = wintypes.RECT()
            if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
                raise ctypes.WinError(ctypes.get_last_error())
            dpr = window.devicePixelRatioF()
            native_size = (rect.right - rect.left, rect.bottom - rect.top)
            check("dock_" + side + "_is_native_visible_at_handle_size",
                  bool(user32.IsWindowVisible(hwnd))
                  and abs(native_size[0] - window.width() * dpr) <= 2
                  and abs(native_size[1] - window.height() * dpr) <= 2,
                  {"native_size": native_size, "dpr": dpr})
            point = wintypes.POINT(native_size[0] // 2, native_size[1] // 2)
            if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
                raise ctypes.WinError(ctypes.get_last_error())
            hit = user32.WindowFromPoint(point)
            root = user32.GetAncestor(hit, 2) if hit else None
            paint_started = time.monotonic()
            while root != hwnd and time.monotonic() - paint_started < .2:
                # Native layered-window paint can be flushed after Qt's resize
                # event; require the real hit target within a short paint budget.
                QTest.qWait(10)
                hit = user32.WindowFromPoint(point)
                root = user32.GetAncestor(hit, 2) if hit else None
            check("dock_" + side + "_native_hit_test_reaches_handle", root == hwnd,
                  {"hit_hwnd": hit, "root_hwnd": root, "handle_window_hwnd": hwnd,
                   "paint_wait_ms": round((time.monotonic() - paint_started) * 1000)})
            rendered = window.grab().toImage()
            check("dock_" + side + "_renders_opaque_water_drop",
                  rendered.pixelColor(rendered.width() // 2, rendered.height() // 2).alpha() > 128)
            check("dock_" + side + "_compact_screenshot_saved",
                  screenshot_widget(window, "dock-" + side + "-compact.png"))

        def drag_widget(widget, delta, name, *, hold=False):
            center = widget.rect().center()
            destination = center + delta
            QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=center)
            try:
                if hold:
                    QTest.qWait(window._dock_hover_timer.interval() + 70)
                    check("dock_handle_remains_visible_during_long_press",
                          window._dock_collapsed and widget.isVisible() and widget.is_pressed())
                    check("dock_handle_long_press_screenshot_saved",
                          screenshot_widget(window, "dock-handle-held.png"))
                QTest.mouseMove(widget, destination, delay=0)
                check(name + "_starts_actual_widget_drag", window._dragging)
            finally:
                QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=destination)
            wait_for(name + "_motion_finishes",
                     lambda: not window._dragging and not window._motion_timer.isActive())

        try:
            window.set_pinned(False)
            window.panel.input.clearFocus()
            window._collapse()
            QTest.qWait(150)
            for side in ("left", "right", "top", "bottom"):
                # The globally outermost work area always exposes this side,
                # including when the user's desktop has adjacent monitors.
                bounds = min(screens, key=lambda area: {
                    "left": area[0], "right": -(area[0] + area[2]),
                    "top": area[1], "bottom": -(area[1] + area[3]),
                }[side])
                x, y, width, height = bounds
                start = QPoint(x + (width - size) // 2, y + (height - size) // 2)
                parking = QPoint(x + width // 2, y + height // 2)
                window._undock()
                window.move(start)
                window.panel.input.clearFocus()
                QTest.qWait(50)  # Allow a real per-monitor DPI transition.
                expected = placement_for(side, bounds, (start.x(), start.y()), size,
                                         padding=window._dock_padding())
                exposed = find_dock(expected.anchor, size, screens, padding=window._dock_padding())
                check("dock_" + side + "_uses_exposed_screen_edge",
                      exposed is not None and exposed.side == side)
                drag_widget(window.ball, QPoint(*expected.anchor) - window.pos(), "dock_" + side)
                wait_for("dock_" + side + "_release_compacts", lambda: window._dock_collapsed)
                check_compact(side)

                move_pointer(window.dock_handle.mapToGlobal(window.dock_handle.rect().center()))
                wait_for("dock_" + side + "_native_hover_reveals",
                         lambda: not window._dock_collapsed and window._expanded
                         and window._dock_reveal_anim is None)
                target = window._dock_target
                hx, hy, hw, hh = target.handle_rect
                gap = {"left": window.x() - x,
                       "right": x + width - window.x() - size,
                       "top": window.y() - y,
                       "bottom": y + height - window.y() - size}[side]
                tangent_delta = ((2 * window.y() + size) - (2 * hy + hh)
                                 if side in ("left", "right")
                                 else (2 * window.x() + size) - (2 * hx + hw))
                check("dock_" + side + "_reveal_stays_close_and_aligned_to_handle",
                      gap == 4 and tangent_delta == 0 and window.pos() == QPoint(*target.anchor),
                      {"core_geometry": list(window.geometry().getRect()),
                       "handle_rect": list(target.handle_rect), "bounds": list(bounds),
                       "edge_gap": gap, "tangent_delta_twice": tangent_delta})
                effects = window.ball.effects
                check("dock_" + side + "_reveal_restores_visible_ball_and_effects",
                      window.width() == window.height() == size and window.ball.isVisible()
                      and window.panel.isVisible() and effects is not None and effects.isVisible()
                      and bool(user32.IsWindowVisible(int(effects.winId())))
                      and (window.ball._timer.isActive() or window.ball.scene.reduced_motion))
                check("dock_" + side + "_expanded_screenshot_saved",
                      capture("dock-" + side + "-expanded.png"))

                if side == "left":
                    click(window.ball)
                    move_pointer(parking)
                    QTest.qWait(550)
                    check("dock_pin_keeps_ball_and_panel_open_outside_hover",
                          window._pinned and not window._dock_collapsed
                          and window.ball.isVisible() and window.panel.isVisible())
                    check("dock_pinned_screenshot_saved", capture("dock-pinned.png"))
                    click(window.ball)
                move_pointer(parking)
                wait_for("dock_" + side + "_native_pointer_leave_compacts",
                         lambda: window._dock_collapsed)
                check_compact(side)
                check_tasks("dock_" + side + "_keeps_tasks", expected_tasks)
                check_ships("dock_" + side + "_keeps_ship_ids")

            # Open settings from the compact handle's actual native menu.
            callback_errors = []
            def select_settings():
                try:
                    popup = QApplication.activePopupWidget()
                    if not isinstance(popup, QMenu):
                        raise AssertionError("The dock handle context menu did not open.")
                    action = next(action for action in popup.actions()
                                  if action.text().startswith("外观设置"))
                    QTest.mouseClick(popup, Qt.MouseButton.LeftButton,
                                     pos=popup.actionGeometry(action).center())
                except Exception:
                    callback_errors.append(traceback.format_exc())
                    popup = QApplication.activePopupWidget()
                    if isinstance(popup, QMenu):
                        popup.close()

            def cancel_stuck_popup():
                popup = QApplication.activePopupWidget()
                if isinstance(popup, QMenu):
                    callback_errors.append("The dock context menu stayed open.")
                    popup.close()

            guard = QTimer(window)
            guard.setSingleShot(True)
            guard.timeout.connect(cancel_stuck_popup)
            guard.start(2000)
            QTimer.singleShot(80, select_settings)
            handle = window.dock_handle
            center = handle.rect().center()
            try:
                QApplication.sendEvent(handle, QContextMenuEvent(QContextMenuEvent.Reason.Mouse,
                                          center, handle.mapToGlobal(center)))
            finally:
                guard.stop()
                guard.deleteLater()
            wait_for("dock_context_menu_opens_native_visible_settings",
                     lambda: not callback_errors and window._appearance_dialog is not None
                     and window._appearance_dialog.isVisible()
                     and bool(user32.IsWindowVisible(int(window._appearance_dialog.winId()))))
            check("dock_settings_menu_cleans_up", not callback_errors and not window._menu_open
                  and QApplication.activePopupWidget() is None, callback_errors)
            move_pointer(parking)
            QTest.qWait(550)
            dialog = window._appearance_dialog
            check("dock_settings_prevents_compaction_outside_hover",
                  not window._dock_collapsed and window.ball.isVisible() and dialog.isVisible()
                  and bool(user32.IsWindowVisible(int(dialog.winId()))))
            check("dock_settings_protected_screenshot_saved",
                  screenshot_widget(dialog, "dock-settings-protected.png"))
            click(dialog.close_button)
            move_pointer(parking)
            wait_for("dock_settings_close_allows_compaction", lambda: window._dock_collapsed)

            # Begin hovering, hold longer than the reveal delay, then drag the
            # same visible handle away. This preserves Qt's implicit mouse grab.
            handle = window.dock_handle
            move_pointer(handle.mapToGlobal(handle.rect().center()))
            inward = {"left": QPoint(180, 0), "right": QPoint(-180, 0),
                      "top": QPoint(0, 180), "bottom": QPoint(0, -180)}[window._dock_target.side]
            drag_widget(handle, inward, "dock_handle_drag_out", hold=True)
            check("dock_handle_drag_out_restores_undocked_ball",
                  window._dock_target is None and not window._dock_collapsed
                  and not window.dock_handle.isVisible() and window.ball.isVisible()
                  and window.width() == window.height() == size
                  and window.ball.effects.isVisible())
            check("dock_drag_out_screenshot_saved",
                  screenshot_widget(window.ball.effects, "dock-dragged-out.png"))
            check_tasks("docking_gestures_keep_tasks", expected_tasks)
            check_ships("docking_gestures_keep_ship_ids")
            check("docking_keeps_task_file_bytes", (output / "tasks.json").read_bytes() == original_tasks)
        finally:
            dialog = window._appearance_dialog
            if dialog is not None and dialog.isVisible():
                dialog.close()
            window._undock()
            window.set_pinned(False)
            window.panel.input.clearFocus()
            window._collapse()
            window.move(saved_position)
            window._motion_position = QPointF(saved_position)
            window._drag_target = QPointF(saved_position)
            window._save_config()
            window.set_pinned(saved_pinned)
            if saved_expanded and not saved_pinned:
                window._expand()
            QCursor.setPos(saved_cursor)
            QTest.qWait(250)
        check("docking_restores_verification_position_and_pin_state",
              window.pos() == saved_position and window._pinned == saved_pinned
              and window._expanded == saved_expanded and window._dock_target is None
              and not window._dock_collapsed and window.ball.isVisible())

    def about_to_quit():
        report["exit_path"] = "window.close -> QApplication.aboutToQuit"
        report["about_to_quit"] = True
        if not state["finished"]:
            report["ok"] = False
            report["error"] = "Application quit before verification finished."
        save_report()

    app.aboutToQuit.connect(about_to_quit)

    def finish():
        if state["finished"]:
            return
        state["finished"] = True
        report["exit_path"] = "window.close requested; awaiting aboutToQuit"
        save_report()
        try:
            accepted = window.close()
            check("close_hides_ball_and_panel", accepted
                  and not window.isVisible() and not window.panel.isVisible())
            effects = window.ball.effects
            check("close_hides_effects_overlay", effects is None or not effects.isVisible())
            check("close_stops_water_animation", not window.ball._timer.isActive())
        except Exception:
            report["ok"] = False
            report["close_error"] = traceback.format_exc()
        save_report()

    def run():
        if state["started"] or state["finished"]:
            return
        state["started"] = True
        try:
            check("normal_windows_qpa", app.platformName() == "windows")
            exposed = QTest.qWaitForWindowExposed(window, 5000)
            expected_size = getattr(getattr(window, "appearance", None), "size", 48)
            check("visible_appearance_sized_ball", exposed and window.isVisible()
                  and window.ball.isVisible()
                  and window.width() == window.height() == expected_size
                  and window.ball.width() == window.ball.height() == expected_size,
                  {"expected_size": expected_size,
                   "window_size": [window.width(), window.height()],
                   "ball_size": [window.ball.width(), window.ball.height()]})
            report["startup_appearance"] = appearance_state()
            check("effects_overlay_is_visible", window.ball.effects.isVisible())
            # The external harness deliberately restarts the same data dir to
            # verify that normal close released the single-instance lock.
            window.tasks = []
            window._save()
            window.rebuild(animated=False)
            QTest.qWait(200)
            check_tasks("isolated_fixture_reset", [])
            check_ships("empty_fixture_has_no_active_ships")
            check("undo_controls_and_history_removed",
                  not any(hasattr(window.panel, name)
                          for name in ("undo_bar", "undo_button", "undo_hint"))
                  and not hasattr(window, "_undo_delete")
                  and not hasattr(window, "_undo_stack"))

            click(window.ball)
            check("ball_click_pins_and_expands", window._pinned
                  and window._expanded and window.panel.isVisible())

            for text in ("GUI verification task 1", "GUI verification task 2"):
                click(window.panel.input)
                QTest.keyClicks(window.panel.input, text)
                QTest.keyClick(window.panel.input, Qt.Key.Key_Return)
                QTest.qWait(450)
            initial = [dict(task) for task in window.tasks]
            check("keyboard_adds_two_tasks", len(initial) == 2
                  and [task["text"] for task in initial]
                  == ["GUI verification task 1", "GUI verification task 2"]
                  and all(task.get("id") for task in initial)
                  and initial[0]["id"] != initial[1]["id"])
            check_tasks("add_is_persisted", initial)
            check_ships("adding_tasks_creates_matching_ships")

            first_id = initial[0]["id"]
            first_row = window._row_map[first_id]
            QTest.mouseDClick(first_row.label, Qt.MouseButton.LeftButton,
                              pos=first_row.label.rect().center())
            QTest.qWait(120)
            editor = first_row._editor
            check("double_click_opens_editor", editor is not None
                  and editor.isVisible())
            QTest.keyClick(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
            QTest.keyClicks(editor, "GUI verification edited task")
            QTest.keyClick(editor, Qt.Key.Key_Return)
            QTest.qWait(450)
            expected = [dict(task) for task in initial]
            expected[0]["text"] = "GUI verification edited task"
            check_tasks("double_click_edit_is_persisted", expected)
            check_ships("editing_tasks_keeps_ship_ids")

            click(window._row_map[first_id].delb)
            check_tasks("delete_button_removes_first_task", [expected[1]])
            check_ships("deleting_task_removes_matching_ship")
            check("remaining_task_keeps_original_id",
                  window.tasks[0]["id"] == initial[1]["id"]
                  and first_id not in window._row_map)
            click(window._row_map[expected[1]["id"]].delb)
            check_tasks("deleting_last_task_persists_empty_list", [])
            check_ships("deleting_all_tasks_removes_active_ships")
            check("empty_list_hint_and_input_are_visible",
                  window.panel.hint.isVisible()
                  and window.panel.input.isVisible()
                  and not window.panel.scroll.isVisible()
                  and window.ball._count == 0)

            # Adding after an empty list exercises the transition back to rows.
            # Keep two representative rows for the release screenshot.
            for text in ("GUI verification edited task", "GUI verification task 2"):
                click(window.panel.input)
                QTest.keyClicks(window.panel.input, text)
                QTest.keyClick(window.panel.input, Qt.Key.Key_Return)
                QTest.qWait(450)
            after_deletion = [dict(task) for task in window.tasks]
            check("input_adds_tasks_after_deleting_all_rows",
                  len(after_deletion) == 2
                  and [task["text"] for task in after_deletion]
                  == ["GUI verification edited task", "GUI verification task 2"]
                  and not window.panel.hint.isVisible()
                  and window.panel.scroll.isVisible()
                  and window.ball._count == 2
                  and not ({task["id"] for task in after_deletion}
                           & {task["id"] for task in initial}),
                  {"tasks": after_deletion, "initial_ids": [task["id"] for task in initial],
                   "hint_visible": window.panel.hint.isVisible(),
                   "scroll_visible": window.panel.scroll.isVisible(),
                   "ball_count": window.ball._count})
            check_tasks("new_tasks_after_empty_list_are_persisted", after_deletion)
            check_ships("adding_after_empty_creates_new_matching_ships")
            exercise_drag()
            exercise_appearance()
            exercise_docking()
            check("rendered_screenshot_saved", capture())
            report["ok"] = True
        except Exception:
            report["ok"] = False
            report["error"] = traceback.format_exc()
            try:
                capture()
            except Exception:
                report["screenshot_error"] = traceback.format_exc()
        finally:
            finish()

    gate_timer = QTimer(window)
    gate_timer.setInterval(50)
    gate_started = time.monotonic()

    def poll_gate():
        if (output / "go").exists():
            gate_timer.stop()
            run()
        elif time.monotonic() - gate_started > 30:
            gate_timer.stop()
            try:
                raise TimeoutError("Verification waited 30 seconds for the go file.")
            except TimeoutError:
                report["error"] = traceback.format_exc()
            finish()

    def ready():
        write_json("ready.json", {
            "pid": os.getpid(),
            "frozen": report["frozen"],
            "platform": report["platform"],
            "executable": sys.executable,
            "window_id": int(window.winId()),
            "visible": window.isVisible(),
            "appearance": appearance_state(),
        })
        save_report()
        if (output / "wait-for-go").exists():
            gate_timer.timeout.connect(poll_gate)
            gate_timer.start()
        else:
            run()

    QTimer.singleShot(300, ready)
