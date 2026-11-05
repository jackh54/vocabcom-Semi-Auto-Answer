"""Saved accounts and the start-up picker.

An account is a Chrome profile folder in data/profiles/<name>. Chrome keeps its cookies
there, so once you sign in to Vocabulary.com in that account's window it stays signed in.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich import box
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from . import browser

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$")


@dataclass(frozen=True)
class Account:
    name: str
    last_used: datetime | None
    in_use: bool  # held by another running vocabbot


def valid_name(name: str) -> bool:
    return bool(_NAME.match(name)) and not name.isdigit()


def list_accounts(profiles: Path) -> list[Account]:
    """Saved accounts, most recently used first."""
    if not profiles.is_dir():
        return []
    accounts = []
    for d in profiles.iterdir():
        if not d.is_dir() or not valid_name(d.name):
            continue
        marker = d / "Local State"  # Chrome rewrites this every run
        last_used = datetime.fromtimestamp((marker if marker.exists() else d).stat().st_mtime)
        lock = browser.lock_profile(d)
        if lock is not None:
            lock.close()
        accounts.append(Account(d.name, last_used, in_use=lock is None))
    accounts.sort(key=lambda a: (a.last_used or datetime.min, a.name), reverse=True)
    return accounts


def parse_selection(text: str, accounts: list[Account]) -> list[str]:
    """'1, 3', 'alice bob', 'all', or a new name. Raises ValueError with a message for the user."""
    tokens = [t for t in re.split(r"[,\s]+", text.strip()) if t]
    if not tokens:
        raise ValueError("Pick at least one account.")
    by_name = {a.name: a for a in accounts}
    names: list[str] = []
    for token in tokens:
        if token.lower() == "all":
            free = [a.name for a in accounts if not a.in_use]
            if not free:
                raise ValueError("There are no saved accounts free to run.")
            names += [n for n in free if n not in names]
            continue
        if token.isdigit():
            number = int(token)
            if not 1 <= number <= len(accounts):
                raise ValueError(f"There's no account number {token}.")
            name = accounts[number - 1].name
        elif valid_name(token):
            name = token
        else:
            raise ValueError(f"{token!r} isn't a valid account name (letters, numbers, - _ . ; max 40).")
        if name in by_name and by_name[name].in_use:
            raise ValueError(f"{name} is already running in another vocabbot.")
        if name not in names:
            names.append(name)
    return names


def pick(console: Console, profiles: Path, display_names: dict[str, str] | None = None) -> list[str]:
    """Ask which accounts to run, one session each. display_names maps profile -> signed-in name."""
    display_names = display_names or {}
    accounts = list_accounts(profiles)
    if accounts:
        table = Table(box=box.SIMPLE, title="Saved accounts", title_justify="left")
        table.add_column("#", justify="right", style="bold")
        table.add_column("Account")
        table.add_column("Signed in as")
        table.add_column("Last used", style="dim")
        for i, a in enumerate(accounts, start=1):
            when = a.last_used.strftime("%Y-%m-%d %H:%M") if a.last_used else "-"
            label = f"{a.name} [yellow](running elsewhere)[/]" if a.in_use else a.name
            shown = Text(display_names[a.name]) if a.name in display_names else Text("-", style="dim")
            table.add_row(str(i), label, shown, when)
        console.print(table)
        console.print("Type numbers or names separated by commas, or [bold]all[/]. "
                      "A new name adds an account; sign in once in its window and it's saved.")
        default = next((str(i) for i, a in enumerate(accounts, start=1) if not a.in_use), None)
    else:
        console.print("No saved accounts yet. Name one (e.g. your first name); "
                      "sign in once in its window and it's saved for next time. "
                      "Separate several names with commas.")
        default = "account-1"

    while True:
        answer = Prompt.ask("Accounts", default=default, console=console)
        try:
            names = parse_selection(answer or "", accounts)
        except ValueError as e:
            console.print(f"[red]{e}[/]")
            continue
        new = [n for n in names if n not in {a.name for a in accounts}]
        if new:
            console.print(f"New: {', '.join(new)}. Sign in when the window opens.")
        return names
