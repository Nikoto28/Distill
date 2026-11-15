"""One album in Distill Resonance, laid out like a music player's album page: the cover, title and buttons on the
left, the track list on the right. A track shows its number until the pointer is over it, then a play button, a save
button and a checkbox."""
from __future__ import annotations

import weakref
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRectF, QSize, Qt, Signal, QVariantAnimation
from PySide6.QtGui import QBrush, QColor, QDrag, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import (QAbstractButton, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QToolButton,
                               QVBoxLayout, QWidget)

from . import icons, motion
from .theme import T
from .trackrow import PlayToggle
from .widgets import AnimCheckBox

COVER = 240  # the cover's side, in pixels
LEFT_W = 264  # the left column
ROW_H = 46  # a track row
FIRST_SHOWN = 60  # tracks drawn before 'Show all'
TILE_W = 176  # an album tile in a grid: the cover's side, which is also the tile's width
TILE_H = TILE_W + 78  # cover, then title, detail and facts
GRID_GAP = 22


@dataclass(slots=True)
class TrackInfo:
    number: str  # as shown in the first column
    title: str
    detail: str  # under the title: format and size
    checked: bool = False
    liked: bool = False
    duration: str = ""  # under the title, as m:ss (blank when the source doesn't say)


def clock(seconds: int | None) -> str:
    """A track's length as people read it: 3:45, or 1:02:09 for an hour or more. Blank for an unknown length."""
    if not seconds or seconds < 0:
        return ""
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


class Cover(QWidget):
    """The cover, cropped square with rounded corners and a hairline edge. A soft tile with a note stands in until it
    arrives. Drawn at the screen's pixel ratio, so it stays sharp at 125 / 150 / 200 % scaling."""

    def __init__(self, side: int = COVER):
        super().__init__()
        self._pix: QPixmap | None = None
        self._crop: tuple[tuple, QPixmap] | None = None  # (key, the cover cropped square at this size): a repaint doesn't rescale
        self.setFixedSize(side, side)

    def set_pixmap(self, pix: QPixmap | None) -> None:
        self._pix = pix
        self._crop = None
        self.update()

    def _cropped(self) -> QPixmap:
        dpr = self.devicePixelRatioF()
        side = max(int(round(self.width() * dpr)), 2)
        key = (self._pix.cacheKey(), side)
        if self._crop is None or self._crop[0] != key:
            scaled = self._pix.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                      Qt.TransformationMode.SmoothTransformation)
            crop = scaled.copy((scaled.width() - side) // 2, (scaled.height() - side) // 2, side, side)
            crop.setDevicePixelRatio(dpr)
            self._crop = (key, crop)
        return self._crop[1]

    def pixmap(self) -> QPixmap:
        """The cover as it is drawn (rounded corners, nothing laid over it), for a flight between two places."""
        dpr = self.devicePixelRatioF()
        pm = QPixmap(max(int(self.width() * dpr), 1), max(int(self.height() * dpr), 1))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        self._draw(p)
        p.end()
        return pm

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        self._draw(p)

    def _draw(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        radius = max(6.0, self.width() * 0.045)  # 11 px on the big cover, 6 on a thumbnail
        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)
        p.setClipPath(clip)
        if self._pix is None or self._pix.isNull():
            tile = QLinearGradient(0, 0, 0, rect.height())
            tile.setColorAt(0.0, T.hover)
            tile.setColorAt(1.0, T.card_border)
            p.fillRect(rect, QBrush(tile))
            glyph = max(int(self.width() * 0.34), 16)
            p.drawPixmap(int((self.width() - glyph) / 2), int((self.height() - glyph) / 2),
                         icons.pixmap("music", T.disabled_fg, glyph))
        else:
            p.drawPixmap(0, 0, self._cropped())
        p.setClipping(False)  # the hairline that keeps a dark cover from melting into the dark page
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 26) if T.dark else QColor(0, 0, 0, 30), 1))
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)


def _glide(owner: QWidget, name: str, goal: float, duration: int, apply) -> None:
    """Move the number `owner.<name>` to `goal` over `duration` ms, calling `apply(value)` on each step."""
    anim = getattr(owner, name + "_anim", None)
    if anim is None:
        anim = QVariantAnimation(owner)
        anim.valueChanged.connect(lambda v: apply(float(v)))
        setattr(owner, name + "_anim", anim)
    anim.stop()
    anim.setDuration(duration)
    anim.setStartValue(getattr(owner, name))
    anim.setEndValue(goal)
    anim.start()


# The play triangle and the pause bars, each as two four-cornered shapes (left, right) so one slides into the other. The
# triangle is cut at x = 2.5 (halfway along it); both are drawn about the button's centre with their corners rounded.
_TRI_HALF = (((-5.5, -9.5), (2.5, -4.75), (2.5, 4.75), (-5.5, 9.5)), ((2.5, -4.75), (10.5, 0.0), (10.5, 0.0), (2.5, 4.75)))
_BAR_HALF = (((-6.5, -8.5), (-1.5, -8.5), (-1.5, 8.5), (-6.5, 8.5)), ((1.5, -8.5), (6.5, -8.5), (6.5, 8.5), (1.5, 8.5)))


