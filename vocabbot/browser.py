"""Start Chrome windows, one profile per session."""
from __future__ import annotations

import functools
import os
import platform
import re
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import IO

import undetected_chromedriver as uc

_BASE_ARGS = (
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-notifications",
)
_DEFAULT_WINDOW_SIZE = "--window-size=1280,900"
_CASCADE_PX = 40  # offset each session's window so they don't stack exactly

_thread_lock = threading.Lock()


@functools.cache
def chrome_major_version() -> int | None:
    """Installed Chrome's major version, so the downloaded ChromeDriver matches it."""
    system = platform.system()
    if system == "Darwin":
        candidates = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    elif system == "Windows":
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
    else:
        candidates = ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"]

    for exe in candidates:
        try:
            result = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            continue
        match = re.search(r"(\d+)\.", result.stdout or result.stderr or "")
        if match:
            return int(match.group(1))
    return None


@contextmanager
def _launch_lock(lock_file: Path):
    """undetected_chromedriver downloads and patches one shared chromedriver binary on every
    launch, so launches must not overlap: across threads always, and across processes on
    macOS/Linux (flock). Running browsers are unaffected; only startup is serialized."""
    with _thread_lock:
        if os.name == "nt":
            yield
            return
        import fcntl

        lock_file.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_file, "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)


def lock_profile(profile_dir: Path) -> IO | None:
    """Claim a profile for this process. Returns an open handle to keep for the process's
    lifetime (the OS drops the lock on exit), or None if another vocabbot process holds it.
    Two Chromes on one profile don't work: the second hands off to the first and exits."""
    profile_dir.parent.mkdir(parents=True, exist_ok=True)
    fh = open(profile_dir.parent / f".{profile_dir.name}.lock", "a")
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def launch(profile_dir: Path, extra_args: tuple[str, ...], index: int) -> uc.Chrome:
    """Open a Chrome window using its own profile directory (logins persist between runs)."""
    profile_dir.mkdir(parents=True, exist_ok=True)

    options = uc.ChromeOptions()  # uc refuses to reuse an options object, so build one per launch
    args = [*_BASE_ARGS, *extra_args]
    if not any(a.startswith("--window-size") for a in args):
        args.append(_DEFAULT_WINDOW_SIZE)
    offset = index * _CASCADE_PX
    args.append(f"--window-position={offset},{offset}")
    for arg in args:
        options.add_argument(arg)

    with _launch_lock(profile_dir.parent / ".launch.lock"):
        return uc.Chrome(
            options=options,
            user_data_dir=str(profile_dir),
            version_main=chrome_major_version(),
        )
