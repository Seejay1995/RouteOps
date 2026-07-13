# M7 — Portable Route Library

## Purpose

M7 replaces the single remembered route path with a bounded recent-route library that remains useful when RouteOps or route files move between portable drives and computers.

## Scope

- Store recent route metadata in the existing EDDiscovery plugin configuration JSON.
- Record route name, ID, type, source format, system/stop counts, completion percentage, last system, fingerprint, path, and last-opened time.
- Deduplicate copied routes by SHA-256 file fingerprint.
- Keep the library bounded to twelve entries by default.
- Recheck availability at startup and whenever the library is displayed.
- Recover moved routes from explicit search roots and the same relative path on other Windows drive roots.
- Avoid unbounded recursive whole-drive scans.
- Add **Recent Route** and **Route Library** controls to the EDDiscovery panel.
- Automatically repair the remembered active route path when a matching moved route is found.
- Verify `route_library.py` during portable installation.

## Portable recovery behavior

Recovery attempts are deterministic and bounded:

1. Original route path.
2. Route filename directly under configured/plugin-adjacent search roots.
3. Route filename under a `Routes` child of those roots.
4. The original drive-relative path on currently available Windows drives.
5. The route filename at the root of currently available Windows drives.

A candidate is accepted only when its content fingerprint matches the stored route fingerprint. When no fingerprint exists for a legacy entry, an existing exact candidate path may be accepted.

## Configuration

The library is stored under `route_library` in the existing EDDiscovery plugin config. Optional additional bounded roots may be supplied as a list under `route_library_roots`.

No separate database or machine-profile storage is introduced.

## Non-goals

- No recursive search of entire drives.
- No cloud synchronization.
- No route editing or optimization.
- No change to route, session-state, or ZMQ formats.
- No automatic deletion of missing entries.

## Exit criteria

- [ ] Complete route-library module replaces the truncated prototype.
- [ ] Recent entries round-trip through EDDiscovery config.
- [ ] Duplicate copies are deduplicated by fingerprint.
- [ ] Library size is bounded.
- [ ] Missing routes recover through bounded portable roots.
- [ ] Incorrect-content candidates are rejected.
- [ ] Successful route loads update the library.
- [ ] Startup repairs a moved remembered route when possible.
- [ ] Recent Route and Route Library controls work without changing route/session formats.
- [ ] Installer verifies `route_library.py`.
- [ ] Python, PowerShell, EDDiscovery, and clean-package validation pass.
- [ ] Migration and rollback evidence is complete.

## Migration and rollback

Existing users begin with an empty library and retain the existing `route_path` behavior. Every successful route load adds or refreshes one library entry. Legacy or malformed library items are ignored rather than blocking startup.

Rollback consists of removing `route_library.py`, the two panel controls, and adapter integration. The additional `route_library` config value can remain because older builds ignore unknown config keys. No route or state conversion is required.
