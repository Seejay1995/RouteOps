# M8-RC — Install Readiness

## Purpose

M8-RC converts the merged RouteOps architecture into a safe portable-install candidate. It does not add navigation intelligence or route-planning features.

## Release candidate

- Version: `0.6.0`
- Canonical version source: repository-root `VERSION`
- Target: EDDiscovery 19.0 or later on Windows
- Supported installation style: standard or portable EDDiscovery data root

## Installation safety

`install.ps1` now performs a transactional installation:

1. Resolve the active EDDiscovery data root.
2. Refuse installation while EDDiscovery is running.
3. Copy the candidate plugin and registration into a temporary staging directory.
4. Verify every required runtime file in staging.
5. Back up the existing plugin and action registration under `<EDD data root>/.routeops-backups/<timestamp>-v0.6.0`.
6. Replace the active plugin only after staging validation succeeds.
7. Verify the installed file set.
8. Automatically restore the backup if installation or verification fails.
9. Write an install report with the selected root, installed version, backup path, and rollback command.

The staging directory is removed whether installation succeeds or fails.

## Rollback

`rollback.ps1` restores either an explicit backup or the newest backup under `.routeops-backups`.

```powershell
powershell -ExecutionPolicy Bypass -File .\rollback.ps1 -EddDataRoot "E:\Your\EDDiscoveryData"
```

An explicit backup can be supplied:

```powershell
powershell -ExecutionPolicy Bypass -File .\rollback.ps1 `
  -EddDataRoot "E:\Your\EDDiscoveryData" `
  -BackupPath "E:\Your\EDDiscoveryData\.routeops-backups\<backup-folder>"
```

## Offline smoke validation

`tools/smoke_test.py` verifies the release without EDDiscovery:

- imports the packaged runtime modules;
- compiles `samples/smoke-expedition.json` through the source-provider/compiler boundary;
- constructs the route engine and route session;
- produces a session snapshot;
- records and persists the route through the portable route library.

The smoke test and version-consistency validator run through `tests/test_release_readiness.py` as part of the existing Windows test workflow.

## First run

1. Fully close EDDiscovery and verify `EDDiscovery.exe` is no longer running.
2. Run `install.ps1` with the portable install/data root when automatic detection is not sufficient.
3. Restart EDDiscovery.
4. Add RouteOps using the `(+)` panel selector.
5. Press **Health** before loading a route.
6. Confirm Python, `pyzmq`, registration, runtime files, and storage checks are healthy.
7. Load `samples/smoke-expedition.json` or a real route.
8. Confirm **Route Library** lists the loaded route and **Recent Route** can reopen it.

## Exit criteria

- [x] Canonical release version exists.
- [x] EDDiscovery action registration and panel UI use version 0.6.0.
- [x] Version consistency is tested automatically.
- [x] Offline compiler/session/library smoke test is tested automatically.
- [x] Installer validates a staged package before replacing active files.
- [x] Existing plugin and registration are backed up together.
- [x] Installation failures automatically restore the prior backup.
- [x] Explicit rollback script is supplied.
- [ ] Windows Python, PowerShell, release, and package validation pass.
- [ ] Release candidate is merged.
- [ ] Portable EDDiscovery installation is completed and first-run Health is verified.
