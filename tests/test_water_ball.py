"""Exercise water rendering, task identity, and the transparent overlay in isolation."""

import math
import os
from pathlib import Path
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from task_ball.water_ball import Satellite, WaterBall, WaterScene


class OrbitSceneTests(unittest.TestCase):
    def test_task_ids_keep_their_orbits_when_other_tasks_change(self):
        scene = WaterScene()
        scene.set_tasks(("first", "second"), animate=False)
        scene.clock = 4.2
        first = scene.ships["first"]
        position = scene.position(first)
        scene.set_tasks(("third", "first"))
        self.assertIs(scene.ships["first"], first)
        self.assertEqual(scene.position(first), position)
        self.assertEqual(scene.task_ids, ("third", "first"))
        self.assertEqual([ship.task_id for ship in scene.exiting], ["second"])
        self.assertEqual(first, Satellite.for_task("first"))

    def test_more_than_one_hundred_tasks_remain_individual_satellites(self):
        scene = WaterScene()
        identifiers = [f"task-{index}" for index in range(321)]
        scene.set_tasks(identifiers, animate=False)
        self.assertEqual(scene.task_ids, tuple(identifiers))
        self.assertEqual(len(scene.ships), 321)
        for ship in scene.ships.values():
            self.assertGreaterEqual(ship.a * (1 - ship.e), 34)
            self.assertLess(ship.a * (1 + ship.e), 44)
            self.assertTrue(all(math.isfinite(value) for value in scene.position(ship)))

    def test_elliptical_focus_distances_and_period_are_consistent(self):
        scene = WaterScene()
        for identifier in ("earth", "moon", "stable-id"):
            ship = Satellite.for_task(identifier)
            rate = math.pi / 10 * (37 / ship.a) ** 1.5
            for mean, expected in ((0, ship.a * (1 - ship.e)),
                                   (math.pi, ship.a * (1 + ship.e))):
                scene.clock = (mean - ship.phase) / rate
                x, y, _, _ = scene.position(ship)
                orbital_x = x * math.cos(ship.node) + y * math.sin(ship.node)
                orbital_y = (-x * math.sin(ship.node) + y * math.cos(ship.node)) / math.cos(ship.inclination)
                self.assertAlmostEqual(math.hypot(orbital_x, orbital_y), expected, places=9)
            scene.clock = 0
            start = scene.position(ship)
            scene.clock = math.tau / rate
            end = scene.position(ship)
            for before, after in zip(start, end):
                self.assertAlmostEqual(before, after, places=10)

    def test_size_scales_the_orbit_without_reassigning_task_identity(self):
        scene = WaterScene()
        scene.set_tasks(("one",), animate=False)
        scene.clock = 3.7
        ship = scene.ships["one"]
        reference = scene.position(ship)
        for size in (40, 54, 80):
            scene.size = size
            x, y, depth, alpha = scene.position(ship)
            self.assertAlmostEqual(x / scene.scale, reference[0])
            self.assertAlmostEqual(y / scene.scale, reference[1])
            self.assertEqual((depth, alpha), reference[2:])

    def test_hidden_ships_freeze_phase_and_create_no_transition_history(self):
        scene = WaterScene()
        scene.set_tasks(("one", "two"), animate=False)
        scene.set_tasks(("one", "three"))
        self.assertTrue(scene.exiting)
        scene.show_ships = False
        scene.clear_transitions()
        scene.set_tasks(("one", "new"))
        scene.advance(.016)
        self.assertEqual(scene.clock, 0)
        self.assertFalse(scene.exiting)
        self.assertTrue(all(ship.entering == 0 for ship in scene.ships.values()))
        self.assertFalse(scene.needs_animation())
        scene.show_ships = True
        scene.advance(.016)
        self.assertGreater(scene.clock, 0)
        self.assertEqual(scene.task_ids, ("one", "new"))

    def test_release_returns_to_idle_without_an_endless_timer(self):
        scene = WaterScene()
        scene.show_ships = False
        scene.set_motion(850, -300, True)
        for _ in range(8):
            scene.advance(.016)
        self.assertGreater(scene.strength, .7)
        self.assertLessEqual(math.hypot(scene.fleet_x, scene.fleet_y), 4)
        scene.release_motion()
        self.assertTrue(scene.ripple)
        for _ in range(40):
            scene.advance(.016)
        self.assertFalse(scene.ripple)
        self.assertFalse(scene.needs_animation())

    def test_reduced_motion_keeps_satellites_static(self):
        scene = WaterScene()
        scene.set_tasks(("one",), animate=False)
        scene.reduced_motion = True
        scene.set_motion(1000, 400, True)
        for _ in range(10):
            scene.advance(.016)
        self.assertEqual(scene.clock, 0)
        self.assertEqual(scene.strength, 0)
        self.assertFalse(scene.needs_animation())


class WaterBallWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.ball = WaterBall()
        self.ball.set_reduced_motion(False)

    def tearDown(self):
        self.ball.stop_effects()
        self.ball.close()
        self.ball.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_every_theme_renders_an_opaque_core_at_all_sizes(self):
        images = []
        for theme, size in (("ocean", 40), ("moon", 54), ("amber", 80)):
            self.ball.set_appearance(theme, size, False)
            self.ball.set_state(100, False)
            image = self.ball.grab().toImage()
            self.assertEqual((image.width(), image.height()), (size, size))
            self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
            self.assertGreater(image.pixelColor(size // 2, size // 2).alpha(), 240)
            images.append(image.pixelColor(round(size * .35), round(size * .35)).rgb())
        self.assertEqual(len(set(images)), 3)

    def test_overlay_is_input_transparent_and_input_widget_stays_ball_sized(self):
        self.ball.set_appearance("amber", 40, True)
        effects = self.ball.attach_effects()
        self.assertEqual(self.ball.size().width(), 40)
        self.assertGreater(effects.width(), self.ball.width())
        self.assertTrue(effects.windowFlags() & Qt.WindowType.WindowTransparentForInput)
        self.assertTrue(effects.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
        self.assertTrue(effects.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        self.assertTrue(effects.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating))
        self.ball.show()
        self.ball.show_effects()
        self.app.processEvents()
        center = self.ball.grab().toImage().pixelColor(20, 20)
        # The near-invisible input plane must survive the lowest window opacity.
        self.assertGreaterEqual(int(center.alpha() * .30), 1)
        self.assertLessEqual(center.alpha() / 255, .02)
        image = effects.grab().toImage()
        self.assertGreater(image.pixelColor(image.width() // 2, image.height() // 2).alpha(), 240)

    def test_show_hide_and_ship_visibility_control_the_real_timer(self):
        self.ball.attach_effects()
        self.ball.set_tasks(("one", "two"))
        self.ball.show()
        self.ball.show_effects()
        self.app.processEvents()
        self.assertTrue(self.ball._timer.isActive())
        self.ball.hide_effects()
        self.assertFalse(self.ball._timer.isActive())
        self.ball.show_effects()
        self.assertTrue(self.ball._timer.isActive())
        self.ball.set_appearance("ocean", 54, False)
        self.assertFalse(self.ball._timer.isActive())
        self.assertEqual(self.ball.scene.task_ids, ("one", "two"))
        self.ball.set_appearance("ocean", 54, True)
        self.assertTrue(self.ball._timer.isActive())
        self.ball.stop_effects()
        self.assertFalse(self.ball._timer.isActive())
        self.assertIsNone(self.ball.effects)

    def test_drag_signals_remain_compatible_without_a_main_window(self):
        self.ball.set_appearance("ocean", 54, False)
        self.ball.show()
        self.app.processEvents()
        clicked = QSignalSpy(self.ball.clicked)
        started = QSignalSpy(self.ball.dragStarted)
        moved = QSignalSpy(self.ball.dragMoved)
        finished = QSignalSpy(self.ball.dragFinished)
        center = self.ball.rect().center()
        QTest.mouseClick(self.ball, Qt.MouseButton.LeftButton, pos=center)
        QTest.mousePress(self.ball, Qt.MouseButton.LeftButton, pos=center)
        QTest.mouseMove(self.ball, center + QPoint(12, 7))
        QTest.mouseRelease(self.ball, Qt.MouseButton.LeftButton, pos=center + QPoint(12, 7))
        self.assertEqual(clicked.count(), 1)
        self.assertEqual(started.count(), 1)
        self.assertEqual(moved.at(0), [QPoint(12, 7)])
        self.assertEqual(finished.count(), 1)

    def test_satellite_pixels_remain_distinct_on_light_and_dark_desktops(self):
        effects = self.ball.attach_effects()
        self.ball.set_paused(True)
        identifier = next(f"visible-{i}" for i in range(100)
                          if math.hypot(*self.ball.scene.position(
                              Satellite.for_task(f"visible-{i}"))[:2]) > 35)
        self.ball.set_tasks((identifier,))
        for theme in ("ocean", "moon", "amber"):
            self.ball.set_appearance(theme, 54, True)
            with_ship = effects.grab().toImage()
            self.ball.set_appearance(theme, 54, False)
            without_ship = effects.grab().toImage()
            for background in (QColor(245, 245, 245), QColor(28, 28, 28)):
                def composite(image):
                    result = QImage(image.size(), QImage.Format.Format_RGB32)
                    result.fill(background)
                    painter = QPainter(result)
                    painter.drawImage(0, 0, image)
                    painter.end()
                    return result
                visible = composite(with_ship)
                baseline = composite(without_ship)
                difference = max(
                    abs(visible.pixelColor(x, y).red() - baseline.pixelColor(x, y).red())
                    + abs(visible.pixelColor(x, y).green() - baseline.pixelColor(x, y).green())
                    + abs(visible.pixelColor(x, y).blue() - baseline.pixelColor(x, y).blue())
                    for y in range(visible.height()) for x in range(visible.width()))
                self.assertGreater(difference, 35, (theme, background.name()))


if __name__ == "__main__":
    unittest.main()
