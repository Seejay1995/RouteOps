# M0 — Reliability Baseline

## Purpose

M0 establishes a trustworthy development and release baseline before the RouteOps 1.0 kernel is introduced.

No activity behavior is redesigned in this phase. Existing functionality is captured, parsed, installed, verified, and reproduced as the behavioral baseline for future migration work.

## Scope

### Repository baseline

- Import the verified RouteOps 0.5.0 source.
- Preserve the current EDDiscovery plugin layout.
- Record the supported Python and EDDiscovery action-file versions.
- Establish deterministic local and CI commands.

### Behavioral baseline

The existing automated suite covers RouteOps engine behavior, importers, navigation, exobiology projection, filtering, state persistence, clipboard/UI behavior, package contracts, and release validation.

Representative sample routes are retained for waypoint, exploration, exobiology, materials, trade, cargo, and mixed-operation workflows.

### Release validation

The repository baseline validates:

- Python syntax compilation
- automated tests
- PowerShell parser validation
- supported `ACTIONFILE` header validation
- JSON parsing
- package manifest verification
- flat package-layout validation
- installed-file verification against the active EDDiscovery data root

## Branch contract

Branch: `phase/m0-reliability-baseline`

Base: `main`

## Exit evidence

- GitHub Actions workflow run 28 passed on commit `1e7186434914599c46d53ff5f91ecbbd80424d5b`.
- Python compilation passed.
- All automated test modules passed.
- PowerShell parsing passed.
- EDDiscovery artifact and release validation passed.
- Package-layout validation passed.
- The full test report was retained as the `m0-test-report` workflow artifact.
- Manual `verify.ps1` validation against the active EDDiscovery installation reported `File verification passed` on July 12, 2026.

## Exit criteria

- [x] Verified RouteOps 0.5.0 source is committed.
- [x] Existing tests pass from a clean checkout.
- [x] Existing behavioral coverage and representative route samples are preserved.
- [x] Every PowerShell file parses without errors.
- [x] Every action file uses a supported header.
- [x] Repository and packaged artifacts pass release validation.
- [x] Package layout is clean and reproducible.
- [x] Current EDDiscovery installation is validated manually.
- [x] M0 documentation and release evidence are complete.

## Non-goals

- No new activity types.
- No RouteOps kernel extraction yet.
- No UI redesign.
- No state-schema rewrite.
- No removal of legacy behavior.

## Definition of done

M0 is complete. The current RouteOps implementation is reproducible, validated, and suitable as the golden behavioral baseline for the 1.0 migration.
