# RouteOps

RouteOps is an EDDiscovery-native route creation, navigation, and execution platform for Elite Dangerous.

It supports the operational lifecycle of existing RouteOps activities—waypoints, exploration, exobiology, trade, cargo, and materials—from route compilation through live journal-driven execution and replanning.

## RouteOps 1.0 direction

RouteOps 1.0 is being developed phase by phase behind stable architectural boundaries:

- immutable route intent and definitions
- append-only journal observations
- explicit, reversible user decisions
- deterministic execution, navigation, progress, and value projections
- isolated activity providers
- typed commands with validation, previews, audit history, and undo
- structured diagnostics and replay-first debugging
- EDDiscovery-native deployment through a thin host adapter

## Development model

Each major 1.0 phase is developed on one branch and delivered through one draft pull request.

| Phase | Branch | Objective |
|---|---|---|
| M0 | `phase/m0-reliability-baseline` | Replay, package validation, installation, rollback, and compatibility baseline |
| M1 | `phase/m1-kernel-foundation` | Identity, observations, decisions, commands, projections, logging, and adapters |
| M2 | `phase/m2-exobiology-provider` | Migrate exobiology behind provider contracts |
| M3 | `phase/m3-route-compiler` | Route requests, candidates, explanations, review, scoring, and ordering |
| M4 | `phase/m4-navigation` | Consolidated explicit navigation and replanning |
| M5 | `phase/m5-provider-migrations` | Waypoint, exploration, trade, cargo, and materials providers |
| M6 | `phase/m6-state-migration` | Legacy state migration and repair |
| M7 | `phase/m7-ui` | Build, Review, Execute, and Diagnose workflows inside EDDiscovery |
| M8 | `phase/m8-release-hardening` | Full 1.0 release validation |

`main` must remain releasable. Phase branches merge only after their documented exit criteria pass.

## Status

Planning is complete. Development begins with M0: Reliability Baseline.
