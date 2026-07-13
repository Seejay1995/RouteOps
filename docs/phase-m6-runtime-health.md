# M6 — Runtime Health and Diagnostics

## Purpose

M6 makes RouteOps installation and runtime failures diagnosable from inside EDDiscovery, including portable installations on arbitrary drives.

## Scope

- Add a runtime-health service independent of route navigation state.
- Check Python compatibility and required Python modules.
- Verify required RouteOps runtime files and `config.json` startup configuration.
- Infer and display the active EDDiscovery data root from the installed plugin path.
- Verify the `Actions`, `Plugins`, and `RouteOpsPanel.act` layout.
- Probe portable fallback storage with a real temporary write and cleanup.
- Report the configured route and both resolved state paths.
- Add always-available **Health** and **Export Health** panel controls.
- Export matching JSON and text reports under `Plugins\RouteOps\Diagnostics`.
- Keep health checks outside the route engine and navigation kernel.

## Status model

- **Pass** — the requirement is available and verified.
- **Info** — useful context that does not require action.
- **Warning** — RouteOps can continue, but configuration may be stale or incomplete.
- **Error** — a required runtime component is unavailable or unusable.

The overall state is `error` when any error exists, `warning` when warnings exist without errors, and `healthy` otherwise.

## Portable-install behavior

The report includes:

- installed RouteOps plugin directory;
- inferred EDDiscovery data root;
- route path, when configured;
- route-adjacent state path;
- plugin-local fallback state path;
- panel registration status;
- fallback storage writability.

A missing route is reported as a warning because portable drive letters can change. The report directs the user to reload the route rather than treating the installation as corrupt.

## Non-goals

- No automatic repair or file deletion.
- No modification of route navigation state.
- No network telemetry or remote diagnostics upload.
- No replacement for the existing exobiology debug bundle.

## Exit criteria

- [x] Health checks run with no route loaded.
- [x] Health checks do not mutate route or kernel state.
- [x] Required files, configuration, dependency, registration, and storage checks are covered.
- [x] Portable state storage is tested with a real write and cleanup.
- [x] Missing routes produce actionable warnings.
- [x] Health controls remain enabled regardless of route state.
- [x] JSON and text exports contain matching report data.
- [x] Installer and package contracts include `runtime_health.py` and both controls.
- [x] Python, PowerShell, EDDiscovery, and clean-package validation pass.
- [x] Migration and rollback evidence is complete.

## Validation evidence

GitHub Actions workflow run #68 passed on Windows at commit `1dcfd8265994ad73b493cbab2e5c8e0fa01bc4e1`. Python compilation, the complete Python test suite, PowerShell parsing, EDDiscovery artifact validation, and clean-package validation all completed successfully.

The regression suite verifies route-free health checks, complete portable layouts, required-file failures, moved or missing routes, route-adjacent and fallback state paths, real fallback-directory write probes with cleanup, JSON/text export consistency, and EDDiscovery panel invocation without a loaded route.

The initial workflow run #67 exposed a Windows short-path versus long-path test comparison. Production path resolution was correct; the test was repaired to compare filesystem identity rather than raw path strings, and run #68 passed.

## Migration and rollback

M6 does not change route files, session state, or the EDDiscovery ZMQ contract. Existing installations gain one runtime module and two panel controls. Rollback consists of removing `runtime_health.py`, the two UI controls, and the adapter health-service integration. No stored data conversion is required.
