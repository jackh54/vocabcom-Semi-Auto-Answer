"""Live terminal table: one row per session plus lifetime totals."""
from __future__ import annotations

import threading
import time

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.table import Table
from rich.text import Text

from .session import Session
from .store import Store

_STATE_STYLE = {
    "answering": "green",
    "waiting": "yellow",
    "done": "bold green",
    "blocked": "yellow",
    "reloading": "magenta",
    "launching": "cyan",
    "starting": "cyan",
    "error": "bold red",
    "closed": "red",
    "stopped": "dim",
}


def _runtime(started: float) -> str:
    secs = int(time.monotonic() - started)
    return f"{secs // 3600:d}:{secs % 3600 // 60:02d}:{secs % 60:02d}"


def _render(sessions: list[Session], store: Store) -> Group:
    table = Table(box=box.ROUNDED, expand=True, title="vocabbot  ·  Ctrl+C to stop")
    table.add_column("Session", style="bold")
    table.add_column("State")
    table.add_column("Right", justify="right", style="green")
    table.add_column("Wrong", justify="right", style="red")
    table.add_column("Cached", justify="right")
    table.add_column("AI", justify="right")
    table.add_column("Done", justify="right", style="green")
    table.add_column("Time", justify="right", style="dim")
    table.add_column("Doing", ratio=1, no_wrap=True, overflow="ellipsis")

    for s in sessions:
        st = s.status
        label = f"{st.account} ({st.name})" if st.account else st.name
        # Text(...) so names/questions containing [brackets] aren't parsed as rich markup
        table.add_row(Text(label), Text(st.state, style=_STATE_STYLE.get(st.state, "")),
                      str(st.correct), str(st.wrong), str(st.cache_hits), str(st.ai_calls),
                      str(st.assignments_done),
                      _runtime(st.started), Text(st.detail))

    c = store.counters()
    lookups = c["cache_hits"] + c["cache_misses"]
    hit_rate = f"{100 * c['cache_hits'] / lookups:.0f}%" if lookups else "-"
    totals = Text(
        f"All time: {c['correct_answers']} right · {c['wrong_answers']} wrong · "
        f"{c['achievements']} achievements · cache hit rate {hit_rate} · "
        f"{store.answer_count()} answers cached",
        style="dim",
    )
    return Group(table, totals)


def run(sessions: list[Session], threads: list[threading.Thread], store: Store, stop: threading.Event,
        console: Console) -> None:
    """Redraw until Ctrl+C (KeyboardInterrupt propagates to the caller) or every session has ended."""
    with Live(_render(sessions, store), console=console, refresh_per_second=2) as live:
        while not stop.is_set() and any(t.is_alive() for t in threads):
            stop.wait(0.5)
            live.update(_render(sessions, store))
        live.update(_render(sessions, store))
