"""The arithmetic behind the frame-by-frame animations: they must move at the same pace at 30, 60 or 144 frames a second."""
from __future__ import annotations

import math
import unittest

from distill.ui import framemath as fm


class RefreshIntervalTests(unittest.TestCase):
    def test_common_screens(self):
        self.assertEqual(fm.refresh_interval_ms(60), 16)
        self.assertEqual(fm.refresh_interval_ms(59.94), 16)
        self.assertEqual(fm.refresh_interval_ms(75), 13)
        self.assertEqual(fm.refresh_interval_ms(120), 8)

    def test_fast_screens_are_capped(self):
        self.assertEqual(fm.refresh_interval_ms(144), 8)  # no faster than 120 frames a second
        self.assertEqual(fm.refresh_interval_ms(360), 8)

    def test_a_screen_that_will_not_say_gets_sixty(self):
        for bad in (0, -1, 5, 5000, float("nan"), float("inf"), None, "fast"):
            self.assertEqual(fm.refresh_interval_ms(bad), 16, bad)


class StepTests(unittest.TestCase):
    def test_first_frame_counts_as_one_ordinary_frame(self):
        self.assertAlmostEqual(fm.step_seconds(100.0, None), 1 / 60)

    def test_steps_are_the_time_between_frames(self):
        self.assertAlmostEqual(fm.step_seconds(10.016, 10.0), 0.016)

    def test_a_stall_does_not_make_it_lurch(self):
        self.assertEqual(fm.step_seconds(50.0, 10.0), fm.MAX_STEP)

    def test_a_clock_that_went_backwards_is_a_zero_step(self):
        self.assertEqual(fm.step_seconds(9.0, 10.0), 0.0)


class FollowTests(unittest.TestCase):
    def test_lands_the_same_wherever_the_time_is_cut(self):
        for frames in (1, 2, 10, 30, 60, 144):
            value = 0.0
            for _ in range(frames):
                value = fm.follow(value, 1.0, 4.0, 1.0 / frames)
            self.assertAlmostEqual(value, 1 - math.exp(-4.0), places=9, msg=frames)

    def test_keeps_the_pace_of_the_old_per_frame_versions(self):
        for share in (0.12, 0.14):  # the seek-bar wave and the Start button's glow used these at 30 frames a second
            old = 0.0
            for _ in range(30):
                old += (1.0 - old) * share
            rate = fm.rate_per_frame(share, 30)
            self.assertAlmostEqual(fm.follow(0.0, 1.0, rate, 1.0), old, places=9)

    def test_stays_put_at_its_goal_and_never_overshoots(self):
        self.assertEqual(fm.follow(0.7, 0.7, 5.0, 0.5), 0.7)
        self.assertLessEqual(fm.follow(0.0, 1.0, 50.0, 1.0), 1.0)
        self.assertGreaterEqual(fm.follow(1.0, 0.0, 50.0, 1.0), 0.0)


class SteadyPaceTests(unittest.TestCase):
    """A ripple that turns by RATE * dt covers the same distance in a second at any frame rate (it used to turn by a fixed step a frame)."""

    def test_same_distance_a_second_at_any_frame_rate(self):
        for rate, was_per_frame, fps in ((2.4, 0.08, 30), (3.6, 0.12, 30), (3.9, 0.13, 30), (8.75, 0.35, 25), (0.105, 0.0035, 30)):
            self.assertAlmostEqual(rate, was_per_frame * fps)
            for shown_fps in (30, 60, 120, 144):
                total = sum(rate * (1.0 / shown_fps) for _ in range(shown_fps))
                self.assertAlmostEqual(total, rate, places=9, msg=(rate, shown_fps))


if __name__ == "__main__":
    unittest.main()
