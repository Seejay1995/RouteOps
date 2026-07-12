# M3 — Source Providers

## Purpose

M3 separates route source acquisition from route compilation. Providers resolve a source identifier into a local compile target and immutable source metadata. `RouteCompiler` remains responsible for normalization and diagnostics.

## Scope

- Define provider-neutral route source contracts.
- Add a file-backed source provider.
- Add ordered provider resolution through a registry.
- Allow `RouteCompiler` to compile provider-resolved sources.
- Preserve `compile_file()` compatibility.
- Keep providers free of route-domain and gameplay logic.

## Non-goals

- No network provider implementation yet.
- No credentials, authentication, or background synchronization.
- No route-model, state, navigation, or UI redesign.
- No provider-specific logic in the kernel.

## Architecture

```text
source identifier
       |
RouteSourceRegistry
       |
RouteSourceProvider
       |
immutable RouteSource
       |
RouteCompiler
       |
normalized Route + diagnostics
```

## Exit criteria

- [ ] Source contracts and metadata are immutable.
- [ ] File sources resolve through the registry.
- [ ] Custom providers can feed the compiler without kernel changes.
- [ ] `compile_file()` behavior remains compatible.
- [ ] Application loading uses provider-aware compilation.
- [ ] Provider and compiler modules are package-validated.
- [ ] Existing regression, EDDiscovery, and package gates remain green.
- [ ] Migration and rollback notes are complete.
