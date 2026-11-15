"""Save backups on the Games page: a game's own window (back up now, restore, delete) and a window that backs up every game's saves at once
(before a RetroArch or core update, say). The work is savebackup.py; only RetroArch's saves are known to Distill."""
from __future__ import annotations

import threading
import time

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QWidget

from .. import games as gm
from .. import savebackup as sb
from . import motion, msgbox
from .frameless import FramelessDialog, hairline
from .theme import T
from .widgets import accent_button, hint

BACKUP_LIST_CSS = lambda: (f"QListWidget {{ background: transparent; border: none; outline: 0; padding: 4px 14px; color: {T.fg.name()}; }}"  # noqa: E731
                           f"QListWidget::item {{ padding: 10px 12px; border-radius: 10px; }}"
                           f"QListWidget::item:hover {{ background: {T.hover.name()}; }}"
                           f"QListWidget::item:selected {{ background: {T.select.name()}; color: {T.title.name()}; }}")


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def describe(info: sb.BackupInfo) -> str:
    when = time.strftime("%d %b %Y, %H:%M", time.localtime(info.created)) if info.created else "Unknown date"
    text = f"{when}  -  {_plural(info.files, 'file', 'files')}"
    return text + (f"  -  {info.reason}" if info.reason else "")


class SavesDialog(FramelessDialog):
    """One game's saves: what it has now, and its backups."""

    def __init__(self, parent: QWidget, game: gm.Game, setup: gm.RetroSetup | None):
        super().__init__(parent, f"Saves: {game.name}", "archive", (620, 580), (520, 460))
        self.game, self.setup = game, setup
        self._infos: list[sb.BackupInfo] = []
        outer = self.content
        self.now = hint("", live=True)
        self.now.setContentsMargins(22, 14, 22, 4)
        outer.addWidget(self.now)
        self.list = QListWidget()
        self.list.setFrameShape(QListWidget.Shape.NoFrame)
        T.bind_css(self.list, BACKUP_LIST_CSS)
        self.list.itemSelectionChanged.connect(self._sync)
        self.list.itemDoubleClicked.connect(lambda _i: self._restore())
        outer.addWidget(self.list, 1)
        self.empty = hint("No backups yet. Back up now, and the saves are kept here; a restore puts them back where the emulator keeps them.", live=True)
        self.empty.setContentsMargins(22, 0, 22, 8)
        outer.addWidget(self.empty)
        outer.addWidget(hairline())
        foot = QHBoxLayout()
        foot.setContentsMargins(22, 12, 22, 14)
        foot.setSpacing(8)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setAutoDefault(False)
        self.delete_btn.clicked.connect(self._delete)
        self.restore_btn = QPushButton("Restore")
        self.restore_btn.setAutoDefault(False)
        self.restore_btn.setToolTip("Put this backup's saves back where the emulator keeps them (what they replace is backed up first)")
        self.restore_btn.clicked.connect(self._restore)
        self.backup_btn = accent_button("Back up now")
        self.backup_btn.setAutoDefault(False)
        self.backup_btn.clicked.connect(self._backup)
        close = QPushButton("Close")
        close.setAutoDefault(False)
        close.clicked.connect(self.reject)
        foot.addWidget(self.delete_btn)
        foot.addStretch(1)
        for b in (close, self.restore_btn, self.backup_btn):
            foot.addWidget(b)
        outer.addLayout(foot)
        self._reload()

    # ---- what there is ---------------------------------------------------------------------------------------------
    def _saves(self) -> list[sb.SaveFile]:
        return sb.find_saves(self.setup, self.game) if self.setup is not None else []

    def _reload(self, select: int = -1) -> None:
        saves = self._saves()
        if self.setup is None:
            self.now.setText("Distill only knows where RetroArch keeps its saves. This game is played with an emulator of its own (or RetroArch isn't set up), "
                             "so there is nothing to back up here.")
        elif not saves:
            self.now.setText("No saves found for this game yet. Play it and save, then come back.")
        else:
            states = sum(1 for s in saves if s.kind == "state")
            parts = [p for p in (_plural(states, "save state", "save states") if states else "", "a battery save" if len(saves) > states else "") if p]
            newest = max((s.path.stat().st_mtime for s in saves if s.path.exists()), default=0.0)
            self.now.setText(f"Now: {' and '.join(parts)}" + (f", last changed {gm.fmt_ago(newest)}." if newest else "."))
        self._infos = sb.list_backups(self.game.id)
        self.list.clear()
        for info in self._infos:
            item = QListWidgetItem(describe(info))
            item.setToolTip("\n".join(info.names))
            self.list.addItem(item)
        if self._infos:
            self.list.setCurrentRow(select if 0 <= select < len(self._infos) else 0)
        self.empty.setVisible(not self._infos)
        self.list.setVisible(bool(self._infos))
        self.backup_btn.setEnabled(bool(saves))
        self._sync()

    def _sync(self) -> None:
        chosen = self.list.currentRow() >= 0 and bool(self._infos)
        self.restore_btn.setEnabled(chosen and self.setup is not None)
        self.delete_btn.setEnabled(chosen)

    def _current(self) -> sb.BackupInfo | None:
        row = self.list.currentRow()
        return self._infos[row] if 0 <= row < len(self._infos) else None

    # ---- doing ---------------------------------------------------------------------------------------------------------
    def _backup(self) -> None:
        if self.setup is None:
            return
        path = sb.backup_game(self.setup, self.game, "backed up by hand")
        if path is None:
            self.now.setText("Nothing was backed up: no saves were found, or the backup couldn't be written.")
            return
        self._reload(0)

    def _restore(self) -> None:
        info = self._current()
        if info is None or self.setup is None:
            return
        if msgbox.question(self, "Restore saves", f"Put the saves from {describe(info).split('  -  ')[0]} back?\n\nAnything they replace is backed up first, "
                           "so this can be undone.") != QMessageBox.StandardButton.Yes:
            return
        result = sb.restore(info.path, self.game.id, self.game.name, self.game.system)
        text = f"Restored {_plural(result.restored, 'file', 'files')}."
        if result.skipped:
            text += " Not restored: " + "; ".join(result.skipped[:3]) + ("..." if len(result.skipped) > 3 else "")
        self._reload()
        self.now.setText(text)

    def _delete(self) -> None:
        info = self._current()
        if info is None:
            return
        if msgbox.question(self, "Delete backup", f"Delete the backup from {describe(info).split('  -  ')[0]}?") != QMessageBox.StandardButton.Yes:
            return
        row = self.list.currentRow()
        sb.delete_backup(info.path)
        self._reload(row)


