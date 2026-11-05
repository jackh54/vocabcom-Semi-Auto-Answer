"""File logging shared by the CLI and the desktop app."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(log_file: Path, level: str = "INFO") -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for noisy in ("urllib3", "selenium", "httpx", "httpcore", "openai", "undetected_chromedriver", "pywebview"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
