"""Sunshine / Moonlight: the apps.json export (streaming.py) and the windowless `--launch` command it points at (launcher.py)."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from distill import games as gm
from distill import launcher
from distill import recomps as rc
from distill import streaming as st

BASE = ["C:\\Distill\\Distill.exe"]


def entry(path, system="SNES"):
    return SimpleNamespace(name=Path(path).name, system=system, kind="SFC", region="USA", size=1, modified=1.0, folder="", path=str(path))


class Fixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        patcher = mock.patch.object(rc, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.store = gm.GameStore(self.root / "games.db")
        self.paths = {n: self.root / n for n in ("Zelda (USA).sfc", "Sonic (USA).md", "Mario (USA).sfc")}
        for p in self.paths.values():
            p.write_bytes(b"x")
        self.store.sync([entry(self.paths["Zelda (USA).sfc"]), entry(self.paths["Sonic (USA).md"], "Mega Drive"),
                         entry(self.paths["Mario (USA).sfc"])], str(self.root))
        self.games = {g.title: g for g in self.store.games()}
        self.rc_store = rc.Store(self.root / "state.json")
        self.apps = self.root / "sunshine" / "apps.json"

    def export(self, **kw):
        kw.setdefault("base", BASE)
        kw.setdefault("plat", "win32")
        return st.export_sunshine(self.store, self.apps, self.rc_store, **kw)

    def read(self):
        return json.loads(self.apps.read_text(encoding="utf-8"))


class CommandTests(unittest.TestCase):
    def test_a_packaged_build_is_started_by_its_exe(self):
        self.assertEqual(st.distill_argv(frozen=True, executable="C:\\D\\Distill.exe"), ["C:\\D\\Distill.exe"])

    def test_a_source_checkout_uses_pythonw_and_the_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            app.mkdir()
            (app / "Distill.pyw").write_text("", encoding="utf-8")
            (Path(tmp) / "python.exe").write_text("", encoding="utf-8")
            (Path(tmp) / "pythonw.exe").write_text("", encoding="utf-8")
            argv = st.distill_argv(frozen=False, executable=str(Path(tmp) / "python.exe"), app_dir=app, plat="win32")
        self.assertEqual([Path(a).name for a in argv], ["pythonw.exe", "Distill.pyw"])

    def test_without_the_script_it_runs_the_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(st.distill_argv(frozen=False, executable="/usr/bin/python3", app_dir=Path(tmp), plat="linux"), ["/usr/bin/python3", "-m", "distill"])

    def test_quoting_follows_the_system(self):
        win = st.entry_command("game", "g1", ["C:\\Program Files\\Distill\\Distill.exe"], "win32")
        self.assertEqual(win, '"C:\\Program Files\\Distill\\Distill.exe" --launch game:g1')
        nix = st.entry_command("recomp", "soh", ["/opt/my apps/distill"], "linux")
        self.assertEqual(nix, "'/opt/my apps/distill' --launch recomp:soh")

    def test_what_is_written_is_what_the_launcher_reads_back(self):
        for plat, base in (("win32", ["C:\\Program Files\\Distill\\Distill.exe"]), ("linux", ["/opt/my apps/distill"])):
            cmd = st.entry_command("game", "g1a2b3c4d5e6f", base, plat)
            self.assertEqual(st.target_of({"cmd": cmd}), "game:g1a2b3c4d5e6f")
        self.assertEqual(st.target_of({"cmd": "steam"}), "")
        self.assertEqual(st.target_of("nonsense"), "")

    def test_apps_file_places(self):
        win = st.apps_file_candidates({"ProgramFiles": "C:\\Program Files"}, "win32")
        self.assertEqual(win[0], Path("C:\\Program Files") / "Sunshine" / "config" / "apps.json")
        nix = st.apps_file_candidates({}, "linux", Path("/home/me"))
        self.assertEqual(nix[0], Path("/home/me/.config/sunshine/apps.json"))


class ExportTests(Fixture):
    def test_favourites_only_by_default_and_the_command_points_at_distill(self):
        self.store.set_favorite(self.games["Zelda"].id, True)
        report = self.export()
        apps = self.read()["apps"]
        self.assertEqual((report.added, [a["name"] for a in apps]), (1, ["Zelda"]))
        self.assertEqual(apps[0]["cmd"], f"{BASE[0]} --launch game:{self.games['Zelda'].id}")
        self.assertEqual(apps[0]["working-dir"], str(st.APP_DIR))

    def test_the_whole_library_when_asked(self):
        self.assertEqual(self.export(favourites_only=False).added, 3)

    def test_a_second_export_adds_nothing_and_leaves_edits_alone(self):
        self.store.set_favorite(self.games["Zelda"].id, True)
        self.export()
        data = self.read()
        data["apps"][0]["name"] = "My Zelda"  # renamed in Sunshine's own page
        data["apps"].append({"name": "Desktop", "image-path": "desktop.png"})
        self.apps.write_text(json.dumps(data), encoding="utf-8")
        again = self.export()
        self.assertEqual((again.added, again.kept), (0, 1))
        self.assertEqual([a["name"] for a in self.read()["apps"]], ["My Zelda", "Desktop"])

    def test_other_entries_and_settings_are_kept_and_the_file_is_backed_up_once(self):
        self.apps.parent.mkdir(parents=True)
        original = {"env": {"PATH": "$(PATH)"}, "apps": [{"name": "Desktop", "image-path": "desktop.png"}]}
        self.apps.write_text(json.dumps(original), encoding="utf-8")
        self.store.set_favorite(self.games["Zelda"].id, True)
        self.export()
        data = self.read()
        self.assertEqual(data["env"], original["env"])
        self.assertEqual(data["apps"][0], original["apps"][0])
        backup = self.apps.with_name("apps.json" + st.BACKUP_SUFFIX)
        self.assertEqual(json.loads(backup.read_text(encoding="utf-8")), original)
        self.store.set_favorite(self.games["Sonic"].id, True)
        self.export()
        self.assertEqual(json.loads(backup.read_text(encoding="utf-8")), original)  # the first backup is the one that stays

    def test_a_file_that_is_not_sunshines_is_not_overwritten(self):
        self.apps.parent.mkdir(parents=True)
        self.apps.write_text("this is not json", encoding="utf-8")
        report = self.export(favourites_only=False)
        self.assertTrue(report.skipped)
        self.assertEqual(self.apps.read_text(encoding="utf-8"), "this is not json")

    def test_a_byte_order_mark_is_fine(self):
        self.apps.parent.mkdir(parents=True)
        self.apps.write_text('{"apps": []}', encoding="utf-8-sig")
        self.assertEqual(self.export(favourites_only=False).added, 3)

    def test_names_are_unique(self):
        other = self.root / "Zelda (Europe).md"
        other.write_bytes(b"x")
        self.store.sync([entry(self.paths["Zelda (USA).sfc"]), entry(other, "Mega Drive")], str(self.root))
        self.export(favourites_only=False)
        names = [a["name"] for a in self.read()["apps"]]
        self.assertEqual(len(names), len({n.casefold() for n in names}))
        self.assertIn("Zelda (Mega Drive)", names)

    def test_a_game_not_downloaded_yet_is_left_out(self):
        g = self.games["Sonic"]
        with self.store._db() as db:
            db.execute("UPDATE games SET source = 'romm', path = ? WHERE id = ?", (str(self.root / "missing.md"), g.id))
        report = self.export(favourites_only=False)
        self.assertEqual(report.left_out, {"not downloaded yet": 1})
        self.assertEqual(report.added, 2)

    def test_installed_recomps_come_first_named_for_the_game(self):
        folder = self.root / "soh"
        folder.mkdir()
        (folder / "soh.exe").write_bytes(b"x")
        self.rc_store.set_installed(rc.Installed("soh", "1", str(folder), "soh.exe"))
        self.rc_store.set_installed(rc.Installed("gone", "1", str(self.root / "nowhere"), "x.exe"))  # its files are missing
        catalog = [rc.Recomp("soh", "Ship of Harkinian", "The Legend of Zelda: Ocarina of Time", "Nintendo 64", "HarbourMasters/Shipwright")]
        with mock.patch.object(rc, "load_catalog", return_value=catalog):
            report = self.export(favourites_only=True)
        apps = self.read()["apps"]
        self.assertEqual((report.added, apps[0]["name"]), (1, "The Legend of Zelda: Ocarina of Time"))
        self.assertTrue(apps[0]["cmd"].endswith("--launch recomp:soh"))

    def test_recomps_can_be_left_out(self):
        folder = self.root / "soh"
        folder.mkdir()
        (folder / "soh.exe").write_bytes(b"x")
        self.rc_store.set_installed(rc.Installed("soh", "1", str(folder), "soh.exe"))
        self.assertEqual(self.export(recomps=False).added, 0)

    def test_covers_are_png_and_other_types_are_converted(self):
        png = self.root / "a.png"
        png.write_bytes(b"\x89PNG")
        jpg = self.root / "b.jpg"
        jpg.write_bytes(b"\xff\xd8\xff")
        self.assertEqual(st.png_cover(png, "x", None, self.root), str(png))
        self.assertEqual(st.png_cover(jpg, "x", None, self.root), "")  # nothing to convert with
        made = []

        def convert(src, dst):
            made.append(dst.name)
            dst.write_bytes(b"\x89PNG")
            return True

        out = st.png_cover(jpg, "g1", convert, self.root)
        self.assertEqual(Path(out).name, "g1.png")
        st.png_cover(jpg, "g1", convert, self.root)
        self.assertEqual(made, ["g1.png"])  # the second time it is already there
        self.assertEqual(st.png_cover(None, "g1", convert, self.root), "")

    def test_the_cover_goes_into_the_entry(self):
        g = self.games["Zelda"]
        self.store.set_favorite(g.id, True)
        poster = self.root / "poster.png"
        poster.write_bytes(b"\x89PNG")
        with mock.patch.object(gm, "cover_path", return_value=poster):
            report = self.export()
        self.assertEqual((report.covers, self.read()["apps"][0]["image-path"]), (1, str(poster)))

    def test_an_unwritable_file_raises_so_the_window_can_say_why(self):
        self.store.set_favorite(self.games["Zelda"].id, True)
        with mock.patch.object(st, "_write_atomic", side_effect=PermissionError("denied")), self.assertRaises(OSError):
            self.export()


class ParseTests(unittest.TestCase):
    def test_arguments(self):
        self.assertEqual(launcher.parse_args(["--launch", "game:g1"]), ("game", "g1", False))
        self.assertEqual(launcher.parse_args(["--launch=recomp:soh", "--resume"]), ("recomp", "soh", True))
        self.assertEqual(launcher.parse_args(["Distill.pyw", "--launch", "game:g1"]), ("game", "g1", False))

    def test_bad_arguments_say_what_is_wrong(self):
        for argv in (["--launch"], ["--launch", "nonsense"], ["--launch", "game:"], ["--launch", "game:a b"], ["--resume"]):
            with self.subTest(argv=argv), self.assertRaises(launcher.LaunchError):
                launcher.parse_args(argv)


class LaunchTests(Fixture):
    def setUp(self):
        super().setUp()
        self.em_store = rc.Store(self.root / "emulators_state.json")
        self.proc = mock.Mock()
        self.proc.wait.return_value = 0

    def run_game(self, title="Zelda", **kw):
        plan = gm.LaunchPlan(["emu", "rom"], str(self.root), "Test emu")
        with mock.patch.object(gm, "plan_launch", return_value=plan) as planned, mock.patch.object(gm, "spawn", return_value=self.proc) as spawned:
            session = launcher.prepare_game(self.games[title].id, store=self.store, em_store=self.em_store, catalog=[], **kw)
        return session, planned, spawned

    def test_a_game_starts_attached_not_detached_and_is_counted(self):
        session, _planned, spawned = self.run_game()
        self.assertEqual(spawned.call_args.kwargs, {"detach": False})
        self.assertEqual(self.store.get(self.games["Zelda"].id).play_count, 1)
        self.assertEqual((session.name, session.label), ("Zelda", "Test emu"))

    def test_waiting_adds_the_play_time(self):
        session, *_ = self.run_game()
        with mock.patch.object(launcher.time, "time", side_effect=[1000.0, 1000.0 + 3600]):
            self.assertEqual(launcher.wait(session), 0)
        self.assertEqual(self.store.get(self.games["Zelda"].id).play_seconds, 3600)

    def test_a_launcher_that_hands_over_at_once_is_not_counted_as_play_time(self):
        session, *_ = self.run_game()
        with mock.patch.object(launcher.time, "time", side_effect=[1000.0, 1002.0]):
            launcher.wait(session)
        self.assertEqual(self.store.get(self.games["Zelda"].id).play_seconds, 0)

    def test_resume_reaches_the_plan(self):
        _s, planned, _sp = self.run_game(resume=True)
        self.assertTrue(planned.call_args.kwargs["resume"])

    def test_a_mac_open_command_waits(self):
        plan = gm.LaunchPlan(["open", "-a", "/Apps/Emu.app", "--args", "rom"], "/Apps", "Emu")
        with mock.patch.object(gm, "plan_launch", return_value=plan), mock.patch.object(gm, "spawn", return_value=self.proc):
            launcher.prepare_game(self.games["Zelda"].id, store=self.store, em_store=self.em_store, catalog=[])
        self.assertEqual(plan.cmd[:2], ["open", "-W"])

    def test_a_game_that_is_gone_says_so(self):
        with self.assertRaises(launcher.LaunchError) as cm:
            launcher.prepare_game("gnope", store=self.store, em_store=self.em_store, catalog=[])
        self.assertIn("isn't in your Distill library", str(cm.exception))

    def test_nothing_installed_explains_instead_of_crashing(self):
        with self.assertRaises(launcher.LaunchError) as cm:  # the real plan: no RetroArch, no emulators
            launcher.prepare_game(self.games["Zelda"].id, store=self.store, em_store=self.em_store, catalog=[])
        self.assertIn("RetroArch", str(cm.exception))

    def test_a_recomp_starts_attached(self):
        folder = self.root / "soh"
        folder.mkdir()
        (folder / "soh.exe").write_bytes(b"x")
        self.rc_store.set_installed(rc.Installed("soh", "1", str(folder), "soh.exe"))
        with mock.patch.object(rc, "launch", return_value=self.proc) as started:
            session = launcher.prepare("recomp", "soh", rc_store=self.rc_store)
        self.assertEqual(started.call_args.kwargs, {"detach": False})
        self.assertEqual(launcher.wait(session), 0)

    def test_a_recomp_that_was_uninstalled_says_so(self):
        with self.assertRaises(launcher.LaunchError):
            launcher.prepare("recomp", "soh", rc_store=self.rc_store)

    def test_only_retroarch_games_resume(self):
        with self.assertRaises(launcher.LaunchError):
            launcher.prepare("recomp", "soh", resume=True, rc_store=self.rc_store)

    def test_main_reports_a_failure_to_a_log_and_exits_with_2(self):
        with mock.patch.object(launcher.sys, "stderr", None):
            code = launcher.main(["--launch", "game:gnope"])
        self.assertEqual(code, 2)
        self.assertIn("isn't in your Distill library", launcher.log_path().read_text(encoding="utf-8"))

    def test_main_with_bad_arguments_exits_with_2(self):
        with mock.patch.object(launcher.sys, "stderr", None):
            self.assertEqual(launcher.main(["--launch"]), 2)


class DetachTests(unittest.TestCase):
    def test_spawn_detaches_by_default_and_not_when_asked(self):
        plan = gm.LaunchPlan(["emu"], ".", "Emu")
        with mock.patch.object(gm.subprocess, "Popen") as popen, mock.patch.object(gm.sys, "platform", "linux"):
            gm.spawn(plan)
            self.assertTrue(popen.call_args.kwargs["start_new_session"])
            gm.spawn(plan, detach=False)
            self.assertFalse(popen.call_args.kwargs["start_new_session"])
        with mock.patch.object(gm.subprocess, "Popen") as popen, mock.patch.object(gm.sys, "platform", "win32"), \
                mock.patch.object(gm.subprocess, "DETACHED_PROCESS", 0x8, create=True), mock.patch.object(gm.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, create=True):
            gm.spawn(plan)
            self.assertEqual(popen.call_args.kwargs["creationflags"], 0x8 | 0x200)
            gm.spawn(plan, detach=False)
            self.assertEqual(popen.call_args.kwargs["creationflags"], 0)


if __name__ == "__main__":
    unittest.main()