class BackupAllDialog(FramelessDialog):
    """Back up the saves of many games, one after another, with a bar and a Stop. Starts as soon as it opens."""
    _progress = Signal(int, int, str)
    _finished = Signal(int, int, bool)

    def __init__(self, parent: QWidget, setup: gm.RetroSetup, games: list[gm.Game], reason: str = "backed up all at once"):
        super().__init__(parent, "Back up saves", "archive", (560, 330), (480, 300))
        self._alive, self._cancel = True, threading.Event()
        outer = self.content
        self.title_label = QLabel(f"Backing up the saves of {_plural(len(games), 'game', 'games')}...")
        self.title_label.setWordWrap(True)
        self.title_label.setContentsMargins(22, 18, 22, 0)
        T.bind_css(self.title_label, lambda: f"color: {T.title.name()}; font-weight: 600; background: transparent;")
        outer.addWidget(self.title_label)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        T.bind_css(self.bar, lambda: (f"QProgressBar {{ background: {T.input.name()}; border: none; border-radius: 4px; }}"
                                       f"QProgressBar::chunk {{ background: {T.accent.name()}; border-radius: 4px; }}"))
        bar_row = QHBoxLayout()
        bar_row.setContentsMargins(22, 12, 22, 0)
        bar_row.addWidget(self.bar)
        outer.addLayout(bar_row)
        self.now = hint("", live=True)
        self.now.setContentsMargins(22, 6, 22, 0)
        outer.addWidget(self.now)
        outer.addStretch(1)
        outer.addWidget(hairline())
        foot = QHBoxLayout()
        foot.setContentsMargins(22, 12, 22, 14)
        foot.addStretch(1)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setAutoDefault(False)
        self.stop_btn.clicked.connect(self._stop)
        self.close_btn = QPushButton("Close")
        self.close_btn.setAutoDefault(False)
        self.close_btn.clicked.connect(self.reject)
        self.close_btn.setVisible(False)
        foot.addWidget(self.stop_btn)
        foot.addWidget(self.close_btn)
        outer.addLayout(foot)
        self._progress.connect(self._on_progress)
        self._finished.connect(self._on_finished)

        def work() -> None:
            done, files = sb.backup_all(setup, games, reason, lambda i, n, name: self._send(self._progress, i, n, name), self._cancel.is_set)
            self._send(self._finished, done, files, self._cancel.is_set())

        threading.Thread(target=work, daemon=True).start()

    def _send(self, signal, *args) -> None:
        if self._alive:
            try:
                signal.emit(*args)
            except RuntimeError:  # the window is gone
                pass

    def _stop(self) -> None:
        self._cancel.set()
        self.stop_btn.setEnabled(False)

    def _on_progress(self, i: int, n: int, name: str) -> None:
        motion.ease_value(self.bar, int(1000 * i / max(1, n)))
        self.now.setText(name)

    def _on_finished(self, done: int, files: int, cancelled: bool) -> None:
        motion.ease_value(self.bar, 1000 if not cancelled else self.bar.value())
        self.title_label.setText(("Stopped: " if cancelled else "Done: ")
                                 + (f"backed up the saves of {_plural(done, 'game', 'games')} ({_plural(files, 'file', 'files')})." if done else "no saves were found to back up."))
        self.now.setText("Each game's backups are in its Saves window (the archive button on its page).")
        self.stop_btn.setVisible(False)
        self.close_btn.setVisible(True)

    def done(self, result: int) -> None:
        self._alive = False
        self._cancel.set()  # closing mid-run stops it
        super().done(result)
