# M5 — Portable Session Storage

## Purpose

M5 makes RouteOps safe for portable EDDiscovery installations on arbitrary drives, including installations rooted anywhere on `E:`. It separates session persistence from the EDDiscovery adapter and makes portable install-root selection explicit and testable.

## Hard requirement

RouteOps must install and run when `EDDiscovery.exe`, the active EDDiscovery data folder, `Actions`, and `Plugins` are located on a portable drive rather than under Program Files or AppData.

## Scope

- Add a `SessionStorage` boundary between the application adapter and file persistence.
- Keep route-adjacent state as the preferred location.
- Resolve fallback state relative to the installed RouteOps plugin.
- Support a relative or absolute `session_state_root` configuration override.
- Add `-EddInstallRoot` and `-EddExecutable` installer parameters.
- Resolve `options*.txt` `-appfolder` values relative to the portable executable directory.
- Evaluate the executable folder, sibling `EDDiscovery` folder, and sibling `Data` folder using database and folder evidence.
- Verify all M1–M5 runtime modules after installation.

## Non-goals

- No change to the EDDiscovery ZMQ startup contract.
- No cloud persistence or synchronization.
- No database-backed RouteOps state store.
- No requirement that the portable install use a specific directory name.

## Portable examples

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 `
  -EddInstallRoot "E:\Portable Apps\EDDiscovery"
```

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 `
  -EddExecutable "E:\Games\Tools\EDD\EDDiscovery.exe"
```

An explicit data root remains supported:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 `
  -EddDataRoot "E:\EDD-Data"
```

## Storage behavior

1. RouteOps first saves beside the route as `<route>.routeops.state.json`.
2. If that location is unavailable, it saves under `Plugins\RouteOps\State` in the active portable EDDiscovery data root.
3. A configured `session_state_root` may be absolute or relative to the installed RouteOps plugin directory.

## Exit criteria

- [ ] Application state loading and saving use `SessionStorage`.
- [ ] Default fallback state is plugin-local and portable-drive safe.
- [ ] Relative and absolute state-root overrides are deterministic.
- [ ] Installer accepts arbitrary portable install and executable paths.
- [ ] `-appfolder` in portable options files has highest precedence.
- [ ] Database evidence selects the correct conventional portable data folder.
- [ ] Installer verifies all session, kernel, compiler, and provider modules.
- [ ] Python, PowerShell, EDDiscovery, and clean-package gates pass.
- [ ] Migration and rollback evidence is complete.

## Migration and rollback

The on-disk state format is unchanged. Existing route-adjacent and plugin-local state files continue to load through `state_store.py`. Rollback consists of restoring direct `load_state` and `save_state` calls in the adapter and invoking `Find-EddDataRoot` directly from the installer; no state conversion is required.
