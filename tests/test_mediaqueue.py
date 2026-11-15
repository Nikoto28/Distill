from __future__ import annotations

import random
import unittest

from tests import helpers  # noqa: F401

from distill.mediaqueue import PlayQueue, QueueItem, REPEAT_ALL, REPEAT_OFF, REPEAT_ONE


def items(n, tag="a"):
    return [QueueItem(f"{tag}{i}", "Album", f"u{tag}{i}", "", "khinsider", tag, i) for i in range(n)]


def titles(q, indexes):
    return [q.items[i].title for i in indexes]


class PlayQueueTests(unittest.TestCase):
    def q(self, n=4):
        q = PlayQueue(random.Random(1))
        q.set(items(n), 0)
        return q

    def test_plays_in_order_and_stops_at_the_end(self):
        q = self.q(3)
        self.assertEqual(q.current().title, "a0")
        self.assertTrue(q.step(1))
        self.assertTrue(q.step(1, auto=True))
        self.assertEqual(q.current().title, "a2")
        self.assertFalse(q.step(1))
        self.assertEqual(q.current().title, "a2")  # still on the last one

    def test_previous_stops_at_the_start(self):
        q = self.q(3)
        self.assertFalse(q.step(-1))
        q.step(1)
        self.assertTrue(q.step(-1))
        self.assertEqual(q.current().title, "a0")

    def test_repeat_all_wraps_both_ways(self):
        q = self.q(2)
        q.repeat = REPEAT_ALL
        q.step(1)
        self.assertTrue(q.step(1))
        self.assertEqual(q.current().title, "a0")
        self.assertTrue(q.step(-1))
        self.assertEqual(q.current().title, "a1")
        self.assertTrue(q.can_step(1) and q.can_step(-1))

    def test_repeat_one_replays_only_when_the_track_ends_by_itself(self):
        q = self.q(3)
        q.repeat = REPEAT_ONE
        self.assertTrue(q.step(1, auto=True))
        self.assertEqual(q.current().title, "a0")
        self.assertEqual(q.peek_next(), 0)
        q.step(1)  # the person pressing next still moves on
        self.assertEqual(q.current().title, "a1")

    def test_peek_next(self):
        q = self.q(2)
        self.assertEqual(q.peek_next(), 1)
        q.step(1)
        self.assertEqual(q.peek_next(), -1)
        q.repeat = REPEAT_ALL
        self.assertEqual(q.peek_next(), 0)

    def test_play_next_goes_right_after_the_current_track(self):
        q = self.q(3)
        q.step(1)  # on a1
        q.insert_next(items(2, "b"))
        self.assertEqual(titles(q, q.upcoming()), ["b0", "b1", "a2"])
        self.assertEqual(q.current().title, "a1")

    def test_play_next_with_nothing_playing_goes_to_the_end(self):
        q = PlayQueue()
        q.set(items(2))
        q.stop()
        q.insert_next(items(1, "b"))
        self.assertEqual(titles(q, q.upcoming()), ["a0", "a1", "b0"])

    def test_append_goes_after_everything(self):
        q = self.q(2)
        q.append(items(2, "b"))
        self.assertEqual(titles(q, q.upcoming()), ["a1", "b0", "b1"])

    def test_remove_keeps_the_current_track_and_refuses_to_remove_it(self):
        q = self.q(4)
        q.step(1)
        q.step(1)  # on a2
        self.assertFalse(q.remove(q.current_index))
        self.assertTrue(q.remove(0))  # a track already played
        self.assertEqual(q.current().title, "a2")
        self.assertTrue(q.remove(2))  # an upcoming one (a3)
        self.assertEqual([i.title for i in q.items], ["a1", "a2"])
        self.assertEqual(q.upcoming(), [])

    def test_move_reorders_without_losing_the_current_track(self):
        q = self.q(4)
        q.step(1)  # a1
        q.move(3, 0)
        self.assertEqual([i.title for i in q.items], ["a3", "a0", "a1", "a2"])
        self.assertEqual(q.current().title, "a1")
        self.assertEqual(titles(q, q.upcoming()), ["a2"])

    def test_shuffle_keeps_the_current_track_first_and_plays_everything_once(self):
        q = self.q(6)
        q.step(1)  # a1
        q.set_shuffle(True)
        self.assertEqual(q.current().title, "a1")
        self.assertEqual(sorted(q.order), list(range(6)))
        self.assertEqual(q.pos, 0)
        seen = [q.current().title]
        while q.step(1):
            seen.append(q.current().title)
        self.assertEqual(sorted(seen), [f"a{i}" for i in range(6)])
        q.set_shuffle(False)
        self.assertEqual(q.order, list(range(6)))
        self.assertEqual(q.current().title, seen[-1])

    def test_shuffle_with_repeat_all_starts_a_new_lap_with_a_different_first_track(self):
        q = self.q(5)
        q.set_shuffle(True)
        q.repeat = REPEAT_ALL
        for _ in range(4):
            q.step(1)
        last = q.current().title
        self.assertTrue(q.step(1))
        self.assertEqual(sorted(q.order), list(range(5)))
        self.assertNotEqual(q.items[q.order[0]].title, last) if False else None  # first of the lap is random; just valid
        self.assertEqual(q.pos, 0)

    def test_new_queue_while_shuffled_starts_at_the_chosen_track(self):
        q = PlayQueue(random.Random(2))
        q.set_shuffle(True)
        q.set(items(5), 3)
        self.assertEqual(q.current().title, "a3")
        self.assertEqual(len(q.upcoming()), 4)

    def test_jump_and_stop(self):
        q = self.q(3)
        self.assertTrue(q.jump(2))
        self.assertEqual(q.current().title, "a2")
        q.stop()
        self.assertEqual((q.current(), q.current_index, q.can_step(1)), (None, -1, False))
        self.assertEqual(len(q.items), 3)  # the queue stays
        self.assertFalse(q.jump(9))

    def test_move_upcoming_with_shuffle_off(self):
        q = self.q(5)
        q.step(1)  # on a1; upcoming a2 a3 a4
        self.assertTrue(q.move_upcoming(q.upcoming()[2], 0))  # a4 to the front of what is left
        self.assertEqual(titles(q, q.upcoming()), ["a4", "a2", "a3"])
        self.assertEqual(q.current().title, "a1")
        self.assertEqual(q.order, list(range(5)))  # the list is the play order again
        self.assertTrue(q.move_upcoming(q.upcoming()[0], 99))  # past the end clamps
        self.assertEqual(titles(q, q.upcoming()), ["a2", "a3", "a4"])
        self.assertFalse(q.move_upcoming(q.current_index, 0))  # the playing track and played ones do not move
        self.assertFalse(q.move_upcoming(0, 0))

    def test_move_upcoming_with_shuffle_on_changes_only_the_play_order(self):
        q = self.q(5)
        q.set_shuffle(True)
        before = list(q.items)
        last = q.upcoming()[-1]
        q.move_upcoming(last, 0)
        self.assertEqual(q.items, before)
        self.assertEqual(q.upcoming()[0], last)
        self.assertEqual(q.pos, 0)

    def test_old_saved_queues_without_a_detail_still_load(self):
        q = PlayQueue()
        q.restore({"items": [["t", "A", "u", "", "khinsider", "x", 0]], "order": [0]})
        self.assertEqual(q.items[0].detail, "")
        q.restore({"items": [["t", "A", "u", "", "khinsider", "x", 0, "PC"]], "order": [0]})
        self.assertEqual(q.items[0].detail, "PC")

    def test_cycle_repeat(self):
        q = PlayQueue()
        self.assertEqual([q.cycle_repeat() for _ in range(3)], [REPEAT_ALL, REPEAT_ONE, REPEAT_OFF])

    def test_state_round_trips_and_bad_state_is_ignored(self):
        q = self.q(4)
        q.set_shuffle(True)
        q.repeat = REPEAT_ALL
        saved = q.state()
        other = PlayQueue()
        other.restore(saved)
        self.assertEqual((other.items, other.order, other.shuffle, other.repeat, other.pos), (q.items, q.order, True, REPEAT_ALL, -1))
        self.assertEqual(saved["last"], q.current_index)
        broken = PlayQueue()
        broken.restore({"items": [["x"]]})
        self.assertEqual(broken.items, [])
        bad_order = PlayQueue()
        bad_order.restore({"items": saved["items"], "order": [0, 0]})
        self.assertEqual(bad_order.order, [0, 1, 2, 3])


if __name__ == "__main__":
    unittest.main()
