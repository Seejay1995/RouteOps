# RouteOps Firsts Radar

A small standalone, colour-coded window that tails your Elite Dangerous journal and
shows — for the system you're currently in — which bodies still offer a **first**:

- **First discovery** (gold) — nobody has scanned this body before
- **First map** (cyan) — nobody has surface-mapped it (planets/moons only)
- **First footfall** (orange) — nobody has walked on it (landable bodies only)
- **BIO~FIRST** — biological signals in an *undiscovered* system, so anything you log
  there is almost certainly a first-logged (5x value) exobiology find

It also keeps a running session tally (first discoveries / maps / footfalls, new codex
entries, and confirmed first-logged bio sold at Vista Genomics).

## Why a radar and not a route

"First" means *nobody has been there* — so those systems aren't in Spansh, EDSM, or any
database (undiscovered = unreported = unlistable). No tool can hand you a list of
undiscovered systems. What works is going where the data is thin (off the exploration
highways: the galactic rim, above/below the plane, empty sectors) and letting this radar
flag the firsts around you **live** as you scan each system. It reads the exact
`WasDiscovered` / `WasMapped` / `WasFootfalled` flags the game writes to every `Scan`.

## Running it

Requires Python 3 (with tkinter, included in standard Windows Python).

- Double-click **`FirstsRadar.bat`**, or
- `pythonw firsts_radar.py`

It reads journals from the default location
(`%USERPROFILE%\Saved Games\Frontier Developments\Elite Dangerous`) and updates every
~1.5s. No EDDiscovery required — it runs beside the game on its own, and is immune to
EDD's panel issues. Tick **Always on top** to keep it over the game window.

## Files

- `firsts.py` — the detection engine (journal → per-body first-status + tallies). Reusable.
- `firsts_radar.py` — the tkinter window.
- `FirstsRadar.bat` — no-console launcher.

Standard library only.
