"""Answer cache and lifetime counters in SQLite.

SQLite (WAL mode) is safe to share between every session thread in this process and
between separate `python main.py` processes, which the old JSON files were not.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

COUNTERS = ("correct_answers", "wrong_answers", "achievements", "cache_hits", "cache_misses")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS answers (
    key        TEXT PRIMARY KEY,   -- normalized question + sorted normalized choices
    answer     TEXT NOT NULL,      -- normalized text of the correct choice
    question   TEXT NOT NULL,      -- original question, for debugging
    choices    TEXT NOT NULL,      -- original choices as a JSON list, for debugging
    first_seen REAL NOT NULL,
    last_used  REAL NOT NULL,
    times_used INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS counters (
    name  TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meta (
    name  TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_PUNCTUATION = re.compile(r"[^\w\s']")


def normalize(text: str) -> str:
    """Lowercase, drop punctuation except apostrophes, collapse whitespace."""
    return " ".join(_PUNCTUATION.sub("", text.lower()).split())


def cache_key(question: str, choices: list[str]) -> str:
    """Order-independent key. Includes the sentence context, so the same prompt with
    different example sentences gets separate entries."""
    return "|".join([normalize(question), *sorted(normalize(c) for c in choices)])


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, timeout=30, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=30000")
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ---- answers -------------------------------------------------------

    def lookup(self, question: str, choices: list[str]) -> int | None:
        """Index of the cached correct choice, or None."""
        key = cache_key(question, choices)
        with self._lock:
            row = self._db.execute("SELECT answer FROM answers WHERE key = ?", (key,)).fetchone()
            if row is None:
                return None
            for i, choice in enumerate(choices):
                if normalize(choice) == row[0]:
                    self._db.execute(
                        "UPDATE answers SET last_used = ?, times_used = times_used + 1 WHERE key = ?",
                        (time.time(), key),
                    )
                    return i
        return None

    def remember(self, question: str, choices: list[str], index: int) -> None:
        self._upsert(cache_key(question, choices), normalize(choices[index]), question, choices)

    def forget(self, question: str, choices: list[str]) -> None:
        with self._lock:
            self._db.execute("DELETE FROM answers WHERE key = ?", (cache_key(question, choices),))

    def answer_count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM answers").fetchone()[0]

    def _upsert(self, key: str, answer: str, question: str, choices: list[str]) -> None:
        with self._lock:
            self._upsert_unlocked(key, answer, question, choices)

    def _upsert_unlocked(self, key: str, answer: str, question: str, choices: list[str]) -> None:
        now = time.time()
        self._db.execute(
            """INSERT INTO answers (key, answer, question, choices, first_seen, last_used)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                   answer = excluded.answer,
                   last_used = excluded.last_used,
                   times_used = times_used + 1""",
            (key, answer, question, json.dumps(choices), now, now),
        )

    # ---- counters ------------------------------------------------------

    def incr(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._incr_unlocked(name, amount)

    def _incr_unlocked(self, name: str, amount: int) -> None:
        self._db.execute(
            """INSERT INTO counters (name, value) VALUES (?, ?)
               ON CONFLICT(name) DO UPDATE SET value = value + excluded.value""",
            (name, amount),
        )

    def counters(self) -> dict[str, int]:
        with self._lock:
            rows = dict(self._db.execute("SELECT name, value FROM counters").fetchall())
        return {name: rows.get(name, 0) for name in COUNTERS}

    # ---- one-time import of the old JSON files -------------------------

    def import_legacy(self, cache_json: Path, stats_json: Path) -> int:
        """Copy question_cache.json / statistics.json into the database once. Returns answers imported.

        Check, import and marker run in one IMMEDIATE transaction, so two processes starting
        together (or a crash midway) can't import twice and double the counters."""
        entries = _read_json(cache_json)
        stats = _read_json(stats_json)

        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                if self._db.execute("SELECT 1 FROM meta WHERE name = 'legacy_imported'").fetchone():
                    self._db.execute("ROLLBACK")
                    return 0
                imported = 0
                for entry in entries.values():
                    question = entry.get("original_question")
                    choices = entry.get("original_choices")
                    answer = entry.get("normalized_answer")
                    if question is None or not choices or not answer:
                        continue
                    self._upsert_unlocked(cache_key(question, choices), answer, question, choices)
                    imported += 1
                for name in COUNTERS:
                    if isinstance(stats.get(name), int):
                        self._incr_unlocked(name, stats[name])
                self._db.execute("INSERT INTO meta (name, value) VALUES ('legacy_imported', ?)",
                                 (str(time.time()),))
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

        if imported:
            log.info("Imported %d cached answers from %s", imported, cache_json.name)
        return imported


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        log.warning("Skipping unreadable %s", path)
        return {}
    return data if isinstance(data, dict) else {}
