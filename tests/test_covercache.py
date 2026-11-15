from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from tests import helpers  # noqa: F401

from distill.covercache import CoverCache


class CoverCacheTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "covers"
        self.limit = 100
        self.cache = CoverCache(self.dir, lambda: self.limit)

    def test_a_cover_is_kept_and_found_again(self):
        self.assertIsNone(self.cache.get("https://x/a.jpg"))
        self.assertTrue(self.cache.put("https://x/a.jpg", b"A" * 10))
        self.assertEqual(self.cache.get("https://x/a.jpg"), b"A" * 10)
        self.assertIsNone(self.cache.get("https://x/b.jpg"))

    def test_off_and_too_big_keep_nothing(self):
        self.limit = 0
        self.assertFalse(self.cache.put("u", b"x"))
        self.limit = 10
        self.assertFalse(self.cache.put("u", b"x" * 11))
        self.assertFalse(self.cache.put("u", b""))
        self.assertEqual(self.cache.size(), 0)

    def test_the_least_recently_used_go_first_when_over_budget(self):
        self.limit = 200  # room for all three while they are put in
        for i, name in enumerate("abc"):
            self.cache.put(name, b"x" * 40)
            old = time.time() - 100 + i  # a oldest, c newest
            os.utime(self.cache._path(name), (old, old))
        self.cache.get("a")  # a is used again: now b is the oldest
        self.limit = 100
        self.cache.put("d", b"x" * 40)  # 160 > 100: two must go
        self.assertIsNone(self.cache.get("b"))
        self.assertIsNone(self.cache.get("c"))
        self.assertIsNotNone(self.cache.get("a"))
        self.assertIsNotNone(self.cache.get("d"))
        self.assertLessEqual(self.cache.size(), 100)

    def test_lowering_the_budget_and_clearing(self):
        for name in "abc":
            self.cache.put(name, b"x" * 30)
        self.limit = 40
        self.assertEqual(self.cache.trim(), 2)
        self.assertLessEqual(self.cache.size(), 40)
        self.assertEqual(self.cache.clear(), 1)
        self.assertEqual(self.cache.size(), 0)


if __name__ == "__main__":
    unittest.main()
