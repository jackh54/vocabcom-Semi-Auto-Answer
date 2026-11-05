import json
import threading

from vocabbot.store import Store, cache_key, normalize


def test_normalize_keeps_apostrophes_and_drops_punctuation():
    assert normalize("  It's  a TEST, really!  ") == "it's a test really"


def test_cache_key_ignores_choice_order_and_includes_context():
    a = cache_key("Q\nContext: one", ["b", "a"])
    assert a == cache_key("Q\nContext: one", ["a", "b"])
    assert a != cache_key("Q\nContext: two", ["a", "b"])


def test_remember_lookup_forget(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    choices = ["Alpha", "Beta.", "Gamma", "Delta"]
    assert store.lookup("q", choices) is None
    store.remember("q", choices, 1)
    # Same choices shuffled with different punctuation still find the answer
    assert store.lookup("q", ["gamma", "beta", "alpha", "delta"]) == 1
    store.forget("q", choices)
    assert store.lookup("q", choices) is None


def test_counters_are_safe_across_threads(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    threads = [threading.Thread(target=lambda: [store.incr("correct_answers") for _ in range(200)])
               for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert store.counters()["correct_answers"] == 1600


def test_two_connections_share_the_database(tmp_path):
    first, second = Store(tmp_path / "db.sqlite"), Store(tmp_path / "db.sqlite")
    first.remember("q", ["a", "b"], 0)
    assert second.lookup("q", ["b", "a"]) == 1


def test_import_legacy_runs_once(tmp_path):
    cache = tmp_path / "question_cache.json"
    cache.write_text(json.dumps({"old-key": {
        "original_question": "Q\nContext: s", "original_choices": ["x", "y"], "normalized_answer": "y",
    }}))
    stats = tmp_path / "statistics.json"
    stats.write_text(json.dumps({"correct_answers": 5, "wrong_answers": 1}))

    store = Store(tmp_path / "db.sqlite")
    assert store.import_legacy(cache, stats) == 1
    assert store.import_legacy(cache, stats) == 0
    assert store.lookup("Q\nContext: s", ["y", "x"]) == 0
    assert store.counters()["correct_answers"] == 5
