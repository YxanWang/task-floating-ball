"""Water material, stable task satellites, and a mouse-transparent effects window."""

from dataclasses import dataclass
import ctypes
import hashlib
import math
import os
import sys
import time

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
    QRadialGradient, QTransform,
)
from PySide6.QtWidgets import QWidget


TAU = math.tau
THEMES = {
    "ocean": dict(top="#1a5662", middle="#0e3b4a", bottom="#102737",
                  text="#ffffff", light="#b4e8e5", refract="#53bcb9",
                  soft=.16, refraction=.14, upper=.29, lower=.32,
                  ship_light="#40889a", ship_dark="#cbecef", edge=None),
    "moon": dict(top="#fbfcfb", middle="#e8eff0", bottom="#c5d3d9",
                 text="#29424e", light="#ffffff", refract="#8aabb6",
                 soft=.46, refraction=.18, upper=.70, lower=.26,
                 ship_light="#718c9a", ship_dark="#deedf4", edge="#9cb4bf"),
    "amber": dict(top="#775d38", middle="#4d3929", bottom="#302626",
                  text="#fff2df", light="#e9d3ab", refract="#c5a16d",
                  soft=.19, refraction=.16, upper=.31, lower=.31,
                  ship_light="#9a794e", ship_dark="#ead4af", edge=None),
}


def _clamp(value, low, high):
    return max(low, min(high, value))


def _color(value, opacity=1.0):
    color = QColor(value)
    color.setAlphaF(_clamp(opacity, 0.0, 1.0))
    return color


def system_reduced_motion():
    """Respect Windows' client-area animation preference, with a test override."""
    override = os.environ.get("TASK_FLOATING_BALL_REDUCED_MOTION")
    if override is not None:
        return override.lower() in ("1", "true", "yes")
    if sys.platform == "win32":
        enabled = ctypes.c_int(1)
        try:
            if ctypes.windll.user32.SystemParametersInfoW(
                    0x1042, 0, ctypes.byref(enabled), 0):
                return not bool(enabled.value)
        except (AttributeError, OSError):
            pass
    return False


@dataclass
class Satellite:
    task_id: str
    a: float
    e: float
    inclination: float
    node: float
    periapsis: float
    phase: float
    entering: float = 0.0
    leaving: float = 0.0

    @classmethod
    def for_task(cls, task_id):
        digest = hashlib.blake2b(task_id.encode("utf-8"), digest_size=24).digest()
        values = [int.from_bytes(digest[i:i + 4], "little") / 0xffffffff
                  for i in range(0, 24, 4)]
        outer = digest[0] & 1
        return cls(task_id, (39 if outer else 37) + (values[0] * 2 - 1) * .65,
                   (.045 if outer else .05) + (values[1] * 2 - 1) * .003,
                   (.84 if outer else .72) + (values[2] * 2 - 1) * .022,
                   (-.23 if outer else -.35) + (values[3] * 2 - 1) * .012,
                   .21 if outer else .24, values[4] * TAU)


