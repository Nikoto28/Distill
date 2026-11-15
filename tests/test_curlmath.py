"""The manual reader's book layout and page-curl geometry (distill/ui/curlmath.py) need no Qt, so these run everywhere."""
from __future__ import annotations

import math
import unittest

from tests import helpers  # noqa: F401  (puts the project on sys.path)
from distill.ui import curlmath as cm

W, H = 400.0, 560.0


class BookLayoutTests(unittest.TestCase):
    def test_the_cover_stands_alone_then_pages_go_in_pairs(self):
        self.assertEqual([cm.spread_pages(s, 5) for s in range(cm.spread_count(5))], [(None, 0), (1, 2), (3, 4)])

    def test_a_last_page_with_no_partner_stands_alone_on_the_left(self):
        self.assertEqual([cm.spread_pages(s, 4) for s in range(cm.spread_count(4))], [(None, 0), (1, 2), (3, None)])

    def test_a_one_page_book_is_just_its_cover(self):
        self.assertEqual(cm.spread_count(1), 1)
        self.assertEqual(cm.spread_pages(0, 1), (None, 0))
        self.assertEqual(cm.spread_count(0), 0)
        self.assertEqual(cm.spread_pages(0, 0), (None, None))

    def test_every_page_is_on_exactly_one_spread(self):
        for pages in range(1, 12):
            seen = [p for s in range(cm.spread_count(pages)) for p in cm.spread_pages(s, pages) if p is not None]
            self.assertEqual(sorted(seen), list(range(pages)), pages)
            for page in range(pages):
                self.assertIn(page, cm.spread_pages(cm.spread_of(page, pages), pages))

    def test_a_closed_book_is_centred_by_sliding_its_spine(self):
        self.assertEqual(cm.book_shift(0, 6), 0.5)
        self.assertEqual(cm.book_shift(1, 6), 0.0)
        self.assertEqual(cm.book_shift(cm.spread_count(6) - 1, 6), -0.5)  # 6 pages: the last spread has the back cover alone

    def test_the_slide_goes_smoothly_from_one_spine_to_the_other(self):
        values = [cm.shift_during_turn(0, 1, 6, i / 10) for i in range(11)]
        self.assertEqual(values[0], 0.5)
        self.assertEqual(values[-1], 0.0)
        self.assertTrue(all(b <= a for a, b in zip(values, values[1:])))

    def test_right_to_left_lifts_the_other_hand_first(self):
        self.assertEqual(cm.reading_order(1, False), 1)
        self.assertEqual(cm.reading_order(-1, False), -1)
        self.assertEqual(cm.reading_order(1, True), -1)
        self.assertEqual(cm.reading_order(-1, True), 1)


