"""Opacity editing remains live while loading preferences stays silent."""

import os
from pathlib import Path
import sys
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from task_ball.appearance import Appearance
from task_ball.appearance_dialog import AppearanceDialog


class OpacityDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dialog = AppearanceDialog(appearance=Appearance(opacity=65))
        self.changed = QSignalSpy(self.dialog.appearanceChanged)

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_loading_opacity_is_silent_and_keeps_settings_opaque(self):
        for opacity in (30, 100, 65):
            with self.subTest(opacity=opacity):
                expected = Appearance("moon", 54, False, opacity)
                self.dialog.set_appearance(expected)
                self.assertEqual(self.dialog.appearance(), expected)
                self.assertEqual(self.dialog.opacity_slider.value(), opacity)
                self.assertEqual(self.dialog.opacity_value.text(), f"{opacity}%")
                self.assertEqual(self.dialog.windowOpacity(), 1.0)
        self.assertEqual(self.changed.count(), 0)

    def test_keyboard_opacity_changes_emit_once_and_respect_limits(self):
        slider = self.dialog.opacity_slider
        QTest.keyClick(slider, Qt.Key.Key_Right)
        self.assertEqual(self.changed.count(), 1)
        self.assertEqual(self.changed.at(0)[0], Appearance(opacity=66))
        self.assertEqual(self.dialog.opacity_value.text(), "66%")
        QTest.keyClick(slider, Qt.Key.Key_Home)
        self.assertEqual(self.changed.count(), 2)
        self.assertEqual(self.dialog.appearance().opacity, 30)
        QTest.keyClick(slider, Qt.Key.Key_Left)
        self.assertEqual(self.changed.count(), 2)
        QTest.keyClick(slider, Qt.Key.Key_End)
        self.assertEqual(self.changed.count(), 3)
        self.assertEqual(self.dialog.appearance().opacity, 100)
        QTest.keyClick(slider, Qt.Key.Key_Right)
        self.assertEqual(self.changed.count(), 3)

    def test_other_controls_preserve_current_opacity(self):
        self.dialog.theme_buttons["moon"].click()
        self.dialog.size_slider.setValue(54)
        self.dialog.ships_checkbox.click()
        self.assertEqual(self.changed.count(), 3)
        self.assertEqual(self.dialog.appearance(), Appearance("moon", 54, False, 65))
        self.assertTrue(all(self.changed.at(index)[0].opacity == 65
                            for index in range(self.changed.count())))
        self.assertEqual(self.dialog.windowOpacity(), 1.0)


if __name__ == "__main__":
    unittest.main()
