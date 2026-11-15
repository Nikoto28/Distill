"""The arithmetic behind the manual reader's book and its page turn, kept free of Qt so it can be tested anywhere.

Two halves:

* **The book.** A manual is read as spreads. The front cover stands alone on the right, then pages go in pairs (1 and 2, 3 and 4 ...), and
  a last page with no partner stands alone on the left (the back cover). `spread_pages` says which pages a spread shows, and `book_shift`
  how far a closed book sits off centre (a book with only one page showing is centred, and slides open as the page turns).

* **The curl.** Everything is worked out in the *frame of the page being turned*: the spine is the line x = 0, the page covers
  x in [0, W] and y in [0, H], and the grabbed point `origin` is on the page's outer edge (x = W). Turning a left-hand page is the same
  thing mirrored, and the widget does that mirroring when it paints. Dragging the origin to `pull` folds the page along the line halfway
  between the two (the fold is the perpendicular bisector of origin and pull): what lies on the origin's side swings over to the other
  side as its mirror image, and what lies on the spine's side stays flat. `curl` returns both parts as polygons, the fold line, and the
  reflection that carries the lifted part, so the painter only has to clip and transform.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

Point = tuple[float, float]

EPS = 1e-6


# ---- the book ---------------------------------------------------------------------------------------------------
def spread_count(pages: int) -> int:
    """How many spreads a book of `pages` pages has: the cover alone, then pairs, then a last page alone when the count is even."""
    return 0 if pages <= 0 else pages // 2 + 1


def spread_pages(spread: int, pages: int) -> tuple[int | None, int | None]:
    """(left page, right page) of a spread, as 0-based page numbers; None where the spread has no page on that side."""
    if pages <= 0:
        return None, None
    if spread <= 0:
        return None, 0
    left, right = 2 * spread - 1, 2 * spread
    return (left if left < pages else None), (right if right < pages else None)


def spread_of(page: int, pages: int) -> int:
    """The spread a page is on."""
    return max(0, min((page + 1) // 2, spread_count(pages) - 1))


def book_shift(spread: int, pages: int) -> float:
    """+0.5 for a spread with only a right page (the front cover), -0.5 for only a left page (the back cover), else 0, as a share of
    one page's width: how far the spine sits from the middle of the book."""
    left, right = spread_pages(spread, pages)
    return 0.5 if left is None and right is not None else -0.5 if right is None and left is not None else 0.0


def shift_during_turn(start: int, target: int, pages: int, t: float) -> float:
    """The spine's offset (in page widths) while a leaf is part-way through turning from spread `start` to `target`, `t` being 0..1."""
    t = max(0.0, min(1.0, t))
    a, b = book_shift(start, pages), book_shift(target, pages)
    eased = t * t * (3 - 2 * t)
    return a + (b - a) * eased


def reading_order(side: int, rtl: bool) -> int:
    """The way a leaf lifted from `side` (+1 the right-hand page, -1 the left-hand one) goes through the book: +1 forwards, -1 backwards.
    In a right-to-left book it is the other way round. The same arithmetic gives the side to lift a leaf from for a direction."""
    return side * (-1 if rtl else 1)


# ---- the curl ---------------------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Curl:
    flat: list[Point]  # the part of the page still lying flat (page frame)
    lifted: list[Point]  # the part that has been picked up, where it lay on the page (page frame, before it swings over)
    landed: list[Point]  # that same part where it is now, after swinging over the fold (page frame)
    fold: tuple[Point, Point] | None  # the two ends of the fold line, clipped to a box around the page; None when the page is flat
    reflect: tuple[float, float, float, float, float, float]  # (m11, m12, m21, m22, dx, dy): the swing, as Qt's QTransform wants it
    normal: Point  # unit vector across the fold, pointing from the flat part towards the lifted part's landing side
    progress: float  # 0 flat .. 1 fully turned


FLAT = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def clamp_pull(origin: Point, pull: Point, w: float, h: float) -> Point:
    """Keep the pulled corner where a page that does not stretch could put it: no further from either end of the spine than the grabbed
    point was. Pulling past that simply stops, as a real page does."""
    x, y = pull
    for ax, ay in ((0.0, 0.0), (0.0, h), (0.0, 0.0), (0.0, h)):  # twice round settles the pair of limits together
        r = math.hypot(origin[0] - ax, origin[1] - ay)
        d = math.hypot(x - ax, y - ay)
        if d > r and d > EPS:
            k = r / d
            x, y = ax + (x - ax) * k, ay + (y - ay) * k
    return x, y