def _paint_play_glyph(p: QPainter, c: QPointF, k: float, morph: float, colour: QColor) -> None:
    """The glyph at `morph` 0 (play triangle) .. 1 (pause bars), centred on `c`, drawn for a 56 px button and scaled by `k`."""
    p.setBrush(colour)
    p.setPen(QPen(colour, 2.4 * k, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))  # soft corners
    for tri, bar in zip(_TRI_HALF, _BAR_HALF):
        pts = [QPointF(c.x() + (a[0] + (b[0] - a[0]) * morph) * k, c.y() + (a[1] + (b[1] - a[1]) * morph) * k)
               for a, b in zip(tri, bar)]
        path = QPainterPath(pts[0])
        for pt in pts[1:]:
            path.lineTo(pt)
        path.closeSubpath()
        p.drawPath(path)


class RoundPlay(QAbstractButton):
    """The big round play / pause button under the cover, in the brand gradient like every other primary action. The
    triangle and the pause bars slide into one another, and the whole button shrinks and darkens while it is held down."""

    SIZE = 56

    def __init__(self, side: int = SIZE):
        super().__init__()
        self._playing = False
        self._side = side
        self._morph = 0.0  # 0 = play triangle, 1 = pause bars
        self._down = 0.0  # 0..1, how far it is held down
        self.pressed.connect(lambda: _glide(self, "_down", 1.0, 90, self._set_down))
        self.released.connect(lambda: _glide(self, "_down", 0.0, 120, self._set_down))
        self.setFixedSize(side, side)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _set_down(self, v: float) -> None:
        self._down = v
        self.update()

    def _set_morph(self, v: float) -> None:
        self._morph = v
        self.update()

    def set_playing(self, on: bool) -> None:
        if on == self._playing:
            return
        self._playing = on
        goal = 1.0 if on else 0.0
        if motion.on() and self.isVisible():
            _glide(self, "_morph", goal, 170, self._set_morph)
        else:
            self._set_morph(goal)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        on = self.isEnabled()  # (a disabled button must not look ready: the album is still loading its tracks)
        c = QPointF(self.rect().center()) + QPointF(0.5, 0.5)  # the middle of the pixel grid, so the glyph isn't half a pixel off
        p.translate(c)
        shrink = 1.0 - 0.08 * self._down  # held down: a little smaller
        p.scale(shrink, shrink)
        p.translate(-c)
        if on:
            lift = 100 + (14 if self.underMouse() else 0) - round(16 * self._down)
            fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
            for stop, col in zip((0.0, 0.5, 1.0), T.grad):
                fill.setColorAt(stop, QColor(col).lighter(lift))
            p.setBrush(QBrush(fill))
        else:
            p.setBrush(T.grad_off)
        p.drawEllipse(rect)
        _paint_play_glyph(p, c, self._side / self.SIZE, self._morph, QColor("#ffffff") if on else QColor(T.disabled_fg))


SCRIM = (10, 12, 18)  # the dark the buttons on a cover are made of: slightly see-through, a little less so under the pointer
SCRIM_ALPHA, SCRIM_ALPHA_HOVER = 150, 205


