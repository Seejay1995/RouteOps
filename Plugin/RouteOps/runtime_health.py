from __future__ import annotations

import importlib.util
import json
import platform
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from session_storage import SessionStorage


STATUS_PASS = "pass"
STATUS_INFO = "info"
STATUS_WARNING = "warning"
STATUS_ERROR = "error"

DEFAULT_REQUIRED_FILES = (
    "config.json",
    "RouteOps.py",
    "routeops_runtime.py",
    "routeops_kernel_app.py",
    "route_compiler.py",
    "source_providers.py",
    "route_session.py",
    "session_storage.py",
    "route_kernel.py",
    "kernel_contracts.py",
    "state_store.py",
    "UIInterface.act",
)


@dataclass(frozen=True)
class HealthCheck:
    """One deterministic runtime-health observation."""

    name: str
    status: str
    summary: str
    detail: str = ""
    action: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "summary": self.summary,
            "detail": self.detail,
            "action": self.action,
        }


@dataclass(frozen=True)
class RuntimeHealthReport:
    """Portable-safe health report for one RouteOps process."""

    generated_at: str
    plugin_directory: str
    eddiscovery_data_root: str
    route_path: str
    storage_primary: str
    storage_fallback: str
    checks: tuple[HealthCheck, ...]

    @property
    def overall_status(self) -> str:
        statuses = {check.status for check in self.checks}
        if STATUS_ERROR in statuses:
            return "error"
        if STATUS_WARNING in statuses:
            return "warning"
        return "healthy"

    @property
    def issue_count(self) -> int:
        return sum(check.status in {STATUS_WARNING, STATUS_ERROR} for check in self.checks)

    @property
    def summary(self) -> str:
        if self.overall_status == "healthy":
            return "Runtime health is healthy."
        return f"Runtime health is {self.overall_status}: {self.issue_count} issue(s) require attention."

    def to_dict(self) -> dict[str, Any]:
        return {
            "generatedAt": self.generated_at,
            "overallStatus": self.overall_status,
            "issueCount": self.issue_count,
            "pluginDirectory": self.plugin_directory,
            "eddiscoveryDataRoot": self.eddiscovery_data_root,
            "routePath": self.route_path,
            "storagePrimary": self.storage_primary,
            "storageFallback": self.storage_fallback,
            "checks": [check.to_dict() for check in self.checks],
        }

    def render_text(self) -> str:
        lines = [
            f"ROUTEOPS RUNTIME HEALTH: {self.overall_status.upper()}",
            f"Generated: {self.generated_at}",
            f"Plugin: {self.plugin_directory}",
            f"EDDiscovery data root: {self.eddiscovery_data_root}",
        ]
        if self.route_path:
            lines.append(f"Route: {self.route_path}")
        if self.storage_primary:
            lines.append(f"Primary state: {self.storage_primary}")
        if self.storage_fallback:
            lines.append(f"Fallback state: {self.storage_fallback}")
        lines.append("")
        for check in self.checks:
            lines.append(f"[{check.status.upper()}] {check.name}: {check.summary}")
            if check.detail:
                lines.append(f"  {check.detail}")
            if check.action:
                lines.append(f"  Action: {check.action}")
        return "\r\n".join(lines)


