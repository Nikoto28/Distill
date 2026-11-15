"""The library check-up (distill/libraryhealth.py)."""
from __future__ import annotations

import unittest

from tests import helpers  # noqa: F401
from distill import games as gm
from distill import libraryhealth as lh


def game(i, title="Metroid", system="SNES", size=1000, path=None, **kw) -> gm.Game:
    return gm.Game(id=f"g{i}", title=title, system=system, path=path or f"/roms/{i}/{title}.sfc", size=size, **kw)


def keys(issues):
    return [i.key for i in issues]


def check(games, missing=(), covered=True, pictures=0):
    return lh.check(games, set(missing), (lambda g: covered) if isinstance(covered, bool) else covered, pictures)


class CheckTests(unittest.TestCase):
    def healthy(self, i, **kw):
        return game(i, title=f"Game {i}", size=1000 + i, developer="Nintendo", **kw)

    def test_a_healthy_library_has_nothing_to_report(self):
        self.assertEqual(check([self.healthy(1), self.healthy(2)]), [])

    def test_an_empty_library_has_nothing_to_report(self):
        self.assertEqual(check([]), [])

    def test_lost_files_are_listed_with_their_games(self):
        games = [self.healthy(1), self.healthy(2), self.healthy(3)]
        (issue,) = check(games, missing={"g2", "g3"})
        self.assertEqual((issue.key, issue.count, sorted(issue.ids), issue.action), ("missing", 2, ["g2", "g3"], "select"))
        self.assertEqual(issue.title, "2 games have lost their files")

    def test_one_lost_file_is_said_in_the_singular(self):
        (issue,) = check([self.healthy(1)], missing={"g1"})
        self.assertEqual(issue.title, "1 game has lost its file")

    def test_the_same_file_stored_twice_is_found_and_one_copy_is_kept(self):
        a, b = game(1, path="/a/Metroid.sfc"), game(2, path="/b/Metroid.sfc")
        issues = check([a, b], covered=True)
        dup = next(i for i in issues if i.key == "duplicates")
        self.assertEqual((dup.count, dup.ids), (1, ["g2"]))  # the first is kept, the spare is offered
        self.assertIn("1 game seems to be stored twice", dup.title)

    def test_different_sizes_names_or_platforms_are_not_duplicates(self):
        self.assertEqual(lh.duplicate_groups([game(1, path="/a"), game(2, path="/b", size=2000)]), [])
        self.assertEqual(lh.duplicate_groups([game(1, path="/a"), game(2, path="/b", title="Zelda")]), [])
        self.assertEqual(lh.duplicate_groups([game(1, path="/a"), game(2, path="/b", system="NES")]), [])

    def test_the_same_path_twice_is_not_a_duplicate_and_a_game_with_no_size_is_never_one(self):
        self.assertEqual(lh.duplicate_groups([game(1, path="/a"), game(2, path="/a")]), [])
        self.assertEqual(lh.duplicate_groups([game(1, path="/a", size=0), game(2, path="/b", size=0)]), [])

    def test_names_are_compared_without_case_or_punctuation(self):
        a, b = game(1, title="Super Metroid", path="/a"), game(2, title="super  metroid!", path="/b")
        self.assertEqual(len(lh.duplicate_groups([a, b])), 1)

    def test_a_game_the_scan_could_not_place(self):
        (issue,) = [i for i in check([self.healthy(1, ), game(2, system=gm.UNKNOWN, developer="x")]) if i.key == "unplaced"]
        self.assertEqual(issue.ids, ["g2"])

    def test_pictures_lacking_is_an_action_not_a_selection(self):
        (issue,) = check([self.healthy(1)], pictures=7)
        self.assertEqual((issue.key, issue.count, issue.action, issue.ids), ("pictures", 7, "fetch", []))

    def test_covers_and_details_are_reported_when_lacking(self):
        bare = game(1, title="Bare", size=5)
        got = {i.key: i for i in check([bare, self.healthy(2)], covered=lambda g: g.id == "g2")}
        self.assertEqual(got["nocover"].ids, ["g1"])
        self.assertEqual(got["nodetails"].ids, ["g1"])

    def test_the_most_serious_come_first(self):
        games = [game(1, path="/a", system=gm.UNKNOWN), game(2, path="/b", system=gm.UNKNOWN)]
        self.assertEqual(keys(check(games, missing={"g1"}, covered=False, pictures=3)),
                         ["missing", "duplicates", "unplaced", "pictures", "nocover", "nodetails"])

    def test_a_game_from_a_server_is_not_a_duplicate_of_anything(self):
        self.assertEqual(lh.duplicate_groups([game(1, path="/a", source="romm"), game(2, path="/b", source="romm")]), [])


if __name__ == "__main__":
    unittest.main()
