"""Ask OpenAI which choice is correct."""
from __future__ import annotations

import re
from collections.abc import Collection

from openai import OpenAI

_SYSTEM = (
    "You answer multiple-choice vocabulary questions. "
    "Reply with only the number of the correct choice and nothing else."
)


def build_prompt(question: str, choices: list[str], exclude: Collection[int] = ()) -> str:
    lines = [f"Question: {question}", "Choices:"]
    lines += [f"{i}. {choice}" for i, choice in enumerate(choices, start=1)]
    if exclude:
        wrong = ", ".join(str(i + 1) for i in sorted(exclude))
        lines.append(f"These choices are wrong, do not pick them: {wrong}.")
    lines.append(f"Answer with a single number from 1 to {len(choices)}.")
    return "\n".join(lines)


def parse_choice(reply: str | None, n_choices: int, exclude: Collection[int] = ()) -> int | None:
    """First number in the reply that is a valid, untried choice, as a 0-based index."""
    for match in re.finditer(r"\d+", reply or ""):
        index = int(match.group()) - 1
        if 0 <= index < n_choices and index not in exclude:
            return index
    return None


class Answerer:
    """Thread-safe: one instance is shared by every session."""

    def __init__(self, api_key: str, model: str):
        self.model = model
        self._client = OpenAI(api_key=api_key, max_retries=3, timeout=30)

    def check(self) -> None:
        """Fail fast on a bad key or model name. Free: it does not run a completion."""
        self._client.models.retrieve(self.model)

    def choose(self, question: str, choices: list[str], exclude: Collection[int] = ()) -> int | None:
        """0-based index of the model's pick, or None if the reply had no usable number.
        Raises openai.OpenAIError on API failure."""
        # No temperature/max_tokens: newer reasoning models reject them, and the reply is one number anyway.
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": build_prompt(question, choices, exclude)},
            ],
        )
        reply = response.choices[0].message.content if response.choices else ""
        return parse_choice(reply, len(choices), exclude)
