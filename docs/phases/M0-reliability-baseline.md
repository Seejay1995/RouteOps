# M0 — Reliability Baseline

## Objective

Establish repeatable validation, replay, packaging, installation, and rollback gates before RouteOps 1.0 architecture work begins.

M0 does not change gameplay behavior. It captures and protects the existing RouteOps behavior so later phases can refactor safely.

## Scope

- Import the latest verified RouteOps v0.5.x source into this branch.
- Compile every Python source file.
- Run the complete existing test suite.
- Parse every PowerShell script before release.
- Validate EDDiscovery `.act` headers against the supported format.
- Validate JSON artifacts and optional SHA-256 manifests.
- Reject nested release roots, backup payloads, bytecode, and temporary files.
- Create replay fixtures for current activity workflows.
- Simulate clean installation, upgrade, rollback, and reinstall.
- Produce diagnostics sufficient to reproduce every M0 failure.

## Required replay scenarios

1. Generic waypoint arrival.
2. Exploration route with explicit body work.
3. Exobiology route with multiple systems and bodies.
4. Bacterium filter applied before and after scan observations.
5. Partial organism progress followed by restart.
6. Body-specific species skip and undo.
7. System entry without body completion.
8. Trade buy and sell observations.
9. Cargo pickup and delivery observations.
10. Material quantity collection.

## Release gates

M0 may merge only when:

- the current RouteOps source is present in the branch;
- all legacy tests pass from a clean checkout;
- every replay produces a stable expected snapshot;
- all Python and PowerShell files parse;
- every action file uses an EDDiscovery-supported header;
- the exact packaged artifact installs into a disposable EDDiscovery-shaped directory;
- rollback restores the previous installation byte-for-byte;
- reinstall succeeds after rollback;
- package validation runs in GitHub Actions on Windows;
- the draft PR documents known baseline defects without silently changing their behavior.

## Out of scope

- Kernel implementation
- Provider migration
- Route compiler implementation
- Navigation redesign
- State schema redesign
- UI redesign

Those changes begin only after M0 is merged.
