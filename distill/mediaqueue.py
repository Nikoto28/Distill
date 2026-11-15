"""The play queue: what plays now, what is up next, shuffle and repeat. Plain objects, no Qt and no audio, so every rule
here is tested without a player.

`items` is the queue as the person built it. `order` is the play order, a permutation of the item indexes: the same
as the items unless shuffle is on. `pos` is where the playing track is in `order` (-1: nothing is playing).
"""
from __future__ import annotations

import random
from typing import NamedTuple

REPEAT_OFF, REPEAT_ALL, REPEAT_ONE = "off", "all", "one"
REPEATS = (REPEAT_OFF, REPEAT_ALL, REPEAT_ONE)


class QueueItem(NamedTuple):
    title: str
    album: str  # the album's title, shown under the track
    url: str  # the track's page or file address (a khinsider page is looked up when played)
    art: str
    source: str  # which provider the album came from
    ident: str  # the album's id at that provider
    position: int  # the track's index within the album's listing
    detail: str = ""  # the album's platform / year line, kept so a play can be logged in full
    seconds: int = 0  # the track's length when the source said (the seek bar shows it before the audio is read)


class PlayQueue:
    def __init__(self, rng: random.Random | None = None):
        self.items: list[QueueItem] = []
        self.order: list[int] = []
        self.pos = -1
        self.shuffle = False
        self.repeat = REPEAT_OFF
        self._rng = rng or random.Random()

    # ---- what is playing ------------------------------------------------------------------------
    @property
    def current_index(self) -> int:
        """Index into `items` of the playing track, or -1."""
        return self.order[self.pos] if 0 <= self.pos < len(self.order) else -1

    def current(self) -> QueueItem | None:
        i = self.current_index
        return self.items[i] if i >= 0 else None

    def upcoming(self) -> list[int]:
        """Item indexes still to play, in play order."""
        return self.order[self.pos + 1:] if self.pos >= 0 else list(self.order)

    def played(self) -> list[int]:
        return self.order[:self.pos] if self.pos > 0 else []

    # ---- building the queue ---------------------------------------------------------------------
    def set(self, items: list[QueueItem], start: int = 0) -> None:
        """Replace the queue and start at `items[start]`. With shuffle on, the rest follow in random order."""
        self.items = list(items)
        self.order = list(range(len(self.items)))
        self.pos = start if 0 <= start < len(self.items) else -1
        if self.shuffle:
            self._reshuffle()

    def _reshuffle(self) -> None:
        cur = self.current_index
        rest = [i for i in range(len(self.items)) if i != cur]
        self._rng.shuffle(rest)
        if cur >= 0:
            self.order, self.pos = [cur] + rest, 0
        else:
            self.order, self.pos = rest, -1

    def insert_next(self, new: list[QueueItem]) -> None:
        """Play these straight after the playing track."""
        if not new:
            return
        cur = self.current_index
        at = cur + 1 if cur >= 0 else len(self.items)
        n = len(new)
        self.items[at:at] = new
        order = [o + n if o >= at else o for o in self.order]
        added = list(range(at, at + n))
        if self.shuffle and self.pos >= 0:
            order[self.pos + 1:self.pos + 1] = added
        elif self.shuffle:
            order = added + order
        else:
            order = list(range(len(self.items)))
        self.order = order

    def append(self, new: list[QueueItem]) -> None:
        """Play these after everything already queued."""
        start = len(self.items)
        self.items.extend(new)
        self.order.extend(range(start, len(self.items)))

    def remove(self, index: int) -> bool:
        """Take an item out. The playing track cannot be removed (False)."""
        if not 0 <= index < len(self.items) or index == self.current_index:
            return False
        k = self.order.index(index)
        del self.items[index]
        del self.order[k]
        self.order = [o - 1 if o > index else o for o in self.order]
        if k < self.pos:
            self.pos -= 1
        return True

    def move(self, index: int, to: int) -> None:
        """Move an item to another place in the list (what the person sees when shuffle is off)."""
        if not (0 <= index < len(self.items)) or not (0 <= to < len(self.items)) or index == to:
            return
        perm = list(range(len(self.items)))
        perm.insert(to, perm.pop(index))
        new_of = {old: new for new, old in enumerate(perm)}
        cur = new_of[self.current_index] if self.current_index >= 0 else -1
        self.items = [self.items[old] for old in perm]
        if self.shuffle:  # the play order is random: the same tracks in the same sequence
            self.order = [new_of[o] for o in self.order]
        else:  # the list is the play order
            self.order = list(range(len(self.items)))
            self.pos = cur

    def move_upcoming(self, index: int, slot: int) -> bool:
        """Put an upcoming item at `slot` among the tracks still to play (0 plays next). Works with shuffle on or off.
        False when the item is not one of the upcoming ones."""
        up = self.upcoming()
        if index not in up:
            return False
        up.remove(index)
        up.insert(max(0, min(slot, len(up))), index)
        head = self.order[:self.pos + 1] if self.pos >= 0 else []
        self.order = head + up
        if not self.shuffle:  # the list is the play order: make the items follow it
            self.items = [self.items[o] for o in self.order]
            self.order = list(range(len(self.items)))
        return True

    def clear(self) -> None:
        self.items, self.order, self.pos = [], [], -1

    def stop(self) -> None:
        """Nothing is playing any more; the queue itself stays."""
        self.pos = -1

    # ---- moving through it ----------------------------------------------------------------------
    def jump(self, index: int) -> bool:
        if not 0 <= index < len(self.items):
            return False
        self.pos = self.order.index(index)
        return True

    def can_step(self, delta: int) -> bool:
        if self.pos < 0:
            return False
        if self.repeat == REPEAT_ALL:
            return len(self.order) > 0
        return 0 <= self.pos + delta < len(self.order)

    def peek_next(self) -> int:
        """The item that will play after this one on its own (-1: none), so it can be got ready early."""
        if self.pos < 0:
            return -1
        if self.repeat == REPEAT_ONE:
            return self.current_index
        if self.pos + 1 < len(self.order):
            return self.order[self.pos + 1]
        return self.order[0] if self.repeat == REPEAT_ALL and self.order else -1

    def step(self, delta: int, auto: bool = False) -> bool:
        """Move to the next (+1) or previous (-1) track. `auto` is the track ending by itself: repeat-one then plays
        it again. False when there is nowhere to go (the end of the queue with repeat off)."""
        if self.pos < 0:
            return False
        if auto and self.repeat == REPEAT_ONE:
            return True
        target = self.pos + delta
        if 0 <= target < len(self.order):
            self.pos = target
            return True
        if self.repeat == REPEAT_ALL and self.order:
            if self.shuffle and delta > 0:  # a new lap, in a new order (the track just played does not open it)
                last = self.current_index
                rest = [i for i in self.order if i != last]
                self._rng.shuffle(rest)
                self.order = rest + [last] if rest else [last]
                self.pos = 0
            else:
                self.pos = 0 if delta > 0 else len(self.order) - 1
            return True
        return False

    def set_shuffle(self, on: bool) -> None:
        if on == self.shuffle:
            return
        self.shuffle = on
        cur = self.current_index
        if on:
            self._reshuffle()
        else:
            self.order = list(range(len(self.items)))
            self.pos = cur

    def cycle_repeat(self) -> str:
        self.repeat = REPEATS[(REPEATS.index(self.repeat) + 1) % len(REPEATS)]
        return self.repeat

    # ---- keeping it between runs ----------------------------------------------------------------
    def state(self) -> dict:
        return {"items": [list(i) for i in self.items], "order": self.order, "last": self.current_index,
                "shuffle": self.shuffle, "repeat": self.repeat}

    def restore(self, state: dict) -> None:
        """Load a saved queue. Nothing is playing after it (`pos` is -1); `last` is what was playing."""
        try:
            items = [QueueItem(*[str(x) for x in row[:6]], int(row[6]), str(row[7]) if len(row) > 7 else "",
                               int(row[8]) if len(row) > 8 else 0) for row in state["items"]]
            order = [int(o) for o in state["order"]]
        except (KeyError, TypeError, ValueError, IndexError):
            return
        if sorted(order) != list(range(len(items))):
            order = list(range(len(items)))
        self.items, self.order, self.pos = items, order, -1
        self.shuffle = bool(state.get("shuffle"))
        self.repeat = state.get("repeat") if state.get("repeat") in REPEATS else REPEAT_OFF