class WaterScene:
    """Animation state independent of windows, files, and the task repository."""

    def __init__(self):
        self.theme = "ocean"
        self.size = 54
        self.show_ships = True
        self.paused = False
        self.reduced_motion = False
        self.ships = {}
        self.exiting = []
        self.clock = 0.0
        self.strength = 0.0
        self.angle = 0.0
        self.vx = self.vy = 0.0
        self.dragging = False
        self.motion_seen = False
        self.fleet_x = self.fleet_y = 0.0
        self.light_x = self.light_y = 0.0
        self.release_age = math.inf
        self.ripple = False

    @property
    def task_ids(self):
        return tuple(self.ships)

    @property
    def scale(self):
        return self.size / 54.0

    @property
    def extent(self):
        return math.ceil(48 * self.scale + 8)

    def clear_transitions(self):
        self.exiting.clear()
        for ship in self.ships.values():
            ship.entering = 0.0

    def set_tasks(self, task_ids, animate=True):
        identifiers = tuple(dict.fromkeys(str(value) for value in task_ids))
        wanted = set(identifiers)
        animate = animate and self.show_ships and not self.paused and not self.reduced_motion
        for identifier in tuple(self.ships):
            if identifier not in wanted:
                ship = self.ships.pop(identifier)
                if animate:
                    ship.entering = 0.0
                    ship.leaving = .001
                    self.exiting.append(ship)
        departed = {ship.task_id: ship for ship in self.exiting}
        ordered = {}
        for identifier in identifiers:
            ship = self.ships.get(identifier)
            if ship is None:
                ship = departed.get(identifier) or Satellite.for_task(identifier)
                self.exiting = [item for item in self.exiting if item.task_id != identifier]
                ship.leaving = 0.0
                ship.entering = 1.0 if animate else 0.0
            ordered[identifier] = ship
        self.ships = ordered
        if not animate:
            self.clear_transitions()

    def set_motion(self, vx, vy, dragging):
        self.vx = _clamp(float(vx), -10000, 10000) if math.isfinite(vx) else 0.0
        self.vy = _clamp(float(vy), -10000, 10000) if math.isfinite(vy) else 0.0
        self.dragging = bool(dragging)
        self.motion_seen |= self.dragging and math.hypot(self.vx, self.vy) > 2

    def release_motion(self):
        if self.dragging or math.hypot(self.vx, self.vy) > 0:
            self.release_age = 0.0
            self.ripple = self.motion_seen and not self.reduced_motion
        self.dragging = False
        self.vx = self.vy = 0.0
        self.motion_seen = False

    def needs_animation(self):
        if self.reduced_motion:
            return False
        orbiting = self.show_ships and not self.paused and bool(self.ships or self.exiting)
        settling = (self.strength > .001 or math.hypot(self.fleet_x, self.fleet_y) > .02
                    or math.hypot(self.light_x, self.light_y) > .005
                    or self.release_age < .5)
        moving = self.dragging and math.hypot(self.vx, self.vy) > 2
        return orbiting or settling or moving

    def advance(self, dt):
        dt = _clamp(float(dt), .001, .05)
        if self.reduced_motion:
            self.strength = self.fleet_x = self.fleet_y = 0.0
            self.light_x = self.light_y = 0.0
            self.ripple = False
            self.clear_transitions()
            return
        speed = math.hypot(self.vx, self.vy)
        desired = min(1.0, speed / 650) if self.dragging else 0.0
        self.strength += (desired - self.strength) * (1 - math.exp(-dt / .042))
        if self.dragging and speed > 8:
            angle = math.atan2(self.vy, self.vx)
            difference = math.atan2(math.sin(angle - self.angle), math.cos(angle - self.angle))
            self.angle += difference * (1 - math.exp(-dt / .028))
        target_x = _clamp(-self.vx / 650, -1, 1) * 1.2 if self.dragging else 0.0
        target_y = _clamp(-self.vy / 650, -1, 1) * 1.2 if self.dragging else 0.0
        follow = 1 - math.exp(-dt / .058)
        self.light_x += (target_x - self.light_x) * follow
        self.light_y += (target_y - self.light_y) * follow
        target_x = -self.vx * .015 if self.dragging else 0.0
        target_y = -self.vy * .015 if self.dragging else 0.0
        distance = math.hypot(target_x, target_y)
        if distance > 4:
            target_x *= 4 / distance
            target_y *= 4 / distance
        follow = 1 - math.exp(-dt / .015)
        self.fleet_x += (target_x - self.fleet_x) * follow
        self.fleet_y += (target_y - self.fleet_y) * follow
        if self.show_ships and not self.paused:
            self.clock += dt
            for ship in self.ships.values():
                ship.entering = max(0.0, ship.entering - dt / .4)
            for ship in self.exiting:
                ship.leaving += dt / .35
            self.exiting = [ship for ship in self.exiting if ship.leaving < 1]
        self.release_age += dt
        self.ripple &= self.release_age < .31
        if self.strength < .001:
            self.strength = 0.0
        if math.hypot(self.fleet_x, self.fleet_y) < .02:
            self.fleet_x = self.fleet_y = 0.0
        if math.hypot(self.light_x, self.light_y) < .005:
            self.light_x = self.light_y = 0.0

    def position(self, ship, mean_offset=0.0):
        rate = math.pi / 10 * (37 / ship.a) ** 1.5
        mean = (ship.phase + self.clock * rate + mean_offset) % TAU
        eccentric = mean
        for _ in range(4):
            eccentric -= (eccentric - ship.e * math.sin(eccentric) - mean) / (1 - ship.e * math.cos(eccentric))
        u = ship.a * (math.cos(eccentric) - ship.e)
        v = ship.a * math.sqrt(1 - ship.e ** 2) * math.sin(eccentric)
        du, dv = -math.sin(eccentric), math.sqrt(1 - ship.e ** 2) * math.cos(eccentric)
        cosine, sine = math.cos(ship.periapsis), math.sin(ship.periapsis)
        x, y = u * cosine - v * sine, u * sine + v * cosine
        tx, ty = du * cosine - dv * sine, du * sine + dv * cosine
        tangent = math.hypot(tx, ty)
        offset = -12 * ship.entering ** 2 + 13 * ship.leaving ** 2
        x += tx / tangent * offset
        y += ty / tangent * offset
        projected_y = y * math.cos(ship.inclination)
        z = y * math.sin(ship.inclination)
        px = (x * math.cos(ship.node) - projected_y * math.sin(ship.node)) * self.scale + self.fleet_x
        py = (x * math.sin(ship.node) + projected_y * math.cos(ship.node)) * self.scale + self.fleet_y
        depth = _clamp(z / (ship.a * math.sin(ship.inclination)), -1, 1)
        alpha = (1 - ship.entering * .7) * (1 - ship.leaving)
        return px, py, depth, alpha


