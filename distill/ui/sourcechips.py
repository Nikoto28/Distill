"""The small tags that credit where a soundtrack came from: KHInsider (orange) or archive.org (blue), in the style of the
LaunchBox chip on the Games page. A chip opens the source's own site when it is clicked; its tooltip says what came from there."""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from .emu_cards import SourceChip
from PySide6.QtCore import Qt

KHINSIDER_COLOUR = "#E8862F"
ARCHIVE_COLOUR = "#4F8FD6"
KHINSIDER_URL = "https://downloads.khinsider.com"
ARCHIVE_URL = "https://archive.org"

KHINSIDER_TIP = ("From KHInsider's Video Game Music database (downloads.khinsider.com): the album lists, covers, track lists "
                 "and the audio you stream or save. Click to open the site.")
ARCHIVE_TIP = "From the Internet Archive (archive.org): audio items shared there. Click to open the site."


class LinkSourceChip(SourceChip):
    """A source chip that opens the source's site when it is clicked."""

    def __init__(self, text: str, tip: str, colour: str, url: str):
        super().__init__(text, tip, colour)
        self._url = url
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._url and self.rect().contains(event.position().toPoint()):
            QDesktopServices.openUrl(QUrl(self._url))
        super().mouseReleaseEvent(event)


def source_chip(provider: str) -> LinkSourceChip | None:
    """The credit chip for a provider ('khinsider', 'archive.org'), or None for one that needs none (files on this computer,
    a pasted link). Each call makes a new chip: a widget can only sit in one place."""
    if provider == "khinsider":
        return LinkSourceChip("KHInsider", KHINSIDER_TIP, KHINSIDER_COLOUR, KHINSIDER_URL)
    if provider == "archive.org":
        return LinkSourceChip("archive.org", ARCHIVE_TIP, ARCHIVE_COLOUR, ARCHIVE_URL)
    return None


def has_chip(provider: str) -> bool:
    return provider in ("khinsider", "archive.org")
