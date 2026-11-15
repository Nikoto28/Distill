"""Backing up and restoring a game's saves (distill/savebackup.py)."""
from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from tests import helpers  # noqa: F401
from distill import games as gm
from distill import savebackup as sb


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for name in ("roms", "states", "saves"):
            (self.root / name).mkdir()
        patch = mock.patch.object(sb, "BACKUP_DIR", self.root / "backups")
        patch.start()
        self.addCleanup(patch.stop)
        self.setup = gm.RetroSetup(self.root / "retroarch.exe", {"snes9x": self.root / "snes9x_libretro.dll"}, {"snes9x": {"corename": "Snes9x"}},
                                   None, state_dir=self.root / "states", save_dir=self.root / "saves")
        self.rom = self.root / "roms" / "Metroid.sfc"
        self.rom.write_bytes(b"rom")
        self.game = gm.Game(id="g1", title="Metroid", system="SNES", path=str(self.rom))

    def write(self, folder: str, name: str, data: bytes = b"data") -> Path:
        p = self.root / folder / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p


class FindTests(Base):
    def test_states_and_battery_saves_are_found_in_their_own_folders(self):
        self.write("states", "Metroid.state")
        self.write("states", "Metroid.state1")
        self.write("states", "Metroid.state.auto")
        self.write("saves", "Metroid.srm")
        got = {(s.kind, s.path.name) for s in sb.find_saves(self.setup, self.game)}
        self.assertEqual(got, {("state", "Metroid.state"), ("state", "Metroid.state1"), ("state", "Metroid.state.auto"), ("save", "Metroid.srm")})

    def test_other_games_files_are_left_out(self):
        self.write("states", "Zelda.state")
        self.write("saves", "Metroid 2.srm")
        self.write("saves", "Metroid.srm.bak")
        self.assertEqual(sb.find_saves(self.setup, self.game), [])

    def test_saves_sorted_into_a_folder_by_core_are_found(self):
        self.write("states/Snes9x", "Metroid.state")
        self.write("saves/Snes9x", "Metroid.srm")
        self.assertEqual({s.path.name for s in sb.find_saves(self.setup, self.game)}, {"Metroid.state", "Metroid.srm"})

    def test_saves_beside_the_game_are_found_when_no_folder_is_set(self):
        bare = gm.RetroSetup(self.root / "retroarch.exe", {"snes9x": self.root / "x.dll"}, {"snes9x": {"corename": "Snes9x"}})
        self.write("roms", "Metroid.state2")
        self.write("roms", "Metroid.srm")
        self.assertEqual({s.path.name for s in sb.find_saves(bare, self.game)}, {"Metroid.state2", "Metroid.srm"})

    def test_a_game_with_no_saves_has_none(self):
        self.assertEqual(sb.find_saves(self.setup, self.game), [])


class BackupTests(Base):
    def files(self):
        return sb.find_saves(self.setup, self.game)

    def test_nothing_to_back_up_makes_no_backup(self):
        self.assertIsNone(sb.create_backup("g1", "Metroid", "SNES", []))
        self.assertIsNone(sb.create_backup("g1", "Metroid", "SNES", [sb.SaveFile(self.root / "missing.srm", "save")]))
        self.assertEqual(sb.list_backups("g1"), [])

    def test_a_backup_is_listed_with_what_is_in_it(self):
        self.write("states", "Metroid.state", b"state-bytes")
        self.write("saves", "Metroid.srm", b"save-bytes")
        path = sb.create_backup("g1", "Metroid", "SNES", self.files(), "before update", now=1_700_000_000)
        (info,) = sb.list_backups("g1")
        self.assertEqual((info.path, info.reason, info.files, info.created), (path, "before update", 2, 1_700_000_000))
        self.assertEqual(sorted(info.names), ["Metroid.srm", "Metroid.state"])
        self.assertGreater(info.size, 0)

    def test_backups_are_newest_first_and_never_overwrite_each_other(self):
        self.write("saves", "Metroid.srm")
        a = sb.create_backup("g1", "Metroid", "SNES", self.files(), now=1_700_000_000)
        b = sb.create_backup("g1", "Metroid", "SNES", self.files(), now=1_700_000_000)  # the same second
        c = sb.create_backup("g1", "Metroid", "SNES", self.files(), now=1_700_000_500)
        self.assertEqual(len({a, b, c}), 3)
        self.assertEqual(sb.list_backups("g1")[0].path, c)

    def test_each_game_has_its_own_backups(self):
        self.write("saves", "Metroid.srm")
        sb.create_backup("g1", "Metroid", "SNES", self.files())
        self.assertEqual(sb.list_backups("g2"), [])

    def test_only_the_newest_are_kept(self):
        self.write("saves", "Metroid.srm")
        for i in range(sb.MAX_BACKUPS + 3):
            sb.create_backup("g1", "Metroid", "SNES", self.files(), now=1_700_000_000 + i * 60)
        backups = sb.list_backups("g1")
        self.assertEqual(len(backups), sb.MAX_BACKUPS)
        self.assertEqual(backups[0].created, 1_700_000_000 + (sb.MAX_BACKUPS + 2) * 60)

    def test_a_file_that_is_not_a_backup_is_ignored(self):
        folder = sb._folder("g1")
        folder.mkdir(parents=True)
        (folder / "junk.zip").write_bytes(b"not a zip")
        self.assertEqual(sb.list_backups("g1"), [])

    def test_a_backup_can_be_deleted(self):
        self.write("saves", "Metroid.srm")
        path = sb.create_backup("g1", "Metroid", "SNES", self.files())
        sb.delete_backup(path)
        self.assertEqual(sb.list_backups("g1"), [])


