"""Terminal assignment picker: once the accounts are signed in, offer assignments every account
shares first, otherwise ask per account. Each session then opens its assignment itself."""
from __future__ import annotations

import os
import select
import sys
import threading
import time
from collections.abc import Collection
from datetime import datetime

from rich import box
from rich.console import Console
from rich.live import Live
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from .assignments import shared_ids
from .session import IDLE_STATES, Session


def _label(s: Session) -> str:
    return f"{s.status.account} ({s.name})" if s.status.account else s.name


def _ready(s: Session, thread: threading.Thread) -> bool:
    st = s.status
    return (not thread.is_alive() or st.state in ("answering", "error", "closed")
            or (st.state in IDLE_STATES and st.assignments_loaded))


def _enter_pressed() -> bool:
    """Non-blocking check for Enter, without leaving a reader thread that would eat later input."""
    if os.name == "nt":
        import msvcrt
        while msvcrt.kbhit():
            if msvcrt.getwch() in ("\r", "\n"):
                return True
        return False
    ready, _, _ = select.select([sys.stdin], [], [], 0)
    if ready:
        sys.stdin.readline()
        return True
    return False


def _wait_table(sessions: list[Session], threads: list[threading.Thread]) -> Table:
    t = Table(box=box.SIMPLE, title="Getting each account's assignments  ·  Enter to skip and pick in the windows",
              title_justify="left")
    t.add_column("Account")
    t.add_column("Status")
    for s, th in zip(sessions, threads):
        status = "ready" if _ready(s, th) else s.status.detail or s.status.state
        t.add_row(Text(_label(s)), Text(status, style="green" if _ready(s, th) else "yellow"))
    return t


def _meta(a: dict) -> str:
    parts = [f"{a['kind_label']}, {a['words']} words" if a.get("words") else a["kind_label"]]
    if a.get("due"):
        try:
            due = datetime.fromisoformat(a["due"].replace("Z", "+00:00")).astimezone()
            day = f"{due:%a %b} {due.day}"
            parts.append(f"overdue since {day}" if due < datetime.now(due.tzinfo) else f"due {day}")
        except ValueError:
            pass
    if a.get("pct"):
        parts.append(f"{a['pct']}% done")
    return ", ".join(parts)


def _numbered(console: Console, title: str, items: list[dict], tag_ids: Collection[str] = ()) -> list[dict]:
    """Print supported assignments numbered from 1; unsupported ones listed without a number."""
    table = Table(box=box.SIMPLE, title=title, title_justify="left", show_header=False)
    table.add_column(justify="right", style="bold")
    table.add_column()
    table.add_column(style="dim")
    choices = []
    for a in sorted(items, key=lambda a: a["id"] not in tag_ids):
        name = Text(a["name"])
        if a["id"] in tag_ids:
            name.append("  all accounts", style="black on yellow")
        if a["supported"]:
            choices.append(a)
            table.add_row(str(len(choices)), name, _meta(a))
        else:
            table.add_row("", Text(a["name"], style="dim"), f"{_meta(a)} (not supported)")
    console.print(table)
    return choices


def _ask(console: Console, prompt: str, count: int, extra: dict[str, str], default: str = "1") -> str:
    """Ask for a number 1..count or one of `extra`'s keys. Returns the answer (lowercase)."""
    hint = ", ".join([f"1-{count}" if count > 1 else "1"] + [f"{k} {v}" for k, v in extra.items()])
    while True:
        answer = (Prompt.ask(f"{prompt} [dim]({hint})[/]", default=default, console=console) or "").strip().lower()
        if answer in extra or (answer.isdigit() and 1 <= int(answer) <= count):
            return answer
        console.print("[red]Type one of the numbers shown.[/]" if count else "[red]Choose one of the options.[/]")


def pick(console: Console, sessions: list[Session], threads: list[threading.Thread], stop: threading.Event) -> None:
    """Wait for the accounts' lists, then open the chosen assignments. Enter skips."""
    if not sys.stdin.isatty():
        return
    skipped = False
    with Live(_wait_table(sessions, threads), console=console, refresh_per_second=2, transient=True) as live:
        while not stop.is_set() and not all(_ready(s, t) for s, t in zip(sessions, threads)):
            if _enter_pressed():
                skipped = True
                break
            time.sleep(0.25)
            live.update(_wait_table(sessions, threads))
    if skipped or stop.is_set():
        console.print("Skipped. Open an assignment in each window and it starts answering.")
        return

    choosers = [s for s, t in zip(sessions, threads)
                if t.is_alive() and s.status.state in IDLE_STATES and s.status.assignments_loaded]
    if not choosers:
        return
    lists = [s.status.assignments for s in choosers]
    shared = shared_ids(lists)

    if shared:
        first = {a["id"]: a for a in lists[0]}
        options = _numbered(console, f"On all {len(choosers)} accounts", [first[i] for i in shared])
        answer = _ask(console, "Start on every account", len(options),
                      {"p": "pick per account", "s": "skip"})
        if answer == "s":
            return
        if answer.isdigit():
            chosen = options[int(answer) - 1]
            for s in choosers:
                _start(console, s, chosen)
            return

    for s in choosers:
        options = _numbered(console, _label(s), s.status.assignments, set(shared))
        if not options:
            console.print(f"[dim]{_label(s)}: no practice assignments to do.[/]")
            continue
        answer = _ask(console, f"Start for {_label(s)}", len(options), {"s": "skip"})
        if answer.isdigit():
            _start(console, s, options[int(answer) - 1])


def _start(console: Console, s: Session, assignment: dict) -> None:
    err = s.request_assignment(assignment["id"])
    if err:
        console.print(f"[red]{_label(s)}: {err}[/]")
    else:
        console.print(f"{_label(s)}: opening [bold]{assignment['name']}[/]")
