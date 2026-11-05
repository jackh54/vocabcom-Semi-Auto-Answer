"""Command-line app: run one or more Vocabulary.com sessions side by side, one per account.

    python main.py                 # pick saved accounts (or add new ones) from a list
                                   # (packaged app: just run `vocabbot` / vocabbot.exe)
    python main.py -a alice -a bob # skip the list: run these accounts
    python main.py -n 3            # three throwaway-named windows: session-1..session-3
"""
from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

import openai
from rich.console import Console
from rich.prompt import Prompt

from vocabbot import __version__, accounts, browser, dashboard
from vocabbot.accounts import valid_name
from vocabbot.answerer import Answerer
from vocabbot.config import ConfigError, MissingKeyError, load_config, write_initial_config
from vocabbot.logfile import setup_logging
from vocabbot.paths import app_home, is_frozen
from vocabbot.session import Session
from vocabbot.store import Store

HOME = app_home()          # repo folder from source; per-user app folder when packaged
DATA = HOME / "data"
LOG_FILE = HOME / "logs" / "vocabbot.log"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Vocabulary.com answer automation")
    parser.add_argument("-a", "--account", "-p", "--profile", dest="profile", action="append", default=[],
                        metavar="NAME", help="account to run; repeat for more. New names are created. "
                                             "Each account keeps its own saved login. Skips the picker")
    parser.add_argument("-n", "--sessions", type=int, default=None,
                        help="open N sessions named session-1..N instead of picking accounts")
    parser.add_argument("-c", "--config", type=Path, default=HOME / "config.json")
    parser.add_argument("--version", action="version", version=f"vocabbot {__version__}")
    args = parser.parse_args(argv)
    if args.sessions is not None and args.sessions < 1:
        parser.error("--sessions must be at least 1")
    if len(set(args.profile)) != len(args.profile):
        parser.error("account names must be unique (two windows can't share one Chrome profile)")
    bad = [n for n in args.profile if not valid_name(n)]
    if bad:
        parser.error(f"invalid account name {bad[0]!r}: use letters, numbers, - _ . (not only digits)")
    return args


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


def first_run_setup(console: Console, config_path: Path, first: bool = True):
    """Ask for an API key and save it, so the packaged app works without editing files."""
    if first:
        console.print("[bold]First run.[/] vocabbot needs an OpenAI API key (https://platform.openai.com/api-keys). "
                      f"It's saved only in {config_path}.")
    try:
        key = Prompt.ask("OpenAI API key", password=True, console=console).strip()
    except (KeyboardInterrupt, EOFError):
        return None
    if not key:
        console.print("[red]No key entered.[/]")
        return None
    write_initial_config(config_path, key)
    try:
        return load_config(config_path)
    except ConfigError as e:
        console.print(f"[red]Config error:[/] {e}")
        return None


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    console = Console()

    if is_frozen():
        console.print(f"vocabbot {__version__}  ·  data folder: {HOME}")
    try:
        config = load_config(args.config)
    except MissingKeyError as e:
        if not sys.stdin.isatty():
            console.print(f"[red]Config error:[/] {e}")
            return 1
        config = first_run_setup(console, args.config)
        if config is None:
            return 1
    except ConfigError as e:
        console.print(f"[red]Config error:[/] {e}")
        return 1
    setup_logging(LOG_FILE, config.log_level)

    answerer = Answerer(config.openai_api_key, config.model)
    for attempt in range(3):
        try:
            answerer.check()
            break
        except openai.AuthenticationError:
            # Rejected key (typo on first run, revoked, ...): ask again rather than failing every launch.
            console.print("[red]OpenAI rejected that API key.[/]")
            if attempt == 2 or not sys.stdin.isatty():
                return 1
            config = first_run_setup(console, args.config, first=False)
            if config is None:
                return 1
            answerer = Answerer(config.openai_api_key, config.model)
        except openai.OpenAIError as e:
            console.print(f"[red]OpenAI check failed for model {config.model!r}:[/] {e}")
            return 1

    store = Store(DATA / "vocabbot.db")
    imported = store.import_legacy(HOME / "question_cache.json", HOME / "statistics.json")
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
                  f"they start on their own. Log: {LOG_FILE}")
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


def run() -> None:
    """Entry point for main.py and the packaged executable."""
    code = main(sys.argv[1:])
    # A double-clicked .exe closes its window on exit; keep errors readable.
    if code and is_frozen() and sys.stdin.isatty():
        try:
            input("Press Enter to close...")
        except (KeyboardInterrupt, EOFError):
            pass
    sys.exit(code)
