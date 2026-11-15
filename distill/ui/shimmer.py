"""Placeholders for pictures that are on their way. Where a picture will appear but has not yet, a quiet panel with a light band sweeping
across it says so, instead of the space staying empty and the picture suddenly being there. All the panels on screen are driven by one shared
timer, which runs only while one is visible; with animations off (see motion.on) they are plain panels.

  Shimmer       a panel (give it the size and corner radius of the picture it stands in for)
  paint_band    the band alone, for something that paints its own placeholder (the poster grid)
  busy          lay a shimmer over a QLabel while its picture is being fetched
  FetchStrip    a slim line saying what is being looked for and how far along it is
"""
from __future__ import annotations

import time
import weakref

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from . import motion
from . import shimmermath as sm
from .theme import T

MIN_FRAME_MS = 25  # a sweep is slow and soft: about 40 frames a second is plenty


def paint_band(p: QPainter, rect: QRectF, delay: float = 0.0, now: float | None = None) -> None:
    """Draw the light band over `rect` (the painter should already be clipped to the shape it stands in for). Nothing while the sweep rests."""
    ph = sm.phase(time.monotonic() if now is None else now, delay)
    if ph is None:
        return
    left, right = sm.band_span(ph, rect.width())
    grad = QLinearGradient(rect.left() + left, 0, rect.left() + right, 0)
    for at, alpha in ((0.0, 0), (0.5, 36), (1.0, 0)):
        c = QColor(T.fg)
        c.setAlpha(alpha)
        grad.setColorAt(at, c)
    p.fillRect(rect, grad)


def _showing(ref: weakref.ref) -> bool:
    """Is the widget still there and on screen? (One deleted by Qt raises when asked.)"""
    w = ref()
    if w is None:
        return False
    try:
        return w.isVisible()
    except RuntimeError:
        return False


class _Beat(QObject):
    """The one timer behind every visible shimmer."""
    tick = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._users: list[weakref.ref] = []
        self._timer = motion.frame_timer(self)
        self._timer.timeout.connect(self._on_timer)

    def join(self, widget: QWidget) -> None:
        self._users.append(weakref.ref(widget))
        if not self._timer.isActive():
            self._timer.start(max(MIN_FRAME_MS, motion.frame_ms(widget)))

    def _on_timer(self) -> None:
        self._users = [r for r in self._users if _showing(r)]
        if not self._users:
            self._timer.stop()  # nothing left to draw: no timer ticking in the background
            return
        self.tick.emit()


_BEAT: _Beat | None = None


def beat() -> _Beat:
    global _BEAT
    if _BEAT is None:
        _BEAT = _Beat()
    return _BEAT


class Shimmer(QWidget):
    """A panel standing in for a picture that is on its way."""

    def __init__(self, radius: float = 12.0, delay: float = 0.0, parent: QWidget | None = None):
        super().__init__(parent)
        self.radius, self.delay = radius, delay
        self._joined = False
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._joined and motion.on():
            self._joined = True
            b = beat()
            b.tick.connect(self.update)
            b.join(self)

    def hideEvent(self, event) -> None:
        if self._joined:
            self._joined = False
            try:
                beat().tick.disconnect(self.update)
            except (RuntimeError, TypeError):
                pass
        super().hideEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self.radius, self.radius)
        p.fillPath(path, T.input)
        p.setPen(QPen(T.card_border, 1))
        p.drawPath(path)
        if self._joined:
            p.setClipPath(path)
            paint_band(p, r, self.delay)


def fade_in(widget: QWidget, duration: int = 260) -> None:
    """Bring a widget that has just been filled in from nothing (it need not be on screen yet: it starts clear, so it never flashes)."""
    if motion.on():
        motion._fade(widget, 0.0, 1.0, duration)


def busy(label: QLabel, on: bool, radius: float = 8.0) -> None:
    """Lay a shimmer over `label` while its picture is being fetched, and take it away again (the picture then shows through)."""
    cover: Shimmer | None = getattr(label, "_busy_cover", None)
    if on:
        if cover is None:
            cover = Shimmer(radius, 0.0, label)
            label._busy_cover = cover
        cover.setGeometry(label.rect())
        cover.raise_()
        cover.show()
    elif cover is not None:
        cover.hide()


class FetchStrip(QWidget):
    """A slim line that appears while a game's pictures are being fetched: what is being looked for, and a bar of how many of the pictures are
    in. It folds away when they all are."""

    stopRequested = Signal()  # the Stop button was pressed

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(4)
        self.text = QLabel()
        T.bind_css(self.text, lambda: f"color: {T.fg3.name()}; font-size: 12px; background: transparent;")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        T.bind_css(self.bar, lambda: (f"QProgressBar {{ background: {T.input.name()}; border: none; border-radius: 2px; }}"
                                       f"QProgressBar::chunk {{ background: {T.accent.name()}; border-radius: 2px; }}"))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.text)
        row.addStretch(1)
        self.stop = QPushButton("Stop")
        self.stop.setFlat(True)
        self.stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop.setToolTip("Stop looking for this game's pictures")
        T.bind_css(self.stop, lambda: (f"QPushButton {{ color: {T.fg3.name()}; font-size: 12px; border: none; background: transparent; padding: 0 2px; }}"
                                        f"QPushButton:hover {{ color: {T.title.name()}; }}"))
        self.stop.clicked.connect(self.stopRequested)
        row.addWidget(self.stop)
        lay.addLayout(row)
        lay.addWidget(self.bar)
        self.setVisible(False)

    def show_progress(self, done: int, total: int, text: str) -> None:
        """`done` of `total` pictures are in; `text` says what is still being looked for."""
        self.text.setText(text)
        self.bar.setMaximum(1000)
        motion.ease_value(self.bar, int(1000 * (done + 0.5) / max(1, total)) if done < total else 1000)
        motion.set_visible(self, True, axis="height")

    def finish(self) -> None:
        motion.set_visible(self, False, axis="height")
