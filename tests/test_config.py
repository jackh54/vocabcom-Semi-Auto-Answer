import json
import os

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


def test_write_initial_config_keeps_existing_settings(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from vocabbot.config import MissingKeyError, write_initial_config
    path = tmp_path / "config.json"
    with pytest.raises(MissingKeyError):
        load_config(path)
    path.write_text(json.dumps({"openai_api_key": "", "max_wait_time": 9}))
    write_initial_config(path, "sk-test")
    cfg = load_config(path)
    assert cfg.openai_api_key == "sk-test" and cfg.max_wait == 9 and cfg.min_wait == 3
    if os.name != "nt":  # Windows has no POSIX permission bits
        assert (path.stat().st_mode & 0o777) == 0o600


def test_app_home_override(monkeypatch, tmp_path):
    from vocabbot.paths import app_home
    monkeypatch.setenv("VOCABBOT_HOME", str(tmp_path))
    assert app_home() == tmp_path
