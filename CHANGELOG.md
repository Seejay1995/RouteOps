# Changelog

## 0.7.0

- Added an in-panel mode switcher (Exobiology / Colonisation / Cargo); each modality gets the whole panel via show/hide since EDDiscovery ZMQ panels have no native tabs.
- Added **Spansh exobiology route generation** directly in-panel: enter a start system, range, radius, min value and max bodies; RouteOps calls Spansh, flattens the result through the existing importer, saves it as a route and loads it.
- Added a **Colonisation Supply** board: reads your latest `ColonisationConstructionDepot` needs from the journal and finds the nearest large-pad source for each outstanding commodity (with trips, distance, buy price and supply), pad filter selectable.
- Added **Cargo (trade) routing**: give a start system (auto-filled from your journal location, cargo capacity from your latest Loadout) and RouteOps finds the nearest real market itself — routing you there for the first buy — then plots a profit-optimised loop. Large-pad toggle.
- Reworked the HEADER into a dashboard (progress meter, next target, legend) and added a live telemetry line (current body / fuel / target) from EDDiscovery `edduievent` pushes.
- Added per-cell tooltips across the system/body/species grids.
- Moved species/body triage onto grid right-click context menus (selectable difficulty and skip reason); retired the triage/body button bars.
- Consolidated the toolbar into Route / Navigation / Diagnostics dropdown menus.
- Added DataGridView column-layout persistence across restarts.
- Fixed a crash parsing journal events with list-valued fields (e.g. `Cargo` with an empty `Inventory`): membership checks now use tuples, not sets, and journal handling is guarded so one bad event cannot terminate the panel.
- Single-sourced the plugin version; the HEADER now reports the running version correctly.
- New modules: `routeops_version.py`, `spansh_client.py`, `colonisation.py`, `cargo.py` (standard library only).

## 0.5.0

- Replaced flat stop navigation with first-class system, body, organism, and explicit navigation-target models.
- Added pre-SAA system and body manifests from RouteOps v5 and compatible Spansh-style route data.
- Added separate system, body, and species queues so inspection no longer silently changes the active navigation target.
- Added Confirm, Auto-copy, and Auto-advance guidance modes; entering a system now selects a body target without completing exobiology work.
- Added route, nearest, highest-value, and stored-manual body ordering.
- Added body-qualified species skip previews with certainty, progress, reason, value impact, and body/system removal impact.
- Added reversible skip decisions and a persistent skip ledger; skips apply to the exact target on the exact body.
- Added per-organism search difficulty and expanded species triage rendering.
- Added state schema v6 for navigation targets, guidance, ordering, difficulty, pending skips, and skip decisions.
- Added navigation and skip-decision data to Exobio Debug Bundles.
- Preserved non-destructive Bacterium filtering, species progress, values, trade, material, cargo, exploration, carrier, docking, landing, and waypoint behavior.
- Expanded automated coverage to 98 tests.

## 0.4.0

- Rebuilt exobiology filtering as a non-mutating active-route projection rather than changing raw task and body status.
- Added canonical genus taxonomy with a versioned alias catalog, including Frontier's internal `Bacterial` identifiers for Bacterium.
- Added a full body species workspace showing inclusion, knowledge level, organism, sample count, exact value or range, active contribution, and source.
- Excluded Bacterium scans now continue to update and persist from `Log` through `Analyse`.
- Bacterium-only bodies and systems leave active navigation without being marked complete or skipped; mixed bodies retain non-Bacterium work.
- Added raw, excluded, active, secured, in-progress, and remaining value reevaluation at body and route levels.
- Added unresolved biological-signal placeholders and conservative body retention.
- Added organism and body inclusion overrides, Active/All body views, Show Excluded, and Exobio Debug Bundle export.
- Added knowledge-only journal history hydration and state schema v5 migration, including repair of old mutation-based filter state.
- Preserved waypoint, trade, cargo, materials, exploration, carrier, docking, and landing behavior through the shared projection refresh path.
- Expanded automated coverage to 85 tests.

## 0.3.2

