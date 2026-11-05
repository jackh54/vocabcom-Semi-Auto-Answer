"""Run one or more Vocabulary.com sessions side by side.

    python main.py                 # one session
    python main.py -n 3            # three windows: session-1..session-3
    python main.py -p alice -p bob # named sessions (each keeps its own login)
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

import openai
from rich.console import Console

from vocabbot import browser, dashboard
from vocabbot.answerer import Answerer
from vocabbot.config import ConfigError, load_config
from vocabbot.session import Session
from vocabbot.store import Store

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
LOG_FILE = ROOT / "logs" / "vocabbot.log"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Vocabulary.com answer automation")
    parser.add_argument("-n", "--sessions", type=int, default=1,
                        help="number of browser sessions to open (default 1)")
    parser.add_argument("-p", "--profile", action="append", default=[], metavar="NAME",
                        help="named session; repeat for more. Overrides -n. Each name keeps its own Chrome login")
    parser.add_argument("-c", "--config", type=Path, default=ROOT / "config.json")
    args = parser.parse_args(argv)
    if args.sessions < 1:
        parser.error("--sessions must be at least 1")
    if len(set(args.profile)) != len(args.profile):
        parser.error("profile names must be unique (two windows can't share one Chrome profile)")
    return args


def setup_logging(level: str) -> None:
    LOG_FILE.parent.mkdir(exist_ok=True)
    handler = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level, logging.INFO))
    for noisy in ("urllib3", "selenium", "httpx", "httpcore", "openai", "undetected_chromedriver"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def claim_profiles(args: argparse.Namespace):
    """Pick profile names this process can own. With -n, skip names another running
    vocabbot already holds (so two terminals get session-1.. and session-2..).
    Returns (names, lock handles), or (None, taken_name) if an explicit -p name is busy."""
    profiles = DATA / "profiles"
    if args.profile:
        locks = []
        for name in args.profile:
            fh = browser.lock_profile(profiles / name)
            if fh is None:
                return None, name
            locks.append(fh)
        return list(args.profile), locks

    names, locks, i = [], [], 1
    while len(names) < args.sessions:
        fh = browser.lock_profile(profiles / f"session-{i}")
        if fh is not None:
            names.append(f"session-{i}")
            locks.append(fh)
        i += 1
    return names, locks


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    console = Console()

    try:
        config = load_config(args.config)
    except ConfigError as e:
        console.print(f"[red]Config error:[/] {e}")
        return 1
    setup_logging(config.log_level)

    answerer = Answerer(config.openai_api_key, config.model)
    try:
        answerer.check()
    except openai.OpenAIError as e:
        console.print(f"[red]OpenAI check failed for model {config.model!r}:[/] {e}")
        return 1

    store = Store(DATA / "vocabbot.db")
    imported = store.import_legacy(ROOT / "question_cache.json", ROOT / "statistics.json")
    if imported:
        console.print(f"Imported {imported} cached answers from question_cache.json")

    names, profile_locks = claim_profiles(args)
    if names is None:
        console.print(f"[red]Profile {profile_locks!r} is already in use by another running vocabbot.[/] "
                      "Pick a different -p name.")
        store.close()
        return 1
    stop = threading.Event()
    sessions = [Session(name, i, DATA / "profiles" / name, config, store, answerer, stop)
                for i, name in enumerate(names)]
    threads = [threading.Thread(target=s.run, name=s.name, daemon=True) for s in sessions]
    for t in threads:
        t.start()

    console.print(f"Opening {len(sessions)} Chrome window(s). Sign in and open an assignment in each; "
                  f"they start on their own. Log: {LOG_FILE.relative_to(ROOT)}")
    try:
        dashboard.run(sessions, threads, store, stop, console)
    except KeyboardInterrupt:
        console.print("\nStopping...")
    finally:
        stop.set()
        try:
            for t in threads:
                t.join(timeout=15)
        except KeyboardInterrupt:
            pass  # second Ctrl+C: stop waiting, but still close the windows below
        for s in sessions:  # anything still stuck in a WebDriver call
            s.close()
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