class TilePlay(QAbstractButton):
    """The play button on an album's cover in a grid: a small round button in the bottom-left corner, the same size and
    the same slightly see-through dark as the more button in the top right, with a rounded play symbol on it. (The big
    gradient button is for the album's own page.)"""

    SIDE = 30

    def __init__(self):
        super().__init__()
        self._down = 0.0
        self.pressed.connect(lambda: _glide(self, "_down", 1.0, 90, self._set_down))
        self.released.connect(lambda: _glide(self, "_down", 0.0, 120, self._set_down))
        self.setFixedSize(self.SIDE, self.SIDE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _set_down(self, v: float) -> None:
        self._down = v
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.SIDE / 2, self.SIDE / 2)
        k = 1.0 - 0.08 * self._down
        p.translate(c)
        p.scale(k, k)
        p.translate(-c)
        alpha = SCRIM_ALPHA_HOVER if self.underMouse() else SCRIM_ALPHA
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(*SCRIM, alpha))
        p.drawEllipse(QRectF(self.rect()))
        p.setBrush(QColor("#ffffff"))
        p.setPen(QPen(QColor("#ffffff"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        tri = QPainterPath(QPointF(c.x() - 3.2, c.y() - 5.0))  # (nudged right of the middle so it looks centred)
        tri.lineTo(QPointF(c.x() + 5.0, c.y()))
        tri.lineTo(QPointF(c.x() - 3.2, c.y() + 5.0))
        tri.closeSubpath()
        p.drawPath(tri)


class IconButton(QToolButton):
    """A round tool button drawn with one of the app's line icons (see icons.py), so it is as sharp as the rest of the
    app and takes the theme's colours. `tone`: soft (grey, white under the pointer), accent, or pink (a liked heart).
    `filled` gives it a resting fill, for the buttons under a cover."""

    def __init__(self, name: str, tip: str, side: int = 30, glyph: int = 18, tone: str = "soft", filled: bool = False,
                 scrim: bool = False):
        super().__init__()
        self._name, self._tone, self._glyph, self._filled, self._scrim = name, tone, glyph, filled, scrim
        self.setToolTip(tip)
        self.setAccessibleName(tip)
        self.setFixedSize(side, side)
        self.setIconSize(QSize(glyph, glyph))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        ref = weakref.ref(self)  # (so the theme's list of restyling widgets doesn't keep a deleted button alive)
        T.bind(self, lambda: ref() is not None and ref()._apply())

    def set_icon(self, name: str | None = None, tone: str | None = None) -> None:
        self._name = name or self._name
        self._tone = tone or self._tone
        self._apply()

    def _apply(self) -> None:
        colour = {"accent": T.accent_text, "pink": T.group_dl}.get(self._tone, T.fg2)
        hover = {"accent": T.accent_text, "pink": T.group_dl}.get(self._tone, T.title)
        rest = T.btn[0].name() if self._filled else "transparent"
        over = T.btn_hover[0].name() if self._filled else T.hover.name()
        if self._scrim:  # on a cover: white on the dark, slightly see-through scrim (as TilePlay)
            colour = hover = QColor("#ffffff")
            rest, over = f"rgba({SCRIM[0]}, {SCRIM[1]}, {SCRIM[2]}, {SCRIM_ALPHA})", f"rgba({SCRIM[0]}, {SCRIM[1]}, {SCRIM[2]}, {SCRIM_ALPHA_HOVER})"
        self.setIcon(icons.button_icon(self._name, colour, hover, self._glyph))
        self.setStyleSheet(f"QToolButton {{ background: {rest}; border: none; border-radius: {self.width() // 2}px; }} "
                           f"QToolButton:hover {{ background: {over}; }} "
                           f"QToolButton:disabled {{ background: transparent; }} "
                           f"QToolButton::menu-indicator {{ image: none; }}")


class EmptyState(QWidget):
    """What a list says when it has nothing in it: a soft icon, a headline and a line of help, centred.
    `setText("Headline\nA sentence of help.")`: the first line is the headline, the rest is the help. Empty text shows
    nothing (the owner decides when the whole thing is shown)."""

    def __init__(self, icon: str = "music", text: str = ""):
        super().__init__()
        self._icon, self._text = icon, ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(48, 56, 48, 40)
        lay.setSpacing(6)
        self._glyph, self._head, self._body = QLabel(), QLabel(), QLabel()
        for label in (self._glyph, self._head, self._body):
            label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            lay.addWidget(label)
        self._glyph.setFixedHeight(52)
        for label in (self._head, self._body):
            label.setWordWrap(True)
        ref = weakref.ref(self)
        T.bind(self, lambda: ref() is not None and ref()._style())
        self.setText(text)

    def _style(self) -> None:
        self._glyph.setPixmap(icons.pixmap(self._icon, T.disabled_fg, 40))
        self._head.setStyleSheet(f"color: {T.title.name()}; font-size: 13pt; font-weight: 600;")
        self._body.setStyleSheet(f"color: {T.fg3.name()};")

    def set_icon(self, name: str) -> None:
        self._icon = name
        self._style()

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        self._text = text
        head, _, body = text.partition("\n")
        self._head.setText(head)
        self._body.setText(body.strip())
        self._glyph.setVisible(bool(text))
        self._head.setVisible(bool(head))
        self._body.setVisible(bool(body.strip()))


class TrackLine(QWidget):
    """[number | play]  title / length ...... format and size ...... [like] [save] [select]. A click anywhere on the row plays it."""

    FACTS_W = 150  # the width kept for 'MP3  ·  4.2 MB', which sits in the middle of the row

    play = Signal()
    save = Signal()
    ticked = Signal(bool)
    like = Signal()
    menu = Signal(object)  # a QPoint, global

    def __init__(self, info: TrackInfo, can_play: bool):
        super().__init__()
        self._current = False
        self._hover = False
        self._liked = info.liked
        self.setFixedHeight(ROW_H)
        self.setMouseTracking(True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 10, 0)
        lay.setSpacing(10)
        self.index = QLabel(info.number)
        self.index.setFixedWidth(32)
        self.index.setAlignment(Qt.AlignmentFlag.AlignCenter)
        T.bind_css(self.index, lambda: f"color: {T.fg3.name()};")
        self.index.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.playbtn = PlayToggle() if can_play else None
        if self.playbtn is not None:
            self.playbtn.setToolTip("Play this track")
        cell = QWidget()
        cell.setFixedSize(32, 24)
        cl = QHBoxLayout(cell)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.index)
        if self.playbtn is not None:
            self.playbtn.setParent(cell)
            self.playbtn.move(5, 1)
            self.playbtn.hide()
            self.playbtn.clicked.connect(self.play)
        lay.addWidget(cell)
        text = QVBoxLayout()
        text.setSpacing(0)
        text.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel(info.title)
        self.title.setToolTip(info.title)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.sub = QLabel(info.duration)  # under the title: how long the track is
        if not info.duration:
            self.sub.hide()  # (hide, not setVisible: a label with no parent yet would open as a window of its own)
        self.sub.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.sub.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        T.bind_css(self.sub, lambda: f"color: {T.fg3.name()}; font-size: 9pt;")
        self._style_title()
        text.addStretch(1)
        text.addWidget(self.title)
        text.addWidget(self.sub)
        text.addStretch(1)
        lay.addLayout(text, 1)
        self._title_text, self._sub_text = info.title, info.duration
        self.facts = QLabel(info.detail, self)  # format and size, in the middle of the row (placed in resizeEvent)
        self.facts.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.facts.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        T.bind_css(self.facts, lambda: f"color: {T.fg3.name()}; font-size: 9pt;")
        self._facts_text = info.detail
        self._pressed = False
        self.heart = IconButton("heart", "Add to your favourites", 30, 17)
        self.heart.clicked.connect(self.like)
        lay.addWidget(self.heart)
        self.savebtn = IconButton("download", "Save this track", 30, 17)
        self.savebtn.clicked.connect(self.save)
        lay.addWidget(self.savebtn)
        self._style_heart()
        self.check = AnimCheckBox("")
        self.check.setToolTip("Select this track to save it with 'Save selected'")
        self.check.setChecked(info.checked)
        self.check.toggled.connect(self.ticked)
        self.check.toggled.connect(lambda _on: self._show_hover())
        lay.addWidget(self.check)
        for w in (self.heart, self.savebtn, self.check):  # these appear under the pointer: their room stays, so the title
            policy = w.sizePolicy()                       # keeps the same width (and its '...') and nothing jumps
            policy.setRetainSizeWhenHidden(True)
            w.setSizePolicy(policy)
        self._show_hover()

    # ---- look -----------------------------------------------------------------------------------
    def _style_title(self) -> None:
        on = self._current
        T.bind_css(self.title, lambda: f"color: {T.accent_text.name() if on else T.title.name()}; "
                                       f"font-weight: {600 if on else 500};")

    def _style_heart(self) -> None:
        liked = self._liked
        self.heart.set_icon("heart-filled" if liked else "heart", "pink" if liked else "soft")
        self.heart.setToolTip("Liked. Click to remove it from your favourites." if liked else "Add to your favourites")
        self.heart.setAccessibleName(self.heart.toolTip())

    def set_liked(self, on: bool) -> None:
        self._liked = on
        self._style_heart()
        self._show_hover()

    def _show_hover(self) -> None:
        show = self._hover or self._current
        self.heart.setVisible(self._hover or self._liked)
        if self.playbtn is not None:
            self.playbtn.setVisible(show)
            self.index.setVisible(not show)
        self.savebtn.setVisible(self._hover)
        self.check.setVisible(self._hover or self.check.isChecked())

    def set_current(self, on: bool, playing: bool = False) -> None:
        if on != self._current:
            self._current = on
            self._style_title()
            self._show_hover()
            self.update()
        if self.playbtn is not None:
            self.playbtn.set_state(on, playing)

    def set_checked(self, on: bool) -> None:
        self.check.blockSignals(True)
        self.check.setChecked(on)
        self.check._t = 1.0 if on else 0.0
        self.check.blockSignals(False)
        self.check.update()
        self._show_hover()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        fw = min(self.FACTS_W, max(self.width() // 3, 0))
        left = (self.width() - fw) // 2
        self.facts.setGeometry(left, 0, fw, self.height())
        fits = bool(self._facts_text) and fw >= 90 and left + fw + 8 <= self.heart.x()  # (the buttons keep their room even when hidden)
        self.facts.setVisible(fits)
        self.facts.setText(self.facts.fontMetrics().elidedText(self._facts_text, Qt.TextElideMode.ElideRight, fw))
        room = max(min(self.title.width(), (left - self.title.x() - 10) if fits else self.title.width()), 40)
        self.title.setText(self.title.fontMetrics().elidedText(self._title_text, Qt.TextElideMode.ElideRight, room))
        self.sub.setText(self.sub.fontMetrics().elidedText(self._sub_text, Qt.TextElideMode.ElideRight, room))

    def enterEvent(self, event) -> None:
        self._hover = True
        self._show_hover()
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self._show_hover()
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        self._pressed = event.button() == Qt.MouseButton.LeftButton
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        """Clicking the track (its name, or anywhere on the row that is not a button) plays it, as its play button does."""
        hit = (self._pressed and event.button() == Qt.MouseButton.LeftButton and self.playbtn is not None
               and self.rect().contains(event.position().toPoint()))
        self._pressed = False
        super().mouseReleaseEvent(event)
        if hit:
            self.play.emit()

    def contextMenuEvent(self, event) -> None:
        self.menu.emit(event.globalPos())

    def paintEvent(self, _event) -> None:
        if not (self._hover or self._current):
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        if self._current:
            wash = QLinearGradient(0, 0, self.width(), 0)
            start, end = T.wash(60, 18)
            wash.setColorAt(0.0, start)
            wash.setColorAt(1.0, end)
            p.setBrush(wash)
        else:
            p.setBrush(QBrush(T.hover))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0, 1, 0, -1), 8, 8)


class AlbumView(QWidget):
    """The whole block for one album."""

    playAlbum = Signal()
    saveAlbum = Signal()
    playTrack = Signal(int)
    saveTrack = Signal(int)
    trackMenu = Signal(int, object)
    tickChanged = Signal()
    favouriteToggled = Signal(int)
    moreMenu = Signal(object)  # the more button, for the owner to pop a menu from
    libraryToggled = Signal()

    def __init__(self, can_play: bool, first_shown: int = FIRST_SHOWN):
        super().__init__()
        self._can_play = can_play
        self._first_shown = first_shown  # tracks drawn before 'Show all'
        self._lines: list[TrackLine] = []
        self._infos: list[TrackInfo] = []
        self._shown_all = False
        root = QHBoxLayout(self)
        root.setContentsMargins(4, 14, 4, 14)
        root.setSpacing(28)

        left = QWidget()
        left.setFixedWidth(LEFT_W)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(4)
        self.cover = Cover()
        ll.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignHCenter)
        ll.addSpacing(12)
        self.title = QLabel("")
        self.title.setWordWrap(True)
        self.title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        T.bind_css(self.title, lambda: f"color: {T.title.name()}; font-size: 15pt; font-weight: 700;")
        ll.addWidget(self.title)
        self.subtitle = QLabel("")
        self.subtitle.setWordWrap(True)
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        T.bind_css(self.subtitle, lambda: f"color: {T.fg2.name()};")
        ll.addWidget(self.subtitle)
        self.meta = QLabel("")  # the facts: songs, length, size (wraps rather than running off the column)
        self.meta.setWordWrap(True)
        self.meta.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        T.bind_css(self.meta, lambda: f"color: {T.fg3.name()};")
        ll.addWidget(self.meta)
        self.source = QLabel("")  # where the album comes from, as a chip of its own (KHInsider, archive.org, On this computer)
        self.source.setObjectName("chip")
        self.source.setToolTip("Where this album comes from")
        self.source.hide()  # (hide, not setVisible: a label with no parent yet would open as a window of its own)
        chip_row = self._source_row = QHBoxLayout()
        self._source_chip: QWidget | None = None  # the credit chip of a source that has one (KHInsider, archive.org)
        chip_row.setContentsMargins(0, 6, 0, 0)
        chip_row.addStretch(1)
        chip_row.addWidget(self.source)
        chip_row.addStretch(1)
        ll.addLayout(chip_row)
        ll.addSpacing(10)
        buttons = QHBoxLayout()
        buttons.setSpacing(14)
        buttons.addStretch(1)
        self.lib_btn = IconButton("star-outline", "Add to your library (stream it later without downloading)", 40, 20,
                                  filled=True)
        self.lib_btn.clicked.connect(self.libraryToggled)
        self.save_btn = IconButton("download", "Save this album", 40, 20, filled=True)
        self.save_btn.clicked.connect(self.saveAlbum)
        self.play_btn = RoundPlay()
        self.play_btn.clicked.connect(self.playAlbum)
        self.more_btn = IconButton("more", "More", 40, 20, filled=True)
        self.more_btn.clicked.connect(lambda: self.moreMenu.emit(self.more_btn))
        for b in (self.lib_btn, self.save_btn, self.play_btn, self.more_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)
        ll.addLayout(buttons)
        self.status = QLabel("")
        self.status.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.status.setWordWrap(True)
        ll.addWidget(self.status)
        ll.addStretch(1)
        # The left column is not in the layout: a blank of its width holds its place, and the column itself is moved down
        # as the page scrolls, so the cover stays in the top left while the tracks go by (see _place_left).
        self._left = left
        self._scroll: QScrollArea | None = None
        left.setParent(self)
        left.installEventFilter(self)
        gap = QWidget()
        gap.setFixedWidth(LEFT_W)
        root.addWidget(gap, 0, Qt.AlignmentFlag.AlignTop)

        right = QWidget()
        self._right = QVBoxLayout(right)
        self._right.setContentsMargins(0, 0, 0, 0)
        self._right.setSpacing(0)
        self.note = QLabel("Loading tracks...")
        T.bind_css(self.note, lambda: f"color: {T.fg3.name()};")
        self._right.addWidget(self.note)
        self._list = QVBoxLayout()
        self._list.setSpacing(0)
        self._right.addLayout(self._list)
        self.more_tracks = QPushButton("")
        self.more_tracks.setFlat(True)  # a quiet text link under the list, not a heavy button
        self.more_tracks.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more_tracks.setVisible(False)
        self.more_tracks.clicked.connect(self._show_all)
        self._right.addWidget(self.more_tracks, 0, Qt.AlignmentFlag.AlignLeft)
        self._right.addStretch(1)
        root.addWidget(right, 1)
        self.set_busy(True)

    # ---- the left column stays put while the tracks scroll ---------------------------------------
    def _left_height(self) -> int:
        lay = self._left.layout()
        tall = lay.totalHeightForWidth(LEFT_W) if lay.hasHeightForWidth() else lay.totalSizeHint().height()
        return max(tall, lay.totalMinimumSize().height())

    def _find_scroll(self) -> None:
        w = self.parentWidget()
        while w is not None and not isinstance(w, QScrollArea):
            w = w.parentWidget()
        if w is not None and w is not self._scroll:
            self._scroll = w
            w.verticalScrollBar().valueChanged.connect(self._place_left)

    def _place_left(self, *_args) -> None:
        top, h = 14, self._left_height()
        y = top
        area = self._scroll
        if area is not None and area.widget() is not None:
            above = area.verticalScrollBar().value() - self.mapTo(area.widget(), QPoint(0, 0)).y()  # how far this album's top is above the window's
            y = min(max(top, above + 10), max(top, self.height() - h - 14))
        self._left.setGeometry(4, y, LEFT_W, h)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._find_scroll()
        self._place_left()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_left()

    def eventFilter(self, obj, event) -> bool:
        if obj is self._left and event.type() == QEvent.Type.LayoutRequest:  # its title wrapped, or a status line came
            self.updateGeometry()
            self._place_left()
        return super().eventFilter(obj, event)

    # ---- content --------------------------------------------------------------------------------
    def set_info(self, title: str, subtitle: str, meta: str, source: str = "") -> None:
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.subtitle.setVisible(bool(subtitle))
        self.meta.setText(meta)
        self.meta.setVisible(bool(meta))
        self.source.setText(source)
        self.source.setVisible(bool(source))

    def set_source(self, provider: str) -> None:
        """Credit the album's source with a clickable chip under its details (none for files on this computer: those keep the plain label)."""
        from .sourcechips import source_chip
        if self._source_chip is not None:
            self._source_chip.setParent(None)
            self._source_chip.deleteLater()
            self._source_chip = None
        chip = source_chip(provider)
        if chip is not None:
            self._source_row.insertWidget(1, chip)
            self._source_chip = chip

    def set_cover(self, pix: QPixmap | None) -> None:
        self.cover.set_pixmap(pix)

    def set_in_library(self, on: bool) -> None:
        tip = "In your library. Click to remove it." if on else "Add to your library (stream it later without downloading)"
        self.lib_btn.set_icon("star" if on else "star-outline", "accent" if on else "soft")
        self.lib_btn.setToolTip(tip)
        self.lib_btn.setAccessibleName(tip)

    def set_busy(self, busy: bool) -> None:
        for b in (self.save_btn, self.play_btn):
            b.setEnabled(not busy)

    def set_note(self, text: str) -> None:
        self.note.setText(text)
        self.note.setVisible(bool(text))

    def set_status(self, text: str, kind: str = "") -> None:
        colour = {"ok": lambda: T.ok, "warn": lambda: T.warn, "bad": lambda: T.bad}.get(kind, lambda: T.fg3)
        T.bind_css(self.status, lambda: f"color: {colour().name()};")
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def set_tracks(self, infos: list[TrackInfo]) -> None:
        self.clear_tracks()
        self._infos = infos
        self._shown_all = len(infos) <= self._first_shown
        self.set_note("" if infos else "No tracks found.")
        for i, info in enumerate(infos if self._shown_all else infos[:self._first_shown]):
            self._add_line(i, info)
        self._update_more()
        self.set_busy(not infos)

    def _add_line(self, i: int, info: TrackInfo) -> None:
        line = TrackLine(info, self._can_play)
        line.play.connect(lambda i=i: self.playTrack.emit(i))
        line.save.connect(lambda i=i: self.saveTrack.emit(i))
        line.menu.connect(lambda pos, i=i: self.trackMenu.emit(i, pos))
        line.ticked.connect(lambda on, i=i: self._ticked(i, on))
        line.like.connect(lambda i=i: self.favouriteToggled.emit(i))
        self._lines.append(line)
        self._list.addWidget(line)

    def _ticked(self, i: int, on: bool) -> None:
        self._infos[i].checked = on
        self.tickChanged.emit()

    def _update_more(self) -> None:
        hidden = len(self._infos) - len(self._lines)
        self.more_tracks.setVisible(hidden > 0)
        self.more_tracks.setText(f"Show all {len(self._infos)} tracks")

    def _show_all(self) -> None:
        for i in range(len(self._lines), len(self._infos)):
            self._add_line(i, self._infos[i])
        self._shown_all = True
        self._update_more()

    def clear_tracks(self) -> None:
        for line in self._lines:
            line.setParent(None)
            line.deleteLater()
        self._lines, self._infos = [], []
        self.more_tracks.setVisible(False)

    # ---- state ----------------------------------------------------------------------------------
    def set_liked(self, index: int, on: bool) -> None:
        if 0 <= index < len(self._infos):
            self._infos[index].liked = on
        if 0 <= index < len(self._lines):
            self._lines[index].set_liked(on)

    def checked_indices(self) -> list[int]:
        return [i for i, info in enumerate(self._infos) if info.checked]

    def set_all_checked(self, on: bool) -> None:
        for info in self._infos:
            info.checked = on
        for line in self._lines:
            line.set_checked(on)
        self.tickChanged.emit()

    def set_playing(self, index: int | None, playing: bool, album_playing: bool) -> None:
        """`index`: the track of this album that is playing or paused (None: none of them)."""
        for i, line in enumerate(self._lines):
            line.set_current(i == index, playing)
        self.play_btn.set_playing(album_playing and playing)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        hint.setHeight(max(hint.height(), COVER + 190, self._left_height() + 28))
        return hint

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        hint.setHeight(max(hint.height(), self._left_height() + 28))
        return hint


class AlbumTile(QWidget):
    """One album in a grid, as a music app shows it: the cover, then title, a line of detail and a line of facts. Click it
    to open the album. Under the pointer a play button and a more button appear on the cover."""

    opened = Signal()
    played = Signal()
    moreClicked = Signal(object)  # the widget to pop the album's menu from

    def __init__(self, title: str, sub: str = "", meta: str = "", art: str = "", can_play: bool = True):
        super().__init__()
        self.art = art
        self._title, self._sub, self._meta = title, sub, meta
        self._meta_lit = False  # the facts line in the accent colour (a status), not the muted one
        self.setFixedSize(TILE_W, TILE_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.cover = Cover(TILE_W)
        lay.addWidget(self.cover)
        lay.addSpacing(8)
        self.title, self.sub, self.meta = QLabel(), QLabel(), QLabel()
        for label in (self.title, self.sub, self.meta):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)  # a click anywhere on the tile opens it
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            lay.addWidget(label)
        lay.addStretch(1)
        # on the cover: a star when the album is kept, and (under the pointer) play and more
        self.star = QLabel(self.cover)
        self.star.setFixedSize(24, 24)
        self.star.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.star.move(8, 8)
        self.star.hide()
        self.star.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.badge = self.meta  # (the facts line is where a library tile says 'Saved on disk' / 'Streaming')
        self.play_btn = TilePlay() if can_play else None
        if self.play_btn is not None:
            self.play_btn.setParent(self.cover)
            self.play_btn.move(8, TILE_W - TilePlay.SIDE - 8)  # bottom left, as far in as the more button is from the top right
            self.play_btn.setToolTip("Play this album")
            self.play_btn.clicked.connect(self.played)
            self.play_btn.hide()
        self.more_btn = IconButton("more", "More", 30, 18, filled=True, scrim=True)
        self.more_btn.setParent(self.cover)
        self.more_btn.move(TILE_W - 30 - 8, 8)
        self.more_btn.clicked.connect(lambda: self.moreClicked.emit(self.more_btn))
        self.more_btn.hide()
        ref = weakref.ref(self)
        T.bind(self, lambda: ref() is not None and ref()._style())
        self._fill()

    def _style(self) -> None:
        self.title.setStyleSheet(f"color: {T.title.name()}; font-weight: 600;")
        self.sub.setStyleSheet(f"color: {T.fg2.name()}; font-size: 9pt;")
        self.meta.setStyleSheet(f"color: {(T.accent_text if self._meta_lit else T.fg3).name()}; font-size: 9pt;")
        self.star.setPixmap(icons.pixmap("star", T.accent_text, 14))
        self.star.setStyleSheet("background: rgba(10, 12, 18, 170); border-radius: 12px;")

    def _fill(self) -> None:
        for label, text in ((self.title, self._title), (self.sub, self._sub), (self.meta, self._meta)):
            label.setText(label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, TILE_W - 4))
            label.setVisible(bool(text))
        self.title.setToolTip(self._title)

    def set_cover(self, pix: QPixmap | None) -> None:
        self.cover.set_pixmap(pix)

    def set_meta(self, text: str, lit: bool = False) -> None:
        self._meta, self._meta_lit = text, lit
        self._style()
        self._fill()

    def set_badge(self, on: bool) -> None:
        """The star on the cover: this album is kept in the library."""
        self.star.setVisible(on)

    def _hover(self, on: bool) -> None:
        for b in (self.play_btn, self.more_btn):
            if b is not None:
                b.setVisible(on)

    def enterEvent(self, event) -> None:
        self._hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover(False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.opened.emit()
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:
        self.moreClicked.emit(self)


class AlbumGrid(QWidget):
    """Album tiles in rows that reflow with the width, like a music app's shelf. The tiles are placed by hand rather than
    by a layout: a layout would hold the page at the width of its widest row and never let it narrow again."""

    def __init__(self):
        super().__init__()
        self._tiles: list[AlbumTile] = []
        self.setMinimumWidth(0)
        self.setFixedHeight(0)

    def tiles(self) -> list[AlbumTile]:
        return list(self._tiles)

    def add_tile(self, tile: AlbumTile) -> None:
        tile.setParent(self)
        self._tiles.append(tile)
        tile.show()
        self._flow()

    def clear(self) -> None:
        for tile in self._tiles:
            tile.setParent(None)
            tile.deleteLater()
        self._tiles = []
        self._flow()

    def columns(self) -> int:
        return max(1, (self.width() + GRID_GAP) // (TILE_W + GRID_GAP))

    def reflow(self) -> None:
        self._flow()

    def _flow(self) -> None:
        cols = self.columns()
        shown = [t for t in self._tiles if not t.isHidden()]  # (a removed album's tile is hidden and leaves no gap)
        for i, tile in enumerate(shown):
            row, col = divmod(i, cols)
            tile.move(col * (TILE_W + GRID_GAP), row * (TILE_H + GRID_GAP))
        rows = -(-len(shown) // cols)
        self.setFixedHeight(rows * TILE_H + (rows - 1) * GRID_GAP + 16 if rows else 0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._flow()


QUEUE_MIME = "application/x-distill-queue-item"


class QueueRow(QWidget):
    """One track in a list: title, album, and play / move / remove. A row that is `movable` can also be dragged."""

    playClicked = Signal()
    upClicked = Signal()
    downClicked = Signal()
    removeClicked = Signal()

    def __init__(self, title: str, album: str, current: bool, can_move: bool, can_remove: bool,
                 item_index: int = -1, movable: bool = False, art: QPixmap | None = None, art_url: str = ""):
        super().__init__()
        self.art = art_url  # the cover's address, so the page can fill it in when it arrives
        self.item_index = item_index
        self.movable = movable
        self._press: QPointF | None = None
        self._current = current
        self._hover = False
        self.setFixedHeight(54)
        self.setMouseTracking(True)
        self.setToolTip("Drag to reorder" if movable else "")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(6)
        if movable:
            grip = QLabel()  # a handle to grab
            grip.setFixedWidth(16)
            grip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ref = weakref.ref(grip)
            T.bind(grip, lambda: ref() is not None and ref().setPixmap(icons.pixmap("grip", T.fg3, 14)))
            grip.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            lay.addWidget(grip)
        self.cover = Cover(38)
        self.cover.set_pixmap(art)
        lay.addWidget(self.cover)
        lay.addSpacing(4)
        text = QVBoxLayout()
        text.setSpacing(0)
        text.addStretch(1)
        t = QLabel(title)
        T.bind_css(t, lambda: f"color: {(T.accent_text if current else T.title).name()}; font-weight: {600 if current else 500};")
        a = QLabel(album)
        T.bind_css(a, lambda: f"color: {T.fg3.name()}; font-size: 9pt;")
        for label in (t, a):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        text.addWidget(t)
        text.addWidget(a)
        text.addStretch(1)
        lay.addLayout(text, 1)
        for name, tip, signal, enabled in (("play", "Play this now", self.playClicked, True),
                                           ("arrow-up", "Move up", self.upClicked, can_move),
                                           ("arrow-down", "Move down", self.downClicked, can_move),
                                           ("close", "Remove", self.removeClicked, can_remove)):
            b = IconButton(name, tip, 28, 15)
            b.setEnabled(enabled)
            b.clicked.connect(signal)
            lay.addWidget(b)

    def set_cover(self, pix: QPixmap | None) -> None:
        self.cover.set_pixmap(pix)

    def mouseDoubleClickEvent(self, event) -> None:
        self.playClicked.emit()

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        if not (self._hover or self._current):
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        if self._current:  # the same wash as the playing track in an album
            wash = QLinearGradient(0, 0, self.width(), 0)
            start, end = T.wash(60, 18)
            wash.setColorAt(0.0, start)
            wash.setColorAt(1.0, end)
            p.setBrush(QBrush(wash))
        else:
            p.setBrush(QBrush(T.hover))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0, 1, 0, -1), 8, 8)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (self.movable and self._press is not None and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position() - self._press).manhattanLength() >= QApplication.startDragDistance()):
            self._press = None
            mime = QMimeData()
            mime.setData(QUEUE_MIME, str(self.item_index).encode())
            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.setPixmap(self.grab())
            drag.setHotSpot(event.position().toPoint())
            drag.exec(Qt.DropAction.MoveAction)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._press = None
        super().mouseReleaseEvent(event)


class QueueBody(QWidget):
    """The scrolling body of the queue: takes a dragged row and says where among the movable rows it was dropped."""

    dropped = Signal(int, int)  # the item's index, and its new slot among the movable rows (0 = first)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self._line: int | None = None

    def _movable_rows(self) -> list[QueueRow]:
        return sorted((r for r in self.findChildren(QueueRow) if r.movable and r.isVisible()), key=lambda r: r.y())

    def _slot_at(self, y: float) -> int:
        return sum(1 for r in self._movable_rows() if r.y() + r.height() / 2 < y)

    def _line_y(self, slot: int) -> int | None:
        rows = self._movable_rows()
        if not rows:
            return None
        return rows[slot].y() if slot < len(rows) else rows[-1].y() + rows[-1].height()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(QUEUE_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(QUEUE_MIME):
            self._line = self._line_y(self._slot_at(event.position().y()))
            self.update()
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._line = None
        self.update()

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasFormat(QUEUE_MIME):
            return
        slot = self._slot_at(event.position().y())
        index = int(bytes(event.mimeData().data(QUEUE_MIME)).decode())
        self._line = None
        self.update()
        event.acceptProposedAction()
        self.dropped.emit(index, slot)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._line is not None:
            p = QPainter(self)
            p.setPen(QPen(T.accent, 2))
            p.drawLine(8, self._line, self.width() - 8, self._line)


class HomeStrip(QWidget):
    """A titled row of album tiles that scrolls sideways, with a 'See all' button when there is more to see."""

    opened = Signal(object)  # the album
    played = Signal(object)
    moreClicked = Signal(object, object)  # (the widget to pop the menu from, the album)
    seeAll = Signal()

    def __init__(self, title: str, can_see_all: bool = False, can_play: bool = True):
        super().__init__()
        self._tiles: list[AlbumTile] = []
        self._can_play = can_play
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 4)
        lay.setSpacing(4)
        head = QHBoxLayout()
        self.title = QLabel(title)
        T.bind_css(self.title, lambda: f"color: {T.title.name()}; font-size: 13pt; font-weight: 700;")
        head.addWidget(self.title)
        head.addStretch(1)
        self.all_btn = QPushButton("See all")
        self.all_btn.setVisible(False)
        self.all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.all_btn.clicked.connect(self.seeAll)
        self._can_see_all = can_see_all
        head.addWidget(self.all_btn)
        lay.addLayout(head)
        self.note = QLabel("Loading...")
        T.bind_css(self.note, lambda: f"color: {T.fg3.name()};")
        lay.addWidget(self.note)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFixedHeight(TILE_H + 24)  # the tiles, and the sideways scroll bar under them
        self.scroll.setVisible(False)
        body = QWidget()
        self._row = QHBoxLayout(body)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(GRID_GAP)
        self._row.addStretch(1)
        self.scroll.setWidget(body)
        lay.addWidget(self.scroll)

    def set_message(self, text: str) -> None:
        self.note.setText(text)
        self.note.setVisible(bool(text))
        self.scroll.setVisible(False)

    def set_albums(self, albums: list, subtitle=lambda a: "", meta=lambda a: "") -> None:
        for tile in self._tiles:
            tile.setParent(None)
            tile.deleteLater()
        self._tiles = []
        if not albums:
            self.set_message("Nothing here yet.")
            return
        self.note.setVisible(False)
        self.scroll.setVisible(True)
        self.all_btn.setVisible(self._can_see_all)
        for i, album in enumerate(albums):
            tile = AlbumTile(album.title, subtitle(album), meta(album), album.art, self._can_play)
            tile.opened.connect(lambda a=album: self.opened.emit(a))
            tile.played.connect(lambda a=album: self.played.emit(a))
            tile.moreClicked.connect(lambda w, a=album: self.moreClicked.emit(w, a))
            self._row.insertWidget(i, tile)
            self._tiles.append(tile)

    def tiles(self) -> list[AlbumTile]:
        return list(self._tiles)
