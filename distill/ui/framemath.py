"""The arithmetic behind the frame-by-frame animations (a ripple, a drifting glow, a turning disc), so each moves at the same pace
whatever the frame rate: they are driven by the time that has really passed, not by counting frames. Nothing here needs Qt."""
from __future__ import annotations

import math

FALLBACK_FPS = 60.0  # when a screen does not say how fast it refreshes
MAX_FPS = 120.0  # never drawn faster than this, however fast the screen is: a glow or ripple gains nothing past it
MAX_STEP = 0.1  # seconds: a stall (a dragged window, say) must not make an animation lurch


def refresh_interval_ms(hz: float, fallback: float = FALLBACK_FPS, cap: float = MAX_FPS) -> int:
    """Milliseconds between frames for a screen refreshing `hz` times a second (60 -> 16, 120 -> 8), at most `cap` frames a second.
    A rate that is missing, zero, negative, not a number or implausible falls back to `fallback`."""
    try:
        hz = float(hz)
    except (TypeError, ValueError):
        hz = 0.0
    if not 24.0 <= hz <= 1000.0:  # (also false for NaN)
        hz = fallback
    return max(1, int(1000.0 / min(hz, cap)))


def step_seconds(now: float, last: float | None, nominal: float = 1.0 / FALLBACK_FPS) -> float:
    """Seconds since the last frame, never more than MAX_STEP and never negative. The first frame (`last` is None) counts as one
    ordinary frame."""
    if last is None:
        return nominal
    return min(max(now - last, 0.0), MAX_STEP)


def rate_per_frame(share: float, fps: float) -> float:
    """The rate, per second, that eases a value towards its goal as quickly as closing `share` of the gap on every frame did at `fps`
    frames a second (how the old fixed-rate animations were written)."""
    return -fps * math.log(1.0 - share)


def follow(value: float, goal: float, rate: float, dt: float) -> float:
    """Ease `value` towards `goal` for `dt` seconds. Ten steps of a tenth of a second land exactly where one step of a second does."""
    return value + (goal - value) * (1.0 - math.exp(-rate * dt))