class RuntimeHealthService:
    """Collects and exports non-mutating RouteOps runtime diagnostics."""

    def __init__(
        self,
        plugin_directory: str | Path,
        storage: SessionStorage,
        required_files: Iterable[str] = DEFAULT_REQUIRED_FILES,
        required_modules: Iterable[str] = ("zmq",),
    ) -> None:
        self.plugin_directory = Path(plugin_directory).expanduser().resolve()
        self.storage = storage
        self.required_files = tuple(required_files)
        self.required_modules = tuple(required_modules)

    @property
    def eddiscovery_data_root(self) -> Path:
        parent = self.plugin_directory.parent
        if self.plugin_directory.name.casefold() == "routeops" and parent.name.casefold() == "plugins":
            return parent.parent
        return parent

    def run(self, route_path: str = "") -> RuntimeHealthReport:
        route_path = str(route_path or "")
        storage_primary = ""
        storage_fallback = ""
        if route_path:
            paths = self.storage.paths_for(route_path)
            storage_primary = str(paths.primary)
            storage_fallback = str(paths.fallback)

        checks: list[HealthCheck] = []
        checks.extend(self._check_python())
        checks.extend(self._check_dependencies())
        checks.extend(self._check_plugin_layout())
        checks.extend(self._check_configuration())
        checks.extend(self._check_eddiscovery_layout())
        checks.extend(self._check_storage())
        checks.extend(self._check_route(route_path))

        return RuntimeHealthReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            plugin_directory=str(self.plugin_directory),
            eddiscovery_data_root=str(self.eddiscovery_data_root),
            route_path=route_path,
            storage_primary=storage_primary,
            storage_fallback=storage_fallback,
            checks=tuple(checks),
        )

    def export(self, report: RuntimeHealthReport, directory: str | Path | None = None) -> Path:
        destination = Path(directory).expanduser().resolve() if directory else self.plugin_directory / "Diagnostics"
        destination.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
        json_path = destination / f"routeops-runtime-health-{stamp}.json"
        text_path = destination / f"routeops-runtime-health-{stamp}.txt"
        json_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        text_path.write_text(report.render_text(), encoding="utf-8")
        return json_path

    def _check_python(self) -> list[HealthCheck]:
        version = platform.python_version()
        if sys.version_info < (3, 10):
            return [HealthCheck(
                "Python runtime",
                STATUS_ERROR,
                f"Python {version} is too old for RouteOps.",
                action="Configure EDDiscovery to use Python 3.10 or later.",
            )]
        return [HealthCheck("Python runtime", STATUS_PASS, f"Python {version} is supported.")]

    def _check_dependencies(self) -> list[HealthCheck]:
        checks: list[HealthCheck] = []
        for module_name in self.required_modules:
            if importlib.util.find_spec(module_name) is None:
                checks.append(HealthCheck(
                    f"Python module {module_name}",
                    STATUS_ERROR,
                    "Required dependency is unavailable.",
                    action="Restart EDDiscovery so its module installer can install the missing dependency.",
                ))
            else:
                checks.append(HealthCheck(f"Python module {module_name}", STATUS_PASS, "Dependency is available."))
        return checks

    def _check_plugin_layout(self) -> list[HealthCheck]:
        checks: list[HealthCheck] = []
        if not self.plugin_directory.is_dir():
            return [HealthCheck(
                "Plugin directory",
                STATUS_ERROR,
                "The RouteOps plugin directory does not exist.",
                detail=str(self.plugin_directory),
                action="Reinstall RouteOps into the active EDDiscovery data root.",
            )]

        missing = [name for name in self.required_files if not (self.plugin_directory / name).is_file()]
        if missing:
            checks.append(HealthCheck(
                "Runtime files",
                STATUS_ERROR,
                f"{len(missing)} required runtime file(s) are missing.",
                detail=", ".join(missing),
                action="Run install.ps1 again against the active portable EDDiscovery installation.",
            ))
        else:
            checks.append(HealthCheck("Runtime files", STATUS_PASS, "All required runtime files are present."))
        return checks

    def _check_configuration(self) -> list[HealthCheck]:
        config_path = self.plugin_directory / "config.json"
        try:
            config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return [HealthCheck(
                "Plugin configuration",
                STATUS_ERROR,
                "config.json cannot be read.",
                detail=str(exc),
                action="Reinstall RouteOps to restore a valid plugin configuration.",
            )]

        python_config = config.get("Python", {}) if isinstance(config, dict) else {}
        start = str(python_config.get("Start", "")) if isinstance(python_config, dict) else ""
        if start.casefold() != "routeops_runtime.py":
            return [HealthCheck(
                "Plugin configuration",
                STATUS_ERROR,
                "EDDiscovery is not configured to start the RouteOps runtime application.",
                detail=f"Configured start file: {start or '<missing>'}",
                action="Reinstall RouteOps so config.json starts routeops_runtime.py.",
            )]
        return [HealthCheck("Plugin configuration", STATUS_PASS, "RouteOps runtime startup is configured correctly.")]

    def _check_eddiscovery_layout(self) -> list[HealthCheck]:
        data_root = self.eddiscovery_data_root
        actions = data_root / "Actions"
        plugins = data_root / "Plugins"
        registration = actions / "RouteOpsPanel.act"
        checks: list[HealthCheck] = []
        if plugins.is_dir() and actions.is_dir():
            checks.append(HealthCheck("EDDiscovery data root", STATUS_PASS, "Actions and Plugins folders are present.", detail=str(data_root)))
        else:
            checks.append(HealthCheck(
                "EDDiscovery data root",
                STATUS_WARNING,
                "The plugin is not under a complete Actions/Plugins data-root layout.",
                detail=str(data_root),
                action="Confirm the installer targeted the active portable EDDiscovery data root.",
            ))
        if registration.is_file():
            checks.append(HealthCheck("Panel registration", STATUS_PASS, "RouteOpsPanel.act is registered."))
        else:
            checks.append(HealthCheck(
                "Panel registration",
                STATUS_WARNING,
                "RouteOpsPanel.act was not found in the inferred Actions folder.",
                detail=str(registration),
                action="Run install.ps1 against the active EDDiscovery data root.",
            ))
        return checks

    def _check_storage(self) -> list[HealthCheck]:
        fallback = getattr(self.storage, "fallback_dir", self.plugin_directory / "State")
        success, detail = self._probe_writable_directory(Path(fallback))
        if success:
            return [HealthCheck("Session storage", STATUS_PASS, "Portable fallback storage is writable.", detail=str(fallback))]
        return [HealthCheck(
            "Session storage",
            STATUS_ERROR,
            "Portable fallback storage is not writable.",
            detail=detail,
            action="Grant write access or configure session_state_root to a writable folder on the portable drive.",
        )]

    def _check_route(self, route_path: str) -> list[HealthCheck]:
        if not route_path:
            return [HealthCheck("Route file", STATUS_INFO, "No route is currently configured.")]
        path = Path(route_path).expanduser()
        if path.is_file():
            return [HealthCheck("Route file", STATUS_PASS, "The configured route file exists.", detail=str(path.resolve()))]
        return [HealthCheck(
            "Route file",
            STATUS_WARNING,
            "The configured route file cannot be found.",
            detail=str(path),
            action="Use Load Route to select the route again; removable-drive letters may have changed.",
        )]

    @staticmethod
    def _probe_writable_directory(directory: Path) -> tuple[bool, str]:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix=".routeops-health-",
                suffix=".tmp",
                dir=directory,
                delete=False,
            ) as probe:
                probe.write("RouteOps health probe")
                probe_path = Path(probe.name)
            probe_path.unlink(missing_ok=True)
            return True, str(directory)
        except OSError as exc:
            return False, f"{directory}: {exc}"
