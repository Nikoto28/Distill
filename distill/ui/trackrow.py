"""One track in the Distill Resonance list: a checkbox (save this track?), a play button that morphs between a triangle
and a square, and the title. The track that is playing is highlighted."""
from __future__ import annotations

import math

from PySide6.QtCore import QAbstractAnimation, QPointF, QRectF, QSize, Qt, QTimer, Signal, QVariantAnimation
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLayout, QSizePolicy, QWidget

from . import motion
from .theme import T
from .widgets import AnimCheckBox

class PlayToggle(QAbstractButton):
    """The play button of a track. Three faces that cross-fade into one another: a play triangle (the track is not the
    current one), a little musical note that sways while it plays (it is the current track), and a pause symbol (shown
    instead of the note while the pointer is over it). While the current track is paused the note holds still, and the
    pointer brings back the play triangle. It shrinks a little while it is held down, like the app's other buttons."""

    SIZE = 22
    FACES = 3  # play, pause, note

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._current, self._playing = False, False
        self._alpha = [1.0, 0.0, 0.0]  # how much of each face is showing now
        self._from = list(self._alpha)
        self._goal = list(self._alpha)
        self._anim = QVariantAnimation(self, duration=150, startValue=0.0, endValue=1.0)
        self._anim.valueChanged.connect(self._blend)
        self._press = 0.0  # 0..1: how far down it is held
        self._press_anim = QVariantAnimation(self, duration=90)
        self._press_anim.valueChanged.connect(self._set_press)
        self.pressed.connect(lambda: self._to_press(1.0))
        self.released.connect(lambda: self._to_press(0.0))
        self._phase = 0.0  # the note's sway
        self._sway_clock = motion.FrameClock()
        self._sway = motion.frame_timer(self)  # a precise timer at the screen's refresh rate, moving by the time that passed
        self._sway.timeout.connect(self._step_sway)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Play this track")

    # ---- state ----------------------------------------------------------------------------------
    @property
    def playing(self) -> bool:
        return self._current and self._playing

    def set_state(self, current: bool, playing: bool) -> None:
        """`current`: this is the track the player has (playing or paused). `playing`: and it is running."""
        self._current, self._playing = current, current and playing
        self.setToolTip("Pause" if self.playing else "Resume" if current else "Play this track")
        self._retarget()

    def set_playing(self, on: bool) -> None:  # (the old name: a playing track is the current one)
        self.set_state(on, on)

    def _targets(self) -> list[float]:
        hover = self.underMouse()
        if not self._current:
            return [1.0, 0.0, 0.0]
        if self._playing:
            return [0.0, 1.0, 0.0] if hover else [0.0, 0.0, 1.0]
        return [1.0, 0.0, 0.0] if hover else [0.0, 0.0, 1.0]  # paused: the note holds still, the pointer offers play

    def _retarget(self) -> None:
        goal = self._targets()
        if self._playing and self.isVisible():
            if not self._sway.isActive():
                self._sway_clock.reset()
                self._sway.start(motion.frame_ms(self))
        else:
            self._sway.stop()  # paused (or not the current track): the note stops where it is
        if goal == self._goal and self._anim.state() == QAbstractAnimation.State.Stopped:
            return
        self._anim.stop()
        self._goal = goal
        if not motion.on() or not self.isVisible():
            self._alpha = list(goal)
            self.update()
            return
        self._from = list(self._alpha)
        self._anim.start()

    def _blend(self, value) -> None:
        v = float(value)
        self._alpha = [a + (b - a) * v for a, b in zip(self._from, self._goal)]
        self.update()

    def _step_sway(self) -> None:
        self._phase = (self._phase + 4.85 * self._sway_clock.dt()) % (2 * math.pi)  # 4.85 rad/s
        self.update()

    def _to_press(self, goal: float) -> None:
        self._press_anim.stop()
        self._press_anim.setStartValue(self._press)
        self._press_anim.setEndValue(goal)
        self._press_anim.start()

    def _set_press(self, value) -> None:
        self._press = float(value)
        self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._retarget()

    def hideEvent(self, event) -> None:
        self._sway.stop()
        super().hideEvent(event)

    def enterEvent(self, event) -> None:
        self._retarget()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._retarget()
        super().leaveEvent(event)

    # ---- drawing --------------------------------------------------------------------------------
    @staticmethod
    def _triangle() -> QPainterPath:
        path = QPainterPath(QPointF(8.2, 6.2))
        path.lineTo(QPointF(15.6, 11.0))
        path.lineTo(QPointF(8.2, 15.8))
        path.closeSubpath()
        return path

    @staticmethod
    def _bars() -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(QRectF(7.0, 6.5, 3.0, 9.0), 1.2, 1.2)
        path.addRoundedRect(QRectF(12.0, 6.5, 3.0, 9.0), 1.2, 1.2)
        return path

    def _note(self) -> QPainterPath:
        """A quaver, swaying a little: its head and flag drift and tilt with the phase."""
        path = QPainterPath()
        path.addEllipse(QPointF(0.0, 4.2), 3.2, 2.4)  # the head, then the stem and the flag, about the note's own origin
        stem = QPainterPath(QPointF(3.0, 3.6))
        stem.lineTo(QPointF(3.0, -6.0))
        stem.cubicTo(QPointF(3.4, -3.0), QPointF(7.2, -3.2), QPointF(6.6, 0.6))
        stem.lineTo(QPointF(6.0, 0.6))
        stem.cubicTo(QPointF(6.2, -1.6), QPointF(4.4, -2.4), QPointF(3.8, -3.4))
        stem.lineTo(QPointF(3.8, 3.6))
        stem.closeSubpath()
        path.addPath(stem)
        return path

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        hover = self.underMouse()
        colour = QColor(T.title if hover else T.accent_text)
        c = QPointF(self.SIZE / 2, self.SIZE / 2)
        p.translate(c)
        k = 1.0 - 0.1 * self._press  # held down: a little smaller
        p.scale(k, k)
        p.translate(-c)
        if hover or self._press > 0.01:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(T.btn_down[0] if self._press > 0.3 else T.hover)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 7, 7)
        for face, alpha in enumerate(self._alpha):
            if alpha < 0.01:
                continue
            p.save()
            pop = 0.78 + 0.22 * alpha  # each face grows in as it appears and shrinks as it goes
            p.translate(c)
            p.scale(pop, pop)
            p.translate(-c)
            tint = QColor(colour)
            tint.setAlphaF(max(0.0, min(1.0, alpha)))
            p.setBrush(tint)
            if face == 0:
                p.setPen(QPen(tint, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))  # soft corners
                p.drawPath(self._triangle())
            elif face == 1:
                p.setPen(Qt.PenStyle.NoPen)
                p.drawPath(self._bars())
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.translate(c.x() - 1.5, c.y() - 0.3 + math.sin(self._phase) * 1.3)
                p.rotate(math.sin(self._phase + 1.2) * 7.0)
                p.drawPath(self._note())
            p.restore()


