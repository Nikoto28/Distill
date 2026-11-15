"""Put Distill's library in Sunshine, so Moonlight shows it as a grid of posters and starts a game with one tap.

Sunshine (the host) keeps its list of apps in apps.json. For each game and each installed PC recomp this adds one entry whose command is
`Distill --launch game:<id>` (see launcher.py), with the poster as its cover. Distill stays the one place that knows which emulator, core and
launch options a game needs, so changing any of them in Distill changes the next stream too, and the play time of a streamed session is counted.

An entry that is already in the file is left exactly as it is (including one the player edited in Sunshine); only games that aren't there yet are
added. Entries Distill didn't write are never touched and nothing is ever removed, and the file is backed up once before its first change.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from . import games as gm
from . import launcher
from . import recomps as rc
from .constants import APP_DIR

BACKUP_SUFFIX = ".distill-backup"
_TARGET_IN_CMD = re.compile(r"--launch(?:=|\s+)\"?((?:game|recomp):[A-Za-z0-9._-]+)\"?")


# ---- how Sunshine starts Distill ----------------------------------------------------------------------------------------
def distill_argv(frozen: bool | None = None, executable: str | None = None, app_dir: Path | None = None, plat: str | None = None) -> list[str]:
    """The program (and anything it needs before the arguments) that starts Distill: the .exe of a packaged build, or Python and Distill.pyw
    from a source checkout (pythonw on Windows, so no console window opens over the stream)."""
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    exe = executable or sys.executable
    app_dir = app_dir or APP_DIR
    plat = plat or sys.platform
    if frozen:
        return [exe]
    if plat == "win32" and Path(exe).name.lower() == "python.exe":
        windowless = Path(exe).with_name("pythonw.exe")
        if windowless.is_file():
            exe = str(windowless)
    script = app_dir / "Distill.pyw"
    return [exe, str(script)] if script.is_file() else [exe, "-m", "distill"]


def command_line(argv: list[str], plat: str | None = None) -> str:
    """One string for Sunshine's `cmd`, quoted for the system it will run on."""
    if (plat or sys.platform) == "win32":
        return subprocess.list2cmdline(argv)
    import shlex  # noqa: PLC0415
    return shlex.join(argv)


def entry_command(kind: str, ident: str, base: list[str] | None = None, plat: str | None = None) -> str:
    return command_line([*(base if base is not None else distill_argv()), launcher.FLAG, launcher.target(kind, ident)], plat)


def target_of(app: object) -> str:
    """'game:g1a2b3c' when a Sunshine app entry starts a Distill game, else ''."""
    if not isinstance(app, dict):
        return ""
    m = _TARGET_IN_CMD.search(str(app.get("cmd", "")))
    return m.group(1) if m else ""


# ---- where Sunshine keeps apps.json -----------------------------------------------------------------------------------
def apps_file_candidates(env: dict | None = None, plat: str | None = None, home: Path | None = None) -> list[Path]:
    env = os.environ if env is None else env
    plat = plat or sys.platform
    home = home or Path.home()
    if plat == "win32":
        bases = [env.get("ProgramFiles"), env.get("ProgramW6432"), env.get("ProgramFiles(x86)"), r"C:\Program Files"]
        return [Path(b) / "Sunshine" / "config" / "apps.json" for b in dict.fromkeys(b for b in bases if b)]
    return [home / ".config" / "sunshine" / "apps.json",
            home / ".var" / "app" / "dev.lizardbyte.app.Sunshine" / "config" / "sunshine" / "apps.json"]


def find_apps_file(**kw) -> Path | None:
    """Sunshine's apps.json where it normally lives, when it is there."""
    return next((p for p in apps_file_candidates(**kw) if p.is_file()), None)


# ---- the export ------------------------------------------------------------------------------------------------------
@dataclass(slots=True)
class SunshineReport:
    file: str = ""
    added: int = 0
    kept: int = 0  # entries Distill had written before
    covers: int = 0
    left_out: dict[str, int] = field(default_factory=dict)  # why games weren't included -> how many
    skipped: str = ""  # why the file was left alone ('' = written or already complete)
    backup: str = ""

    def summary(self) -> str:
        if self.skipped:
            return f"{Path(self.file).name} was left alone: {self.skipped}"
        lines = [f"{self.added} app{'s' if self.added != 1 else ''} added to {self.file}, {self.kept} already there."
                 if self.added else f"Nothing new to add: all {self.kept} are already in {self.file}." if self.kept else "Nothing to export."]
        if self.added:
            lines.append("If Moonlight doesn't show them yet, restart Sunshine.")
        if self.left_out:
            lines.append("Left out: " + ", ".join(f"{n} {why}" for why, n in self.left_out.items()) + ".")
        return "\n\n".join(lines)


