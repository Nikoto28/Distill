"""A game's manual: a PDF the player chose, kept in the media folder (distill/gamemedia.py)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import helpers  # noqa: F401
from distill import gamemedia as mm


class ManualTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        patch = mock.patch.object(mm, "MEDIA_DIR", self.tmp / "media")
        patch.start()
        self.addCleanup(patch.stop)

    def pdf(self, name="manual.pdf", body=b"%PDF-1.4\n%fake\n"):
        p = self.tmp / name
        p.write_bytes(body)
        return p

    def test_a_game_has_no_manual_until_one_is_chosen(self):
        self.assertIsNone(mm.cached_manual("g1"))

    def test_a_chosen_pdf_is_kept_as_a_copy(self):
        src = self.pdf()
        self.assertTrue(mm.set_manual("g1", src))
        src.unlink()  # moving or deleting the original loses nothing
        kept = mm.cached_manual("g1")
        self.assertIsNotNone(kept)
        self.assertTrue(kept.read_bytes().startswith(b"%PDF-"))

    def test_something_that_is_not_a_pdf_is_refused_and_leaves_the_old_manual(self):
        mm.set_manual("g1", self.pdf())
        before = mm.cached_manual("g1").read_bytes()
        self.assertFalse(mm.set_manual("g1", self.pdf("notes.pdf", b"just words")))
        self.assertEqual(mm.cached_manual("g1").read_bytes(), before)
        self.assertFalse(mm.set_manual("g1", self.tmp / "missing.pdf"))

    def test_choosing_again_replaces_it(self):
        mm.set_manual("g1", self.pdf())
        mm.set_manual("g1", self.pdf("two.pdf", b"%PDF-1.7\nsecond"))
        self.assertIn(b"second", mm.cached_manual("g1").read_bytes())

    def test_a_manual_belongs_to_its_own_game(self):
        mm.set_manual("g1", self.pdf())
        self.assertIsNone(mm.cached_manual("g2"))

    def test_removing_it_takes_it_away(self):
        mm.set_manual("g1", self.pdf())
        mm.clear_manual("g1")
        self.assertIsNone(mm.cached_manual("g1"))
        mm.clear_manual("g1")  # (again: nothing to remove is fine)

    def test_editing_a_game_does_not_forget_its_manual(self):
        """clear_media forgets fetched pictures so they are looked for again; the manual is the player's own file."""
        mm.set_manual("g1", self.pdf())
        mm.clear_media("g1")
        self.assertIsNotNone(mm.cached_manual("g1"))


if __name__ == "__main__":
    unittest.main()
