from datetime import datetime

import pytest

from vocabbot import browser
from vocabbot.accounts import Account, list_accounts, parse_selection, valid_name

ACCOUNTS = [
    Account("alice", datetime(2026, 1, 2), in_use=False),
    Account("bob", datetime(2026, 1, 1), in_use=False),
    Account("busy", datetime(2025, 1, 1), in_use=True),
]


def test_numbers_names_and_new_names():
    assert parse_selection("1, bob", ACCOUNTS) == ["alice", "bob"]
    assert parse_selection("2 carol", ACCOUNTS) == ["bob", "carol"]
    assert parse_selection("1,1,alice", ACCOUNTS) == ["alice"]


def test_all_skips_accounts_running_elsewhere():
    assert parse_selection("all", ACCOUNTS) == ["alice", "bob"]


@pytest.mark.parametrize("text", ["", "9", "busy", "3", "bad name!"])
def test_rejects_bad_selections(text):
    with pytest.raises(ValueError):
        parse_selection(text, ACCOUNTS)


def test_valid_name():
    assert valid_name("jack.h_2")
    assert not valid_name("12")          # would be read as a list number
    assert not valid_name("../escape")
    assert not valid_name("")


def test_list_accounts_marks_locked_profiles(tmp_path):
    (tmp_path / "free").mkdir()
    (tmp_path / "held").mkdir()
    lock = browser.lock_profile(tmp_path / "held")
    try:
        found = {a.name: a.in_use for a in list_accounts(tmp_path)}
    finally:
        lock.close()
    assert found == {"free": False, "held": True}