class TrackRow(QWidget):
    """[tick] [play] title. `toggled(bool)` when the tick changes, `playClicked()` when the play button is pressed."""

    toggled = Signal(bool)
    playClicked = Signal()
    ROW_MIN = 28  # the row's own minimum height; its list may squeeze it lower while it folds open or shut
    SOFT = 48  # px: the soft edge of the left-to-right wipe while the row is written in
    _fold_h: int | None = None  # while its list folds it open or shut: the height it is allowed right now

    def __init__(self, title: str, checked: bool, can_play: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self._title = title
        self._current = False
        lay = QHBoxLayout(self)
        lay.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)  # the layout must not hold the row open
        lay.setContentsMargins(1, 0, 8, 0)  # + the tick's own 2px of room: the box sits where it always did
        lay.setSpacing(3)
        self.check = AnimCheckBox("")
        self.check.setChecked(checked)
        self.check.setToolTip("Select the tracks to save")
        self.check.toggled.connect(self.toggled)
        lay.addWidget(self.check)
        self.play = PlayToggle() if can_play else None
        if self.play is not None:
            self.play.clicked.connect(self.playClicked)
            lay.addWidget(self.play)
        self.label = QLabel(title)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)  # clicks reach the list (select, menu)
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.label.setToolTip(title)
        lay.addWidget(self.label, 1)
        self.setMinimumHeight(self.ROW_MIN)

    def set_checked(self, on: bool) -> None:
        """Show a tick state set by the list (the parent game's box), without announcing it."""
        self.check.blockSignals(True)
        self.check.setChecked(on)
        self.check._t = 1.0 if on else 0.0
        self.check.blockSignals(False)
        self.check.update()

    def sizeHint(self) -> QSize:
        # A tree sizes a row as the taller of its own hint and its widget's hint. While the list folds this row
        # open or shut the widget has to follow, or the row would stay full height and only fade.
        hint = super().sizeHint()
        if self._fold_h is not None:
            hint.setHeight(self._fold_h)
        return hint

    def set_reveal(self, opacity: float | None = None, height: int | None = None, front: float | None = None) -> None:
        """Show the row part-way while its list folds it open or shut: `opacity` (0..1), the `height` it is allowed,
        and `front`, how far right (in this row's own x) it has been written so far, with a soft edge. Nothing given
        puts the row back to normal."""
        plain = (opacity is None or opacity >= 1.0) and front is None  # nothing to fade or sweep
        if plain:
            if self.graphicsEffect() is not None:  # an idle effect makes Qt draw the row off-screen first
                self.setGraphicsEffect(None)
            if height is None:
                self._fold_h = None
                self.setMinimumHeight(self.ROW_MIN)
                self.updateGeometry()
                return
        else:
            effect = self.graphicsEffect()
            if not isinstance(effect, QGraphicsOpacityEffect):
                effect = QGraphicsOpacityEffect(self)
                self.setGraphicsEffect(effect)
            effect.setOpacity(1.0 if opacity is None else max(0.0, min(1.0, opacity)))
            if front is None:
                effect.setOpacityMask(QBrush())
            else:
                sweep = QLinearGradient(front - self.SOFT, 0.0, front, 0.0)  # solid up to the front, clear beyond it
                sweep.setColorAt(0.0, QColor(0, 0, 0, 255))
                sweep.setColorAt(1.0, QColor(0, 0, 0, 0))
                effect.setOpacityMask(QBrush(sweep))
        self._fold_h = height
        self.setMinimumHeight(0)
        self.updateGeometry()

    def set_current(self, on: bool) -> None:
        """Highlight this row while its track is the one playing (or paused)."""
        if on == self._current:
            return
        self._current = on
        T.bind_css(self.label, lambda: f"color: {T.accent_text.name()}; font-weight: 600;" if on else "")
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.label.setText(self.label.fontMetrics().elidedText(self._title, Qt.TextElideMode.ElideRight,
                                                               max(self.label.width(), 40)))

    def paintEvent(self, _event) -> None:
        if not self._current:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        wash = QLinearGradient(0, 0, self.width(), 0)
        start, end = T.wash(70, 24)
        wash.setColorAt(0.0, start)
        wash.setColorAt(1.0, end)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(wash)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0, 1, -2, -1), 7, 7)
        p.setBrush(T.accent)
        p.drawRoundedRect(QRectF(0, 5, 3, self.height() - 10), 1.5, 1.5)
