"""Runs sessions on demand for a UI: start/stop per account, settings, and a state snapshot.

The CLI starts every session up front; the desktop app starts and stops accounts while it
runs, so this keeps that bookkeeping (threads, profile locks, settings) in one place.
"""
from __future__ import annotations

import collections
import json
import logging
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO

import openai

from . import __version__, browser
from .accounts import list_accounts, valid_name
from .answerer import Answerer
from .config import Config, ConfigError, MissingKeyError, load_config, write_initial_config
from .session import Session
from .store import Store

log = logging.getLogger(__name__)


@dataclass
class _Running:
    session: Session
    thread: threading.Thread
    stop: threading.Event
    lock: IO | None


class _EventFeed(logging.Handler):
    """Keeps recent session log lines (picks, completions) for the activity feed."""

    def __init__(self, size: int = 300):
        super().__init__(level=logging.INFO)
        self._items: collections.deque = collections.deque(maxlen=size)
        self._seq = 0
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        name = record.name.split("vocabbot.session.", 1)[-1]  # account names may contain dots
        with self._lock:
            self._seq += 1
            self._items.append({"id": self._seq, "time": record.created, "session": name,
                                "level": record.levelname.lower(), "text": record.getMessage()})

    def since(self, last_id: int) -> list[dict]:
        with self._lock:
            return [e for e in self._items if e["id"] > last_id]


