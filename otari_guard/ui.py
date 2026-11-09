"""Terminal UI: a live timeline of agent stages with a running cost meter."""

from __future__ import annotations

import time

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .agent import Event

ICONS = {"start": ("…", "cyan"), "ok": ("✔", "green"), "fail": ("✘", "red"), "warn": ("▲", "yellow"),
         "info": ("•", "blue"), "block": ("⛔", "magenta")}
STAGE_STYLE = {"guard": "magenta", "safeguard": "magenta", "budget": "magenta", "escalate": "yellow",
               "research": "blue", "verify": "cyan", "review": "green"}


class TimelineUI:
    def __init__(self, console: Console, client, budget: float, title: str):
        self.console, self.client, self.budget, self.title = console, client, budget, title
        self.rows: list[Event] = []
        self.t0 = time.time()
        self.live = Live(self._render(), console=console, refresh_per_second=8, transient=False)

    def __enter__(self):
        self.live.__enter__()
        return self

    def __exit__(self, *exc):
        self.live.update(self._render(final=True))
        self.live.__exit__(*exc)

    def on_event(self, ev: Event) -> None:
        # collapse "start" rows once the same stage reports a result
        if self.rows and self.rows[-1].status == "start" and self.rows[-1].stage == ev.stage and ev.status != "start":
            self.rows[-1] = ev
        else:
            self.rows.append(ev)
        self.live.update(self._render())

    def _meter(self) -> Text:
        spent = self.client.spent_usd
        frac = min(spent / self.budget, 1.0) if self.budget else 0
        width = 30
        filled = int(frac * width)
        color = "green" if frac < 0.6 else "yellow" if frac < 0.9 else "red"
        t = Text("  budget ")
        t.append("█" * filled, style=color)
        t.append("░" * (width - filled), style="grey37")
        t.append(f"  ${spent:.4f} / ${self.budget:.2f}", style="bold")
        t.append(f"   calls {len(self.client.calls)}   {time.time() - self.t0:5.1f}s", style="grey62")
        return t

    def _render(self, final: bool = False):
        tbl = Table.grid(padding=(0, 1))
        tbl.add_column(width=2)
        tbl.add_column(style="bold", width=10)
        tbl.add_column(ratio=1)
        tbl.add_column(style="grey62", justify="right")
        for ev in self.rows[-22:]:
            icon, color = ICONS.get(ev.status, ("•", "white"))
            title = Text(ev.title, style=color if ev.status in ("fail", "block", "warn") else "")
            if ev.detail and ev.status != "start":
                title.append("\n" + ev.detail[:220], style="grey50")
            tbl.add_row(Text(icon, style=color), Text(ev.stage, style=STAGE_STYLE.get(ev.stage, "white")),
                        title, ev.model or "")
        return Panel(Group(tbl, Text(""), self._meter()), title=f"[bold]🛡️ Otari-Guard[/] · {self.title}",
                     border_style="green" if final else "cyan")
