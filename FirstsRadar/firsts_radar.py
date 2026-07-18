"""RouteOps Firsts Radar -- a standalone, colour-coded window that tails the Elite
Dangerous journal and shows, for the system you're in, which bodies still offer a
FIRST (first discovery / first map / first footfall), plus likely-first-logged bio.

Standalone: standard library only (tkinter), no EDDiscovery needed. Run it beside
the game:  pythonw firsts_radar.py   (or double-click FirstsRadar.bat)
"""

from __future__ import annotations

import json
import os
import tkinter as tk
from tkinter import ttk

import firsts

POLL_MS = 1500

# Elite-ish dark palette
BG = "#0e0f0b"
PANEL = "#17180f"
HEAD = "#2a2a1c"
DIM = "#6b6b5a"
ORANGE = "#ff7b00"   # first footfall (rarest / on-foot)
GOLD = "#ffd23f"     # first discovery
CYAN = "#33d6ff"     # first map
GREEN = "#57d957"    # undiscovered-system banner
TEXT = "#d9d2b0"


class RadarApp:
    def __init__(self, root: tk.Tk, journal_dir: str | None = None) -> None:
        self.root = root
        self.journal_dir = journal_dir or firsts.DEFAULT_JOURNAL_DIR
        self.radar = firsts.Radar()
        self.journal_path = firsts.latest_journal(self.journal_dir)
        self.offset = 0

        root.title("RouteOps Firsts Radar")
        root.configure(bg=BG)
        root.geometry("760x520")
        root.minsize(560, 320)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL,
                        foreground=TEXT, rowheight=22, font=("Consolas", 10), borderwidth=0)
        style.configure("Treeview.Heading", background=HEAD, foreground=GOLD,
                        font=("Consolas", 10, "bold"), borderwidth=0)
        style.map("Treeview.Heading", background=[("active", HEAD)])
        style.map("Treeview", background=[("selected", "#3a3a24")])

        # Banner
        self.banner = tk.Label(root, text="Waiting for the journal...", bg=BG, fg=TEXT,
                               font=("Consolas", 14, "bold"), anchor="w", padx=10, pady=6)
        self.banner.pack(fill="x")

        # Body table
        cols = ("body", "type", "dist", "bio", "firsts")
        self.tree = ttk.Treeview(root, columns=cols, show="headings", selectmode="browse")
        for cid, txt, w, anchor in (
            ("body", "Body", 210, "w"), ("type", "Type", 150, "w"),
            ("dist", "Dist (ls)", 90, "e"), ("bio", "Bio", 50, "e"),
            ("firsts", "Firsts available", 230, "w"),
        ):
            self.tree.heading(cid, text=txt)
            self.tree.column(cid, width=w, anchor=anchor, stretch=(cid == "firsts"))
        self.tree.tag_configure("footfall", foreground=ORANGE)
        self.tree.tag_configure("discovery", foreground=GOLD)
        self.tree.tag_configure("map", foreground=CYAN)
        self.tree.tag_configure("none", foreground=DIM)
        self.tree.pack(fill="both", expand=True, padx=6, pady=(0, 4))

        # Footer: session tally + controls
        footer = tk.Frame(root, bg=BG)
        footer.pack(fill="x", padx=8, pady=(0, 6))
        self.tally = tk.Label(footer, text="", bg=BG, fg=TEXT, font=("Consolas", 10), anchor="w")
        self.tally.pack(side="left")
        self.ontop = tk.BooleanVar(value=False)
        tk.Checkbutton(footer, text="Always on top", variable=self.ontop, command=self._toggle_top,
                       bg=BG, fg=DIM, selectcolor=PANEL, activebackground=BG, activeforeground=TEXT,
                       font=("Consolas", 9)).pack(side="right")

        legend = tk.Label(root, bg=BG, font=("Consolas", 9), anchor="w", padx=10,
                          text="● first footfall   ● first discovery   ● first map   ● bio~first (undiscovered)")
        # colour the legend dots by inserting coloured segments is fiddly in one Label;
        # keep a compact single-colour hint instead.
        legend.configure(fg=DIM, text="footfall=orange  discovery=gold  map=cyan  |  BIO~FIRST = bio in an undiscovered system")
        legend.pack(fill="x", pady=(0, 6))

        self._tick()

    def _toggle_top(self) -> None:
        self.root.attributes("-topmost", self.ontop.get())

    def _read_new(self) -> list[dict]:
        # roll to a newer session journal if one appeared
        latest = firsts.latest_journal(self.journal_dir)
        if latest and latest != self.journal_path:
            self.journal_path = latest
            self.offset = 0
        if not self.journal_path:
            return []
        try:
            with open(self.journal_path, "rb") as handle:
                handle.seek(self.offset)
                data = handle.read()
        except OSError:
            return []
        newline = data.rfind(b"\n")
        if newline == -1:
            return []  # no complete line yet
        consume = data[: newline + 1]
        self.offset += len(consume)
        events = []
        for raw in consume.split(b"\n"):
            raw = raw.strip()
            if not raw:
                continue
            try:
                events.append(json.loads(raw.decode("utf-8", "replace")))
            except (ValueError, TypeError):
                continue
        return events

    def _tick(self) -> None:
        changed = False
        for event in self._read_new():
            self.radar.apply(event)
            changed = True
        if changed:
            self._refresh()
        self.root.after(POLL_MS, self._tick)

    def _refresh(self) -> None:
        r = self.radar
        avail = sum(1 for b in r.bodies.values() if b.has_first)
        if r.undiscovered_system:
            self.banner.configure(text=f"★ {r.system or '?'}  —  UNDISCOVERED SYSTEM — everything here is a first", fg=GREEN)
        elif avail:
            self.banner.configure(text=f"{r.system or '?'}  —  {avail} bodies with a first available", fg=GOLD)
        else:
            self.banner.configure(text=f"{r.system or '?'}  —  no firsts here", fg=DIM)

        self.tree.delete(*self.tree.get_children())
        for b in r.rows():
            badges = b.badges()
            tag = ("footfall" if b.first_footfall else "discovery" if b.first_discovery
                   else "map" if b.first_map else "none")
            dist = f"{b.distance_ls:,.0f}" if b.distance_ls is not None else "-"
            self.tree.insert("", "end", tags=(tag,), values=(
                b.name or "?", b.kind or "?", dist, b.bio_signals or "", "  ".join(badges) or "-",
            ))

        t = r.tally
        self.tally.configure(text=(
            f"This session — first discoveries: {t['first_discovery']}   "
            f"first maps: {t['first_map']}   first footfalls: {t['first_footfall']}   "
            f"new codex: {t['codex_new']}   first-logged sold: {t['first_logged_sold']}"
        ))


def main() -> None:
    root = tk.Tk()
    RadarApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
