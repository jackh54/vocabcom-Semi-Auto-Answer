"""Where vocabbot keeps its config, database, Chrome profiles and logs.

- Running from source: the repo folder (unchanged from before).
- Running the packaged app: the normal per-user app-data folder, since the program
  itself may sit in Downloads or be replaced by a newer version.
- VOCABBOT_HOME overrides both.
"""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

APP_NAME = "vocabbot"


def is_frozen() -> bool:
    """True when running as a PyInstaller-built executable."""
    return bool(getattr(sys, "frozen", False))


def app_home() -> Path:
    override = os.environ.get("VOCABBOT_HOME")
    if override:
        return Path(override).expanduser()
    if not is_frozen():
        return Path(__file__).resolve().parent.parent
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if system == "Windows":
        # Local, not Roaming: Chrome profiles are large and machine-specific.
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP_NAME
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / APP_NAME