def _read(path: Path) -> dict | None:
    """Sunshine's apps.json, or None when it isn't the JSON object Sunshine writes (a damaged file is never overwritten)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("apps", []), list) else None


def _write_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.stem + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp)


def covers_dir() -> Path:
    d = rc.root() / "sunshine-covers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def png_cover(src: Path | None, ident: str, to_png: Callable[[Path, Path], bool] | None, folder: Path | None = None) -> str:
    """A PNG file Sunshine can use as the app's cover ('' = none). Sunshine reads PNG, so another image type is converted (by `to_png`, which
    the window supplies because Qt does the decoding); a conversion that is already up to date is reused."""
    if src is None or not src.is_file():
        return ""
    if src.suffix.lower() == ".png":
        return str(src)
    if to_png is None:
        return ""
    dst = (folder or covers_dir()) / f"{ident}.png"
    with contextlib.suppress(OSError):
        if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
            return str(dst)
    try:
        return str(dst) if to_png(src, dst) and dst.is_file() else ""
    except (OSError, ValueError):
        return ""


def _unique(name: str, taken: set[str], extras: Iterable[str]) -> str:
    """Sunshine tells apps apart by name, so two with the same one get a qualifier ('Sonic (Mega Drive)'), then a number."""
    name = re.sub(r"\s+", " ", name).strip() or "Game"
    if name.casefold() not in taken:
        return name
    for extra in extras:
        if extra and (candidate := f"{name} ({extra})").casefold() not in taken:
            return candidate
    n = 2
    while f"{name} ({n})".casefold() in taken:
        n += 1
    return f"{name} ({n})"


def export_sunshine(store: gm.GameStore, apps_file: Path | str, rc_store: rc.Store | None = None, *, favourites_only: bool = True,
                    recomps: bool = True, to_png: Callable[[Path, Path], bool] | None = None, base: list[str] | None = None,
                    plat: str | None = None, progress: Callable[[str], None] | None = None) -> SunshineReport:
    """Add the library to Sunshine's apps.json. `favourites_only` keeps a big library from filling Moonlight's grid; installed PC recomps are
    included unless `recomps` is off. Raises OSError when the file can't be written (Sunshine's folder in Program Files often needs an
    administrator): the caller says so in words."""
    apps_file = Path(apps_file)
    report = SunshineReport(str(apps_file))
    if apps_file.exists():
        data = _read(apps_file)
        if data is None:
            report.skipped = "it isn't the JSON file Sunshine writes, so Distill didn't dare change it"
            return report
    else:
        data = {"env": {}, "apps": []}
    apps = data.setdefault("apps", [])
    have = {t for a in apps if (t := target_of(a))}
    taken = {str(a.get("name", "")).casefold() for a in apps if isinstance(a, dict)}
    base = base if base is not None else distill_argv()
    workdir = str(APP_DIR)  # (the folder holding Distill.exe, or the source checkout)
    new: list[dict] = []
    left = report.left_out

    def add(kind: str, ident: str, name: str, extras: list[str], cover: Path | None) -> None:
        tgt = launcher.target(kind, ident)
        if tgt in have:
            report.kept += 1
            return
        have.add(tgt)
        image = png_cover(cover, f"{kind}-{ident}", to_png)
        entry = {"name": _unique(name, taken, extras), "cmd": entry_command(kind, ident, base, plat), "working-dir": workdir}
        taken.add(entry["name"].casefold())
        if image:
            entry["image-path"] = image
            report.covers += 1
        new.append(entry)

    if rc_store is not None and recomps:
        catalog = {r.id: r for r in rc.load_catalog()}
        for rid in sorted(rc_store.data.get("installed") or {}):
            inst = rc_store.installed(rid)
            if inst is None or not inst.exe_path().exists():
                continue
            r = catalog.get(rid)
            if progress:
                progress(r.name if r else rid)
            add("recomp", rid, (r.game or r.name) if r else rid, [r.name if r else "", "PC port"], rc.cached_cover(r) if r else None)
    for g in store.games(favorites=favourites_only):
        if not g.installed or not g.path:
            left["not downloaded yet"] = left.get("not downloaded yet", 0) + 1
            continue
        if progress:
            progress(g.name)
        add("game", g.id, g.name, [g.system], gm.cover_path(g))
    if new:
        if apps_file.exists():
            backup = apps_file.with_name(apps_file.name + BACKUP_SUFFIX)
            if not backup.exists():
                shutil.copy2(apps_file, backup)
                report.backup = str(backup)
        apps.extend(new)
        _write_atomic(apps_file, data)
        report.added = len(new)
    return report
