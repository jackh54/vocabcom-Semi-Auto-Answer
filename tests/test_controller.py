import json
import logging
import time

import pytest

from vocabbot import controller as C
from vocabbot.session import SessionStatus


class FakeSession:
    """Stands in for a Chrome session: runs until its stop event is set."""

    def __init__(self, name, index, profile_dir, config, store, answerer, stop):
        self.name, self.index, self.stop = name, index, stop
        self.status = SessionStatus(name, state="answering", detail="pernicious means:")
        self.closed = False
        profile_dir.mkdir(parents=True, exist_ok=True)

    def run(self):
        logging.getLogger(f"vocabbot.session.{self.name}").info("Picked 'harmful': right")
        self.stop.wait(10)
        self.status.state = "stopped"

    def close(self):
        self.closed = True


@pytest.fixture
def ctl(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(C, "Session", FakeSession)
    monkeypatch.setattr(C.Answerer, "check", lambda self: None)
    logging.getLogger("vocabbot").setLevel(logging.INFO)
    (tmp_path / "config.json").write_text(json.dumps({"openai_api_key": "sk-test"}))
    c = C.Controller(tmp_path)
    yield c
    c.shutdown(timeout=2)


def wait_for(cond, timeout=3):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_start_stop_and_snapshot(ctl):
    assert ctl.start("alice") is None
    assert ctl.start("bob") is None
    snap = ctl.snapshot()
    assert {s["name"] for s in snap["sessions"]} == {"alice", "bob"}
    assert sorted(s["name"] for s in snap["sessions"]) and all(s["alive"] for s in snap["sessions"])
    assert wait_for(lambda: len(ctl.snapshot()["events"]) == 2)
    assert {a["name"]: a["running"] for a in ctl.accounts()} == {"alice": True, "bob": True}

    ctl.stop("alice")
    assert wait_for(lambda: not next(s for s in ctl.snapshot()["sessions"] if s["name"] == "alice")["alive"])
    ctl.dismiss("alice")
    assert [s["name"] for s in ctl.snapshot()["sessions"]] == ["bob"]


def test_events_since(ctl):
    ctl.start("alice")
    assert wait_for(lambda: ctl.snapshot()["events"])
    last = ctl.snapshot()["events"][-1]["id"]
    assert ctl.snapshot(events_since=last)["events"] == []


def test_profile_locked_elsewhere_is_refused(ctl):
    held = C.browser.lock_profile(ctl.profiles / "carol")
    try:
        assert "another vocabbot" in ctl.start("carol")
    finally:
        held.close()


def test_window_slots_are_reused(ctl):
    ctl.start("a")
    ctl.start("b")
    ctl.stop("a")
    assert wait_for(lambda: not ctl._running["a"].thread.is_alive())
    ctl.start("c")
    assert ctl._running["c"].session.index == 0


def test_forget_account_requires_stopped(ctl):
    ctl.start("dave")
    assert "Stop this account" in ctl.forget_account("dave")
    ctl.stop("dave")
    assert wait_for(lambda: not ctl._running["dave"].thread.is_alive())
    assert ctl.forget_account("dave") is None
    assert not (ctl.profiles / "dave").exists()


def test_settings_validation_and_save(ctl):
    assert "longest wait" in ctl.save_settings("gpt-4o-mini", 5, 3)
    assert ctl.save_settings("gpt-4o-mini", 2, 4) is None
    assert ctl.config.min_wait == 2 and ctl.config.max_wait == 4
    assert json.loads(ctl.config_path.read_text())["openai_api_key"] == "sk-test"


def test_missing_key_then_set(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(C.Answerer, "check", lambda self: None)
    c = C.Controller(tmp_path)
    try:
        assert c.config is None and not c.settings()["has_key"]
        assert "API key" in c.start("x")
        assert c.set_api_key("  sk-new  ") is None
        assert c.settings()["key_hint"] == "…-new"
    finally:
        c.shutdown(timeout=1)


def test_next_account_name(ctl):
    (ctl.profiles / "account-1").mkdir(parents=True)
    assert ctl.next_account_name() == "account-2"


def test_feed_keeps_dotted_account_names(ctl):
    ctl.start("jack.h")
    assert wait_for(lambda: ctl.snapshot()["events"])
    assert ctl.snapshot()["events"][0]["session"] == "jack.h"


def test_accounts_dont_probe_running_profiles(ctl, monkeypatch):
    ctl.start("alice")
    probed = []
    real = C.browser.lock_profile
    monkeypatch.setattr(C.browser, "lock_profile", lambda p: probed.append(p.name) or real(p))
    monkeypatch.setattr("vocabbot.accounts.browser.lock_profile", lambda p: probed.append(p.name) or real(p))
    (ctl.profiles / "bob").mkdir(parents=True)
    accounts = {a["name"]: a for a in ctl.accounts(max_age=0)}
    assert accounts["alice"]["running"] and not accounts["alice"]["elsewhere"]
    assert "alice" not in probed and "bob" in probed


def _give(ctl, name, assignments, state="choosing"):
    st = ctl._running[name].session.status
    st.assignments, st.assignments_loaded, st.state = assignments, True, state


def _a(id_, supported=True):
    return {"id": id_, "name": id_.upper(), "url": f"https://example.test/{id_}", "supported": supported,
            "kind_label": "Practice" if supported else "Quiz"}


def test_shared_assignments_and_open_shared(ctl, monkeypatch):
    opened = []
    monkeypatch.setattr(FakeSession, "request_assignment",
                        lambda self, aid: opened.append((self.name, aid)) or None, raising=False)
    ctl.start("alice")
    ctl.start("bob")
    _give(ctl, "alice", [_a("u7"), _a("u8"), _a("quiz", False)])
    _give(ctl, "bob", [_a("u8"), _a("quiz", False), _a("u7")])
    assert [a["id"] for a in ctl.snapshot()["shared"]] == ["u7", "u8"]
    assert ctl.snapshot()["shared"][0]["accounts"] == 2

    _give(ctl, "bob", [_a("u8")], state="answering")   # busy accounts don't count
    assert ctl.snapshot()["shared"] == []

    _give(ctl, "bob", [_a("u8")])
    assert ctl.open_shared("u8") is None
    assert sorted(opened) == [("alice", "u8"), ("bob", "u8")]
    assert "No waiting account" in ctl.open_shared("missing")


def test_vocabtrainer_all_targets_idle_accounts(ctl, monkeypatch):
    started = []
    monkeypatch.setattr(FakeSession, "request_vocabtrainer", lambda self: started.append(self.name) or None, raising=False)
    ctl.start("alice")
    ctl.start("bob")
    _give(ctl, "alice", [])
    _give(ctl, "bob", [_a("u8")], state="answering")
    assert ctl.snapshot()["idle_accounts"] == 1
    assert ctl.open_vocabtrainer_all() is None
    assert started == ["alice"]
