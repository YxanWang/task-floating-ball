"""Coordinate task widgets, panel geometry, animation and persistence."""
import math
import os
import time

from PySide6.QtCore import (Qt, QTimer, QRect, QPoint, QPointF, QPropertyAnimation,
                            QVariantAnimation, QEasingCurve, QFileSystemWatcher)
from PySide6.QtGui import QCursor, QAction
from PySide6.QtWidgets import QApplication, QWidget, QMenu

from .settings import (APP_NAME, PANEL_W, ROW_H, HEAD_H, MAX_VISIBLE,
                       GAP, SLIDE, ROW_LABEL_W)
from .storage import (AppPaths, default_paths, raw_bytes, load_tasks, save_tasks,
                      new_task, parse_tasks, load_position, save_position)
from .appearance import Appearance, load_appearance, save_appearance
from .appearance_dialog import AppearanceDialog
from .docking import exposed_placement, find_dock, placement_for, released_position
from .dock_handle import DockHandle
from .themes import menu_qss
from .water_ball import WaterBall
from .widgets import PanelWindow, TaskRow


class TaskFloatingBall(QWidget):
    """A compact input window, with separate task panel and click-through effects."""

    def __init__(self, paths: AppPaths | None = None):
        super().__init__()
        self.paths = paths or default_paths()
        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.appearance = load_appearance(self.paths.config)
        self.setFixedSize(self.appearance.size, self.appearance.size)
        self._appearance_dialog = None
        self._closing = False
        self._dock_target = None
        self._dock_collapsed = False
        self._dock_transitioning = False
        self._dock_reveal_anim = None
        self._drag_from_handle = False

        self.tasks = load_tasks(self.paths.tasks)
        self._expanded = False
        self._pinned = False
        self._menu_open = False
        self._editing_count = 0
        self._dragging = False
        self._drag_was_expanded = False
        self._panel_mirrored = False
        self._panel_anim = None
        self._h_anim = None
        self._row_map = {}
        self._last_raw = raw_bytes(self.paths.tasks)
        self._drag_target = QPointF()
        self._motion_position = QPointF()
        self._motion_time = 0.0
        self._motion_timer = QTimer(self)
        self._motion_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._motion_timer.setInterval(16)
        self._motion_timer.timeout.connect(self._advance_motion)

        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.setInterval(180)
        self._collapse_timer.timeout.connect(self._maybe_collapse)

        self._dock_hover_timer = QTimer(self)
        self._dock_hover_timer.setSingleShot(True)
        self._dock_hover_timer.setInterval(120)
        self._dock_hover_timer.timeout.connect(self._dock_reveal)
        self._dock_compact_timer = QTimer(self)
        self._dock_compact_timer.setSingleShot(True)
        self._dock_compact_timer.setInterval(110)
        self._dock_compact_timer.timeout.connect(self._dock_compact)
        self._dock_watch_timer = QTimer(self)
        self._dock_watch_timer.setInterval(80)
        self._dock_watch_timer.timeout.connect(self._check_dock_hover)

        self.ball = WaterBall()
        self.ball.setParent(self)
        self.ball.set_appearance(self.appearance.theme, self.appearance.size,
                                 self.appearance.show_ships)
        self.ball.setGeometry(self.rect())
        self.ball.attach_effects(self)
        self.ball.clicked.connect(lambda: self.set_pinned(not self._pinned))
        self.ball.dragStarted.connect(self._start_drag)
        self.ball.dragMoved.connect(self._drag_move)
        self.ball.dragFinished.connect(self._after_drag)
        self.ball.menuRequested.connect(self._show_context_menu)

        self.dock_handle = DockHandle(self, theme=self.appearance.theme)
        self.dock_handle.hide()
        self.dock_handle.revealed.connect(self._queue_dock_reveal)
        self.dock_handle.dragStarted.connect(lambda: self._start_drag(True))
        self.dock_handle.dragMoved.connect(self._drag_move)
        self.dock_handle.dragFinished.connect(self._after_drag)
        self.dock_handle.menuRequested.connect(self._show_context_menu)

        self.panel = PanelWindow(self.appearance.theme)
        self.panel.setParent(self, self.panel.windowFlags())
        self.panel.entered.connect(self._panel_enter)
        self.panel.left.connect(self._panel_left)
        self.panel.submitted.connect(self._add_from_input)
        self._apply_opacity()

        self._watcher = QFileSystemWatcher([str(self.paths.directory)], self)
        self._watcher.directoryChanged.connect(self._on_fs_change)
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(150)
        self._reload_timer.timeout.connect(self._reload_external)

        self._load_config()
        self.rebuild(animated=False)

        if os.environ.get("TASK_FLOATING_BALL_AUTOPIN"):   # 调试钩子：启动即固定展开
            QTimer.singleShot(400, lambda: self.set_pinned(True))

    # ---------------- 尺寸计算（基于球所在的那块屏，而非主屏） ----------------
    def _show_context_menu(self, position):
        self._dock_hover_timer.stop()
        self._stop_dock_reveal(snap=True)
        self._menu_open = True
        menu = QMenu(self)
        menu.setStyleSheet(menu_qss(self.appearance.theme))
        pin = QAction("固定显示", menu)
        pin.setCheckable(True)
        pin.setChecked(self._pinned)
        pin.toggled.connect(self.set_pinned)
        menu.addAction(pin)
        undock = menu.addAction("取消贴边") if self._dock_target is not None else None
        menu.addSeparator()
        appearance = menu.addAction("外观设置…")
        menu.addSeparator()
        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self.close)
        menu.addAction(quit_action)
        try:
            selected = menu.exec(position)
        finally:
            self._menu_open = False
            menu.deleteLater()
        if selected is appearance:
            # Let the native popup finish restoring focus before showing a dialog.
            QTimer.singleShot(0, self._show_appearance_settings)
        elif undock is not None and selected is undock:
            QTimer.singleShot(0, self._undock)

    def _show_appearance_settings(self):
        self._dock_reveal(expand=False)
        self._collapse_timer.stop()
        self._collapse()
        if self._appearance_dialog is None:
            self._appearance_dialog = AppearanceDialog(self, self.appearance)
            self._appearance_dialog.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
            self._appearance_dialog.appearanceChanged.connect(self.set_appearance)
            self._appearance_dialog.finished.connect(self._appearance_finished)
        self._appearance_dialog.set_appearance(self.appearance)
        self._appearance_dialog.adjustSize()
        self._appearance_dialog.show()
        screen = self._screen_for_ball().availableGeometry()
        frame = self._appearance_dialog.frameGeometry()
        frame.moveCenter(screen.center())
        self._appearance_dialog.move(frame.topLeft())
        self._appearance_dialog.raise_()
        self._appearance_dialog.activateWindow()

    def _appearance_finished(self, _result):
        if not self._closing and self._pinned:
            self._expand()
        elif not self._closing and self._dock_target is not None:
            self._dock_watch_timer.start()

    def set_appearance(self, appearance: Appearance):
        self._stop_dock_reveal(snap=True)
        was_compact = self._dock_collapsed
        if was_compact:
            self._dock_reveal(expand=False)
        old_size = self.width()
        center = self.pos() + QPoint(old_size // 2, old_size // 2)
        theme_changed = self.appearance.theme != appearance.theme
        self.appearance = appearance
        self._apply_opacity()
        self._motion_timer.stop()
        self.setFixedSize(appearance.size, appearance.size)
        self.ball.set_appearance(appearance.theme, appearance.size, appearance.show_ships)
        self.ball.setGeometry(self.rect())
        self.dock_handle.set_appearance(appearance.theme)
        if theme_changed:
            self.panel.set_theme(appearance.theme)
            for row in self._row_map.values():
                row.set_theme(appearance.theme)
        if self._appearance_dialog is not None:
            self._appearance_dialog.set_appearance(appearance)
        position = center - QPoint(appearance.size // 2, appearance.size // 2)
        if self._dock_target is None:
            position = self._clamped_position(position)
        if self._dock_target is not None:
            candidate = placement_for(
                self._dock_target.side, self._dock_target.bounds,
                (position.x(), position.y()), appearance.size, padding=self._dock_padding())
            if exposed_placement(candidate, self._dock_screens()):
                self._dock_target = candidate
                position = QPoint(*candidate.anchor)
            else:
                self._dock_target = None
                self._dock_watch_timer.stop()
                position = QPoint(*released_position(
                    (position.x(), position.y()), appearance.size, self._dock_screens(),
                    padding=self._dock_padding()))
        self.move(position)
        self._motion_position = QPointF(position)
        self._drag_target = QPointF(position)
        if self._expanded:
            self._stop_panel_anims()
            geometry, self._panel_mirrored = self._panel_geometry()
            self.panel.setFixedSize(geometry.size())
            self.panel.move(geometry.topLeft())
        try:
            save_appearance(self.paths.config, appearance)
        except OSError:
            # Applying a visual preference must not break the running GUI.
            pass
        self._save_config()
        if self.isVisible():
            self.ball.show_effects()
        if was_compact:
            self._dock_compact(force=True)

    def _apply_opacity(self):
        opacity = self.appearance.opacity / 100
        self.setWindowOpacity(opacity)
        self.panel.setWindowOpacity(opacity)
        if self.ball.effects is not None:
            self.ball.effects.setWindowOpacity(opacity)

    # ---------------- 屏幕贴边：正常球锚点与紧凑手柄分开保存 ----------------
    def _dock_screens(self):
        return [(r.x(), r.y(), r.width(), r.height())
                for screen in QApplication.screens()
                for r in (screen.availableGeometry(),)]

    def _dock_padding(self):
        return 4

    def _dock_capture_distance(self):
        # Preserve the previous drag-to-edge capture band independently of the
        # much tighter revealed position; large balls still have drag padding.
        previous_padding = (self.ball.scene.extent - self.appearance.size // 2 + 2
                            if self.appearance.show_ships else 4)
        return 24 + previous_padding - self._dock_padding()

    def _dock_blocked(self):
        return (self._closing or self._dragging or self._motion_timer.isActive()
                or self._dock_reveal_anim is not None
                or self._pinned or self._menu_open
                or self._editing_count > 0 or self.panel.input.hasFocus()
                or (self._appearance_dialog is not None
                    and self._appearance_dialog.isVisible()))

    def _dock_pointer_inside(self):
        if self._dock_target is None:
            return False
        # Keep the path from the old edge handle to the restored sphere open.
        final_ball = QRect(*self._dock_target.anchor,
                           self.appearance.size, self.appearance.size)
        corridor = (QRect(*self._dock_target.handle_rect).united(self.geometry())
                    .united(final_ball))
        return corridor.contains(QCursor.pos())

    def _queue_dock_reveal(self):
        if (self._dock_collapsed and not self._dragging and not self._menu_open
                and self._dock_pointer_inside()):
            self._dock_hover_timer.start()

    def _dock_reveal(self, expand=True):
        self._dock_hover_timer.stop()
        self._dock_compact_timer.stop()
        if (self._dock_target is None
                or (self._dock_collapsed and self.dock_handle.is_pressed())):
            return
        if not expand:
            self._stop_dock_reveal(snap=True)
        if self._dock_collapsed:
            self._dock_transitioning = True
            animated = expand and not self.ball.scene.reduced_motion
            try:
                self._dock_collapsed = False
                self.dock_handle.hide()
                self.setFixedSize(self.appearance.size, self.appearance.size)
                anchor = QPoint(*self._dock_target.anchor)
                if animated:
                    x, y, width, height = self._dock_target.bounds
                    size = self.appearance.size
                    start = {
                        "left": QPoint(x - size + 12, anchor.y()),
                        "right": QPoint(x + width - 12, anchor.y()),
                        "top": QPoint(anchor.x(), y - size + 12),
                        "bottom": QPoint(anchor.x(), y + height - 12),
                    }[self._dock_target.side]
                    self.move(start)
                else:
                    self.move(anchor)
                self.ball.setGeometry(self.rect())
                self.ball.show()
                if self.isVisible():
                    self.ball.show_effects()
                if animated:
                    animation = QPropertyAnimation(self, b"pos", self)
                    animation.setDuration(140)
                    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
                    animation.setStartValue(start)
                    animation.setEndValue(anchor)
                    self._dock_reveal_anim = animation

                    def finished():
                        if self._dock_reveal_anim is not animation:
                            return
                        self._dock_reveal_anim = None
                        self._dock_transitioning = False
                        animation.deleteLater()
                        if not self._closing:
                            self._expand()

                    animation.finished.connect(finished)
                    animation.start()
            finally:
                if self._dock_reveal_anim is None:
                    self._dock_transitioning = False
        self._dock_watch_timer.start()
        if expand and self._dock_reveal_anim is None:
            self._expand()

    def _stop_dock_reveal(self, snap=False):
        animation = self._dock_reveal_anim
        if animation is None:
            return
        self._dock_reveal_anim = None
        animation.stop()
        animation.deleteLater()
        self._dock_transitioning = True
        try:
            if snap and self._dock_target is not None and not self._dock_collapsed:
                self.move(QPoint(*self._dock_target.anchor))
        finally:
            self._dock_transitioning = False

    def _dock_compact(self, force=False):
        if (self._dock_target is None or self._dock_collapsed or self._dock_blocked()
                or (not force and (self._expanded or self._dock_pointer_inside()))):
            return
        self._dock_transitioning = True
        try:
            self._collapse_timer.stop()
            self._dock_hover_timer.stop()
            self._dock_compact_timer.stop()
            self._dock_watch_timer.stop()
            self._stop_panel_anims()
            self.panel.hide()
            self._expanded = False
            self.ball.hide()
            self.ball.hide_effects()
            self._dock_collapsed = True
            x, y, width, height = self._dock_target.handle_rect
            self.setFixedSize(width, height)
            self.move(x, y)
            self.dock_handle.set_appearance(self.appearance.theme, self._dock_target.side)
            self.dock_handle.setGeometry(self.rect())
            self.dock_handle.show()
            # Flush the new layered-window pixels before returning the compact
            # state; its previous transparent ball corners must not pass clicks.
            self.dock_handle.repaint()
            self._save_config()
        finally:
            self._dock_transitioning = False

    def _check_dock_hover(self):
        if self._dock_target is None or self._dock_collapsed:
            self._dock_watch_timer.stop()
            return
        w = QApplication.widgetAt(QCursor.pos())
        over_panel = w is self.panel or (w is not None and self.panel.isAncestorOf(w))
        if self._dock_blocked() or self._dock_pointer_inside() or over_panel:
            self._collapse_timer.stop()
        elif not self._collapse_timer.isActive():
            self._collapse_timer.start()

    def _undock(self):
        self._dock_reveal(expand=False)
        self._dock_target = None
        self._dock_hover_timer.stop()
        self._dock_compact_timer.stop()
        self._dock_watch_timer.stop()
        self._save_config()

    def _editing_started(self):
        self._editing_count += 1

    def _editing_finished(self):
        self._editing_count = max(0, self._editing_count - 1)

    def _screen_for_ball(self):
        s = QApplication.screenAt(self.pos() + self.rect().center())
        return s if s is not None else QApplication.primaryScreen()

    def _desktop_bounds(self):
        """所有显示器的联合包围盒（拖动可在多屏间移动）。"""
        return QApplication.primaryScreen().virtualGeometry()

    def _visible_rows(self):
        n = len(self.tasks)
        if n == 0:
            return 0
        rows = min(n, MAX_VISIBLE)
        scr = self._screen_for_ball().availableGeometry()
        avail = scr.bottom() + 1 - self.y()
        fit = (avail - (10 + HEAD_H + 6 + 6 + 34 + 10)) // ROW_H
        if fit < rows:
            rows = max(1, min(rows, fit))
        return rows

    def _panel_h(self):
        rows = self._visible_rows()
        inner = 22 if rows == 0 else HEAD_H + 6 + rows * ROW_H
        return 10 + inner + 6 + 34 + 10

    def _panel_geometry(self):
        h = self._panel_h()
        scr = self._screen_for_ball().availableGeometry()
        bx, by = self.x(), self.y()
        gap = GAP + (math.ceil(self.width() * .35) if self.appearance.show_ships else 0)
        mirrored = (bx + self.width() + gap + PANEL_W) > (scr.right() + 1)
        px = bx - gap - PANEL_W if mirrored else bx + self.width() + gap
        px = max(scr.left(), min(px, scr.right() - PANEL_W + 1))
        py = max(scr.top(), min(by, scr.bottom() - h + 1))
        return QRect(px, py, PANEL_W, h), mirrored

    # ---------------- 展开与收起（从球后滑出/滑回，纯几何动画） ----------------
    # 注意：WA_TranslucentBackground 的分层窗口上绝不能用 windowOpacity 或
    # QGraphicsOpacityEffect 做渐变——Windows 会把系统级 alpha 卡在半路，
    # 导致面板背景永久变透明（实机踩坑验证过）。
    def _stop_panel_anims(self):
        if self._panel_anim is not None:
            self._panel_anim.stop()
            self._panel_anim.deleteLater()
            self._panel_anim = None

    def _away_vector(self):
        return QPoint(-SLIDE if self._panel_mirrored else SLIDE, 0)

    def _expand(self):
        if self._closing or self._dock_reveal_anim is not None:
            return
        if self._dock_collapsed:
            self._dock_reveal()
            return
        if self._expanded or self._dragging:
            return
        self._dock_compact_timer.stop()
        self._expanded = True
        geo, mirrored = self._panel_geometry()
        self._panel_mirrored = mirrored
        self._stop_panel_anims()
        p = self.panel
        p.setFixedSize(geo.width(), geo.height())
        start = geo.topLeft() - self._away_vector()
        p.move(start)
        p.show()
        p.raise_()
        pa = QPropertyAnimation(p, b"pos", self)
        pa.setDuration(200)
        pa.setEasingCurve(QEasingCurve.Type.OutCubic)
        pa.setStartValue(start)
        pa.setEndValue(geo.topLeft())
        self._panel_anim = pa
        pa.start()

    def _collapse(self):
        if not self._expanded:
            if self._dock_target is not None and not self._dock_collapsed:
                self._dock_compact_timer.start(0)
            return
        self._expanded = False
        self._stop_panel_anims()
        p = self.panel
        pa = QPropertyAnimation(p, b"pos", self)
        pa.setDuration(110)
        pa.setEasingCurve(QEasingCurve.Type.InCubic)
        pa.setStartValue(p.pos())
        pa.setEndValue(p.pos() - self._away_vector())
        pa.finished.connect(p.hide)
        self._panel_anim = pa
        pa.start()
        if self._dock_target is not None:
            self._dock_compact_timer.start(110)
        self._save_config()

    # ---------------- 悬停逻辑 ----------------
    def enterEvent(self, e):
        self._collapse_timer.stop()
        if self._dock_transitioning:
            return super().enterEvent(e)
        if self._dock_collapsed:
            self._queue_dock_reveal()
        elif not self._expanded and not self._dragging:
            self._expand()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._dock_hover_timer.stop()
        if not self._dragging:
            self._collapse_timer.start()
        super().leaveEvent(e)

    def _panel_enter(self):
        self._collapse_timer.stop()

    def _panel_left(self):
        if not self._dragging:
            self._collapse_timer.start()

    def _maybe_collapse(self):
        if self._dock_blocked():
            return
        if self._dock_pointer_inside():
            return
        w = QApplication.widgetAt(QCursor.pos())
        if w is not None and (w is self or self.isAncestorOf(w)
                              or w is self.panel or self.panel.isAncestorOf(w)):
            return
        self._collapse()

    def set_pinned(self, val):
        self._pinned = bool(val)
        self.ball.set_state(len(self.tasks), self._pinned)
        if self._pinned:
            self._expand()

    # ---------------- 拖动：球永不出屏，面板绝不弹出 ----------------
    def _start_drag(self, from_handle=False):
        self._stop_dock_reveal()
        self._drag_from_handle = bool(from_handle)
        self._dock_target = None
        self._dock_hover_timer.stop()
        self._dock_compact_timer.stop()
        self._dock_watch_timer.stop()
        self._dragging = True
        self._drag_was_expanded = self._expanded or self._pinned
        self._collapse_timer.stop()
        self._stop_panel_anims()
        self._expanded = False
        self.panel.hide()
        self._drag_target = QPointF(self.pos())
        self._motion_position = QPointF(self.pos())
        self._motion_time = time.monotonic()
        self.ball.set_motion(0.0, 0.0, True)

    def _drag_move(self, delta):
        self._drag_target = QPointF(self._clamped_position(
            (self._drag_target + QPointF(delta)).toPoint()))
        if not self._motion_timer.isActive():
            self._motion_time = time.monotonic()
            self._motion_timer.start()

    def _after_drag(self):
        if self._drag_from_handle:
            self._restore_handle_drag()
        self._dragging = False
        self.ball.release_motion()
        position = self._drag_target.toPoint()
        screens = self._dock_screens()
        target = QPoint(*released_position(
            (position.x(), position.y()), self.appearance.size, screens,
            padding=self._dock_padding()))
        self._drag_target = QPointF(target)
        self._dock_target = find_dock(
            (target.x(), target.y()), self.appearance.size, screens,
            padding=self._dock_padding(), threshold=self._dock_capture_distance())
        if self._dock_target is not None:
            self._drag_target = QPointF(QPoint(*self._dock_target.anchor))
        if self._drag_target != self._motion_position and not self._motion_timer.isActive():
            self._motion_time = time.monotonic()
            self._motion_timer.start()
        if not self._motion_timer.isActive():
            self._finish_motion()

    def _restore_handle_drag(self):
        offset = QPointF((self.width() - self.appearance.size) / 2,
                         (self.height() - self.appearance.size) / 2)
        self._drag_from_handle = False
        self._dock_transitioning = True
        try:
            self._dock_collapsed = False
            self.dock_handle.hide()
            self.setFixedSize(self.appearance.size, self.appearance.size)
            self._motion_position = QPointF(self._clamped_position(
                (self._motion_position + offset).toPoint()))
            self._drag_target = QPointF(self._clamped_position(
                (self._drag_target + offset).toPoint()))
            self.move(self._motion_position.toPoint())
            self.ball.setGeometry(self.rect())
            self.ball.show()
            self.ball.show_effects()
        finally:
            self._dock_transitioning = False

    def _advance_motion(self):
        now = time.monotonic()
        dt = max(.001, min(.034, now - self._motion_time))
        self._motion_time = now
        previous = QPointF(self._motion_position)
        follow = (1.0 if self.ball.scene.reduced_motion
                  else 1 - math.exp(-dt / .0602))
        self._motion_position += (self._drag_target - self._motion_position) * follow
        difference = self._drag_target - self._motion_position
        distance = math.hypot(difference.x(), difference.y())
        maximum = 37 * self.width() / 54
        if self._dragging and distance > maximum:
            self._motion_position = self._drag_target - difference * (maximum / distance)
        velocity = (self._motion_position - previous) / dt
        self.move(self._motion_position.toPoint())
        self.ball.set_motion(velocity.x(), velocity.y(), self._dragging)
        if not self._dragging and distance < .2:
            self._motion_timer.stop()
            self._motion_position = QPointF(self._drag_target)
            self.move(self._drag_target.toPoint())
            self.ball.set_motion(0.0, 0.0, False)
            self._finish_motion()

    def _finish_motion(self):
        self._save_config()
        if self._dock_target is not None:
            self._drag_was_expanded = False
            if self._pinned:
                self._expand()
                self._dock_watch_timer.start()
            else:
                self._dock_compact(force=True)
            return
        if self._drag_was_expanded and (
                self._pinned
                or self.rect().contains(self.mapFromGlobal(QCursor.pos()))):
            self._expand()
        self._drag_was_expanded = False

    def _clamped_position(self, position):
        desk = self._desktop_bounds()
        if self._drag_from_handle:
            return QPoint(max(desk.left(), min(position.x(), desk.right() - self.width() + 1)),
                          max(desk.top(), min(position.y(), desk.bottom() - self.height() + 1)))
        padding = math.ceil(self.width() * (.40 if self.appearance.show_ships else .25))
        return QPoint(max(desk.left() + padding,
                          min(position.x(), desk.right() - self.width() - padding + 1)),
                      max(desk.top() + padding,
                          min(position.y(), desk.bottom() - self.height() - padding + 1)))

    # ---------------- 行布局：绝对定位 + 平滑归位（纯几何动画） ----------------
    def _row_slide_dir(self):
        """行从球一侧滑入/滑出：默认球在左从左滑入，镜像时球在右从右滑入。"""
        return QPoint(SLIDE if self._panel_mirrored else -SLIDE, 0)

    def _animate_row(self, row, start, target, duration, *, remove=False):
        old = getattr(row, "_pos_anim", None)
        if old is not None:
            old.stop()
            old.deleteLater()
        row.move(start)
        a = QPropertyAnimation(row, b"pos", row)
        a.setDuration(duration)
        a.setEasingCurve(QEasingCurve.Type.InCubic if remove
                         else QEasingCurve.Type.OutCubic)
        a.setStartValue(start)
        a.setEndValue(target)

        def finished():
            if getattr(row, "_pos_anim", None) is a:
                row._pos_anim = None
            if remove:
                row.deleteLater()
            a.deleteLater()

        a.finished.connect(finished)
        row._pos_anim = a
        a.start()

    def _animate_row_move(self, row, target):
        if row.pos() != target:
            self._animate_row(row, row.pos(), target, 230)

    def _animate_row_in(self, row, target):
        self._animate_row(row, target + self._row_slide_dir(), target, 240)

    def _animate_row_out(self, row):
        self._animate_row(row, row.pos(), row.pos() + self._row_slide_dir(),
                          180, remove=True)

    def _tween_panel_height(self, new_h):
        p = self.panel
        if self._h_anim is not None:
            self._h_anim.stop()
            self._h_anim.deleteLater()
            self._h_anim = None

        def apply_height(height):
            p.setFixedHeight(int(height))
            if p.isVisible():
                scr = self._screen_for_ball().availableGeometry()
                py = max(scr.top(), min(self.y(), scr.bottom() - p.height() + 1))
                p.move(p.x(), py)

        if p.isVisible() and self._expanded:
            # 高度变化时结束展开位移动画，避免旧的 y 坐标覆盖新的贴边位置。
            self._stop_panel_anims()
            p.move(self._panel_geometry()[0].x(), p.y())
        if not p.isVisible() or abs(p.height() - new_h) < 2:
            apply_height(new_h)
            return
        a = QVariantAnimation(p)
        a.setStartValue(p.height())
        a.setEndValue(new_h)
        a.setDuration(150)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        a.valueChanged.connect(apply_height)

        def finished():
            apply_height(new_h)
            if self._h_anim is a:
                self._h_anim = None
            a.deleteLater()

        a.finished.connect(finished)
        self._h_anim = a
        a.start()

    def rebuild(self, animated=None):
        if animated is None:
            animated = self.panel.isVisible()
        order = list(self.tasks)
        ids = {t["id"] for t in order}

        for rid in list(self._row_map):
            if rid not in ids:
                row = self._row_map.pop(rid)
                row.cancel_edit()
                if animated:
                    old = getattr(row, "_pos_anim", None)
                    if old is not None:
                        old.stop()
                    self._animate_row_out(row)
                else:
                    row.deleteLater()

        for i, t in enumerate(order):
            target = QPoint(0, i * ROW_H)
            row = self._row_map.get(t["id"])
            if row is None:
                row = TaskRow(t, ROW_LABEL_W, self.appearance.theme)
                row.deleted.connect(self._delete)
                row.edited.connect(self._edit)
                row.editingStarted.connect(self._editing_started)
                row.editingFinished.connect(self._editing_finished)
                row.setParent(self.panel.host)
                self._row_map[t["id"]] = row
                row.show()
                if animated:
                    self._animate_row_in(row, target)
                else:
                    row.move(target)
            else:
                row.refresh(t)
                if animated:
                    self._animate_row_move(row, target)
                else:
                    old = getattr(row, "_pos_anim", None)
                    if old is not None:
                        old.stop()
                        old.deleteLater()
                        row._pos_anim = None
                    row.move(target)

        n = len(order)
        self.panel.host.setFixedHeight(max(n, 1) * ROW_H)
        if n:
            self.panel.scroll.show()
            self.panel.scroll.setFixedHeight(self._visible_rows() * ROW_H)
        else:
            self.panel.scroll.hide()
        self.panel.hint.setVisible(n == 0)
        self.panel.head.setVisible(n > 0)
        self.panel.head_count.setText(str(n))
        self._tween_panel_height(self._panel_h())
        self.ball.set_tasks([task["id"] for task in order])
        self.ball.set_state(n, self._pinned)

    # ---------------- 增删改 ----------------
    def _add_from_input(self):
        text = self.panel.input.text().strip()
        if not text:
            return
        self.tasks.append(new_task(text))
        self._save()
        self.rebuild()
        self.panel.input.clear()
        self.panel.input.setFocus()

    def _delete(self, tid):
        for index, task in enumerate(self.tasks):
            if task["id"] == tid:
                del self.tasks[index]
                break
        else:
            return
        self._save()
        self.rebuild()

    def _edit(self, tid, text):
        for t in self.tasks:
            if t["id"] == tid:
                t["text"] = text
                break
        self._save()
        self.rebuild()

    def _save(self):
        save_tasks(self.paths.tasks, self.tasks)
        self._last_raw = raw_bytes(self.paths.tasks)

    # ---------------- 外部文件变化 ----------------
    def _on_fs_change(self, _path):
        self._reload_timer.start()

    def _reload_external(self):
        raw = raw_bytes(self.paths.tasks)
        if raw == self._last_raw:
            return
        try:
            tasks = parse_tasks(raw)
        except ValueError:
            return
        self.tasks = tasks
        self._last_raw = raw
        self.rebuild()

    # ---------------- 位置配置 ----------------
    def _load_config(self):
        pos = load_position(self.paths.config)
        scr = QApplication.primaryScreen().availableGeometry()
        if pos is None:
            pos = (scr.right() - self.width() - 24, scr.top() + 120)
        self.move(self._clamped_position(QPoint(*pos)))

    def _save_config(self):
        try:
            if self._dock_target is not None:
                x, y = self._dock_target.anchor
            elif self._dock_collapsed:
                x = self.x() + (self.width() - self.appearance.size) // 2
                y = self.y() + (self.height() - self.appearance.size) // 2
            else:
                x, y = self.x(), self.y()
            save_position(self.paths.config, x, y)
        except OSError:
            pass

    def closeEvent(self, e):
        self._closing = True
        self._stop_dock_reveal(snap=True)
        self._collapse_timer.stop()
        self._dock_hover_timer.stop()
        self._dock_compact_timer.stop()
        self._dock_watch_timer.stop()
        self._motion_timer.stop()
        self._stop_panel_anims()
        if self._h_anim is not None:
            self._h_anim.stop()
            self._h_anim.deleteLater()
            self._h_anim = None
        self.ball.stop_effects()
        if self._appearance_dialog is not None:
            self._appearance_dialog.close()
        self._save_config()
        self.panel.close()
        super().closeEvent(e)
        # Qt.Tool 窗口关闭时不会自动结束应用，必须退出事件循环并释放实例锁。
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._dock_collapsed:
            self.ball.show_effects()

    def hideEvent(self, event):
        if hasattr(self, "ball"):
            self.ball.hide_effects()
        super().hideEvent(event)

    def moveEvent(self, event):
        super().moveEvent(event)
        if hasattr(self, "ball") and self.ball.effects is not None:
            self.ball.effects.sync_to_ball()
