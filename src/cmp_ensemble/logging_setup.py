"""Rich-backed logging configuration."""

from __future__ import annotations

import logging
from pathlib import Path

from rich.logging import RichHandler


def setup_logging(
    level: str = "INFO",
    log_dir: Path | None = None,
    file_level: str = "DEBUG",
) -> None:
    """Configure root logger with a rich console handler and optional file handler.

    Safe to call multiple times — existing handlers are cleared first.
    """
    # Force UTF-8 on the console so Cyrillic / arrows in log messages don't crash
    # the RichHandler on a cp1251 Windows terminal (errors='replace' is a backstop).
    import sys

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for h in list(root.handlers):
        root.removeHandler(h)

    console = RichHandler(rich_tracebacks=True, show_time=True, show_path=False)
    console.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.addHandler(console)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = log_dir / f"{stamp}.log"
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setLevel(getattr(logging, file_level.upper(), logging.DEBUG))
        fh.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root.addHandler(fh)
