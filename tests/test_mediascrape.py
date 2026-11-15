"""Fetching pictures for many games at once (distill/mediascrape.py): who needs what, the fetching, cancelling, and the words at the end."""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from tests import helpers  # noqa: F401
from distill import gamemedia as mm
from distill import mediascrape as ms

PNG = b"\x89PNG\r\n\x1a\n" + bytes(64)
JPG = b"\xff\xd8\xff\xe0" + bytes(64)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.object(mm, "MEDIA_DIR", Path(tmp.name) / "media")
        patch.start()
        self.addCleanup(patch.stop)


class LacksTests(Base):
    def test_a_game_with_nothing_lacks_everything_its_platform_has(self):
        self.assertTrue(ms.lacks("g1", "SNES", "back", False))
        self.assertTrue(ms.lacks("g1", "SNES", "disc", False))  # (its cartridge)
        self.assertTrue(ms.lacks("g1", "SNES", "shots", False))

    def test_a_platform_with_no_disc_or_cartridge_never_lacks_one(self):
        self.assertEqual(mm.media_kind("Arcade"), "")
        self.assertFalse(ms.lacks("g1", "Arcade", "disc", False))
        self.assertTrue(ms.lacks("g1", "Arcade", "back", False))

    def test_what_is_there_is_not_lacking_whoever_chose_it(self):
        (mm._dir() / "back_g1.jpg").write_bytes(JPG)  # found online
        mm.set_art("g1", "cart", PNG)  # chosen by the player
        self.assertFalse(ms.lacks("g1", "SNES", "back", False))
        self.assertFalse(ms.lacks("g1", "SNES", "disc", False))
        self.assertFalse(ms.lacks("g1", "SNES", "back", True))  # (not even when asked to look again)

    def test_what_the_player_turned_off_is_left_alone(self):
        mm.turn_art_off("g1", "back")
        mm.turn_art_off("g1", "cart")
        mm.clear_screenshots("g1", keep_mine=False)
        for kind in ("back", "disc", "shots"):
            self.assertFalse(ms.lacks("g1", "SNES", kind, True), kind)

    def test_screenshots_the_player_added_do_not_count_as_found_ones(self):
        mm.add_screenshot("g1", JPG)
        self.assertTrue(ms.lacks("g1", "SNES", "shots", False))
        (mm._dir() / "shot_g1_00.jpg").write_bytes(JPG)
        self.assertFalse(ms.lacks("g1", "SNES", "shots", False))

    def test_something_looked_for_this_week_in_vain_waits_unless_asked_again(self):
        (mm._dir() / "cart_g1.miss").write_text(mm.MISS_MARK)
        self.assertFalse(ms.lacks("g1", "SNES", "disc", False))
        self.assertTrue(ms.lacks("g1", "SNES", "disc", True))
        self.assertTrue(mm.recently_missed("g1", "cart"))
        self.assertFalse(mm.recently_missed("g1", "back"))

    def test_a_miss_written_by_the_old_launchbox_search_is_not_believed(self):
        (mm._dir() / "cart_g1.miss").write_text("miss")  # (written before the search was fixed)
        self.assertTrue(ms.lacks("g1", "SNES", "disc", False))
        self.assertFalse(mm.recently_missed("g1", "cart"))