class WaterEffects(QWidget):
    """Top-level visual surface; Windows sends all its input to windows below."""

    def __init__(self, ball, owner=None):
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                 | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput
                 | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.NoDropShadowWindowHint)
        super().__init__(owner, flags)
        self.ball = ball
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWindowTitle("任务悬浮球 · 水感效果")
        self.sync_to_ball()

    def sync_to_ball(self):
        extent = self.ball.scene.extent
        size = extent * 2
        center = self.ball.mapToGlobal(QPoint(self.ball.width() // 2, self.ball.height() // 2))
        self.setGeometry(center.x() - extent, center.y() - extent, size, size)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.ball._paint_scene(painter, QPointF(self.width() / 2, self.height() / 2), True)


class WaterBall(QWidget):
    """Input target plus a reusable water scene; attach_effects enables its overlay."""

    clicked = Signal()
    dragStarted = Signal()
    dragMoved = Signal(QPoint)
    dragFinished = Signal()
    menuRequested = Signal(QPoint)

    def __init__(self, parent=None, *, input_only=False):
        super().__init__(parent)
        self.scene = WaterScene()
        self.scene.reduced_motion = system_reduced_motion()
        self.input_only = bool(input_only)
        self.effects = None
        self._count = 0
        self._pinned = False
        self._press = None
        self._moved = False
        self._have_tasks = False
        self._stopped = False
        self._last_time = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(54, 54)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def attach_effects(self, owner=None):
        if self.effects is None:
            self.effects = WaterEffects(self, owner)
        self.input_only = True
        self.update()
        return self.effects

    def show_effects(self):
        if self.effects is not None and not self._stopped:
            self.effects.sync_to_ball()
            self.effects.show()
            self.effects.raise_()
        self._ensure_timer()

    def hide_effects(self):
        if self.effects is not None:
            self.effects.hide()
        self._timer.stop()

    def stop_effects(self):
        self._stopped = True
        self._timer.stop()
        if self.effects is not None:
            self.effects.close()
            self.effects.deleteLater()
            self.effects = None

    def set_state(self, count, pinned):
        self._count = max(0, int(count))
        self._pinned = bool(pinned)
        if not self._have_tasks:
            self.scene.set_tasks((f"count-{i}" for i in range(self._count)), animate=False)
        self._refresh()

    def set_tasks(self, task_ids):
        animate = self._have_tasks and self.isVisible()
        self.scene.set_tasks(task_ids, animate=animate)
        self._have_tasks = True
        self._count = len(self.scene.ships)
        self._refresh()

    def set_appearance(self, theme, size, show_ships):
        self.scene.theme = theme if theme in THEMES else "ocean"
        self.scene.size = _clamp(int(round(float(size) / 2)) * 2, 40, 80)
        self.scene.show_ships = bool(show_ships)
        if not self.scene.show_ships:
            self.scene.clear_transitions()
        self.setFixedSize(self.scene.size, self.scene.size)
        if self.effects is not None:
            self.effects.sync_to_ball()
        self._refresh()

    def set_motion(self, vx, vy, dragging):
        self.scene.set_motion(vx, vy, dragging)
        if self.scene.reduced_motion:
            self.scene.advance(.016)
        self._refresh()

    def release_motion(self):
        self.scene.release_motion()
        self._refresh()

    def set_paused(self, paused):
        self.scene.paused = bool(paused)
        if self.scene.paused:
            self.scene.clear_transitions()
        self._refresh()

    def set_reduced_motion(self, reduced):
        self.scene.reduced_motion = bool(reduced)
        if reduced:
            self.scene.advance(.016)
        self._refresh()

    def _ensure_timer(self):
        visible = self.isVisible() and (self.effects is None or self.effects.isVisible())
        if not self._stopped and visible and self.scene.needs_animation():
            if not self._timer.isActive():
                self._last_time = time.monotonic()
                self._timer.start()
        else:
            self._timer.stop()

    def _refresh(self):
        self.update()
        if self.effects is not None:
            self.effects.update()
        self._ensure_timer()

    def _tick(self):
        now = time.monotonic()
        self.scene.advance(now - self._last_time)
        self._last_time = now
        self.update()
        if self.effects is not None:
            self.effects.update()
        self._ensure_timer()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.input_only:
            # Keep at least one effective alpha step even at 30% window opacity,
            # so Windows still sends clicks to the otherwise transparent target.
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 4))
            painter.drawEllipse(QRectF(self.rect()))
        else:
            self._paint_scene(painter, QPointF(self.width() / 2, self.height() / 2), False)

    def _paint_scene(self, painter, center, include_satellites):
        painter.save()
        painter.translate(center)
        if include_satellites:
            self._paint_satellites(painter, front=False)
        self._paint_core(painter)
        if include_satellites:
            self._paint_satellites(painter, front=True)
        if self.scene.ripple and not self.scene.reduced_motion:
            progress = _clamp(self.scene.release_age / .31, 0, 1)
            radius = self.scene.size / 2 * (1.015 + progress * .16)
            painter.setPen(QPen(_color(THEMES[self.scene.theme]["refract"], (1 - progress) * .15), .65))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(), radius, radius)
        painter.restore()

    def _paint_core(self, painter):
        scene = self.scene
        theme = THEMES[scene.theme]
        painter.save()
        painter.scale(scene.scale, scene.scale)
        rebound = 0.0
        if not scene.reduced_motion and scene.release_age < .35:
            rebound = math.sin(scene.release_age / .35 * TAU) * math.exp(-scene.release_age / .085) * .045
        strength = scene.strength + rebound
        positive = max(0.0, strength)
        front, back = 27 + .6 * positive, -27 - 12 * positive
        ry, k = 27 * (1 - .12 * strength), 14.9117
        handle = k * (1 - .1 * positive)
        path = QPainterPath(QPointF(front, 0))
        path.cubicTo(front, -k, k, -ry, 0, -ry)
        path.cubicTo(-k, -ry, back, -handle, back, 0)
        path.cubicTo(back, handle, -k, ry, 0, ry)
        path.cubicTo(k, ry, front, k, front, 0)
        path.closeSubpath()
        transform = QTransform().rotate(math.degrees(scene.angle))
        path = transform.map(path)
        if theme["edge"]:
            shadow = QTransform().translate(0, 1.0).map(path)
            painter.fillPath(shadow, QColor(43, 68, 82, 24))
        gradient = QLinearGradient(QPointF(-13, -27), QPointF(17, 27))
        for stop, key in ((0.0, "top"), (.46, "middle"), (1.0, "bottom")):
            gradient.setColorAt(stop, QColor(theme[key]))
        painter.fillPath(path, gradient)
        if theme["edge"]:
            painter.setPen(QPen(_color(theme["edge"], .45), .55))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        painter.save()
        painter.setClipPath(path)
        painter.translate(scene.light_x, scene.light_y)
        soft = QRadialGradient(QPointF(-10, -15), 30)
        soft.setColorAt(0, _color(theme["light"], theme["soft"]))
        soft.setColorAt(1, _color(theme["light"], 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(soft)
        painter.drawEllipse(QRectF(-35, -31, 54, 38))
        refract = QRadialGradient(QPointF(17, 17), 24)
        refract.setColorAt(0, _color(theme["refract"], theme["refraction"]))
        refract.setColorAt(1, _color(theme["refract"], 0))
        painter.setBrush(refract)
        painter.drawEllipse(QRectF(-12, -11, 44, 44))
        upper = QPainterPath(QPointF(-22, -4))
        upper.cubicTo(-19, -17, -6, -25, 9, -20)
        lower = QPainterPath(QPointF(1, 23))
        lower.cubicTo(14, 22, 21, 13, 22, 2)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_color(theme["light"], theme["upper"]), .7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(upper)
        painter.setPen(QPen(_color(theme["refract"], theme["lower"]), .85, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(lower)
        painter.restore()
        painter.restore()
        text = str(self._count)
        base = 23 if len(text) == 1 else 19 if len(text) == 2 else 15 if len(text) == 3 else 12
        font = QFont()
        font.setFamilies(["Segoe UI Variable Display", "Segoe UI", "Microsoft YaHei UI"])
        font.setWeight(QFont.Weight.Medium)
        font.setPixelSize(max(11, round(base * scene.scale)))
        painter.setFont(font)
        painter.setPen(QColor(theme["text"]))
        radius = scene.size / 2
        painter.drawText(QRectF(-radius, -radius, scene.size, scene.size), Qt.AlignmentFlag.AlignCenter, text)
        if self._pinned:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_color(theme["refract"], .95))
            painter.drawEllipse(QPointF(0, radius - 4 * scene.scale), 1.6 * scene.scale, 1.6 * scene.scale)

    def _paint_satellites(self, painter, front):
        scene = self.scene
        if not scene.show_ships:
            return
        theme = THEMES[scene.theme]
        # A transparent desktop window cannot infer the wallpaper from the
        # system's light/dark window palette. A bright core and hairline dark
        # rim remain legible on both light and dark desktop backgrounds.
        color = theme["ship_dark"]
        density = _clamp((len(scene.ships) - 12) / 39, 0.0, 1.0)
        point_scale = _clamp(scene.scale ** .28, .88, 1.12)
        radius = (1.13 - density * .43) * point_scale
        tail = 2.1 * (1 - density) * .72 * point_scale
        glow = .28 * 4.1 * (1 - density * .88) * point_scale
        for ship in (*scene.ships.values(), *scene.exiting):
            x, y, depth, opacity = scene.position(ship)
            if (depth >= 0) != front:
                continue
            opacity *= .59 + .36 * (depth + 1) / 2
            r = radius * (.93 + .07 * (depth + 1) / 2)
            if tail > .05 and not scene.reduced_motion:
                px, py, _, _ = scene.position(ship, -tail / ship.a)
                gradient = QLinearGradient(QPointF(px, py), QPointF(x, y))
                gradient.setColorAt(0, _color(color, 0))
                gradient.setColorAt(1, _color(color, opacity))
                painter.setPen(QPen(QBrush(gradient), radius * .85, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawLine(QPointF(px, py), QPointF(x, y))
            painter.setPen(Qt.PenStyle.NoPen)
            if glow > .25:
                halo = QRadialGradient(QPointF(x, y), r + glow)
                halo.setColorAt(0, _color(color, opacity * .2))
                halo.setColorAt(1, _color(color, 0))
                painter.setBrush(halo)
                painter.drawEllipse(QPointF(x, y), r + glow, r + glow)
            painter.setBrush(_color(color, opacity))
            painter.setPen(QPen(_color(theme["bottom"], opacity * .68), .3))
            painter.drawEllipse(QPointF(x, y), r, r)

    def showEvent(self, event):
        super().showEvent(event)
        self._ensure_timer()

    def hideEvent(self, event):
        self.hide_effects()
        super().hideEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.globalPosition().toPoint()
            self._moved = False
            event.accept()

    def mouseMoveEvent(self, event):
        if self._press is not None and event.buttons() & Qt.MouseButton.LeftButton:
            current = event.globalPosition().toPoint()
            if not self._moved and (current - self._press).manhattanLength() > 4:
                self._moved = True
                self.dragStarted.emit()
            if self._moved:
                self.dragMoved.emit(current - self._press)
                self._press = current

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._press is not None:
            moved = self._moved
            self._press = None
            if moved:
                self.dragFinished.emit()
            else:
                self.clicked.emit()

    def contextMenuEvent(self, event):
        self.menuRequested.emit(event.globalPos())

    def closeEvent(self, event):
        self.stop_effects()
        super().closeEvent(event)
