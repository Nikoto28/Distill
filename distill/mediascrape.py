"""Fetching pictures for many games at once: the engine behind the Games page's "Fetch pictures..." window.

`build_jobs` works out, for the games asked about, which pictures each still lacks (leaving alone what the player turned off, and what was
looked for in the last week without luck unless `retry`); `scrape` then fetches them a few games at a time, reporting after every picture
which one is being fetched and how many are done, and stopping promptly when asked. Nothing here knows about windows, so it is tested on its own.
"""
from __future__ import annotations

import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Iterable

from . import gamemedia as mm
from . import games as gm

KINDS = ("cover", "back", "disc", "shots")  # 'disc' stands for whichever of disc or cartridge the game's platform has
LABELS = {"cover": "cover", "back": "background", "disc": "disc or cartridge", "shots": "screenshots"}
WORKERS = 2  # games fetched at once: gentle on the sites asked
PAUSE = 0.12  # seconds a worker waits between pictures


@dataclass(slots=True)
class CoverHooks:
    """Covers belong to the Games page (they are kept per game and drawn in its grid), so the page says which games lack one and fetches it."""
    needs: Callable[[str, bool], bool]  # (game id, look again?) -> does the game lack a cover that is worth looking for
    fetch: Callable[[str, bool], bool]  # (game id, look again?) -> a cover was found


@dataclass(slots=True)
class Job:
    key: str  # what the game's pictures are kept under (versions of one game share it)
    name: str
    system: str
    platform: str  # LaunchBox's name for the platform ('' when it has none)
    wants: list[str]  # the KINDS this game still lacks
    gid: str = ""  # the game's own id (what its cover is kept under)

    def label(self, kind: str) -> str:
        if kind == "disc":
            return {"disc": "disc", "cart": "cartridge"}.get(mm.media_kind(self.system), LABELS["disc"])
        return LABELS[kind]


@dataclass(slots=True)
class Tally:
    found: Counter = field(default_factory=Counter)  # kind -> pictures found
    missed: Counter = field(default_factory=Counter)  # kind -> games it wasn't found for
    errors: int = 0
    games: int = 0  # games finished
    pictures: int = 0  # pictures tried, found or not

    def total_found(self) -> int:
        return sum(self.found.values())


@dataclass(slots=True)
class Progress:
    games_done: int
    games_total: int
    name: str  # the game being fetched for
    kind: str  # the picture being fetched ('' when between pictures)
    label: str  # that picture in words ('background')
    pictures_done: int
    pictures_total: int
    found: int  # pictures found so far
    missed: int  # pictures there was nothing online for
    errors: int


def lacks(key: str, system: str, kind: str, retry: bool, gid: str = "", covers: CoverHooks | None = None) -> bool:
    """Does the game still lack this kind of picture (and is it worth looking)?"""
    if kind == "cover":
        return covers is not None and bool(gid) and covers.needs(gid, retry)
    if kind == "shots":
        if mm._art_marker(key, "shot", "off").is_file():
            return False
        if [p for p in mm.cached_screenshots(key) if not mm._is_custom_shot(p)]:
            return False
        return retry or not mm.recently_missed(key, "shot")
    stem = mm.media_kind(system) if kind == "disc" else kind
    if not stem:  # a platform with neither disc nor cartridge
        return False
    return mm.art_state(key, stem) == "none" and (retry or not mm.recently_missed(key, stem))


def build_jobs(entries: Iterable[tuple], kinds: Iterable[str], retry: bool = False, covers: CoverHooks | None = None) -> list[Job]:
    """`entries` are (picture key, name, platform[, game id]) for the games asked about; the game id is needed for covers. One job for each
    game that lacks something of `kinds` (versions of a game share their pictures, so they make one job)."""
    wanted = [k for k in KINDS if k in set(kinds)]
    jobs: list[Job] = []
    seen: set[str] = set()
    for key, name, system, *rest in entries:
        if key in seen:
            continue
        seen.add(key)
        gid = rest[0] if rest else ""
        wants = [k for k in wanted if lacks(key, system, k, retry, gid, covers)]
        if wants:
            jobs.append(Job(key, name, system, gm.LB_PLATFORM_NAMES.get(system, "" if system in ("", gm.UNKNOWN) else system), wants, gid))
    return jobs


def fetch_one(job: Job, kind: str, sgdb_key: str, retry: bool) -> bool:
    """Fetch one kind of picture for a game; True when it is there now."""
    if kind == "back":
        return mm.fetch_backdrop(job.key, job.name, job.platform, sgdb_key, retry=retry) is not None
    if kind == "disc":
        stem = mm.media_kind(job.system)
        return bool(stem) and mm.fetch_media_art(job.key, stem, job.name, job.platform, retry=retry) is not None
    got = mm.fetch_screenshots(job.key, job.name, job.platform, retry=retry)
    return any(not mm._is_custom_shot(p) for p in got)


def scrape(jobs: list[Job], sgdb_key: str, retry: bool, on_progress: Callable[[Progress], None], cancelled: Callable[[], bool],
           workers: int = WORKERS, pause: float = PAUSE, covers: CoverHooks | None = None) -> Tally:
    """Fetch what the jobs ask for. Blocks until done or cancelled; `on_progress` is called (from worker threads) before each picture and
    after each game. A picture that can't be fetched is counted and the rest carry on."""
    tally = Tally()
    lock = threading.Lock()
    total_pictures = sum(len(j.wants) for j in jobs)

    def report(name: str, kind: str, label: str) -> None:
        with lock:
            snap = Progress(tally.games, len(jobs), name, kind, label, tally.pictures, total_pictures, tally.total_found(),
                            sum(tally.missed.values()), tally.errors)
        on_progress(snap)

    def work(job: Job) -> None:
        for kind in job.wants:
            if cancelled():
                return
            report(job.name, kind, job.label(kind))
            try:
                ok = covers.fetch(job.gid, retry) if kind == "cover" and covers is not None else fetch_one(job, kind, sgdb_key, retry)
            except Exception:  # a game that can't be fetched for must not stop the others
                ok = None
            with lock:
                tally.pictures += 1
                if ok is None:
                    tally.errors += 1
                elif ok:
                    tally.found[kind] += 1
                else:
                    tally.missed[kind] += 1
            time.sleep(pause)
        with lock:
            tally.games += 1
        report(job.name, "", "")

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(work, jobs))
    return tally


def summary(tally: Tally, cancelled: bool) -> str:
    """The result in words, for the window to show when it is over."""
    parts = [f"{n} {LABELS[k]}" for k in KINDS if (n := tally.found[k])]
    found = "found " + ", ".join(parts) if parts else "found nothing new"
    gone = sum(tally.missed.values())
    out = ("Stopped: " if cancelled else "Done: ") + found
    if gone:
        out += f". Nothing online for {gone} picture{'s' if gone != 1 else ''}"
    if tally.errors:
        out += f". {tally.errors} couldn't be fetched (check the connection and try again)"
    return out + "."
