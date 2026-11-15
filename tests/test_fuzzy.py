"""Typo-tolerant search: folding, matching, spelling variants, suggestions and the retry in find_albums (no network)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import helpers  # noqa: F401  (puts the project on sys.path)
from tests.helpers import IsolatedSoundtrackFiles

from distill import fuzzy
from distill import soundtracks as st


class FoldTests(unittest.TestCase):
    def test_accents_case_and_punctuation_go(self):
        self.assertEqual(fuzzy.fold("Pokémon Legends: Z-A"), "pokemon legends z a")
        self.assertEqual(fuzzy.fold("Ratchet & Clank"), "ratchet and clank")

    def test_single_letters_join(self):
        self.assertEqual(fuzzy.merge_letters(["legends", "z", "a"]), ["legends", "za"])
        self.assertEqual(fuzzy.merge_letters(["final", "fantasy", "x"]), ["final", "fantasy", "x"])


class MatchTests(unittest.TestCase):
    def test_punctuation_and_accents_do_not_matter(self):
        for typed in ("pokemon legends za", "Pokemon Legends Z-A", "pokemon legends: z-a", "POKÉMON LEGENDS Z A"):
            self.assertTrue(fuzzy.fuzzy_match(typed, "Pokémon Legends: Z-A"), typed)

    def test_typos_match(self):
        self.assertTrue(fuzzy.fuzzy_match("pokmon legnds", "Pokémon Legends: Z-A"))  # missing letters
        self.assertTrue(fuzzy.fuzzy_match("chorno trigger", "Chrono Trigger"))  # swapped letters
        self.assertTrue(fuzzy.fuzzy_match("persona", "Persona 5"))  # still typing

    def test_other_games_do_not_match(self):
        self.assertFalse(fuzzy.fuzzy_match("persona 4", "Persona 5"))  # numbers never get a typo
        self.assertFalse(fuzzy.fuzzy_match("zelda", "Metroid Prime"))
        self.assertFalse(fuzzy.fuzzy_match("fez", "Fear"))  # short words are exact

    def test_edit_distance(self):
        self.assertEqual(fuzzy.edit_distance("trigger", "trigger", 2), 0)
        self.assertEqual(fuzzy.edit_distance("chorno", "chrono", 2), 1)  # a swap is one edit
        self.assertGreater(fuzzy.edit_distance("abcdef", "uvwxyz", 2), 2)


class VariantTests(unittest.TestCase):
    def test_variants(self):
        v = fuzzy.query_variants("Pokemon Legends: Z-A")
        self.assertIn("pokemon legends z a", v)
        self.assertIn("pokemon legends za", v)
        self.assertIn("Pokemon Legends", v)
        self.assertNotIn("Pokemon Legends: Z-A", v)

    def test_known_title_fixes_a_typo(self):
        self.assertIn("Pokémon Legends: Z-A", fuzzy.query_variants("pokmon legnds za", ["Pokémon Legends: Z-A"]))

    def test_correct_never_changes_a_number(self):
        self.assertEqual(fuzzy.correct("persona 4", ["Persona 5"]), "")


class HistoryTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.path = Path(td.name) / "h.json"
        self.h = fuzzy.History(self.path)
        for t in ("Pokémon Legends: Z-A", "Persona 5", "Chrono Trigger"):
            self.h.add(t, searched=True)

    def test_suggest_prefix_and_typo(self):
        self.assertEqual(self.h.suggest("pok"), ["Pokémon Legends: Z-A"])
        self.assertEqual(self.h.suggest("pokmon legnds"), ["Pokémon Legends: Z-A"])
        self.assertEqual(self.h.suggest("chrno"), ["Chrono Trigger"])

    def test_empty_text_gives_latest_first(self):
        self.assertEqual(self.h.suggest("")[0], "Chrono Trigger")

    def test_persists_and_dedupes(self):
        self.h.add("persona 5", searched=True)
        again = fuzzy.History(self.path)
        self.assertEqual(sorted(again.titles(), key=str.casefold).count("Persona 5") + again.titles().count("persona 5"), 1)

    def test_broken_file_is_ignored(self):
        self.path.write_text("not json", encoding="utf-8")
        self.assertEqual(fuzzy.History(self.path).titles(), [])

    def test_clean_title(self):
        self.assertEqual(fuzzy.clean_title("Pokémon Legends: Z-A (Original Soundtrack)"), "Pokémon Legends: Z-A")
        self.assertEqual(fuzzy.clean_title("Persona 5 Original Soundtrack"), "Persona 5")


class ScoreTests(unittest.TestCase):
    def test_accent_and_letter_forms_match_the_album(self):
        for typed in ("Pokemon Legends Z-A", "pokemon legends za", "Pokemon Legends: Z A"):
            self.assertGreaterEqual(st.match_score(typed, "Pokémon Legends: Z-A Original Soundtrack"), st.MATCH_MIN, typed)

    def test_other_pokemon_game_does_not(self):
        self.assertLess(st.match_score("Pokemon Legends Z-A", "Pokémon Legends: Arceus Original Soundtrack"), st.MATCH_MIN)


class _Stub:
    """A source that only finds the album when asked in the folded spelling."""
    name = "stub"

    def __init__(self):
        self.asked: list[str] = []

    def search(self, game):
        self.asked.append(game)
        if game == "pokemon legends z a":
            return [st.Album(self.name, "x", "Pokémon Legends: Z-A Original Soundtrack", "", st.match_score(game, "Pokémon Legends: Z-A Original Soundtrack"))]
        return []

    def tracks(self, album, prefer="best"):
        return []


class RetryTests(IsolatedSoundtrackFiles):
    def test_retries_other_spellings_when_nothing_found(self):
        stub = _Stub()
        with unittest_mock_patch_rank():
            res = st.find_albums([st.GameRequest("Pokemon Legends: Z-A")], providers=(stub,), pause=0)[0]
        self.assertEqual([a.ident for a in res.albums], ["x"])
        self.assertEqual(stub.asked[0], "Pokemon Legends: Z-A")
        self.assertIn("pokemon legends z a", stub.asked)
        self.assertIn("Pokémon Legends: Z-A", fuzzy.HISTORY.titles())  # a real title, kept for suggestions


def unittest_mock_patch_rank():
    from unittest import mock
    return mock.patch.object(st, "_rank_playable", lambda albums, providers: albums)


if __name__ == "__main__":
    unittest.main()