- Fixed the Bacterium filter so filtered organisms are removed from the organism grid rather than only marked skipped internally.
- Bacterium-only planets are now removed from the active route grid while the filter is enabled.
- Route-grid selection now maps visible rows back to the correct underlying route stop after filtered planets are hidden.
- Expanded genus recognition to catch imported Bacterium targets from genus, species, variant, target, label, and common metadata fields.
- Re-enabling Bacterium restores hidden organisms and planets with their prior state.
- Expanded regression coverage from 66 to 70 tests.

## 0.3.1

- Fixed exobiology routes being restored or advanced as complete from system-arrival-only state.
- Added **Use Exobio** for converting a plain EDDiscovery expedition into non-completing exobiology operations.
- Plain expedition stops in Exobio Mode now wait in-system, bind to bodies from live journal events, and create additional body operations as new planets are visited.
- Dynamic bodies with no known biological-signal count remain manual-completion operations, preventing the first analysed species from completing a planet that may contain more lifeforms.
- Added persistent **Bacterium: On/Off** filtering. Filtered Bacterium targets are hidden, ignored by organic scan progress, excluded from sample totals, and removed from estimated route value.
- Entire Bacterium-only bodies are skipped automatically while the filter is active and can be restored by re-enabling Bacterium.
- Added state schema v4 persistence for Exobio Mode, organism filters, journal-discovered body operations, and filtered task restoration.
- Expanded regression coverage from 58 to 66 tests.

## 0.3.0

- Added body-scoped exobiology operations, organism sampling progress, exobiology values, live SAA enrichment, dynamic organisms, and Vista Genomics sale tracking.
- Added RouteOps schema v3 and state schema v3 migration.
- Added Spansh-style exobiology JSON and CSV normalization.
- Preserved trade, materials, cargo, exploration, carrier, and waypoint workflows.
## 0.2.2

- Added direct import of EDDiscovery Route-panel CSV/TSV exports.
- Added a parser for the exact Spansh Trade Router notes generated by EDDiscovery:
  - `Station: ...`
  - `<commodity> buy <amount> profit <value>`
  - `Profit so far: ...`
  - `Fly to <station> and sell all`
- Automatically generates dock, buy, and sell tasks for every trade leg.
- Carries each leg's purchased commodities into sell tasks at the following station.
- Supports comma, semicolon, and tab delimiters with quoted multiline notes.
- Renamed **Load JSON** to **Load Route** and expanded the chooser to JSON, CSV, and TSV.
- Added explicit warnings when a trade-named expedition JSON has already lost its station and commodity data.
- Added EDDiscovery Trade Router CSV sample and regression coverage.

## 0.2.1

- Fixed a regression where a blank or whitespace-only row in an expedition `Systems` list caused the entire route load to fail.
- Blank route rows are ignored with an import warning, matching RouteOps 0.1.x behavior.
- Preserved original source indexes for later stop IDs so legacy sidecar progress remains compatible.

## 0.2.0

- Rebuilt the panel layout to prevent the fill-docked route table from overlapping fixed controls.
- Added compact route header and selected-stop detail pane.
- Added six-column route table: number, stop, specialty, target, status, progress.
- Added waypoint, exploration, exobiology, materials, trade, cargo, carrier, dock, land, checklist, and mixed modes.
- Added row selection, Jump To, Reopen, Complete Task, and Reset Stop.
- Added RouteOps JSON schema v2 and v1 compatibility.
- Added normalized journal handling for navigation, scanning, organic scans, materials, market transactions, cargo, docking, and landing.
- Added state schema v2, v1 migration, atomic writes, corruption backup, and fallback state storage.
- Fixed Windows 64-bit clipboard pointer signatures and added retry/fallback behavior.
- Added four specialty sample routes.
- Expanded automated coverage to 33 tests plus fake-EDD ZMQ integration.

## 0.1.4

- Corrected EDDiscovery's exact `Module Check OK` checker response.

## 0.1.3

- Added authoritative `-appfolder` detection and strict-mode-safe registry inspection.

## 0.1.1

- Corrected active data-root database detection and panel registration placement.
