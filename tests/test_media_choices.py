"""The pictures a player chooses for a game (the Edit window's Media tab): kept over renames, 'none' respected, plans applied on Save."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import helpers  # noqa: F401
from distill import gamemedia as mm

PNG = b"\x89PNG\r\n\x1a\n" + bytes(64)
JPG = b"\xff\xd8\xff\xe0" + bytes(64)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        patch = mock.patch.object(mm, "MEDIA_DIR", self.tmp / "media")
        patch.start()
        self.addCleanup(patch.stop)
        mm._PAGES.clear()  # (pages are kept for a few minutes: one test's must not be another's)

    def no_network(self):
        """Anything that reaches for the web fails the test."""
        for name in ("launchbox_images", "lb_game_id"):
            p = mock.patch.object(mm, name, side_effect=AssertionError(f"{name} should not be called"))
            p.start()
            self.addCleanup(p.stop)


class CheckImageTests(unittest.TestCase):
    def test_pictures_pass_and_other_things_do_not(self):
        for data in (PNG, JPG, b"GIF89a" + bytes(20), b"RIFF\x00\x00\x00\x00WEBPVP8 "):
            self.assertEqual(mm.check_image(data), data)
        for data in (b"", b"<html>not a picture</html>", b"RIFF\x00\x00\x00\x00WAVEfmt "):
            with self.assertRaises(mm.MediaError):
                mm.check_image(data)

    def test_a_huge_file_is_refused(self):
        with self.assertRaises(mm.MediaError):
            mm.check_image(PNG + bytes(mm.MAX_IMAGE_BYTES))

    def test_a_file_that_is_not_there_says_so(self):
        with self.assertRaises(mm.MediaError):
            mm.read_image("/no/such/picture.png")


class SingleArtTests(Base):
    def test_a_chosen_picture_is_kept_and_marked_as_chosen(self):
        self.assertEqual(mm.art_state("g1", "back"), "none")
        path = mm.set_art("g1", "back", JPG)
        self.assertEqual(path.read_bytes(), JPG)
        self.assertEqual(mm.art_state("g1", "back"), "custom")
        self.assertEqual(mm.cached_backdrop("g1"), path)

    def test_a_fetched_picture_is_automatic(self):
        (mm._dir() / "back_g1.jpg").write_bytes(JPG)
        self.assertEqual(mm.art_state("g1", "back"), "auto")

    def test_a_bad_picture_is_refused_and_leaves_the_old_one(self):
        mm.set_art("g1", "disc", PNG)
        with self.assertRaises(mm.MediaError):
            mm.set_art("g1", "disc", b"nope")
        self.assertEqual(mm.cached_media_art("g1", "disc").read_bytes(), PNG)

    def test_none_removes_the_picture_and_stops_it_being_looked_for(self):
        self.no_network()
        mm.set_art("g1", "back", JPG)
        mm.turn_art_off("g1", "back")
        self.assertEqual(mm.art_state("g1", "back"), "off")
        self.assertIsNone(mm.cached_backdrop("g1"))
        self.assertIsNone(mm.fetch_backdrop("g1", "Metroid", "Super Nintendo Entertainment System", "key", retry=True))

    def test_none_for_a_disc_also_stops_the_fetch(self):
        self.no_network()
        mm.turn_art_off("g1", "disc")
        self.assertIsNone(mm.fetch_media_art("g1", "disc", "Gran Turismo", "Sony PlayStation", retry=True))

    def test_automatic_again_forgets_every_trace(self):
        mm.set_art("g1", "cart", PNG)
        mm.reset_art("g1", "cart")
        self.assertEqual(mm.art_state("g1", "cart"), "none")
        self.assertEqual(sorted(p.name for p in mm._dir().glob("cart_g1.*")), [])
        mm.turn_art_off("g1", "cart")
        mm.reset_art("g1", "cart")
        self.assertEqual(mm.art_state("g1", "cart"), "none")

    def test_a_game_keeps_its_own_pictures(self):
        mm.set_art("g1", "back", JPG)
        self.assertEqual(mm.art_state("g2", "back"), "none")


class EditingAGameTests(Base):
    def test_renaming_forgets_what_was_found_but_not_what_was_chosen(self):
        (mm._dir() / "back_g1.jpg").write_bytes(JPG)  # found online
        (mm._dir() / "back_g1.miss").write_text("miss")
        mm.set_art("g1", "disc", PNG)  # chosen
        (mm._dir() / "cart_g1.png").write_bytes(PNG)  # found online
        mm.turn_art_off("g1", "back")
        (mm._dir() / "back_g1.jpg").write_bytes(JPG)  # (a leftover beside an 'off' is still the player's 'off')
        mm.clear_media("g1")
        self.assertEqual(mm.art_state("g1", "disc"), "custom")
        self.assertEqual(mm.art_state("g1", "back"), "off")
        self.assertEqual(mm.art_state("g1", "cart"), "none")

    def test_fetched_screenshots_go_but_the_players_own_stay(self):
        (mm._dir() / "shot_g1_00.jpg").write_bytes(JPG)
        (mm._dir() / "shot_g1_00_t.jpg").write_bytes(JPG)
        (mm._dir() / "shot_g1.miss").write_text("miss")
        mine = mm.add_screenshot("g1", JPG)
        mm.clear_media("g1")
        self.assertEqual([p.name for p in mm.cached_screenshots("g1")], [mine.name])
        self.assertFalse((mm._dir() / "shot_g1.miss").exists())

    def test_screenshots_turned_off_stay_off_when_a_game_is_edited(self):
        mm.clear_screenshots("g1", keep_mine=False)
        mm.clear_media("g1")
        self.assertTrue((mm._dir() / "shot_g1.off").is_file())


class ScreenshotTests(Base):
    def test_added_screenshots_are_numbered_after_the_fetched_ones(self):
        (mm._dir() / "shot_g1_00.jpg").write_bytes(JPG)
        a, b = mm.add_screenshot("g1", JPG), mm.add_screenshot("g1", PNG)
        self.assertEqual((a.name, b.name), ("shot_g1_50.jpg", "shot_g1_51.jpg"))
        self.assertEqual([p.name for p in mm.cached_screenshots("g1")], ["shot_g1_00.jpg", "shot_g1_50.jpg", "shot_g1_51.jpg"])

    def test_a_removed_number_is_not_reused_while_others_remain_above_it_only_when_free(self):
        a, b = mm.add_screenshot("g1", JPG), mm.add_screenshot("g1", JPG)
        mm.remove_screenshot("g1", a)
        self.assertEqual(mm.add_screenshot("g1", JPG).name, a.name)  # the gap is filled
        self.assertTrue(b.is_file())

    def test_the_limit_is_stated_in_words(self):
        for _ in range(mm.MAX_CUSTOM_SHOTS):
            mm.add_screenshot("g1", JPG)
        with self.assertRaises(mm.MediaError):
            mm.add_screenshot("g1", JPG)

    def test_off_returns_only_the_players_own_without_going_online(self):
        self.no_network()
        mine = mm.add_screenshot("g1", JPG)
        mm.clear_screenshots("g1", keep_mine=True)
        mm._art_marker("g1", "shot", "off").write_text("off")
        self.assertEqual(mm.fetch_screenshots("g1", "Metroid", "SNES"), [mine])

    def test_removing_the_last_fetched_one_stops_a_refetch(self):
        shot = mm._dir() / "shot_g1_00.jpg"
        shot.write_bytes(JPG)
        mm.remove_screenshot("g1", shot)
        self.assertTrue((mm._dir() / "shot_g1.off").is_file())

    def test_removing_one_of_several_keeps_fetching_as_before(self):
        for n in (0, 1):
            (mm._dir() / f"shot_g1_{n:02d}.jpg").write_bytes(JPG)
        mm.remove_screenshot("g1", mm._dir() / "shot_g1_00.jpg")
        self.assertFalse((mm._dir() / "shot_g1.off").exists())

    def test_adding_one_after_none_turns_screenshots_back_on(self):
        mm.clear_screenshots("g1", keep_mine=False)
        mm.add_screenshot("g1", JPG)
        self.assertFalse((mm._dir() / "shot_g1.off").exists())

    def test_back_to_automatic_keeps_the_players_own_and_looks_again(self):
        (mm._dir() / "shot_g1_00.jpg").write_bytes(JPG)
        mine = mm.add_screenshot("g1", JPG)
        mm.clear_screenshots("g1", keep_mine=True)
        self.assertEqual(mm.cached_screenshots("g1"), [mine])

    def test_a_fetch_keeps_the_players_own_after_the_fetched_ones(self):
        mine = mm.add_screenshot("g1", JPG)
        page = {"screenshots": ["https://images.launchbox-app.com/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.jpg"], "fanart": []}
        with mock.patch.object(mm, "lb_game_id", return_value="1"), mock.patch.object(mm, "launchbox_images", return_value=page), \
                mock.patch.object(mm, "_download", side_effect=lambda url, dest: dest.write_bytes(JPG) or True):
            got = mm.fetch_screenshots("g1", "Metroid", "SNES")
        self.assertEqual([p.name for p in got], ["shot_g1_00.jpg", mine.name])


class PlanTests(Base):
    def test_an_empty_plan_does_nothing(self):
        self.assertTrue(mm.MediaPlan().empty())
        self.assertEqual(mm.apply_plan("g1", mm.MediaPlan()), [])

    def test_a_plan_is_carried_out_on_save_and_not_before(self):
        plan = mm.MediaPlan(art={"back": ("set", JPG), "disc": ("off", None)}, shots_add=[JPG, PNG])
        self.assertFalse(plan.empty())
        self.assertEqual(mm.art_state("g1", "back"), "none")  # staged: nothing on disk yet
        self.assertEqual(mm.apply_plan("g1", plan), [])
        self.assertEqual((mm.art_state("g1", "back"), mm.art_state("g1", "disc")), ("custom", "off"))
        self.assertEqual(len(mm.cached_screenshots("g1")), 2)

    def test_a_bad_picture_is_reported_and_the_rest_still_happens(self):
        plan = mm.MediaPlan(art={"back": ("set", b"junk"), "cart": ("set", PNG)}, shots_add=[b"junk"])
        problems = mm.apply_plan("g1", plan)
        self.assertEqual(len(problems), 2)
        self.assertEqual(mm.art_state("g1", "cart"), "custom")

    def test_screenshots_are_cleared_before_new_ones_are_added(self):
        (mm._dir() / "shot_g1_00.jpg").write_bytes(JPG)
        old = mm.add_screenshot("g1", JPG)
        mm.apply_plan("g1", mm.MediaPlan(shots_mode="off", shots_add=[PNG]))
        names = [p.name for p in mm.cached_screenshots("g1")]
        self.assertEqual(names, ["shot_g1_50.jpg"])
        self.assertEqual(old.name, "shot_g1_50.jpg")

    def test_removing_chosen_screenshots(self):
        a, b = mm.add_screenshot("g1", JPG), mm.add_screenshot("g1", JPG)
        mm.apply_plan("g1", mm.MediaPlan(shots_remove=[a]))
        self.assertEqual(mm.cached_screenshots("g1"), [b])

    def test_the_manual_is_set_or_cleared(self):
        pdf = self.tmp / "m.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        self.assertEqual(mm.apply_plan("g1", mm.MediaPlan(manual=("set", str(pdf)))), [])
        self.assertIsNotNone(mm.cached_manual("g1"))
        mm.apply_plan("g1", mm.MediaPlan(manual=("clear", "")))
        self.assertIsNone(mm.cached_manual("g1"))
        notpdf = self.tmp / "n.pdf"
        notpdf.write_bytes(b"words")
        self.assertEqual(len(mm.apply_plan("g1", mm.MediaPlan(manual=("set", str(notpdf))))), 1)


class CandidateTests(Base):
    PAGE = {"screenshots": ["https://x/s1.jpg", "https://x/s2.jpg", "https://x/s2_small.jpg"], "fanart": ["https://x/f1.jpg", "https://x/f1.jpg"],
            "disc": ["https://x/d1.png"], "cart": ["https://x/c1.png"], "thumbs": {"https://x/s2.jpg": "https://x/s2_small.jpg"}}

    def candidates(self, kind, key=""):
        with mock.patch.object(mm, "lb_game_id", return_value="7"), mock.patch.object(mm, "launchbox_images", return_value=self.PAGE):
            return mm.art_candidates(kind, "Metroid", "SNES", key)

    def test_each_kind_comes_from_its_own_list(self):
        self.assertEqual(self.candidates("disc"), [("https://x/d1.png", "LaunchBox")])
        self.assertEqual(self.candidates("cart"), [("https://x/c1.png", "LaunchBox")])
        self.assertEqual(self.candidates("back"), [("https://x/f1.jpg", "LaunchBox")])  # (listed twice, offered once)

    def test_screenshots_leave_out_the_small_previews(self):
        self.assertEqual([u for u, _s in self.candidates("shots")], ["https://x/s1.jpg", "https://x/s2.jpg"])

    def test_steamgriddb_heroes_come_first_for_a_background(self):
        with mock.patch.object(mm.rc, "sgdb_games", return_value=[{"id": 5}]), mock.patch.object(mm.rc, "_sgdb", return_value=[{"url": "https://s/h1.jpg"}]):
            got = self.candidates("back", "key")
        self.assertEqual(got, [("https://s/h1.jpg", "SteamGridDB"), ("https://x/f1.jpg", "LaunchBox")])

    def test_a_busy_steamgriddb_does_not_lose_the_launchbox_ones(self):
        with mock.patch.object(mm.rc, "sgdb_games", side_effect=mm.rc.SgdbBusy("busy")):
            got = self.candidates("back", "key")
        self.assertEqual(got, [("https://x/f1.jpg", "LaunchBox")])

    def test_a_game_nothing_is_known_about_has_none(self):
        with mock.patch.object(mm, "lb_game_id", return_value=""):
            self.assertEqual(mm.art_candidates("disc", "Unknown", "SNES"), [])


UUID = "0123abcd-4567-89ab-cdef-0123456789ab"
LB_LOGO_PAGE = f"""
<h3>Clear Logo</h3>
<img src="https://images.launchbox-app.com/{UUID.replace('0123', 'aaaa')}.png" alt="Super Metroid - Clear Logo">
<h3>Box - Front</h3>
<img src="https://images.launchbox-app.com/{UUID.replace('0123', 'bbbb')}.jpg" alt="Super Metroid - Box - Front">
<h3>Screenshot - Gameplay</h3>
<img src="https://images.launchbox-app.com/{UUID.replace('0123', 'cccc')}.jpg" alt="Super Metroid - Screenshot - Gameplay">
"""


class ClearLogoIsGoneTests(Base):
    """The clear logo was tried in place of the game's name and taken out again: the name is always text now."""

    def test_launchbox_clear_logos_are_left_alone(self):
        got = mm.parse_launchbox_images(LB_LOGO_PAGE)
        self.assertNotIn("logo", got)
        self.assertEqual(len(got["screenshots"]), 1)  # (the clear logo is not mistaken for a screenshot, nor box art for anything)
        self.assertEqual(got["fanart"], [])

    def test_there_is_no_logo_picture_to_keep_or_fetch(self):
        self.assertNotIn("logo", mm.ART_EXT)
        self.assertFalse(hasattr(mm, "fetch_logo"))
        self.assertFalse(hasattr(mm, "cached_logo"))


if __name__ == "__main__":
    unittest.main()
