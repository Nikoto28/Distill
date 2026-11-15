"""What can play a platform, as the Edit window's Emulator tab shows it (games.emulator_options)."""
from __future__ import annotations

import unittest
from pathlib import Path

from tests import helpers  # noqa: F401
from distill import games as gm


def setup(*cores: str) -> gm.RetroSetup:
    return gm.RetroSetup(Path("/ra/retroarch.exe"), {c: Path(f"/ra/cores/{c}_libretro.dll") for c in cores}, {})


PCSX2 = gm.Standalone("pcsx2", "PCSX2", Path("/emu/pcsx2.exe"))
DUCK = gm.Standalone("duckstation", "DuckStation", Path("/emu/duck.exe"), "--fast {rom}")


class EmulatorOptionsTests(unittest.TestCase):
    def test_nothing_installed_says_what_to_install(self):
        o = gm.emulator_options("SNES", None, {}, "")
        self.assertFalse(o.playable)
        self.assertEqual((o.choices, o.auto_label), ([], ""))
        self.assertIn("Nothing installed can play SNES", o.problem)
        self.assertIn("Emulators page", o.problem)

    def test_a_platform_with_no_known_core_just_asks_for_an_emulator(self):
        o = gm.emulator_options("Some Odd Console", None, {}, "")
        self.assertTrue(o.problem.endswith("Emulators page."))

    def test_cores_and_emulators_of_their_own_are_all_offered(self):
        o = gm.emulator_options("PlayStation 2", setup(), {"pcsx2": PCSX2}, "")
        self.assertEqual(o.choices, [("pcsx2", "PCSX2")])
        o = gm.emulator_options("SNES", setup("snes9x"), {}, "")
        self.assertEqual([c for c, _l in o.choices], ["retroarch:snes9x"])
        self.assertTrue(o.choices[0][1].startswith("RetroArch · "))
        self.assertTrue(o.playable)
        self.assertEqual(o.problem, "")

    def test_automatic_is_the_first_core_when_there_is_one(self):
        o = gm.emulator_options("SNES", setup("snes9x"), {}, "")
        self.assertEqual(o.auto_label, setup("snes9x").core_label("snes9x"))

    def test_automatic_without_retroarch_is_the_first_emulator_of_its_own(self):
        o = gm.emulator_options("PlayStation", None, {"duckstation": DUCK, "pcsx2": PCSX2}, "")
        self.assertEqual(o.auto_label, "DuckStation")

    def test_the_platform_default_decides_what_automatic_means(self):
        o = gm.emulator_options("PlayStation 2", setup("pcsx2"), {"pcsx2": PCSX2}, "pcsx2")
        self.assertEqual(o.auto_label, "PCSX2")
        self.assertEqual(o.default, "pcsx2")
        self.assertEqual(o.label_of("pcsx2"), "PCSX2")
        self.assertEqual(o.label_of("nope"), "")

    def test_a_default_that_is_no_longer_installed_falls_back_to_what_is(self):
        o = gm.emulator_options("PlayStation", None, {"duckstation": DUCK}, "retroarch:beetle_psx")
        self.assertEqual(o.auto_label, "DuckStation")

    def test_launch_options_are_listed_for_emulators_of_their_own(self):
        o = gm.emulator_options("PlayStation", None, {"duckstation": DUCK, "pcsx2": PCSX2}, "")
        name, used, own = o.args["duckstation"]
        self.assertEqual((name, used), ("DuckStation", "--fast {rom}"))
        self.assertEqual(own, gm.STANDALONE_ARGS.get("duckstation", "{rom}"))
        name, used, own = o.args["pcsx2"]  # none written: Distill's own are what it is started with
        self.assertEqual(used, own)

    def test_which_emulator_a_choice_means(self):
        o = gm.emulator_options("PlayStation", setup("mednafen_psx"), {"duckstation": DUCK}, "")
        self.assertEqual(o.effective("duckstation"), "duckstation")
        self.assertEqual(o.effective("retroarch:mednafen_psx"), "retroarch")
        self.assertEqual(o.effective(""), "retroarch")  # automatic: a core is installed, so RetroArch
        o = gm.emulator_options("PlayStation", None, {"duckstation": DUCK}, "")
        self.assertEqual(o.effective(""), "duckstation")
        o = gm.emulator_options("PlayStation", None, {"duckstation": DUCK}, "duckstation")
        self.assertEqual(o.effective(""), "duckstation")  # the platform's default
        self.assertEqual(gm.emulator_options("SNES", None, {}, "").effective(""), "")


if __name__ == "__main__":
    unittest.main()
