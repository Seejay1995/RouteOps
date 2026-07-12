# M0 — Reliability Baseline

## Purpose

M0 establishes a trustworthy development and release baseline before the RouteOps 1.0 kernel is introduced.

No activity behavior is redesigned in this phase. Existing functionality is captured, replayed, parsed, installed, verified, rolled back, and reproduced.

## Scope

### Repository baseline

- Import the latest verified RouteOps v0.5.x source.
- Preserve the current EDDiscovery plugin layout.
- Record the supported Python and EDDiscovery action-file versions.
- Establish deterministic local and CI commands.

### Replay baseline

Capture representative fixtures for:

- waypoint arrival
- exploration system and body work
- multi-body exobiology
- Bacterium filtering
- partial organism sampling and restart
- species skip and undo
- trade buy and sell
- cargo pickup and delivery
- material collection

Each replay must define expected progress, navigation, value, and completion outputs.

### Release validation

The exact packaged artifact must pass:

- Python syntax compilation
- automated tests
- PowerShell parser validation
- supported `ACTIONFILE` header validation
- JSON parsing
- package manifest verification
- flat ZIP layout validation
- clean install simulation
- upgrade simulation
- rollback simulation
- reinstall after rollback

## Branch contract

Branch: `phase/m0-reliability-baseline`

Base: `main`

The branch remains a draft pull request until every exit criterion below is met.

## Exit criteria

- [ ] Latest verified v0.5.x source is committed.
- [ ] Existing tests pass from a clean checkout.
- [ ] Replay fixtures reproduce current behavior.
- [ ] Every PowerShell file parses without errors.
- [ ] Every action file uses a supported header.
- [ ] Package verification runs against the exact ZIP contents.
- [ ] Clean install simulation passes.
- [ ] Rollback and reinstall simulation pass.
- [ ] Current EDDiscovery installation is validated manually.
- [ ] M0 documentation and release evidence are complete.

## Non-goals

- No new activity types.
- No new RouteOps kernel yet.
- No UI redesign.
- No state-schema rewrite.
- No removal of legacy behavior.

## Definition of done

M0 is complete when the current RouteOps implementation can be reproduced and released reliably enough to serve as the golden behavioral baseline for the 1.0 migration.