class BuildJobsTests(Base):
    ENTRIES = [("a", "Metroid", "SNES"), ("b", "Gran Turismo", "PlayStation"), ("a", "Metroid (again)", "SNES")]

    def test_one_job_for_each_game_with_what_it_lacks(self):
        jobs = ms.build_jobs(self.ENTRIES, ms.KINDS)
        self.assertEqual([j.key for j in jobs], ["a", "b"])  # versions of a game share their pictures: one job
        self.assertEqual(jobs[0].wants, ["back", "disc", "shots"])

    def test_only_the_kinds_asked_for(self):
        jobs = ms.build_jobs(self.ENTRIES, ["disc", "back"])
        self.assertEqual(jobs[0].wants, ["back", "disc"])  # (in the usual order, however they were asked for)

    def test_games_with_everything_asked_for_are_left_out(self):
        (mm._dir() / "back_a.jpg").write_bytes(JPG)
        jobs = ms.build_jobs(self.ENTRIES, ["back"])
        self.assertEqual([j.key for j in jobs], ["b"])

    def test_nothing_asked_for_is_no_jobs(self):
        self.assertEqual(ms.build_jobs(self.ENTRIES, []), [])

    def test_the_launchbox_platform_name_is_looked_up(self):
        job = ms.build_jobs([("a", "Metroid", "SNES")], ["back"])[0]
        self.assertEqual(job.platform, "Super Nintendo Entertainment System")
        odd = ms.build_jobs([("z", "Mystery", "Unknown system")], ["back"])[0]
        self.assertEqual(odd.platform, "")

    def test_the_disc_label_says_which(self):
        self.assertEqual(ms.Job("a", "x", "PlayStation", "Sony Playstation", ["disc"]).label("disc"), "disc")
        self.assertEqual(ms.Job("a", "x", "SNES", "SNES", ["disc"]).label("disc"), "cartridge")
        job = ms.Job("a", "x", "Arcade", "Arcade", ["back"])
        self.assertEqual(job.label("back"), "background")


class ScrapeTests(Base):
    def jobs(self, n=3, wants=("back", "disc")):
        return [ms.Job(f"k{i}", f"Game {i}", "SNES", "SNES", list(wants)) for i in range(n)]

    def run_scrape(self, jobs, outcome, cancelled=lambda: False, workers=1):
        seen: list[ms.Progress] = []
        with mock.patch.object(ms, "fetch_one", side_effect=outcome):
            tally = ms.scrape(jobs, "key", False, seen.append, cancelled, workers=workers, pause=0)
        return tally, seen

    def test_every_picture_is_tried_and_counted(self):
        tally, _seen = self.run_scrape(self.jobs(), lambda job, kind, key, retry: kind == "back")
        self.assertEqual((tally.found["back"], tally.missed["disc"], tally.games, tally.pictures, tally.errors), (3, 3, 3, 6, 0))
        self.assertEqual(tally.total_found(), 3)

    def test_progress_names_the_game_and_the_picture_being_fetched(self):
        _tally, seen = self.run_scrape(self.jobs(1), lambda *a: True)
        fetching = [(p.name, p.label) for p in seen if p.kind]
        self.assertEqual(fetching, [("Game 0", "background"), ("Game 0", "cartridge")])
        self.assertEqual(seen[0].pictures_total, 2)
        self.assertEqual(seen[0].games_total, 1)
        self.assertEqual((seen[-1].games_done, seen[-1].pictures_done, seen[-1].found), (1, 2, 2))

    def test_progress_never_goes_backwards_with_several_workers(self):
        _tally, seen = self.run_scrape(self.jobs(12), lambda *a: True, workers=3)
        for field in ("games_done", "pictures_done", "found"):
            values = [getattr(p, field) for p in seen]
            self.assertEqual(values[-1], max(values), field)
        self.assertEqual(max(p.pictures_done for p in seen), 24)

    def test_a_game_that_fails_does_not_stop_the_others(self):
        def outcome(job, kind, key, retry):
            if job.key == "k1":
                raise OSError("network down")
            return True

        tally, _seen = self.run_scrape(self.jobs(3), outcome)
        self.assertEqual((tally.errors, tally.found["back"], tally.games), (2, 2, 3))

    def test_cancelling_stops_before_the_next_picture(self):
        flag = threading.Event()

        def outcome(job, kind, key, retry):
            flag.set()  # cancelled after the first picture
            return True

        tally, _seen = self.run_scrape(self.jobs(4), outcome, cancelled=flag.is_set)
        self.assertEqual(tally.pictures, 1)

    def test_nothing_to_do_returns_at_once(self):
        tally, seen = self.run_scrape([], lambda *a: True)
        self.assertEqual((tally.games, seen), (0, []))

    def test_the_options_reach_the_fetcher(self):
        job = ms.Job("k", "Metroid", "SNES", "Super Nintendo Entertainment System", ["back", "disc", "shots"])
        with mock.patch.object(mm, "fetch_backdrop", return_value=Path("b")) as back, \
                mock.patch.object(mm, "fetch_media_art", return_value=Path("d")) as disc, mock.patch.object(mm, "fetch_screenshots", return_value=[]) as shots:
            self.assertTrue(ms.fetch_one(job, "back", "KEY", True))
            self.assertTrue(ms.fetch_one(job, "disc", "KEY", False))
            self.assertFalse(ms.fetch_one(job, "shots", "KEY", False))
        back.assert_called_once_with("k", "Metroid", "Super Nintendo Entertainment System", "KEY", retry=True)
        self.assertEqual(disc.call_args.args[:2], ("k", "cart"))
        self.assertFalse(shots.call_args.kwargs["retry"])


