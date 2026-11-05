"""Run one or more Vocabulary.com sessions side by side, one per account.

    python main.py                 # pick saved accounts (or add new ones) from a list
    python main.py -a alice -a bob # skip the list: run these accounts
    python main.py -n 3            # three throwaway-named windows: session-1..session-3
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

from vocabbot import accounts, browser, dashboard
from vocabbot.accounts import valid_name
from vocabbot.answerer import Answerer
from vocabbot.config import ConfigError, load_config
from vocabbot.session import Session
from vocabbot.store import Store

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
LOG_FILE = ROOT / "logs" / "vocabbot.log"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Vocabulary.com answer automation")
    parser.add_argument("-a", "--account", "-p", "--profile", dest="profile", action="append", default=[],
                        metavar="NAME", help="account to run; repeat for more. New names are created. "
                                             "Each account keeps its own saved login. Skips the picker")
    parser.add_argument("-n", "--sessions", type=int, default=None,
                        help="open N sessions named session-1..N instead of picking accounts")
    parser.add_argument("-c", "--config", type=Path, default=ROOT / "config.json")
    args = parser.parse_args(argv)
    if args.sessions is not None and args.sessions < 1:
        parser.error("--sessions must be at least 1")
    if len(set(args.profile)) != len(args.profile):
        parser.error("account names must be unique (two windows can't share one Chrome profile)")
    bad = [n for n in args.profile if not valid_name(n)]
    if bad:
        parser.error(f"invalid account name {bad[0]!r}: use letters, numbers, - _ . (not only digits)")
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


def claim_profiles(names: list[str] | None, count: int):
    """Lock the profiles this process will use. With explicit names, every one must be free.
    Without, take the first `count` free session-N names (so two terminals get different ones).
    Returns (names, lock handles), or (None, taken_name) if an explicit name is busy."""
    profiles = DATA / "profiles"
    if names:
        locks = []
        for name in names:
            fh = browser.lock_profile(profiles / name)
            if fh is None:
                return None, name
            locks.append(fh)
        return list(names), locks

    names, locks, i = [], [], 1
    while len(names) < count:
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

    names = args.profile
    if not names and args.sessions is None:
        try:
            names = accounts.pick(console, DATA / "profiles", store.account_names()) if sys.stdin.isatty() else ["session-1"]
        except (KeyboardInterrupt, EOFError):
            store.close()
            return 0
    names, profile_locks = claim_profiles(names, args.sessions or 1)
    if names is None:
        console.print(f"[red]Account {profile_locks!r} is already in use by another running vocabbot.[/] "
                      "Pick a different one.")
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
