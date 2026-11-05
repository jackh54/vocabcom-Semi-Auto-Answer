import json

import pytest

from vocabbot.config import ConfigError, load_config


def test_chrome_options_become_flags(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "openai_api_key": "k",
        "chrome_options": {"disable_gpu": True, "no_sandbox": False, "window_size": "800,600"},
    }))
    cfg = load_config(path)
    assert cfg.chrome_args == ("--disable-gpu", "--window-size=800,600")


def test_env_key_used_when_config_key_blank(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"openai_api_key": ""}))
    assert load_config(path).openai_api_key == "from-env"


def test_missing_key_is_an_error(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        load_config(tmp_path / "missing.json")
