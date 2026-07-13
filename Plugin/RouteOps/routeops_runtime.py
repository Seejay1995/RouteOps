#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import RouteOps as legacy
from routeops_kernel_app import KernelRouteOpsApplication

VERSION = "0.6.1.0"


class RouteOpsRuntimeApplication(KernelRouteOpsApplication):
    """Release runtime that initializes only UI operations supported by EDDiscovery."""

    def start(self) -> None:
        self.route_library.refresh_availability(self.route_library_roots)
        self.route_library.save_to_config(self.client.config)

        if self.route_path and not Path(self.route_path).is_file():
            recovered = self._library_entry_for_path(self.route_path)
            if recovered and recovered.available:
                self.route_path = recovered.path
                self.client.config["route_path"] = recovered.path
                self.last_message = f"Recovered moved route: {recovered.name}."

        self.health_report = self.health_service.run(self.route_path)
        if self.health_report.overall_status != "healthy" and not self.last_message.startswith(
            "Recovered moved route"
        ):
            self.last_message = self.health_report.summary

        for grid in ("DGV", "BODIES", "ORGANISMS"):
            self.client.ui_set_dgv_setting(
                grid,
                column_reorder=True,
                per_column_word_wrap=False,
                allow_header_visibility=True,
                single_row_select=True,
            )

        if self.route_path and Path(self.route_path).is_file():
            self.load_route(self.route_path, quiet=True)
        else:
            self.refresh_ui()


def main() -> int:
    legacy.VERSION = VERSION
    legacy.RouteOpsApplication = RouteOpsRuntimeApplication
    return legacy.main()


if __name__ == "__main__":
    raise SystemExit(main())
