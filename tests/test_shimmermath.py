"""The timing of the shimmer shown where a picture is on its way (distill/ui/shimmermath.py); no Qt needed."""
from __future__ import annotations

import unittest

from tests import helpers  # noqa: F401
from distill.ui import shimmermath as sm


class PhaseTests(unittest.TestCase):
    def test_a_sweep_runs_from_nothing_to_all(self):
        self.assertEqual(sm.phase(0.0), 0.0)
        self.assertAlmostEqual(sm.phase(sm.PERIOD / 2), 0.5)
        self.assertLess(sm.phase(sm.PERIOD - 1e-6), 1.0 + 1e-9)
        self.assertGreater(sm.phase(sm.PERIOD - 1e-6), 0.999)

    def test_it_only_ever_moves_forward_within_a_sweep(self):
        values = [sm.phase(i * sm.PERIOD / 40) for i in range(40)]
        self.assertTrue(all(b >= a for a, b in zip(values, values[1:])))

    def test_it_rests_between_sweeps_and_then_goes_again(self):
        self.assertIsNone(sm.phase(sm.PERIOD + sm.REST / 2))
        self.assertEqual(sm.phase(sm.PERIOD + sm.REST), 0.0)
        self.assertAlmostEqual(sm.phase(3 * (sm.PERIOD + sm.REST) + sm.PERIOD / 2), 0.5)

    def test_a_delayed_panel_starts_later(self):
        self.assertEqual(sm.phase(sm.stagger(2), sm.stagger(2)), 0.0)
        self.assertGreater(sm.phase(0.5, 0.0), sm.phase(0.5, sm.stagger(2)))

    def test_neighbours_are_staggered_in_order(self):
        self.assertEqual([sm.stagger(i) for i in range(3)], [0.0, sm.STEP, 2 * sm.STEP])
        self.assertEqual(sm.stagger(-1), 0.0)


class BandTests(unittest.TestCase):
    def test_the_band_enters_beyond_the_left_edge_and_leaves_beyond_the_right(self):
        left, right = sm.band_span(0.0, 200.0)
        self.assertLessEqual(right, 0.0)
        left, right = sm.band_span(1.0, 200.0)
        self.assertGreaterEqual(left, 200.0)

    def test_the_band_keeps_its_width(self):
        for p in (0.0, 0.3, 0.7, 1.0):
            left, right = sm.band_span(p, 160.0)
            self.assertAlmostEqual(right - left, sm.BAND * 160.0)

    def test_halfway_the_band_is_centred_over_the_middle_of_the_panel(self):
        left, right = sm.band_span(0.5, 200.0)
        self.assertAlmostEqual((left + right) / 2, 100.0 + 0.0 * 200, delta=0.5 * sm.BAND * 200)
        self.assertLess(left, 100.0)
        self.assertGreater(right, 100.0)


if __name__ == "__main__":
    unittest.main()
