"""A folder of cover images kept between runs, so covers show at once and still show offline. Plain files, trimmed
oldest-used-first to a size the person sets (Settings > Disk space). No Qt, no network."""
from __future__ import annotations

import hashlib
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

DEFAULT_MB = 100
MB = 1024 * 1024


class CoverCache:
    def __init__(self, folder: Path, limit_bytes: Callable[[], int]):
        self.folder = Path(folder)
        self._limit = limit_bytes
        self._lock = threading.Lock()

    def _path(self, url: str) -> Path:
        return self.folder / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".img")

    def get(self, url: str) -> bytes | None:
        """The kept image for this address (and it counts as used), or None."""
        path = self._path(url)
        try:
            data = path.read_bytes()
            os.utime(path, None)
        except OSError:
            return None
        return data or None

    def put(self, url: str, data: bytes) -> bool:
        """Keep an image. False when the cache is off (limit 0) or the image alone is bigger than the whole budget."""
        limit = self._limit()
        if not data or limit <= 0 or len(data) > limit:
            return False
        with self._lock:
            try:
                self.folder.mkdir(parents=True, exist_ok=True)
                tmp = self._path(url).with_suffix(".part")
                tmp.write_bytes(data)
                tmp.replace(self._path(url))
            except OSError:
                return False
            self._trim_locked(limit, keep=self._path(url))
        return True

    def _files(self) -> list[tuple[float, int, Path]]:
        out = []
        try:
            for p in self.folder.glob("*.img"):
                try:
                    st = p.stat()
                except OSError:
                    continue
                out.append((st.st_mtime, st.st_size, p))
        except OSError:
            pass
        return sorted(out)

    def _trim_locked(self, limit: int, keep: Path | None = None) -> int:
        files = self._files()
        total = sum(size for _m, size, _p in files)
        removed = 0
        for _mtime, size, path in files:  # oldest used first
            if total <= limit:
                break
            if path == keep:
                continue
            try:
                path.unlink()
            except OSError:
                continue
            total -= size
            removed += 1
        return removed

    def trim(self) -> int:
        """Make the folder fit the budget now (after the person lowered it). Returns how many images went."""
        with self._lock:
            return self._trim_locked(max(0, self._limit()))

    def size(self) -> int:
        return sum(size for _m, size, _p in self._files())

    def clear(self) -> int:
        with self._lock:
            files = self._files()
            for _m, _s, path in files:
                try:
                    path.unlink()
                except OSError:
                    pass
        return len(files)