class Controller:
    def __init__(self, home: Path):
        self.home = home
        self.data = home / "data"
        self.profiles = self.data / "profiles"
        self.config_path = home / "config.json"
        self.store = Store(self.data / "vocabbot.db")
        self.store.import_legacy(home / "question_cache.json", home / "statistics.json")
        self.config: Config | None = None
        self.answerer: Answerer | None = None
        self._running: dict[str, _Running] = {}
        self._lock = threading.RLock()
        self._accounts_cache: tuple[float, list[dict]] | None = None
        self.feed = _EventFeed()
        logging.getLogger("vocabbot.session").addHandler(self.feed)
        self.reload_config()

    # ---- settings ------------------------------------------------------

    def reload_config(self) -> str | None:
        """Load config.json. Returns an error message, or None when ready to run."""
        try:
            self.config = load_config(self.config_path)
        except MissingKeyError:
            self.config = None
            return "missing_key"
        except ConfigError as e:
            self.config = None
            return str(e)
        self.answerer = Answerer(self.config.openai_api_key, self.config.model)
        return None

    def set_api_key(self, key: str) -> str | None:
        """Check the key with OpenAI (free call) and save it. Returns an error message or None."""
        key = key.strip()
        if not key:
            return "Enter your OpenAI API key."
        model = self.config.model if self.config else None
        try:
            Answerer(key, model or "gpt-4o-mini").check()
        except openai.AuthenticationError:
            return "OpenAI rejected that key. Check it at platform.openai.com/api-keys."
        except openai.OpenAIError as e:
            return f"Couldn't check the key: {e}"
        write_initial_config(self.config_path, key)
        return self.reload_config()

    def settings(self) -> dict:
        c = self.config
        return {
            "has_key": c is not None,
            "key_hint": f"…{c.openai_api_key[-4:]}" if c else "",
            "model": c.model if c else "gpt-4o-mini",
            "min_wait": c.min_wait if c else 3,
            "max_wait": c.max_wait if c else 5,
            "home": str(self.home),
            "version": __version__,
        }

    def save_settings(self, model: str, min_wait: float, max_wait: float) -> str | None:
        model = (model or "").strip()
        try:
            min_wait, max_wait = float(min_wait), float(max_wait)
        except (TypeError, ValueError):
            return "Wait times must be numbers."
        if not model:
            return "Enter a model name."
        if min_wait < 0 or max_wait < min_wait or max_wait > 120:
            return "Use a shortest wait of 0 or more, and a longest wait between that and 120 seconds."
        if self.config and model != self.config.model:
            try:
                Answerer(self.config.openai_api_key, model).check()
            except openai.NotFoundError:
                return f"OpenAI doesn't offer a model called {model!r} on this key."
            except openai.OpenAIError as e:
                return f"Couldn't check the model: {e}"
        raw = json.loads(self.config_path.read_text()) if self.config_path.exists() else {}
        raw.update({"model": model, "min_wait_time": min_wait, "max_wait_time": max_wait})
        self.config_path.write_text(json.dumps(raw, indent=2) + "\n")
        return self.reload_config()  # applies to sessions started from now on

    # ---- accounts ------------------------------------------------------

    def accounts(self, max_age: float = 2.0) -> list[dict]:
        """Saved accounts. Checking whether another vocabbot has a profile open briefly takes its
        lock file, so the check runs under self._lock (never alongside start/forget in this app)
        and at most every max_age seconds."""
        now = time.monotonic()
        if self._accounts_cache and now - self._accounts_cache[0] < max_age:
            return self._accounts_cache[1]
        names = self.store.account_names()
        with self._lock:
            running = {n for n, r in self._running.items() if r.thread.is_alive()}
            found = list_accounts(self.profiles, skip=running)
        out = []
        for a in found:
            out.append({
                "name": a.name,
                "display_name": names.get(a.name, ""),
                "last_used": a.last_used.timestamp() if a.last_used else None,
                "running": a.name in running,
                "elsewhere": a.in_use and a.name not in running,
            })
        self._accounts_cache = (now, out)
        return out

    def next_account_name(self) -> str:
        existing = {a.name for a in list_accounts(self.profiles)} | set(self._running)
        i = 1
        while f"account-{i}" in existing:
            i += 1
        return f"account-{i}"

    def forget_account(self, name: str) -> str | None:
        """Delete an account's Chrome profile (its saved login). Not allowed while it runs."""
        if not valid_name(name):
            return "Invalid account name."
        with self._lock:  # held throughout, so start() can't begin this account mid-delete
            r = self._running.get(name)
            if r and r.thread.is_alive():
                return "Stop this account before removing it."
            profile = self.profiles / name
            lock = browser.lock_profile(profile)
            if lock is None:
                return "This account is open in another vocabbot."
            try:
                if profile.is_dir():
                    shutil.rmtree(profile)
            finally:
                lock.close()
            self._running.pop(name, None)
            self._accounts_cache = None
        return None

    # ---- sessions ------------------------------------------------------

    def start(self, name: str) -> str | None:
        """Open a Chrome window for this account and start answering. Returns an error or None."""
        if self.config is None or self.answerer is None:
            return "Add your OpenAI API key first."
        if not valid_name(name):
            return "Use letters, numbers, - _ or . for the account name."
        with self._lock:
            current = self._running.get(name)
            if current and current.thread.is_alive():
                return None  # already running
            lock = browser.lock_profile(self.profiles / name)
            if lock is None:
                return f"{name} is open in another vocabbot."
            index = self._free_slot()
            stop = threading.Event()
            session = Session(name, index, self.profiles / name, self.config, self.store, self.answerer, stop)
            thread = threading.Thread(target=self._run, args=(name, session), name=name, daemon=True)
            self._running[name] = _Running(session, thread, stop, lock)
            self._accounts_cache = None
            thread.start()
        return None

    def stop(self, name: str) -> None:
        with self._lock:
            r = self._running.get(name)
        if r:
            r.stop.set()

    def stop_all(self) -> None:
        with self._lock:
            for r in self._running.values():
                r.stop.set()

    def dismiss(self, name: str) -> None:
        """Remove a finished session's panel."""
        with self._lock:
            r = self._running.get(name)
            if r and not r.thread.is_alive():
                del self._running[name]

    def shutdown(self, timeout: float = 15) -> None:
        self.stop_all()
        deadline = time.monotonic() + timeout
        with self._lock:
            running = list(self._running.values())
        for r in running:
            r.thread.join(max(0.0, deadline - time.monotonic()))
            if r.thread.is_alive() and r.session.status.state == "launching":
                r.thread.join(30)  # Chrome is still starting; let it finish so it can be closed
            r.session.close()  # anything stuck in a WebDriver call
        self.store.close()

    def _run(self, name: str, session: Session) -> None:
        try:
            session.run()
        finally:
            with self._lock:
                r = self._running.get(name)
                if r and r.lock:
                    r.lock.close()  # release the profile for other processes
                    r.lock = None

    def _free_slot(self) -> int:
        used = {r.session.index for r in self._running.values() if r.thread.is_alive()}
        i = 0
        while i in used:
            i += 1
        return i

    # ---- snapshot for the UI ------------------------------------------

    def snapshot(self, events_since: int = 0) -> dict:
        with self._lock:
            items = list(self._running.items())
        sessions = []
        for name, r in items:
            st = r.session.status
            sessions.append({
                "name": name, "account": st.account, "state": st.state, "detail": st.detail,
                "correct": st.correct, "wrong": st.wrong, "cache_hits": st.cache_hits,
                "ai_calls": st.ai_calls, "done": st.assignments_done,
                "seconds": int(time.monotonic() - st.started),
                "alive": r.thread.is_alive(), "stopping": r.stop.is_set() and r.thread.is_alive(),
            })
        c = self.store.counters()
        lookups = c["cache_hits"] + c["cache_misses"]
        return {
            "sessions": sessions,
            "totals": {**c, "answers_cached": self.store.answer_count(),
                       "hit_rate": round(100 * c["cache_hits"] / lookups) if lookups else None},
            "events": self.feed.since(events_since),
        }
