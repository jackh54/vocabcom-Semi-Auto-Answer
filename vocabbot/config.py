"""Load and validate config.json."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL = "gpt-4o-mini"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    openai_api_key: str
    model: str = DEFAULT_MODEL
    chrome_args: tuple[str, ...] = ()
    min_wait: float = 3.0
    max_wait: float = 5.0
    log_level: str = "INFO"


def _chrome_args(options: dict) -> tuple[str, ...]:
    """Turn {"disable_gpu": true, "window_size": "1920,1080"} into Chrome command-line flags."""
    args = []
    for name, value in options.items():
        flag = "--" + name.replace("_", "-")
        if value is True:
            args.append(flag)
        elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
            args.append(f"{flag}={value}")
    return tuple(args)


def load_config(path: Path) -> Config:
    raw: dict = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            raise ConfigError(f"{path} is not valid JSON: {e}") from e

    api_key = raw.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise ConfigError(
            f"No OpenAI API key. Set openai_api_key in {path.name} or the OPENAI_API_KEY environment variable."
        )

    min_wait = float(raw.get("min_wait_time", 3))
    max_wait = float(raw.get("max_wait_time", 5))
    if min_wait < 0 or max_wait < min_wait:
        raise ConfigError("min_wait_time must be >= 0 and <= max_wait_time")

    return Config(
        openai_api_key=api_key,
        model=raw.get("model") or DEFAULT_MODEL,
        chrome_args=_chrome_args(raw.get("chrome_options", {})),
        min_wait=min_wait,
        max_wait=max_wait,
        log_level=str(raw.get("log_level", "INFO")).upper(),
    )
