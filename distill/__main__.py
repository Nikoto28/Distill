"""Run with:  python -m distill   (or double-click Distill.pyw)."""
from __future__ import annotations

import sys


def run() -> int:
    if "--launch" in sys.argv[1:]:  # `Distill --launch game:<id>`: what a Sunshine entry runs. No window, no Qt, no first-start installs
        from .launcher import main as launch_main
        return launch_main(sys.argv[1:])
    from .bootstrap import ensure_dependencies, fatal, missing_qt_message

    ensure_dependencies()  # the first start of a source checkout installs PySide6 and py7zr
    try:
        from .app import main
    except ImportError as exc:
        if (exc.name or "").split(".")[0] != "PySide6":
            raise  # a real bug, not a missing dependency
        fatal(missing_qt_message(exc))
        return 1
    return main()


if __name__ == "__main__":
    sys.exit(run())
