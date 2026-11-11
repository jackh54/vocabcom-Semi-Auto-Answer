from vocabbot.answerer import build_prompt, parse_choice


def test_parse_choice_returns_zero_based_index():
    assert parse_choice("3", 4) == 2
    assert parse_choice("The answer is 2.", 4) == 1


def test_parse_choice_skips_out_of_range_and_excluded():
    assert parse_choice("7 or 1", 4) == 0
    assert parse_choice("2, otherwise 4", 4, exclude={1}) == 3
    assert parse_choice("no idea", 4) is None
    assert parse_choice(None, 4) is None


def test_parse_choice_handles_more_than_four_choices():
    assert parse_choice("5", 5) == 4


def test_build_prompt_lists_excluded_choices():
    prompt = build_prompt("Q", ["a", "b", "c"], exclude={0, 2})
    assert "1. a" in prompt and "3. c" in prompt
    assert "do not pick them: 1, 3" in prompt


def test_clean_word():
    from vocabbot.answerer import clean_word
    assert clean_word("Stream of consciousness.") == "stream of consciousness"
    assert clean_word('"zephyr"\nIt means a breeze.') == "zephyr"
    assert clean_word("well-being") == "well-being"
    assert clean_word("") is None and clean_word(None) is None
    assert clean_word("It's 42") is None   # digits aren't a word
    assert clean_word("zephyr", exclude={"Zephyr"}) is None
