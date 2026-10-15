"""Dock geometry uses real work areas and excludes shared display edges."""

from dataclasses import FrozenInstanceError
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from task_ball.docking import (
    DockPlacement, exposed_placement, find_dock, placement_for, released_position,
)


class DockPlacementTests(unittest.TestCase):
    def test_all_edges_have_expected_anchors_and_handle_rectangles(self):
        bounds = (0, 0, 1920, 1040)
        expected = {
            "left": ((16, 200), (0, 204, 12, 32)),
            "right": ((1864, 200), (1908, 204, 12, 32)),
            "top": ((400, 16), (404, 0, 32, 12)),
            "bottom": ((400, 984), (404, 1028, 32, 12)),
        }
        for side, (anchor, handle) in expected.items():
            with self.subTest(side=side):
                self.assertEqual(placement_for(side, bounds, (400, 200), 40, padding=16),
                                 DockPlacement(side, bounds, anchor, handle))

    def test_placement_is_immutable(self):
        placement = placement_for("left", (0, 0, 800, 600), (16, 200), 40, padding=16)
        with self.assertRaises(FrozenInstanceError):
            placement.side = "right"

    def test_negative_coordinates_preserve_work_area_and_tangent_center(self):
        bounds = (-1280, -200, 1280, 1024)
        placement = placement_for("left", bounds, (-1000, -100), 40, padding=16)
        self.assertEqual(placement.anchor, (-1264, -100))
        self.assertEqual(placement.handle_rect, (-1280, -96, 12, 32))

    def test_sizes_and_corner_positions_keep_ball_and_handle_inside_work_area(self):
        bounds = (-1280, -200, 1280, 1024)
        x, y, width, height = bounds
        for size in (40, 48, 80):
            for side in ("left", "right", "top", "bottom"):
                for position in ((-9999, -9999), (9999, 9999)):
                    with self.subTest(size=size, side=side, position=position):
                        placement = placement_for(side, bounds, position, size, padding=24)
                        bx, by = placement.anchor
                        hx, hy, hw, hh = placement.handle_rect
                        self.assertGreaterEqual(bx, x)
                        self.assertGreaterEqual(by, y)
                        self.assertLessEqual(bx + size, x + width)
                        self.assertLessEqual(by + size, y + height)
                        self.assertGreaterEqual(hx, x)
                        self.assertGreaterEqual(hy, y)
                        self.assertLessEqual(hx + hw, x + width)
                        self.assertLessEqual(hy + hh, y + height)
                        if side in ("left", "right"):
                            self.assertEqual(hy + hh // 2, by + size // 2)
                        else:
                            self.assertEqual(hx + hw // 2, bx + size // 2)

    def test_resizing_recalculates_existing_edge_with_new_padding(self):
        bounds = (0, 0, 800, 600)
        before = placement_for("right", bounds, (744, 200), 40, padding=16)
        after = placement_for(before.side, before.bounds, before.anchor, 80, padding=32)
        self.assertEqual(after.anchor, (688, 200))
        self.assertEqual(after.handle_rect, (788, 224, 12, 32))

    def test_small_work_area_reduces_padding_instead_of_leaving_screen(self):
        placement = placement_for("bottom", (10, 20, 40, 40), (999, 999), 40, padding=32)
        self.assertEqual(placement.anchor, (10, 20))
        self.assertEqual(placement.handle_rect, (14, 48, 32, 12))


class FindDockTests(unittest.TestCase):
    def test_threshold_is_inclusive_and_uses_standard_ball_anchor(self):
        screens = [(0, 0, 800, 600)]
        self.assertEqual(find_dock((40, 200), 40, screens, padding=16).side, "left")
        self.assertIsNone(find_dock((41, 200), 40, screens, padding=16))
        self.assertEqual(find_dock((16, 200), 40, screens, padding=16, threshold=0).side,
                         "left")

    def test_no_snap_in_middle_and_nearest_edge_wins(self):
        screens = [(0, 0, 800, 600)]
        self.assertIsNone(find_dock((300, 200), 40, screens, padding=16))
        self.assertEqual(find_dock((20, 27), 40, screens, padding=16).side, "left")
        self.assertEqual(find_dock((30, 19), 40, screens, padding=16).side, "top")

    def test_horizontal_display_seam_is_never_a_docking_edge(self):
        screens = [(0, 0, 800, 600), (800, 0, 800, 600)]
        self.assertIsNone(find_dock((744, 200), 40, screens, padding=16))
        self.assertIsNone(find_dock((816, 200), 40, screens, padding=16))
        self.assertEqual(find_dock((1544, 200), 40, screens, padding=16).side, "right")

    def test_vertical_display_seam_is_never_a_docking_edge(self):
        screens = [(0, 0, 800, 600), (0, 600, 800, 600)]
        self.assertIsNone(find_dock((200, 544), 40, screens, padding=16))
        self.assertIsNone(find_dock((200, 616), 40, screens, padding=16))
        self.assertEqual(find_dock((200, 1144), 40, screens, padding=16).side, "bottom")

    def test_offset_display_blocks_only_overlapping_edge_segment(self):
        screens = [(0, 0, 800, 600), (800, 200, 800, 600)]
        self.assertEqual(find_dock((744, 50), 40, screens, padding=16).side, "right")
        self.assertIsNone(find_dock((744, 250), 40, screens, padding=16))

    def test_entire_handle_tangent_range_must_be_clear_of_other_screen(self):
        screens = [(0, 0, 800, 600), (800, 200, 800, 600)]
        self.assertIsNone(find_dock((744, 180), 40, screens, padding=16))
        placement = find_dock((744, 164), 40, screens, padding=16)
        self.assertEqual(placement.side, "right")
        self.assertEqual(placement.handle_rect[1] + placement.handle_rect[3], 200)

    def test_negative_offset_monitors_have_exposed_and_shared_segments(self):
        screens = [(-1280, -200, 1280, 1024), (0, 0, 1920, 1040)]
        self.assertEqual(find_dock((-56, -100), 40, screens, padding=16).side, "right")
        self.assertIsNone(find_dock((-56, 100), 40, screens, padding=16))

    def test_taskbar_work_area_boundary_is_respected(self):
        screens = [(0, 40, 1920, 1000)]
        placement = find_dock((200, 56), 40, screens, padding=16)
        self.assertEqual(placement.side, "top")
        self.assertEqual(placement.anchor, (200, 56))
        self.assertEqual(placement.handle_rect, (204, 40, 32, 12))

    def test_gap_uses_nearest_real_screen_rather_than_virtual_bounding_box(self):
        screens = [(0, 0, 800, 600), (1000, 0, 800, 600)]
        self.assertIsNone(find_dock((944, 200), 40, screens, padding=16))
        placement = find_dock((944, 200), 40, screens, padding=16, threshold=100)
        self.assertEqual(placement.bounds, screens[1])
        self.assertEqual(placement.anchor, (1016, 200))

    def test_empty_or_too_small_work_areas_do_not_offer_docking(self):
        self.assertIsNone(find_dock((0, 0), 40, [], padding=16))
        self.assertIsNone(find_dock((0, 0), 40, [(0, 0, 30, 30)], padding=16))


class ReleasedPositionTests(unittest.TestCase):
    def test_l_shaped_display_gap_returns_to_nearest_actual_work_area(self):
        screens = [(0, 0, 1920, 1080), (-1280, 200, 1280, 1024)]
        position = (-500, 80)
        # Dock discovery itself still rejects the original point beyond 24 px.
        self.assertIsNone(find_dock(position, 40, screens, padding=26))
        self.assertEqual(released_position(position, 40, screens, padding=26),
                         (-500, 226))

    def test_negative_display_coordinates_are_clamped_without_primary_screen_bias(self):
        screens = [(-1920, -1080, 1920, 1040), (0, 0, 1920, 1040)]
        self.assertEqual(released_position((-2500, -1500), 80, screens, padding=32),
                         (-1888, -1048))
        self.assertEqual(released_position((-600, -400), 80, screens, padding=32),
                         (-600, -400))

    def test_diagonal_display_gap_chooses_nearest_screen_by_ball_center(self):
        screens = [(-1920, -1080, 1920, 1080), (0, 0, 1920, 1080)]
        self.assertEqual(released_position((-100, 100), 40, screens, padding=16),
                         (16, 100))

    def test_taskbar_available_geometry_is_used_for_both_top_and_bottom(self):
        screens = [(0, 40, 1920, 1000)]
        self.assertEqual(released_position((100, -30), 40, screens, padding=26),
                         (100, 66))
        self.assertEqual(released_position((100, 1030), 40, screens, padding=26),
                         (100, 974))

    def test_ball_center_inside_screen_keeps_that_screen(self):
        screens = [(-800, 0, 800, 600), (0, 0, 800, 600)]
        self.assertEqual(released_position((-30, 200), 40, screens, padding=16),
                         (-56, 200))
        self.assertEqual(released_position((-10, 200), 40, screens, padding=16),
                         (16, 200))

    def test_no_usable_screen_preserves_existing_position(self):
        self.assertEqual(released_position((-100, 200), 40, [], padding=16), (-100, 200))
        self.assertEqual(released_position((-100, 200), 40, [(0, 0, 20, 20)], padding=16),
                         (-100, 200))


class ExposedPlacementTests(unittest.TestCase):
    def test_resizing_can_move_an_exposed_handle_into_a_shared_edge(self):
        screens = [(0, 0, 800, 600), (800, 70, 800, 600)]
        original = placement_for("right", screens[0], (734, 26), 40, padding=26)
        self.assertEqual(original.handle_rect, (788, 30, 12, 32))
        self.assertTrue(exposed_placement(original, screens))
        resized = placement_for("right", original.bounds, original.anchor, 80, padding=42)
        self.assertEqual(resized.handle_rect, (788, 66, 12, 32))
        self.assertFalse(exposed_placement(resized, screens))

    def test_removed_screen_does_not_leave_an_exposed_stale_placement(self):
        screens = [(-1280, 0, 1280, 1024), (0, 0, 1920, 1040)]
        placement = placement_for("left", screens[0], (-1254, 200), 40, padding=26)
        self.assertTrue(exposed_placement(placement, screens))
        self.assertFalse(exposed_placement(placement, [screens[1]]))
        self.assertFalse(exposed_placement(placement, []))


if __name__ == "__main__":
    unittest.main()
