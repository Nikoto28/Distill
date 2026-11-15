"""The Games page's "Library health..." window: what the check-up found, each problem with a button that acts on it (select the games it
is about so the tools bar can deal with them, or open Fetch pictures). The check itself is libraryhealth.py."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .. import libraryhealth as lh
from .frameless import FramelessDialog, hairline
from .theme import T
from .widgets import accent_button, hint

BUTTONS = {"select": "Select these games", "fetch": "Fetch pictures..."}


class LibraryHealthDialog(FramelessDialog):
    def __init__(self, parent: QWidget, issues: list[lh.Issue], total: int):
        super().__init__(parent, "Library health", "search", (640, 640), (520, 480))
        self.choice: tuple[str, list[str]] | None = None  # what the player chose to do: ('select', game ids) or ('fetch', [])
        outer = self.content
        head = hint(f"{total} game{'s' if total != 1 else ''} checked." + (f" {len(issues)} thing{'s' if len(issues) != 1 else ''} to look at." if issues else ""), live=True)
        head.setContentsMargins(22, 14, 22, 0)
        outer.addWidget(head)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.viewport().setAutoFillBackground(False)
        host = QWidget()
        host.setObjectName("healthBody")
        host.setStyleSheet("#healthBody { background: transparent; }")
        scroll.setWidget(host)
        body = QVBoxLayout(host)
        body.setContentsMargins(22, 12, 22, 12)
        body.setSpacing(10)
        if not issues:
            ok = QLabel("Your library looks healthy: every file is where it should be, nothing is stored twice, and every game has a platform, a cover and details.")
            ok.setWordWrap(True)
            T.bind_css(ok, lambda: f"color: {T.title.name()}; font-weight: 600; background: transparent;")
            body.addWidget(ok)
        for issue in issues:
            body.addWidget(self._row(issue))
        body.addStretch(1)
        outer.addWidget(scroll, 1)
        outer.addWidget(hairline())
        foot = QHBoxLayout()
        foot.setContentsMargins(22, 12, 22, 14)
        foot.addStretch(1)
        close = QPushButton("Close")
        close.setAutoDefault(False)
        close.clicked.connect(self.reject)
        foot.addWidget(close)
        outer.addLayout(foot)

    def _row(self, issue: lh.Issue) -> QFrame:
        card = QFrame()
        card.setObjectName("healthRow")
        T.bind_css(card, lambda: f"#healthRow {{ background: {T.card.name()}; border: 1px solid {T.card_border.name()}; border-radius: 12px; }}")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(16, 12, 14, 12)
        lay.setSpacing(14)
        text = QVBoxLayout()
        text.setSpacing(3)
        title = QLabel(issue.title)
        title.setWordWrap(True)
        T.bind_css(title, lambda: f"color: {T.title.name()}; font-weight: 600; background: transparent;")
        text.addWidget(title)
        text.addWidget(hint(issue.detail, live=True))
        lay.addLayout(text, 1)
        button = accent_button(BUTTONS[issue.action]) if issue.action == "fetch" else QPushButton(BUTTONS[issue.action])
        button.setAutoDefault(False)
        button.clicked.connect(lambda _c=False, i=issue: self._choose(i))
        lay.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
        return card

    def _choose(self, issue: lh.Issue) -> None:
        self.choice = (issue.action, list(issue.ids))
        self.accept()
