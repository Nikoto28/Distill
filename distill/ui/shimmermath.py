"""The timing of the shimmer shown where a picture is still on its way: a light band sweeps across the empty panel, rests a moment, and
sweeps again. Kept apart from Qt so it can be tested on its own (see shimmer.py for the painting)."""
from __future__ import annotations

PERIOD = 1.5  # seconds one sweep takes
REST = 0.4  # seconds of calm between sweeps
BAND = 0.5  # the band's width, as a share of the panel's width
STEP = 0.14  # seconds between neighbouring panels, so a row of them ripples instead of flashing together


def phase(t: float, delay: float = 0.0) -> float | None:
    """How far the sweep has got (0 at the start, 1 at the end, eased), or None while it rests between sweeps."""
    u = (t - delay) % (PERIOD + REST)
    if u >= PERIOD:
        return None
    x = u / PERIOD
    return x * x * (3 - 2 * x)


def band_span(p: float, width: float) -> tuple[float, float]:
    """The band's left and right edge across a panel `width` wide: it comes in from beyond the left edge and leaves beyond the right."""
    band = BAND * width
    left = -band + p * (width + band)
    return left, left + band


def stagger(index: int) -> float:
    """The delay of the `index`th panel in a row."""
    return max(0, index) * STEP