def clip_halfplane(poly: list[Point], point: Point, direction: Point, keep_positive: bool) -> list[Point]:
    """Sutherland-Hodgman: the part of a convex polygon on one side of the line through `point` that is square to the unit vector
    `direction`: the side where (p - point) . direction is >= 0 (`keep_positive`), or <= 0."""
    sign = 1.0 if keep_positive else -1.0

    def side(p: Point) -> float:
        return sign * ((p[0] - point[0]) * direction[0] + (p[1] - point[1]) * direction[1])

    out: list[Point] = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        sa, sb = side(a), side(b)
        if sa >= 0:
            out.append(a)
        if (sa >= 0) != (sb >= 0):
            k = sa / (sa - sb)
            out.append((a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k))
    return out


def area(poly: list[Point]) -> float:
    return abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly)))) / 2 if len(poly) > 2 else 0.0


def reflect_point(p: Point, m: Point, u: Point) -> Point:
    """`p` mirrored across the line through `m` along the unit vector `u`."""
    dx, dy = p[0] - m[0], p[1] - m[1]
    along = dx * u[0] + dy * u[1]
    return m[0] + 2 * along * u[0] - dx, m[1] + 2 * along * u[1] - dy


def curl(origin: Point, pull: Point, w: float, h: float, clamp: bool = True) -> Curl:
    """The page (w by h, spine at x = 0) with the point `origin` dragged to `pull`."""
    page = [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)]
    p = clamp_pull(origin, pull, w, h) if clamp else pull
    dx, dy = p[0] - origin[0], p[1] - origin[1]
    dist = math.hypot(dx, dy)
    if dist < 0.5:
        return Curl(page, [], [], None, FLAT, (-1.0, 0.0), 0.0)
    d = (dx / dist, dy / dist)  # from the grabbed point towards where it was dragged
    mid = ((origin[0] + p[0]) / 2, (origin[1] + p[1]) / 2)
    u = (-d[1], d[0])  # along the fold
    flat = clip_halfplane(page, mid, d, keep_positive=True)  # the spine's side of the fold
    lifted = clip_halfplane(page, mid, d, keep_positive=False)  # the origin's side
    landed = [reflect_point(q, mid, u) for q in lifted]
    # the swing as a matrix: x' = m + (2 u u^T - I)(x - m)
    m11, m12, m21, m22 = 2 * u[0] * u[0] - 1, 2 * u[0] * u[1], 2 * u[0] * u[1], 2 * u[1] * u[1] - 1
    dxf = mid[0] - (m11 * mid[0] + m21 * mid[1])
    dyf = mid[1] - (m12 * mid[0] + m22 * mid[1])
    reach = 2 * (w + h)
    fold = ((mid[0] - u[0] * reach, mid[1] - u[1] * reach), (mid[0] + u[0] * reach, mid[1] + u[1] * reach))
    progress = max(0.0, min(1.0, (w - p[0]) / (2 * w))) if w > 0 else 0.0
    return Curl(flat, lifted, landed, fold, (m11, m12, m21, m22, dxf, dyf), d, progress)


# ---- letting go -------------------------------------------------------------------------------------------------
def completes(progress: float, vx: float, w: float) -> bool:
    """Does a page that has been let go of finish its turn? Past a third of the way it does, unless it is being flicked back; a quick
    flick forward finishes it from much earlier. `vx` is the pointer's speed along the frame's x axis (negative = towards the far side),
    in pixels per second."""
    flick = 2.5 * w  # a flick: crossing the page's width in under about 0.4 s
    if vx <= -flick * 0.4 and progress > 0.04:
        return True
    if vx >= flick * 0.4:
        return False
    return progress >= 0.34


def turn_target(origin: Point, w: float, done: bool) -> Point:
    """Where the grabbed point comes to rest: back where it was, or on the other side of the spine (the page is flat on the opposite page)."""
    return (-w, origin[1]) if done else origin


def hint_pull(origin: Point, w: float, h: float, amount: float = 1.0) -> Point:
    """A small peel from a corner, to show the page can be picked up. `origin` should be near the top or bottom corner of the outer edge."""
    up = -1.0 if origin[1] < h / 2 else 1.0
    return origin[0] - 0.07 * w * amount, origin[1] - up * 0.045 * h * amount
