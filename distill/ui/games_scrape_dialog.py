"""The Games page's "Fetch pictures..." window: look online for the pictures many games lack, all at once.

The player chooses which games (the whole library, the selected games, or one platform), which kinds of picture, and whether to look again
for ones that weren't found before. A line says how many games and pictures that comes to; then a bar and two lines show which game and
which picture is being fetched, and how many were found. Stopping (or closing the window) is prompt. The fetching itself is mediascrape.py.
"""
from __future__ import annotations

import threading
from collections import Counter

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from .. import mediascrape as ms
from . import motion
from .frameless import FramelessDialog, hairline
from .recomp_dialog import _stack
from .theme import T
from .widgets import AnimCheckBox, accent_button, hint

Entry = tuple[str, str, str, str]  # (the key the game's pictures are kept under, its name, its platform, its own id)

PLURAL = {"cover": "Covers", "back": "Backgrounds", "disc": "Discs and cartridges", "shots": "Screenshots"}


class MediaScrapeDialog(FramelessDialog):
    _progress = Signal(object)
    _finished = Signal(object, bool)

    def __init__(self, parent: QWidget, everything: list[Entry], selected: list[Entry] | None, sgdb_key: str, covers: ms.CoverHooks | None = None):
        super().__init__(parent, "Fetch pictures", "search", (620, 640), (520, 560))
        self.sgdb_key, self.covers = sgdb_key, covers
        self._scopes: list[tuple[str, list[Entry]]] = [(f"Whole library ({len({e[0] for e in everything})} games)", everything)]
        if selected:
            self._scopes.insert(0, (f"Selected games ({len({e[0] for e in selected})})", selected))
        for system in sorted({e[2] for e in everything}):
            games = [e for e in everything if e[2] == system]
            self._scopes.append((f"{system} ({len({e[0] for e in games})} games)", games))
        self._cancel = threading.Event()
        self._alive = True
        self._running = False
        self._ran = False
        self.found_any = False  # something new was fetched (so the page should show it)
        self._jobs: list[ms.Job] = []
        outer = self.content
        body = QVBoxLayout()
        body.setContentsMargins(22, 16, 22, 10)
        body.setSpacing(12)
        body.addWidget(hint("Looks online (LaunchBox, and SteamGridDB when you have added its key) for the pictures your games don't have yet. "
                            "Pictures you chose, or turned off, are never touched. Covers are fetched as you scroll the library.", live=True))
        self.scope = QComboBox()
        self.scope.setMinimumHeight(38)
        for label, _entries in self._scopes:
            self.scope.addItem(label)
        self.scope.activated.connect(lambda _i: self._soon())
        body.addLayout(_stack("Games", self.scope))
        self.boxes: dict[str, AnimCheckBox] = {}
        self.options = QWidget()
        opts = QVBoxLayout(self.options)
        opts.setContentsMargins(0, 0, 0, 0)
        opts.setSpacing(8)
        for kind in ms.KINDS:
            box = AnimCheckBox(PLURAL[kind])
            box.setChecked(True)
            box.toggled.connect(lambda _on: self._soon())
            self.boxes[kind] = box
            opts.addWidget(box)
        self.retry = AnimCheckBox("Look again for pictures that weren't found before")
        self.retry.setToolTip("A picture that wasn't found is not looked for again for a week. Tick this to look now.")
        self.retry.toggled.connect(lambda _on: self._soon())
        opts.addWidget(self.retry)
        body.addWidget(self.options)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        T.bind_css(self.summary, lambda: f"color: {T.title.name()}; font-weight: 600; background: transparent;")
        body.addWidget(self.summary)

        self.run_box = QWidget()  # the progress, shown once the fetching starts
        run = QVBoxLayout(self.run_box)
        run.setContentsMargins(0, 4, 0, 0)
        run.setSpacing(6)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        T.bind_css(self.bar, lambda: (f"QProgressBar {{ background: {T.input.name()}; border: none; border-radius: 4px; }}"
                                       f"QProgressBar::chunk {{ background: {T.accent.name()}; border-radius: 4px; }}"))
        self.now_game = QLabel()
        T.bind_css(self.now_game, lambda: f"color: {T.title.name()}; font-weight: 600; background: transparent;")
        self.now_kind = hint("", live=True)
        self.counts = hint("", live=True)
        for w in (self.bar, self.now_game, self.now_kind, self.counts):
            run.addWidget(w)
        self.run_box.setVisible(False)
        body.addWidget(self.run_box)
        body.addStretch(1)
        outer.addLayout(body, 1)

        outer.addWidget(hairline())
        foot = QHBoxLayout()
        foot.setContentsMargins(22, 12, 22, 14)
        self.note = hint("Closing this window stops the fetching.", live=False)
        self.note.setVisible(False)
        foot.addWidget(self.note, 1)
        self.close_btn = QPushButton("Close")
        self.close_btn.setAutoDefault(False)
        self.close_btn.clicked.connect(self.reject)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setAutoDefault(False)
        self.stop_btn.clicked.connect(self._stop)
        self.stop_btn.setVisible(False)
        self.start_btn = accent_button("Start")
        self.start_btn.setAutoDefault(False)
        self.start_btn.clicked.connect(self._start)
        for b in (self.close_btn, self.stop_btn, self.start_btn):
            foot.addWidget(b)
        outer.addLayout(foot)
        self._timer = QTimer(self)  # the line of totals is recounted once the player stops clicking
        self._timer.setSingleShot(True)
        self._timer.setInterval(160)
        self._timer.timeout.connect(self._recount)
        self._progress.connect(self._on_progress)
        self._finished.connect(self._on_finished)
        self._recount()

    # ---- choosing -------------------------------------------------------------------------------------------------
    def _soon(self) -> None:
        self._ran = False  # a choice was changed: the totals line is about the new choices, not the last run
        self._timer.start()

    def _entries(self) -> list[Entry]:
        return self._scopes[max(0, self.scope.currentIndex())][1]

    def _kinds(self) -> list[str]:
        return [k for k, box in self.boxes.items() if box.isChecked()]

    def _recount(self) -> None:
        """What would be fetched with the choices as they are now: the totals line, and the count beside each kind."""
        retry = self.retry.isChecked()
        every = ms.build_jobs(self._entries(), ms.KINDS, retry, self.covers)
        per_kind = Counter(kind for job in every for kind in job.wants)
        for kind, box in self.boxes.items():
            box.setText(f"{PLURAL[kind]}  ({per_kind[kind]} missing)" if per_kind[kind] else f"{PLURAL[kind]}  (none missing)")
        self._jobs = ms.build_jobs(self._entries(), self._kinds(), retry, self.covers)
        pictures = sum(len(j.wants) for j in self._jobs)
        self.summary.setText(f"{len(self._jobs)} game{'s' if len(self._jobs) != 1 else ''} to look for, {pictures} picture{'s' if pictures != 1 else ''} in all."
                             if self._jobs else "Nothing to fetch: every game here has what is ticked, or was looked for recently without luck.")
        self.start_btn.setEnabled(bool(self._jobs))

    # ---- fetching -------------------------------------------------------------------------------------------------
    def _start(self) -> None:
        if not self._jobs or self._running:
            return
        self._running, self._ran = True, True
        self._cancel.clear()
        self.options.setEnabled(False)
        self.scope.setEnabled(False)
        self.start_btn.setVisible(False)
        self.close_btn.setVisible(False)
        self.stop_btn.setVisible(True)
        self.stop_btn.setEnabled(True)
        self.note.setVisible(True)
        self.bar.setValue(0)
        self.now_game.setText("Starting...")
        self.now_kind.setText("")
        self.counts.setText("")
        motion.set_visible(self.run_box, True, axis="height")
        self.summary.setText(f"Fetching pictures for {len(self._jobs)} game{'s' if len(self._jobs) != 1 else ''}...")
        jobs, sgdb, retry, covers = list(self._jobs), self.sgdb_key, self.retry.isChecked(), self.covers

        def work() -> None:
            tally = ms.scrape(jobs, sgdb, retry, lambda p: self._send(self._progress, p), self._cancel.is_set, covers=covers)
            self._send(self._finished, tally, self._cancel.is_set())

        threading.Thread(target=work, daemon=True).start()

    def _stop(self) -> None:
        self._cancel.set()
        self.stop_btn.setEnabled(False)
        self.now_kind.setText("Stopping after the pictures being fetched...")

    def _send(self, signal, *args) -> None:
        if self._alive:
            try:
                signal.emit(*args)
            except RuntimeError:  # the window is gone
                pass

    def _on_progress(self, p: ms.Progress) -> None:
        if not self._running:
            return
        total = max(1, p.pictures_total)
        motion.ease_value(self.bar, int(1000 * p.pictures_done / total))
        if p.kind:
            self.now_game.setText(p.name)
            self.now_kind.setText(f"Looking for the {p.label}...")
        text = f"{p.games_done} of {p.games_total} games  -  found {p.found}  -  nothing online for {p.missed}"
        self.counts.setText(text + (f"  -  {p.errors} failed" if p.errors else ""))

    def _on_finished(self, tally: ms.Tally, cancelled: bool) -> None:
        self._running = False
        self._ran = True
        motion.ease_value(self.bar, 1000 if not cancelled else self.bar.value())
        self.now_game.setText("")
        self.now_kind.setText("")
        self.summary.setText(ms.summary(tally, cancelled))
        self.counts.setText("")
        self.stop_btn.setVisible(False)
        self.note.setVisible(False)
        self.close_btn.setVisible(True)
        self.close_btn.setText("Close")
        self.options.setEnabled(True)
        self.scope.setEnabled(True)
        self.start_btn.setText("Fetch more")
        self.start_btn.setVisible(True)
        self._jobs = ms.build_jobs(self._entries(), self._kinds(), self.retry.isChecked(), self.covers)  # (what is still missing after this run)
        self.start_btn.setEnabled(bool(self._jobs))
        self.found_any = self.found_any or tally.total_found() > 0

    def done(self, result: int) -> None:
        self._alive = False
        self._cancel.set()  # closing mid-run stops it
        super().done(result)
