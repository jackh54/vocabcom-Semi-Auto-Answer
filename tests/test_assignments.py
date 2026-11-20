from vocabbot.assignments import parse, shared_ids

API = {
    "classes": [{"id": "c1", "name": "Period 3 English"}],
    "assignments": [
        {"id": "a1", "name": "Unit 7", "type": "p", "length": 20, "wordlist_id": 7414062, "class_id": "c1",
         "progress": 0.71, "due_at": "2026-11-09T14:59:00.000Z", "visible_at": "2026-11-05T13:00:00.000Z",
         "max_progress_activity_id": "act9"},
        {"id": "a2", "name": "Unit 6", "type": "p", "wordlist_id": 7102886, "class_id": "c1", "progress": 1.0},
        {"id": "a3", "name": "Bee", "type": "s", "wordlist_id": 55, "class_id": "c1", "progress": 0,
         "due_at": "2026-11-08T00:00:00Z"},
        {"id": "a4", "name": "Future", "type": "p", "wordlist_id": 56, "progress": 0, "visible_at": "2999-01-01T00:00:00Z"},
    ],
}
CACHE = {"value": {"classes": {"memberOf": [{"name": "Period 3 English", "assignments": [
    {"id": "a1", "name": "Unit 7", "type": "p", "pctComplete": 71, "url": "/lists/7414062/practice",
     "dueDate": "2026-11-09T14:59:00.000Z", "visibleDate": "2026-11-05T13:00:00.000Z", "length": 20},
    {"id": "a2", "name": "Unit 6", "type": "p", "pctComplete": 100, "url": "/lists/7102886/practice"},
]}]}}}


def test_live_list_is_parsed_filtered_and_sorted():
    items, source = parse({"api": API, "cache": CACHE})
    assert source == "live"
    assert [a.id for a in items] == ["a3", "a1"]          # soonest due first; finished and not-yet-visible dropped
    unit7 = items[1]
    assert unit7.pct == 71 and unit7.class_name == "Period 3 English" and unit7.words == 20
    assert unit7.url == "https://www.vocabulary.com/lists/7414062/practice?aid=act9"   # resumes where it left off
    assert unit7.supported and not items[0].supported                                  # spelling bee unsupported
    assert items[0].url.endswith("/lists/55/bee")


def test_falls_back_to_cached_copy():
    items, source = parse({"api": None, "apiError": "timed out", "cache": CACHE})
    assert source == "cached"
    assert [(a.id, a.pct, a.url) for a in items] == [("a1", 71, "https://www.vocabulary.com/lists/7414062/practice")]


def test_nothing_available():
    assert parse({"api": None, "cache": None}) == ([], "none")


def test_shared_ids_keeps_first_lists_order_and_skips_unsupported():
    a = [{"id": "x", "supported": True}, {"id": "y", "supported": True}, {"id": "bee", "supported": False}]
    b = [{"id": "y", "supported": True}, {"id": "bee", "supported": False}, {"id": "x", "supported": True}]
    c = [{"id": "y", "supported": True}]
    assert shared_ids([a, b]) == ["x", "y"]
    assert shared_ids([a, b, c]) == ["y"]
    assert shared_ids([a]) == []


def test_session_request_rules(tmp_path):
    import threading
    from vocabbot.config import Config
    from vocabbot.session import Session
    from vocabbot.store import Store
    s = Session("alice", 0, tmp_path / "p", Config(openai_api_key="x"), Store(tmp_path / "db"), None, threading.Event())
    s.status.assignments = [
        {"id": "u8", "name": "Unit 8", "url": "https://x/u8", "supported": True, "kind_label": "Practice"},
        {"id": "bee", "name": "Bee", "url": "https://x/bee", "supported": False, "kind_label": "Spelling Bee"},
    ]
    s.status.state = "answering"
    assert "busy" in s.request_assignment("u8")
    s.status.state = "choosing"
    assert "isn't in this account's list" in s.request_assignment("gone")
    assert "Spelling Bee" in s.request_assignment("bee")
    assert s.request_assignment("u8") is None and s._open_request == ("https://x/u8", "Unit 8", None)