class CoverTests(Base):
    """Covers belong to the page, which says which games lack one and fetches it."""

    def hooks(self, missing=("g1", "g3"), found=("g1",)):
        calls = []

        def fetch(gid, retry):
            calls.append((gid, retry))
            return gid in found

        return ms.CoverHooks(lambda gid, retry: gid in missing, fetch), calls

    ENTRIES = [("k1", "Metroid", "SNES", "g1"), ("k2", "Zelda", "SNES", "g2"), ("k3", "Pong", "Arcade", "g3")]

    def test_only_the_games_the_page_says_lack_a_cover_get_the_job(self):
        hooks, _calls = self.hooks()
        jobs = ms.build_jobs(self.ENTRIES, ["cover"], False, hooks)
        self.assertEqual([(j.key, j.gid, j.wants) for j in jobs], [("k1", "g1", ["cover"]), ("k3", "g3", ["cover"])])

    def test_without_the_page_there_are_no_covers_to_fetch(self):
        self.assertEqual(ms.build_jobs(self.ENTRIES, ["cover"], False), [])
        self.assertEqual(ms.build_jobs([("k1", "Metroid", "SNES")], ["cover"], False, self.hooks()[0]), [])  # (no game id: nothing to look under)

    def test_a_cover_comes_first_among_what_a_game_lacks(self):
        hooks, _calls = self.hooks()
        job = ms.build_jobs(self.ENTRIES, ["back", "cover"], False, hooks)[0]
        self.assertEqual(job.wants, ["cover", "back"])

    def test_the_page_fetches_the_covers_and_the_look_again_choice_reaches_it(self):
        hooks, calls = self.hooks()
        jobs = ms.build_jobs(self.ENTRIES, ["cover"], True, hooks)
        with mock.patch.object(ms, "fetch_one", side_effect=AssertionError("a cover is not fetched by the engine")):
            tally = ms.scrape(jobs, "key", True, lambda p: None, lambda: False, workers=1, pause=0, covers=hooks)
        self.assertEqual(sorted(calls), [("g1", True), ("g3", True)])
        self.assertEqual((tally.found["cover"], tally.missed["cover"]), (1, 1))

    def test_the_summary_names_covers(self):
        t = ms.Tally()
        t.found.update({"cover": 4})
        self.assertEqual(ms.summary(t, False), "Done: found 4 cover.")


class SummaryTests(unittest.TestCase):
    def test_what_was_found_is_listed(self):
        t = ms.Tally()
        t.found.update({"back": 12, "shots": 3})
        self.assertEqual(ms.summary(t, False), "Done: found 12 background, 3 screenshots.")

    def test_nothing_new_and_misses_and_errors_are_said(self):
        t = ms.Tally()
        t.missed.update({"disc": 2})
        t.errors = 1
        text = ms.summary(t, False)
        self.assertTrue(text.startswith("Done: found nothing new. Nothing online for 2 pictures"))
        self.assertIn("1 couldn't be fetched", text)

    def test_a_stopped_run_says_so(self):
        t = ms.Tally()
        t.found.update({"disc": 1})
        self.assertEqual(ms.summary(t, True), "Stopped: found 1 disc or cartridge.")


if __name__ == "__main__":
    unittest.main()
