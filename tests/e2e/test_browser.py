"""Browser tests: real headless Chrome against local mock pages that copy Vocabulary.com's markup
(practice quiz, assignments page, VocabTrainer). No network, no OpenAI: a stand-in "AI" always
picks the first choice it hasn't tried, which exercises the wrong-answer paths.

Slow (about 2 minutes) and need Chrome, so they only run when asked:
    VOCABBOT_E2E=1 python -m pytest tests/e2e -q
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("VOCABBOT_E2E") != "1", reason="set VOCABBOT_E2E=1 to run browser tests")

PAGES = Path(__file__).parent / "pages"


class FirstUntriedAI:
    SPELLINGS = {"small": ["small", "tiny"],            # wrong first, then right
                 "breeze": ["wind", "breeze", "gust"]}  # never right: ends with GIVE UP

    def spell(self, sentence, exclude=()):
        for clue, guesses in self.SPELLINGS.items():
            if clue in sentence:
                return next((g for g in guesses if g not in exclude), None)
        return None

    def choose(self, question, choices, exclude=()):
        if question.startswith("stubborn"):
            return 0  # keeps repeating a wrong answer, like a stubborn model
        return next(i for i in range(len(choices)) if i not in exclude)


def wait_for(cond, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.3)
    return False


@pytest.fixture
def make_session(tmp_path):
    from vocabbot.config import Config
    from vocabbot.session import Session
    from vocabbot.store import Store

    store = Store(tmp_path / "db.sqlite")
    config = Config(openai_api_key="x", chrome_args=("--headless=new",), min_wait=0.4, max_wait=0.6)
    started = []

    def make(name: str, page: str, query: str = "", index: int = 0):
        stop = threading.Event()
        s = Session(name, index, tmp_path / "profiles" / name, config, store, FirstUntriedAI(), stop)
        s.start_url = (PAGES / page).as_uri() + (f"?{query}" if query else "")
        t = threading.Thread(target=s.run, daemon=True)
        t.start()
        started.append((s, t, stop))
        return s

    yield make
    for s, t, stop in started:
        stop.set()
    for s, t, stop in started:
        t.join(20)
    store.close()


def test_practice_page_wrong_answers_and_completion(make_session):
    s = make_session("p", "practice.html")
    assert wait_for(lambda: s.status.state == "done", 120), s.status
    # normal: 1 wrong then right; stubborn AI: 2 wrong; silent markers: not counted; premarked: skipped
    assert (s.status.correct, s.status.wrong, s.status.assignments_done) == (4, 3, 1)


def test_assignments_shared_then_per_account(make_session):
    from vocabbot.assignments import shared_ids

    alice = make_session("alice", "activities.html", "acct=a", 0)
    bob = make_session("bob", "activities.html", "acct=b", 1)
    assert wait_for(lambda: alice.status.state == "choosing" and bob.status.state == "choosing", 60)
    ids_a = [a["id"] for a in alice.status.assignments]
    ids_b = [a["id"] for a in bob.status.assignments]
    assert shared_ids([alice.status.assignments, bob.status.assignments]) == ["u8"]
    assert "bee" in ids_a and "b-only" in ids_b

    assert alice.request_assignment("u8") is None and bob.request_assignment("u8") is None
    assert wait_for(lambda: alice.status.state == "done" and bob.status.state == "done", 120)
    assert alice.status.correct == 4 and bob.status.correct == 4
    assert wait_for(lambda: len(bob.status.assignments) == 2, 30)  # list reloaded on the assignments page

    assert "aren't supported" in alice.request_assignment("bee")
    assert bob.request_assignment("b-only") is None
    assert wait_for(lambda: bob.status.assignments_done == 2, 120)


class Picks(logging.Handler):
    """Collects "Picked 'x': result" lines from the session log, in order."""

    def __init__(self):
        super().__init__(logging.INFO)
        self.lines: list[str] = []

    def emit(self, record):
        msg = record.getMessage()
        if msg.startswith(("Picked", "Spelled", "Couldn't spell", "Saved the revealed")):
            self.lines.append(msg)
        elif msg.startswith("VocabTrainer paused"):
            self.lines.append("VocabTrainer paused")  # countdown text varies


def test_vocabtrainer(make_session, monkeypatch):
    from vocabbot import session as S

    picks = Picks()
    logging.getLogger("vocabbot.session.vt").addHandler(picks)
    logging.getLogger("vocabbot").setLevel(logging.INFO)
    monkeypatch.setattr(S, "VOCABTRAINER_URL", (PAGES / "vocabtrainer.html").as_uri())
    s = make_session("vt", "activities.html", "acct=a")
    assert wait_for(lambda: s.status.state == "choosing", 60)
    assert s.request_vocabtrainer() is None

    def seen(text):
        return any(text in line for line in picks.lines)
    # Round 1, then into round 2 (the mock loops after its round report).
    assert wait_for(lambda: seen("Spelled 'zephyr': right"), 180), picks.lines
    first_round = picks.lines[: next(i for i, l in enumerate(picks.lines) if "'frank'" in l) + 1]
    assert first_round == [
        "Picked 'dull': wrong", "Picked 'eager': right",             # retry after a wrong pick
        "Picked 'long': wrong", "Picked 'kind': wrong",              # Next after a wrong answer isn't "right"
        "Picked 'picture 1': wrong", "Picked 'picture 2': wrong",    # failed pictures remembered across redraws
        "Spelled 'small': wrong", "Spelled 'tiny': right",           # spelling from the blanked sentence via AI
        "Spelled 'wind': wrong", "Spelled 'breeze': wrong", "Spelled 'gust': wrong",   # 3 wrong guesses...
        "Couldn't spell it; using the page's GIVE UP button",
        "Saved the revealed spelling 'zephyr'",
        "VocabTrainer paused",                                       # waits out the "you're rushing" pause
        "Picked 'frank': right",
    ], picks.lines
    second_round = picks.lines[len(first_round):]
    assert second_round[:5] == ["Picked 'eager': right", "Picked 'brief': right", "Picked 'picture 3': right",
                                "Spelled 'tiny': right", "Spelled 'zephyr': right"], picks.lines   # from saved answers
