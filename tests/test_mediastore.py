from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import helpers  # noqa: F401  (puts the project on sys.path)

from distill import soundtracks as st
from distill.mediastore import MB, MediaStore, split_detail


def album(ident="p5", title="Persona 5", detail="PlayStation 4 \u00b7 Gamerip \u00b7 2016", source="khinsider"):
    return st.Album(source, ident, title, detail, 1.0, "https://x/c.jpg")


def tracks(n=3):
    return [st.Track(f"https://khi/{i}.mp3", ".flac", f"Song {i}", i, 100 * i) for i in range(1, n + 1)]


class MediaStoreTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.store = MediaStore(self.dir / "media.db")
        self.addCleanup(self.store.close)

    def test_detail_is_split_into_platform_and_year(self):
        self.assertEqual(split_detail("PlayStation 4 \u00b7 Gamerip \u00b7 2016"), ("PlayStation 4", 2016))
        self.assertEqual(split_detail(""), ("", 0))

    def test_library_add_list_remove_and_snapshot(self):
        a = album()
        self.assertTrue(self.store.add_to_library(a, tracks()))
        self.assertFalse(self.store.add_to_library(a))  # already there
        (entry,) = self.store.library()
        self.assertEqual((entry.title, entry.platform, entry.year, entry.track_count, entry.has_snapshot),
                         ("Persona 5", "PlayStation 4", 2016, 3, True))
        loaded = self.store.load_snapshot(a)
        self.assertEqual([t.title for t in loaded], ["Song 1", "Song 2", "Song 3"])
        self.assertEqual(loaded[0].size, 100)
        self.store.remove_from_library(a)
        self.assertEqual(self.store.library(), [])
        self.assertIsNone(self.store.load_snapshot(a))

    def test_library_sorts_and_filters(self):
        for ident, title, detail in (("b", "Banjo", "N64 \u00b7 1998"), ("a", "Altered Beast", "Genesis \u00b7 1989"),
                                     ("c", "Celeste", "PC \u00b7 2018")):
            self.store.add_to_library(album(ident, title, detail))
        self.assertEqual([e.title for e in self.store.library("title")], ["Altered Beast", "Banjo", "Celeste"])
        self.assertEqual([e.title for e in self.store.library("year")], ["Altered Beast", "Banjo", "Celeste"])
        self.assertEqual([e.title for e in self.store.library("year", descending=True)], ["Celeste", "Banjo", "Altered Beast"])
        self.assertEqual([e.title for e in self.store.library(text="ban")], ["Banjo"])
        self.assertEqual([e.title for e in self.store.library(platform="pc")], ["Celeste"])
        self.assertEqual(self.store.library_platforms(), ["Genesis", "N64", "PC"])

    def test_snapshot_budget_drops_least_recently_used_first(self):
        big = tracks(200)
        one = len(__import__("json").dumps([__import__("dataclasses").asdict(t) for t in big], separators=(",", ":")))
        self.store.set_snapshot_limit_mb((one * 2.5) / MB)  # room for two
        for ident in ("a", "b"):
            self.store.add_to_library(album(ident, ident.upper()), big)
        self.store.load_snapshot(album("a", "A"))  # a is used more recently than b
        self.store.add_to_library(album("c", "C"), big)
        have = {e.title: e.has_snapshot for e in self.store.library()}
        self.assertEqual(have, {"A": True, "B": False, "C": True})  # b's list went, the album stayed

    def test_a_snapshot_bigger_than_the_whole_budget_is_not_kept_but_the_album_is(self):
        self.store.set_snapshot_limit_mb(0)
        self.store.add_to_library(album(), tracks())
        (entry,) = self.store.library()
        self.assertFalse(entry.has_snapshot)
        self.assertEqual(self.store.snapshot_bytes(), 0)

    def test_lowering_the_budget_trims_at_once(self):
        for i in range(5):
            self.store.add_to_library(album(f"a{i}", f"A{i}"), tracks(50))
        before = self.store.snapshot_bytes()
        dropped = self.store.set_snapshot_limit_mb(before / 2 / MB)
        self.assertGreater(dropped, 0)
        self.assertLessEqual(self.store.snapshot_bytes(), before / 2)

    def test_old_snapshots_can_be_refused(self):
        a = album()
        self.store.add_to_library(a, tracks())
        self.assertIsNotNone(self.store.load_snapshot(a, max_age_days=30))
        self.assertIsNone(self.store.load_snapshot(a, max_age_days=-1))

    def test_favourites(self):
        a = album()
        self.store.set_favourite(a, 2)
        self.assertTrue(self.store.is_favourite(a, 2))
        self.assertFalse(self.store.is_favourite(a, 1))
        self.assertEqual([(x.title, p) for x, p in self.store.favourites()], [("Persona 5", 2)])
        self.store.set_favourite(a, 2, False)
        self.assertEqual(self.store.favourites(), [])
        self.assertIsNone(self.store.album_id("khinsider", "p5"))  # nothing refers to it any more

    def test_playlists_add_reorder_remove_and_delete(self):
        a, b = album(), album("c", "Celeste", "PC \u00b7 2018")
        pid = self.store.create_playlist("Mix")
        self.store.add_to_playlist(pid, a, [1, 2])
        self.store.add_to_playlist(pid, b, [1])
        items = self.store.playlist_items(pid)
        self.assertEqual([(x.title, p) for _i, x, p in items], [("Persona 5", 1), ("Persona 5", 2), ("Celeste", 1)])
        self.store.move_in_playlist(pid, items[2][0], 0)
        self.assertEqual([x.title for _i, x, _p in self.store.playlist_items(pid)], ["Celeste", "Persona 5", "Persona 5"])
        self.store.remove_from_playlist(pid, self.store.playlist_items(pid)[0][0])
        self.assertEqual(len(self.store.playlist_items(pid)), 2)
        self.store.rename_playlist(pid, "Best")
        self.assertEqual(self.store.playlists(), [(pid, "Best", 2)])
        self.store.delete_playlist(pid)
        self.assertEqual(self.store.playlists(), [])
        self.assertIsNone(self.store.album_id("khinsider", "p5"))

    def test_history_counts_plays_and_lists_albums_once(self):
        a, b = album(), album("c", "Celeste", "PC \u00b7 2018")
        self.store.add_to_library(a)
        self.store.record_play(a, 1, when=100.0)
        self.store.record_play(b, 1, when=200.0)
        self.store.record_play(a, 2, when=300.0)
        self.assertEqual([x.title for x in self.store.recent_albums()], ["Persona 5", "Celeste"])
        (entry,) = self.store.library()
        self.assertEqual((entry.play_count, entry.last_played_at), (2, 300.0))
        self.store.clear_history()
        self.assertEqual(self.store.recent_albums(), [])
        self.assertEqual(self.store.library()[0].play_count, 0)

    def test_plays_hearts_and_playlist_entries_do_not_wipe_what_the_library_knows(self):
        full = album()
        self.store.add_to_library(full)
        bare = st.Album("khinsider", "p5", "Persona 5", "", 1.0, "")
        self.store.record_play(bare, 1)
        self.store.set_favourite(bare, 2)
        self.store.add_to_playlist(self.store.create_playlist("x"), bare, [3])
        (entry,) = self.store.library()
        self.assertEqual((entry.platform, entry.year, entry.art), ("PlayStation 4", 2016, "https://x/c.jpg"))
        self.assertEqual(self.store.favourite_positions(full), {2})
        self.assertEqual(self.store.favourite_positions(album("other", "Other")), set())
        self.assertEqual(self.store.playlist_name(1), "x")

    def test_audio_cache_is_off_by_default_and_trims_to_its_budget(self):
        self.assertIsNone(self.store.cache_put("t1", b"x" * 10))  # off
        self.store.set_audio_cache_limit_mb(25 / MB)  # 25 bytes
        p1 = self.store.cache_put("t1", b"a" * 10)
        p2 = self.store.cache_put("t2", b"b" * 10)
        self.assertTrue(p1.is_file() and p2.is_file())
        self.store.cache_path("t1")  # t1 was used last
        p3 = self.store.cache_put("t3", b"c" * 10)
        self.assertIsNone(self.store.cache_path("t2"))  # the least recently used went
        self.assertFalse(p2.exists())
        self.assertTrue(self.store.cache_path("t1") and self.store.cache_path("t3"))
        self.assertLessEqual(self.store.audio_cache_bytes(), 25)
        self.assertIsNone(self.store.cache_put("huge", b"z" * 100))  # bigger than the whole budget

    def test_lowering_the_cache_budget_to_zero_empties_it_and_clearing_keeps_the_budget(self):
        self.store.set_audio_cache_limit_mb(1)
        path = self.store.cache_put("t1", b"a" * 10)
        self.assertEqual(self.store.clear_audio_cache(), 1)
        self.assertFalse(path.exists())
        self.assertEqual(self.store.audio_cache_limit(), MB)
        self.store.cache_put("t2", b"a" * 10)
        self.store.set_audio_cache_limit_mb(0)
        self.assertEqual(self.store.audio_cache_bytes(), 0)

    def test_web_lists_are_kept_until_they_are_too_old(self):
        self.assertIsNone(self.store.web_get("home:top40", 3600))
        self.store.web_put("home:top40", [{"slug": "a", "title": "A"}])
        self.assertEqual(self.store.web_get("home:top40", 3600), [{"slug": "a", "title": "A"}])
        self.assertIsNone(self.store.web_get("home:top40", -1))  # older than allowed
        self.store.web_put("home:top40", [])  # replaced
        self.assertEqual(self.store.web_get("home:top40", 3600), [])
        self.store.web_clear()
        self.assertIsNone(self.store.web_get("home:top40", 3600))

    def test_reopening_keeps_everything(self):
        self.store.add_to_library(album(), tracks())
        self.store.set_snapshot_limit_mb(5)
        self.store.close()
        again = MediaStore(self.dir / "media.db")
        self.addCleanup(again.close)
        self.assertEqual(len(again.library()), 1)
        self.assertEqual(again.snapshot_limit(), 5 * MB)
        self.store = again