class CurlTests(unittest.TestCase):
    def test_an_untouched_page_is_flat(self):
        c = cm.curl((W, H), (W, H), W, H)
        self.assertEqual(c.progress, 0.0)
        self.assertIsNone(c.fold)
        self.assertAlmostEqual(cm.area(c.flat), W * H)
        self.assertEqual(c.lifted, [])

    def test_the_page_keeps_its_area_whatever_the_pull(self):
        for origin, pull in [((W, H), (300, 500)), ((W, H), (0, 400)), ((W, 280), (100, 280)), ((W, 0), (150, 90)), ((W, 200), (-300, 250))]:
            c = cm.curl(origin, pull, W, H)
            self.assertAlmostEqual(cm.area(c.flat) + cm.area(c.lifted), W * H, delta=1e-6 * W * H, msg=str((origin, pull)))
            self.assertAlmostEqual(cm.area(c.landed), cm.area(c.lifted), delta=1e-6 * W * H)

    def test_the_grabbed_corner_lands_where_it_was_dragged(self):
        origin, pull = (W, H), (300.0, 500.0)
        c = cm.curl(origin, pull, W, H, clamp=False)
        m11, m12, m21, m22, dx, dy = c.reflect
        x, y = m11 * origin[0] + m21 * origin[1] + dx, m12 * origin[0] + m22 * origin[1] + dy
        self.assertAlmostEqual(x, pull[0], places=6)
        self.assertAlmostEqual(y, pull[1], places=6)

    def test_the_fold_is_halfway_between_the_grab_and_the_pull(self):
        c = cm.curl((W, H), (200.0, H), W, H)
        (ax, ay), (bx, by) = c.fold
        self.assertAlmostEqual(ax, 300.0)
        self.assertAlmostEqual(bx, 300.0)  # a straight lift: the fold is a vertical line half way across the pulled distance

    def test_what_lies_towards_the_spine_stays_flat(self):
        c = cm.curl((W, 280), (100, 280), W, H)  # grabbed mid-edge, pulled left: the fold is at x = 250
        self.assertTrue(all(x <= 250 + 1e-9 for x, _y in c.flat))
        self.assertTrue(all(x >= 250 - 1e-9 for x, _y in c.lifted))
        self.assertAlmostEqual(c.progress, 0.375)

    def test_a_page_does_not_stretch(self):
        o = (W, 100.0)
        for pull in [(-5000.0, 100.0), (-W * 3, 900.0), (-W, -300.0)]:
            x, y = cm.clamp_pull(o, pull, W, H)
            self.assertLessEqual(math.hypot(x, y), math.hypot(*o) + 1e-6)
            self.assertLessEqual(math.hypot(x, y - H), math.hypot(o[0], o[1] - H) + 1e-6)

    def test_a_pull_within_reach_is_left_alone(self):
        self.assertEqual(cm.clamp_pull((W, H), (250.0, 450.0), W, H), (250.0, 450.0))

    def test_a_fully_turned_page_lies_flat_on_the_other_side(self):
        c = cm.curl((W, H), (-W, H), W, H)
        self.assertAlmostEqual(c.progress, 1.0)
        self.assertAlmostEqual(cm.area(c.flat), 0.0, delta=1e-6)
        xs = [x for x, _y in c.landed]
        self.assertAlmostEqual(min(xs), -W, delta=1e-6)
        self.assertAlmostEqual(max(xs), 0.0, delta=1e-6)

    def test_clipping_a_square_through_its_middle_gives_half(self):
        square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        self.assertAlmostEqual(cm.area(cm.clip_halfplane(square, (5.0, 5.0), (1.0, 0.0), True)), 50.0)
        self.assertEqual(cm.clip_halfplane(square, (50.0, 0.0), (1.0, 0.0), True), [])


class LettingGoTests(unittest.TestCase):
    def test_past_a_third_of_the_way_it_finishes(self):
        self.assertTrue(cm.completes(0.40, 0.0, W))
        self.assertFalse(cm.completes(0.20, 0.0, W))

    def test_a_flick_decides_it_either_way(self):
        self.assertTrue(cm.completes(0.10, -2.5 * W, W))
        self.assertFalse(cm.completes(0.60, 2.5 * W, W))

    def test_a_flick_needs_the_page_to_have_been_lifted_at_all(self):
        self.assertFalse(cm.completes(0.0, -2.5 * W, W))

    def test_it_comes_to_rest_where_the_decision_says(self):
        self.assertEqual(cm.turn_target((W, H), W, False), (W, H))
        self.assertEqual(cm.turn_target((W, H), W, True), (-W, H))

    def test_the_corner_hint_lifts_inwards_from_either_corner(self):
        x, y = cm.hint_pull((W, H), W, H)
        self.assertLess(x, W)
        self.assertLess(y, H)
        x, y = cm.hint_pull((W, 0.0), W, H)
        self.assertLess(x, W)
        self.assertGreater(y, 0.0)
        c = cm.curl((W, H), cm.hint_pull((W, H), W, H), W, H)
        self.assertGreater(c.progress, 0.0)
        self.assertLess(c.progress, 0.06)  # a peek, not a turn


if __name__ == "__main__":
    unittest.main()