class RestoreTests(Base):
    def test_files_go_back_where_they_came_from(self):
        state = self.write("states", "Metroid.state", b"original-state")
        srm = self.write("saves", "Metroid.srm", b"original-save")
        path = sb.create_backup("g1", "Metroid", "SNES", sb.find_saves(self.setup, self.game))
        state.write_bytes(b"ruined")
        srm.unlink()
        result = sb.restore(path, "g1", "Metroid", "SNES")
        self.assertEqual((result.restored, result.skipped), (2, []))
        self.assertEqual((state.read_bytes(), srm.read_bytes()), (b"original-state", b"original-save"))

    def test_what_a_restore_overwrites_is_backed_up_first(self):
        state = self.write("states", "Metroid.state", b"good")
        path = sb.create_backup("g1", "Metroid", "SNES", sb.find_saves(self.setup, self.game), now=1_700_000_000)
        state.write_bytes(b"newer progress")
        result = sb.restore(path, "g1", "Metroid", "SNES")
        self.assertIsNotNone(result.safety)
        newest = sb.list_backups("g1")[0]
        self.assertEqual(newest.reason, "before restore")
        with zipfile.ZipFile(newest.path) as z:
            self.assertIn(b"newer progress", [z.read(n) for n in z.namelist() if n.endswith(".state")])
        self.assertEqual(state.read_bytes(), b"good")

    def test_a_restore_that_overwrites_nothing_makes_no_safety_backup(self):
        state = self.write("states", "Metroid.state", b"good")
        path = sb.create_backup("g1", "Metroid", "SNES", sb.find_saves(self.setup, self.game))
        state.unlink()
        self.assertIsNone(sb.restore(path, "g1").safety)
        self.assertEqual(len(sb.list_backups("g1")), 1)

    def test_a_missing_folder_is_made_again(self):
        self.write("saves/Snes9x", "Metroid.srm", b"x")
        path = sb.create_backup("g1", "Metroid", "SNES", sb.find_saves(self.setup, self.game))
        (self.root / "saves" / "Snes9x" / "Metroid.srm").unlink()
        (self.root / "saves" / "Snes9x").rmdir()
        self.assertEqual(sb.restore(path, "g1").restored, 1)
        self.assertTrue((self.root / "saves" / "Snes9x" / "Metroid.srm").is_file())

    def test_a_backup_that_names_something_that_is_not_a_save_is_not_obeyed(self):
        evil = self.root / "evil.txt"
        path = self.root / "tampered.zip"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("00_evil.txt", "pwned")
            z.writestr("manifest.json", json.dumps({"files": [{"arc": "00_evil.txt", "origin": str(evil), "kind": "save"}], "created": 1}))
        result = sb.restore(path, "g1")
        self.assertEqual(result.restored, 0)
        self.assertFalse(evil.exists())
        self.assertTrue(any("not a save file" in s for s in result.skipped))

    def test_an_unreadable_backup_says_so(self):
        bad = self.root / "bad.zip"
        bad.write_bytes(b"nope")
        result = sb.restore(bad, "g1")
        self.assertEqual(result.restored, 0)
        self.assertEqual(result.skipped, ["That backup can't be read."])


class BackupAllTests(Base):
    def games(self):
        out = []
        for i, name in enumerate(("Metroid", "Zelda", "Kirby")):
            rom = self.root / "roms" / f"{name}.sfc"
            rom.write_bytes(b"rom")
            out.append(gm.Game(id=f"g{i}", title=name, system="SNES", path=str(rom)))
        return out

    def test_only_games_with_saves_are_backed_up(self):
        games = self.games()
        self.write("saves", "Metroid.srm")
        self.write("states", "Kirby.state")
        self.write("states", "Kirby.state1")
        self.assertEqual(sb.backup_all(self.setup, games, "before update"), (2, 3))
        self.assertEqual(len(sb.list_backups("g0")), 1)
        self.assertEqual(sb.list_backups("g1"), [])
        self.assertEqual(sb.list_backups("g2")[0].reason, "before update")

    def test_progress_is_reported_and_cancelling_stops(self):
        games = self.games()
        for name in ("Metroid", "Zelda", "Kirby"):
            self.write("saves", f"{name}.srm")
        seen = []
        stop = [False]

        def progress(done, total, name):
            seen.append((done, total, name))
            if done == 1:
                stop[0] = True

        done, _files = sb.backup_all(self.setup, games, "x", progress, lambda: stop[0])
        self.assertEqual(done, 1)
        self.assertEqual(seen[0], (0, 3, "Metroid"))

    def test_nothing_to_back_up(self):
        self.assertEqual(sb.backup_all(self.setup, self.games(), "x"), (0, 0))


if __name__ == "__main__":
    unittest.main()
