"""A check-up of the games library: what is wrong or lacking, in a list the player can act on.

`check` looks at the games (and what the page already knows: which files are missing, which games have a cover, how many lack pictures) and
returns the problems found, each with the games it is about so the page can select them for the bulk tools. No windows here, so it is
tested on its own.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Iterable

from . import games as gm


@dataclass(slots=True)
class Issue:
    key: str  # 'missing', 'duplicates', 'unplaced', 'nocover', 'nodetails' or 'pictures'
    title: str
    detail: str  # what it means and what can be done, in a sentence or two
    count: int  # games it is about
    ids: list[str] = field(default_factory=list)  # their ids, to select them
    action: str = "select"  # 'select' (select these games) or 'fetch' (open the Fetch pictures window)


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _title_key(g: gm.Game) -> str:
    return re.sub(r"\W+", " ", (g.custom_title or g.title).lower()).strip()


def duplicate_groups(games: Iterable[gm.Game]) -> list[list[gm.Game]]:
    """Games that look like one file stored twice: the same platform, the same size and the same name, in different places."""
    seen: dict[tuple[str, int, str], list[gm.Game]] = defaultdict(list)
    for g in games:
        if g.size > 0 and not g.remote:
            seen[(g.system, g.size, _title_key(g))].append(g)
    return [group for group in seen.values() if len({g.path for g in group}) > 1]


def check(games: list[gm.Game], missing_ids: set[str], has_cover: Callable[[gm.Game], bool], games_lacking_pictures: int = 0) -> list[Issue]:
    """The problems with the library, most serious first. Nothing is returned for a healthy library."""
    out: list[Issue] = []
    gone = [g for g in games if g.id in missing_ids]
    if gone:
        out.append(Issue("missing", f"{_plural(len(gone), 'game has', 'games have')} lost its file" if len(gone) == 1 else f"{len(gone)} games have lost their files",
                         "Their files are no longer where the scan found them (moved, renamed or on a drive that isn't connected). Select them to remove them "
                         "from the library, or put the files back and scan again.", len(gone), [g.id for g in gone]))
    groups = duplicate_groups(games)
    if groups:
        extra = [g for group in groups for g in group[1:]]  # one of each is kept; the rest are the spare copies
        out.append(Issue("duplicates", f"{_plural(len(groups), 'game seems', 'games seem')} to be stored twice",
                         "The same platform, size and name in more than one place. Select the spare copies to remove them from the library "
                         "(the files themselves are left where they are).", len(extra), [g.id for g in extra]))
    unplaced = [g for g in games if g.system == gm.UNKNOWN]
    if unplaced:
        out.append(Issue("unplaced", f"{_plural(len(unplaced), 'game has', 'games have')} no platform",
                         "The scan couldn't tell which platform they belong to. Select them and choose a platform from the tools bar.", len(unplaced),
                         [g.id for g in unplaced]))
    if games_lacking_pictures:
        out.append(Issue("pictures", f"{_plural(games_lacking_pictures, 'game lacks', 'games lack')} backgrounds, discs or screenshots",
                         "Look for them online in one go.", games_lacking_pictures, [], "fetch"))
    nocover = [g for g in games if not has_cover(g)]
    if nocover:
        out.append(Issue("nocover", f"{_plural(len(nocover), 'game has', 'games have')} no cover",
                         "Covers are fetched as you scroll the library, or all at once in Fetch pictures. These have none yet, or none was found.",
                         len(nocover), [g.id for g in nocover]))
    nodetails = [g for g in games if not (g.developer or g.publisher or g.year or g.genre)]
    if nodetails:
        out.append(Issue("nodetails", f"{_plural(len(nodetails), 'game has', 'games have')} no details",
                         "No developer, publisher, year or genre. Select them and use Get info from LaunchBox.", len(nodetails), [g.id for g in nodetails]))
    return out