if __name__ == "__main__":
    unittest.main()


class GameAndLocalStoreTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = MediaStore(Path(tmp.name) / "m.db")
        self.addCleanup(self.store.close)

    def test_the_album_chosen_for_a_game_is_remembered(self):
        a = album()
        self.assertIsNone(self.store.game_album("g1"))
        self.store.set_game_album("g1", a)
        self.assertEqual(self.store.game_album("g1").title, "Persona 5")
        self.store.set_game_album("g1", album("c", "Celeste"))  # choosing another replaces it
        self.assertEqual(self.store.game_album("g1").title, "Celeste")
        self.store.clear_game_album("g1")
        self.assertIsNone(self.store.game_album("g1"))
        self.assertIsNone(self.store.album_id("khinsider", "p5"))

    def test_disk_albums_sync_into_the_library_and_vanish_with_their_folder(self):
        one = st.Album("local", "/music/Celeste", "Celeste", "", 1.0)
        two = st.Album("local", "/music/Hades", "Hades", "", 1.0)
        self.assertEqual(self.store.sync_local([(one, 12), (two, 20)]), (2, 0))
        self.assertEqual(self.store.sync_local([(one, 12), (two, 20)]), (0, 0))
        self.assertEqual({e.title: e.track_count for e in self.store.library()}, {"Celeste": 12, "Hades": 20})
        self.assertEqual(self.store.sync_local([(one, 12)]), (0, 1))
        self.assertEqual([e.title for e in self.store.library()], ["Celeste"])
        self.store.add_to_library(album())  # a streamed album is not touched by a scan
        self.store.sync_local([])
        self.assertEqual([e.source for e in self.store.library()], ["khinsider"])


class BackupTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.src = MediaStore(self.dir / "a.db")
        self.addCleanup(self.src.close)
        self.dst = MediaStore(self.dir / "b.db")
        self.addCleanup(self.dst.close)

    def fill(self):
        a, b = album(), album("c", "Celeste", "PC \u00b7 2018")
        self.src.add_to_library(a, tracks())
        self.src.set_favourite(b, 1)
        pid = self.src.create_playlist("Mix")
        self.src.add_to_playlist(pid, a, [0, 2])
        self.src.add_to_playlist(pid, b, [1])
        self.src.record_play(a, 1, when=100.0)
        self.src.set_game_album("g1", b)
        self.src.sync_local([(st.Album("local", "/music/Hades", "Hades", "", 1.0), 5)])  # not part of a backup
        self.src.set_snapshot_limit_mb(7)

    def test_a_backup_restores_into_an_empty_library(self):
        self.fill()
        data = self.src.export_data()
        self.assertNotIn("local|/music/Hades", data["albums"])
        import json
        added = self.dst.import_data(json.loads(json.dumps(data)))  # through real JSON, as a file would be
        self.assertEqual(added, {"library": 1, "favourites": 1, "playlists": 1, "playlist tracks": 3, "history": 1, "games": 1})
        self.assertEqual([e.title for e in self.dst.library()], ["Persona 5"])
        self.assertEqual(self.dst.library()[0].platform, "PlayStation 4")
        self.assertEqual([p for _i, _a, p in self.dst.playlist_items(self.dst.playlists()[0][0])], [0, 2, 1])
        self.assertEqual(self.dst.game_album("g1").title, "Celeste")
        self.assertEqual(self.dst.snapshot_limit(), 7 * MB)
        self.assertEqual(self.dst.recent_albums()[0].title, "Persona 5")

    def test_restoring_twice_adds_nothing_and_never_replaces(self):
        self.fill()
        data = self.src.export_data()
        self.dst.import_data(data)
        self.dst.set_snapshot_limit_mb(9)  # the person's own choice is kept
        again = self.dst.import_data(data)
        self.assertEqual(again, {"library": 0, "favourites": 0, "playlists": 0, "playlist tracks": 0, "history": 0, "games": 0})
        self.assertEqual(self.dst.snapshot_limit(), 9 * MB)
        self.assertEqual(len(self.dst.playlists()), 1)

    def test_a_playlist_of_the_same_name_is_added_to_not_duplicated(self):
        self.fill()
        pid = self.dst.create_playlist("mix")
        self.dst.add_to_playlist(pid, album(), [0])  # already has Persona 5 track 0
        self.dst.import_data(self.src.export_data())
        self.assertEqual(len(self.dst.playlists()), 1)
        self.assertEqual(sorted(p for _i, _a, p in self.dst.playlist_items(pid)), [0, 1, 2])

    def test_something_that_is_not_a_backup_is_refused(self):
        for bad in ({}, {"format": "other", "version": 1}, {"format": "distill-media-backup", "version": 99}, [], None):
            with self.assertRaises(ValueError):
                self.dst.import_data(bad)

    def test_the_cover_budget_is_a_setting(self):
        self.assertEqual(self.dst.cover_cache_limit(), 100 * MB)
        self.dst.set_cover_cache_limit_mb(5)
        self.assertEqual(self.dst.cover_cache_limit(), 5 * MB)
        self.assertEqual(self.dst.cover_dir().name, "distill_covers")
