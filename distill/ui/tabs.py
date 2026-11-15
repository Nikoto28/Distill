"""The tab strip of Distill Resonance (Search, Library, Playlists, Queue, Settings).

Two pieces of motion, both in the style the rest of the app already uses:
  * the underline under the current tab is drawn by the strip itself and slides from the tab it was under to the one chosen;
  * the page being left is photographed and laid over the new one, then fades and drifts away (the same dissolve as
    `SizedStack` uses between the app's pages), sideways here, towards where the old tab sits.
Nothing animates when motion is reduced (Settings > Reduce Motion)."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPointF, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QStackedWidget, QTabBar, QTabWidget, QWidget

from . import motion
from .theme import T


class SlidingTabBar(QTabBar):
    """A tab strip whose underline is one bar that glides between tabs (the stylesheet draws no underline of its own)."""

    INSET = 2  # px the bar stops short of the tab's edges
    THICK = 2.0

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._span = (0.0, 0.0)  # (left, width) of the bar as drawn now
        self._from = self._to = self._span
        self._anim = QVariantAnimation(self, duration=240, startValue=0.0, endValue=1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._step)
        self.currentChanged.connect(self._glide)

    def _target(self) -> tuple[float, float]:
        if self.currentIndex() < 0:
            return (0.0, 0.0)
        r = self.tabRect(self.currentIndex())
        return (float(r.left() + self.INSET), float(max(r.width() - 2 * self.INSET, 0)))

    def _glide(self, _index: int) -> None:
        self._anim.stop()
        self._from, self._to = self._span, self._target()
        if not motion.on() or not self.isVisible() or self._from[1] <= 0:
            self._span = self._to
            self.update()
            return
        self._anim.start()

    def _step(self, value) -> None:
        t = float(value)
        self._span = tuple(a + (b - a) * t for a, b in zip(self._from, self._to))  # type: ignore[assignment]
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._anim.state() != QVariantAnimation.State.Running:
            self._span = self._target()  # at rest it sits under the current tab, whatever resized or restyled the strip
        left, width = self._span
        if width <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(T.accent)
        p.drawRoundedRect(QRectF(left, self.height() - self.THICK, width, self.THICK), 1.0, 1.0)


class MediaTabs(QTabWidget):
    """A QTabWidget with the sliding underline and the page dissolve."""

    VEIL_MS, DRIFT = 200, 22  # as SizedStack's dissolve, with how far the old page drifts

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setTabBar(SlidingTabBar(self))
        self._shot: QPixmap | None = None  # the page on show, photographed just before a change
        self._last = -1
        self._veil: QLabel | None = None
        self._veil_dir = -1
        self.tabBar().installEventFilter(self)  # a click or a key on the strip is about to change the page
        self.currentChanged.connect(self._changed)

    # ---- the photograph is taken before the page changes ------------------------------------------
    def _shoot(self) -> None:
        stack = self.findChild(QStackedWidget)
        if stack is None or not motion.on() or not self.isVisible() or not self.window().isVisible():
            self._shot = None
            return
        self._shot = stack.grab()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.tabBar() and event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress,
                                                      QEvent.Type.Wheel):
            self._shoot()
        return super().eventFilter(obj, event)

    def setCurrentIndex(self, index: int) -> None:  # (a change made by the program rather than a click)
        if index != self.currentIndex():
            self._shoot()
        super().setCurrentIndex(index)

    def setCurrentWidget(self, widget: QWidget) -> None:
        self.setCurrentIndex(self.indexOf(widget))

    # ---- the dissolve ------------------------------------------------------------------------------
    def _changed(self, index: int) -> None:
        before, self._last = self._last, index
        shot, self._shot = self._shot, None
        stack = self.findChild(QStackedWidget)
        if shot is None or shot.isNull() or stack is None or before < 0 or before == index:
            return
        self._veil_dir = -1 if index > before else 1  # the old page drifts towards the tab it was on
        if self._veil is None:
            veil = self._veil = QLabel(stack)
            veil.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            veil.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            self._veil_fx = QGraphicsOpacityEffect(veil)
            veil.setGraphicsEffect(self._veil_fx)
            self._veil_anim = QVariantAnimation(self, duration=self.VEIL_MS, startValue=0.0, endValue=1.0)
            self._veil_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._veil_anim.valueChanged.connect(self._veil_step)
            self._veil_anim.finished.connect(self._end_veil)
        self._veil_anim.stop()
        veil = self._veil
        dpr = shot.devicePixelRatio() or 1.0
        veil.setParent(stack)
        veil.setPixmap(shot)
        veil.setGeometry(0, 0, round(shot.width() / dpr), round(shot.height() / dpr))
        self._veil_fx.setOpacity(1.0)
        veil.raise_()
        veil.show()
        self._veil_anim.start()

    def _veil_step(self, value) -> None:
        t = float(value)
        self._veil_fx.setOpacity(1.0 - t)
        self._veil.move(round(self.DRIFT * t) * self._veil_dir, 0)

    def _end_veil(self) -> None:
        if self._veil is not None:
            self._veil_anim.stop()
            self._veil.hide()
            self._veil.move(0, 0)
            self._veil.setPixmap(QPixmap())
