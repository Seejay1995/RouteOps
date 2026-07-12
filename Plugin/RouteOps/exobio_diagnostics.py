from __future__ import annotations

import json
import zipfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any


def _write_json(archive: zipfile.ZipFile, name: str, value: Any) -> None:
    archive.writestr(name, json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, default=str))


def export_debug_bundle(engine: Any, destination_dir: str | Path | None = None) -> Path:
    folder = Path(destination_dir) if destination_dir else Path.home() / "Downloads"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = folder / f"RouteOps-Exobio-Debug-{stamp}.zip"

    route = engine.route
    projection = engine.projection
    normalized_route = {
        "id": route.id,
        "name": route.name,
        "routeType": route.route_type,
        "sourceFormat": route.source_format,
        "sourcePath": route.source_path,
        "settings": route.settings.to_dict(),
        "stops": [
            {
                "id": stop.id,
                "system": stop.system,
                "systemAddress": stop.system_address,
                "body": stop.body,
                "bodyId": stop.body_id,
                "status": stop.status,
                "phase": stop.operation_phase,
                "biologicalSignals": stop.biological_signal_count,
                "tasks": [task.to_state() for task in stop.tasks],
            }
            for stop in route.stops
        ],
    }
    projection_json = {
        "activeIndices": list(projection.active_indices),
        "visibleIndices": list(projection.visible_indices),
        "routeValues": {
            "rawExact": projection.raw_exact_value,
            "rawMin": projection.raw_min_value,
            "rawMax": projection.raw_max_value,
            "excludedExact": projection.excluded_exact_value,
            "excludedMin": projection.excluded_min_value,
            "excludedMax": projection.excluded_max_value,
            "activeExact": projection.active_exact_value,
            "activeMin": projection.active_min_value,
            "activeMax": projection.active_max_value,
            "secured": projection.secured_active_value,
            "inProgress": projection.in_progress_active_value,
            "remaining": projection.remaining_active_value,
            "unknownSlots": projection.unknown_value_slots,
        },
        "bodies": {stop_id: asdict(body) for stop_id, body in projection.bodies.items()},
    }
    navigation_json = {
        "target": engine.navigation_target.to_dict(),
        "guidanceMode": engine.guidance_mode,
        "bodyOrderMode": engine.body_order_mode,
        "selectedSystemKey": engine.selected_system_key,
        "selectedStopId": engine.selected_stop.id if engine.selected_stop else "",
        "currentStopId": engine.current_stop.id if engine.current_stop else "",
        "systems": [asdict(system) for system in engine.navigation.systems],
    }
    skip_json = {
        "pending": dict(engine.pending_skip) if engine.pending_skip else None,
        "decisions": [item.to_dict() for item in engine.skip_decisions],
    }
    summary_lines = [
        f"Route: {route.name}",
        f"Route ID: {route.id}",
        f"Source: {route.source_path}",
        f"Excluded genera: {', '.join(route.settings.excluded_organism_genera) or 'none'}",
        f"Active bodies: {len(projection.active_indices)}",
        f"Filtered bodies: {len(route.stops) - len(projection.active_indices)}",
        f"Raw exact value: {projection.raw_exact_value}",
        f"Excluded exact value: {projection.excluded_exact_value}",
        f"Active exact value: {projection.active_exact_value}",
        f"Guidance mode: {engine.guidance_mode}",
        f"Body order: {engine.body_order_mode}",
        f"Navigation target: {engine.navigation_target.target_type} / {engine.navigation_target.text}",
        f"Skip decisions: {len(engine.skip_decisions)}",
        "",
    ]
    for stop in route.stops:
        body = projection.body_for(stop)
        if not body:
            continue
        summary_lines.extend(
            [
                f"{stop.system} / {stop.body or '(system placeholder)'}",
                f"  inclusion: {body.inclusion_state} ({body.inclusion_reason})",
                f"  included/excluded/unresolved: {body.included_count}/{body.excluded_count}/{body.unresolved_count}",
                f"  active/excluded/raw exact value: {body.values.active_exact}/{body.values.excluded_exact}/{body.values.raw_exact}",
            ]
        )
        for item in body.tasks:
            summary_lines.append(
                f"    {item.task_id}: {item.taxonomy.genus_id or '?'} / {item.taxonomy.species_name or '?'} "
                f"{item.sample_count}/{item.sample_target} {item.decision.state} ({item.decision.reason})"
            )

    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        source_path = Path(route.source_path)
        if source_path.is_file():
            try:
                archive.write(source_path, f"route-source{source_path.suffix or '.txt'}")
            except OSError:
                pass
        _write_json(archive, "normalized-route.json", normalized_route)
        _write_json(archive, "active-projection.json", projection_json)
        _write_json(archive, "navigation-plan.json", navigation_json)
        _write_json(archive, "skip-decisions.json", skip_json)
        _write_json(archive, "state.json", engine.to_state())
        _write_json(archive, "recent-exobio-events.json", list(getattr(engine, "recent_exobio_events", [])))
        _write_json(archive, "filter-profile.json", {
            "excludedGenera": list(route.settings.excluded_organism_genera),
            "showExcludedOrganisms": route.settings.show_excluded_organisms,
            "hideEmptyBodies": route.settings.hide_empty_bodies,
            "hideEmptySystems": route.settings.hide_empty_systems,
            "routeViewMode": route.settings.route_view_mode,
        })
        archive.writestr("diagnostic-summary.txt", "\r\n".join(summary_lines))
    return destination
