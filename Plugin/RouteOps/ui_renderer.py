from __future__ import annotations

from typing import Any

from exobio_taxonomy import InclusionState, KnowledgeLevel
from navigation_model import SKIP_REASON_LABELS
from route_engine import RouteEngine
from route_models import OperationPhase, ProgressStatus, RouteStop, StopType, TaskStatus
from routeops_version import DISPLAY_VERSION
from specializations import display_name


def _credits(value: int | None) -> str:
    number = int(value or 0)
    if number >= 1_000_000_000:
        return f"{number / 1_000_000_000:.2f}B CR"
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M CR"
    if number >= 1_000:
        return f"{number / 1_000:.1f}K CR"
    return f"{number:,} CR"


def _value_or_range(exact: int | None, low: int | None, high: int | None) -> str:
    if exact is not None:
        return _credits(exact)
    low_value = int(low or 0)
    high_value = int(high or low_value)
    if low_value == 0 and high_value == 0:
        return "Unknown"
    if low_value == high_value:
        return _credits(low_value)
    return f"{_credits(low_value)}-{_credits(high_value)}"


def _distance(value: float | None) -> str:
    if value is None:
        return "?"
    if value >= 1000:
        return f"{value:,.0f} ls"
    return f"{value:.1f} ls"


def _manifest_label(value: str) -> str:
    return {
        "exact": "EXACT",
        "bodies-known": "BODIES",
        "system-only": "SYSTEM ONLY",
        "live": "LIVE",
    }.get(value, value.upper() if value else "UNKNOWN")


def _bar(fraction: float, width: int = 18) -> str:
    """Monochrome text progress bar, e.g. [########----------]."""
    if fraction < 0:
        fraction = 0.0
    elif fraction > 1:
        fraction = 1.0
    filled = int(round(fraction * width))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def _progress_line(metrics) -> str:
    total = metrics.total_stops or 0
    resolved = metrics.complete_stops + metrics.skipped_stops
    fraction = (resolved / total) if total else 0.0
    pct = int(round(fraction * 100))
    skipped = f" ({metrics.skipped_stops} skipped)" if metrics.skipped_stops else ""
    samples = (
        f" - SAMPLES {metrics.completed_samples}/{metrics.total_samples}"
        if metrics.total_samples
        else ""
    )
    return f"PROGRESS {_bar(fraction)} {pct}% - BODIES {metrics.complete_stops}/{total}{skipped}{samples}"


def render_header(engine: RouteEngine, last_message: str = "", telemetry: str = "") -> str:
    metrics = engine.route_metrics()
    target = engine.navigation_target
    current = engine.current_stop
    system = engine.current_system
    target_text = target.text or "No active target"
    target_kind = target.target_type.replace("-", " ").upper()
    location = system.name if system else (current.system if current else "No active system")
    if current and current.body:
        location += f" / {current.body}"
    system_summary = ""
    if system:
        system_summary = f" - {system.active_body_count} bodies - {system.target_count} targets - {_credits(system.active_value)}"
    status = f" - STATUS: {last_message}" if last_message else ""
    lines = [
        f"ROUTEOPS {DISPLAY_VERSION} - {engine.route.name}",
        _progress_line(metrics),
    ]
    if telemetry:
        lines.append(telemetry)
    lines.extend(
        [
            f"NAVIGATION: {target_kind} - {target_text}",
            f"LOCATION: {location}{system_summary}",
            f"GUIDANCE: {engine.guidance_mode.upper()} - ORDER: {engine.body_order_mode.upper()} - ACTIVE: {_credits(metrics.active_base_value)} - SECURED: {_credits(metrics.secured_base_value)}{status}",
            "LEGEND: >=current  *=selected  -  right-click a body or species row for actions",
        ]
    )
    return "\r\n".join(lines)


def _skip_preview_lines(engine: RouteEngine) -> list[str]:
    pending = engine.pending_skip
    if not pending:
        return []
    body_removed = "Yes" if pending.get("bodyRemovedFromRoute") else "No"
    system_removed = "Yes" if pending.get("systemRemovedFromRoute") else "No"
    return [
        "",
        "SKIP IMPACT PREVIEW",
        f"SYSTEM: {pending.get('systemName', '')}",
        f"BODY: {pending.get('bodyName', '')}",
        f"ORGANISM: {pending.get('organismName', '')}",
        f"CERTAINTY: {str(pending.get('certainty', 'unknown')).replace('-', ' ').upper()}",
        f"PROGRESS: {pending.get('progress', '0/3')}",
        f"REASON: {SKIP_REASON_LABELS.get(str(pending.get('reason')), str(pending.get('reason')))}",
        f"VALUE REMOVED: {_credits(int(pending.get('valueRemoved', 0) or 0))}",
        f"BODY VALUE: {_credits(int(pending.get('bodyValueBefore', 0) or 0))} -> {_credits(int(pending.get('bodyValueAfter', 0) or 0))}",
        f"REMOVE BODY FROM ACTIVE NAVIGATION: {body_removed}",
        f"REMOVE SYSTEM FROM ACTIVE NAVIGATION: {system_removed}",
        "Use Confirm Skip to apply this body-specific decision, or Cancel Skip.",
    ]


def render_detail(engine: RouteEngine) -> str:
    stop = engine.selected_stop
    if not stop:
        return "No body selected."
    body = engine.body_projection(stop)
    plan = engine.navigation.body(stop.id)
    selected_task = engine.selected_task
    lines = [
        f"INSPECTING SYSTEM: {stop.system}",
        f"BODY: {stop.body or 'System-level placeholder'}",
        f"MANIFEST: {_manifest_label(plan.manifest_completeness if plan else stop.manifest_completeness)} - "
        f"SOURCE: {(plan.manifest_source if plan else stop.manifest_source) or engine.route.source_format}",
    ]
    if plan:
        lines.append(f"DISTANCE FROM ARRIVAL: {_distance(plan.distance_from_arrival_ls)}")
    if body and stop.stop_type == StopType.EXOBIOLOGY:
        included_current, included_total = engine.sample_progress(stop)
        excluded_current, excluded_total = engine.sample_progress(stop, include_excluded=True)
        excluded_current -= included_current
        excluded_total -= included_total
        lines.extend(
            [
                f"BIOLOGICAL SIGNALS: {stop.biological_signal_count if stop.biological_signal_count is not None else '?'}",
                f"TARGETS: {body.included_count} included - {body.excluded_count} filtered - {body.unresolved_count} unresolved",
                f"SAMPLES: {included_current}/{included_total} active - {max(0, excluded_current)}/{max(0, excluded_total)} excluded",
                f"VALUE: {_value_or_range(body.values.active_exact if body.values.active_min == body.values.active_max else None, body.values.active_min, body.values.active_max)} active - "
                f"{_value_or_range(body.values.excluded_exact if body.values.excluded_min == body.values.excluded_max else None, body.values.excluded_min, body.values.excluded_max)} excluded - "
                f"{_value_or_range(body.values.raw_exact if body.values.raw_min == body.values.raw_max else None, body.values.raw_min, body.values.raw_max)} raw",
            ]
        )
        if selected_task:
            projection = engine.task_projection(selected_task, stop)
            lines.extend(
                [
                    "",
                    "SELECTED SPECIES TARGET",
                    f"SYSTEM / BODY: {stop.system} / {stop.body}",
                    f"GENUS: {selected_task.genus or 'Unknown'}",
                    f"SPECIES: {selected_task.species or 'Unresolved'}",
                    f"VARIANT: {selected_task.variant or 'Not confirmed'}",
                    f"CERTAINTY: {(projection.knowledge_level if projection else selected_task.knowledge_level).replace('-', ' ').upper()}",
                    f"SCANS: {selected_task.quantity_completed}/{selected_task.quantity_required}",
                    f"DIFFICULTY: {selected_task.search_difficulty.replace('-', ' ').upper()}",
                    f"VALUE: {_value_or_range(projection.value_exact if projection else selected_task.base_value, projection.value_min if projection else None, projection.value_max if projection else None)}",
                ]
            )
            if selected_task.status == TaskStatus.SKIPPED:
                reason = str(selected_task.metadata.get("skipReason") or "other")
                lines.append(f"DECISION: SKIPPED ON THIS BODY - {SKIP_REASON_LABELS.get(reason, reason)}")
            elif projection and projection.excluded:
                lines.append("DECISION: FILTERED - progress remains recorded but does not count toward active value or completion.")
    else:
        lines.append(f"OPERATION: {display_name(stop.stop_type)} - STATUS: {stop.status.upper()}")
        if stop.station:
            lines.append(f"STATION: {stop.station}")
        if stop.settlement:
            lines.append(f"SETTLEMENT: {stop.settlement}")
        if stop.tasks:
            lines.extend(["", "TASKS"])
            for task in stop.tasks:
                marker = "[COMPLETE]" if task.complete else ("[SKIPPED]" if task.status == TaskStatus.SKIPPED else "[ ]")
                lines.append(f"{marker} {task.label} - {task.quantity_completed}/{task.quantity_required}")
    if stop.instructions:
        lines.extend(["", f"INSTRUCTIONS: {stop.instructions}"])
    if stop.notes:
        lines.extend(["", f"NOTES: {stop.notes}"])
    lines.extend(_skip_preview_lines(engine))
    return "\r\n".join(lines)


def render_summary(engine: RouteEngine, last_message: str = "") -> str:
    return render_header(engine, last_message) + "\r\n\r\n" + render_detail(engine)


def render_system_rows(engine: RouteEngine) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    current_key = engine.current_system.key if engine.current_system else ""
    selected_key = engine.selected_system.key if engine.selected_system else ""
    for index, system in enumerate(engine.system_plans, start=1):
        prefix = "> " if system.key == current_key else ("* " if system.key == selected_key else "")
        state = "IN SYSTEM" if system.key == current_key and engine.current_location.get("system") else (
            "COMPLETE" if system.active_body_count == 0 and system.complete_body_count else "PLANNED"
        )
        system_tip = "\r\n".join(
            [
                system.name,
                f"Bodies: {len(system.bodies)} ({system.active_body_count} active)",
                f"Targets: {system.completed_target_count}/{system.target_count}",
                f"Active value: {_credits(system.active_value)}",
                f"Manifest: {_manifest_label(system.manifest_completeness)}",
            ]
        )
        rows.append(
            {
                "row": -2,
                "cells": [
                    {"type": "text", "value": str(index)},
                    {"type": "text", "value": prefix + system.name, "tooltip": system_tip},
                    {"type": "text", "value": str(len(system.bodies))},
                    {"type": "text", "value": str(system.active_body_count)},
                    {"type": "text", "value": f"{system.completed_target_count}/{system.target_count}"},
                    {"type": "text", "value": _credits(system.active_value)},
                    {"type": "text", "value": _manifest_label(system.manifest_completeness)},
                    {"type": "text", "value": state},
                ],
            }
        )
    return rows


def _progress_text(engine: RouteEngine, stop: RouteStop) -> str:
    if stop.stop_type == StopType.EXOBIOLOGY:
        body = engine.projection.body_for(stop)
        if not body:
            return "-"
        current, total = engine.sample_progress(stop)
        complete = sum(1 for item in body.tasks if item.included and item.complete)
        if body.included_count or body.unresolved_count:
            return f"{complete}/{body.included_count} species - {current}/{total} scans"
        return "Filtered"
    required = stop.required_tasks
    if not required:
        return "Done" if stop.status == ProgressStatus.COMPLETE else "-"
    completed = sum(1 for task in required if task.complete)
    return f"{completed}/{len(required)} tasks"


def render_body_rows(engine: RouteEngine) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for order, plan in enumerate(engine.selected_system_body_plans, start=1):
        stop = engine.route.stops[plan.route_index]
        current = plan.route_index == engine.current_index and engine.current_stop is not None
        selected = plan.route_index == engine.selected_index
        prefix = "> " if current else ("* " if selected else "")
        targets = f"{plan.included_targets} in / {plan.excluded_targets} out"
        if plan.unresolved_targets:
            targets += f" / {plan.unresolved_targets} ?"
        if not plan.included:
            state = "FILTERED"
        elif plan.skipped:
            state = "SKIPPED"
        elif plan.complete:
            state = "COMPLETE"
        elif current:
            state = stop.operation_phase.upper()
        else:
            state = "QUEUED"
        body_tip = "\r\n".join(
            [
                plan.body_name or "Unresolved body",
                f"Distance: {_distance(plan.distance_from_arrival_ls)}",
                f"Bio signals: {plan.biological_signals if plan.biological_signals is not None else '?'}",
                f"Targets: {targets}",
                f"Samples: {plan.sample_current}/{plan.sample_total}",
                f"Value: {_value_or_range(plan.active_value if plan.active_value_min == plan.active_value_max else None, plan.active_value_min, plan.active_value_max)}",
                f"State: {state}",
            ]
        )
        rows.append(
            {
                "row": -2,
                "cells": [
                    {"type": "text", "value": str(order)},
                    {"type": "text", "value": prefix + (plan.body_name or "Unresolved body"), "tooltip": body_tip},
                    {"type": "text", "value": _distance(plan.distance_from_arrival_ls)},
                    {"type": "text", "value": str(plan.biological_signals) if plan.biological_signals is not None else "?"},
                    {"type": "text", "value": targets},
                    {"type": "text", "value": f"{plan.sample_current}/{plan.sample_total}"},
                    {"type": "text", "value": _value_or_range(plan.active_value if plan.active_value_min == plan.active_value_max else None, plan.active_value_min, plan.active_value_max)},
                    {"type": "text", "value": state},
                ],
            }
        )
    return rows


def render_rows(engine: RouteEngine) -> list[dict[str, Any]]:
    """Compatibility body-route renderer retained for older tests and callers."""
    rows: list[dict[str, Any]] = []
    for visible_number, index in enumerate(engine.visible_stop_indices, start=1):
        stop = engine.route.stops[index]
        body = engine.projection.body_for(stop)
        plan = engine.navigation.body(stop.id)
        selected = index == engine.selected_index
        current = index == engine.current_index and engine.current_stop is not None
        prefix = "> " if current else ("* " if selected else "")
        if stop.stop_type == StopType.EXOBIOLOGY and body:
            bio = str(stop.biological_signal_count) if stop.biological_signal_count is not None else "?"
            included = f"{body.included_count} in / {body.excluded_count} out"
            value = _value_or_range(
                body.values.active_exact if body.values.active_min == body.values.active_max else None,
                body.values.active_min,
                body.values.active_max,
            )
            state = body.inclusion_state.upper() if not body.included_body else stop.operation_phase.upper()
        else:
            bio = "-"
            included = display_name(stop.stop_type)
            value = stop.status.upper()
            state = stop.status.upper()
        rows.append(
            {
                "row": -2,
                "cells": [
                    {"type": "text", "value": str(visible_number)},
                    {"type": "text", "value": prefix + stop.system},
                    {"type": "text", "value": stop.body or stop.station or stop.settlement or stop.system},
                    {"type": "text", "value": bio},
                    {"type": "text", "value": included},
                    {"type": "text", "value": _progress_text(engine, stop)},
                    {"type": "text", "value": value},
                    {"type": "text", "value": state},
                ],
            }
        )
    return rows


def render_species_rows(engine: RouteEngine) -> list[dict[str, Any]]:
    stop = engine.selected_stop
    if not stop:
        return []
    body = engine.projection.body_for(stop)
    projected_by_id = {item.task_id: item for item in body.tasks} if body else {}
    rows: list[dict[str, Any]] = []
    for task in engine.visible_tasks(stop):
        projected = projected_by_id.get(task.id)
        if projected:
            use = {
                InclusionState.INCLUDED: "KEEP",
                InclusionState.EXCLUDED: "FILTER",
                InclusionState.UNRESOLVED: "?",
                InclusionState.MANUAL_INCLUDED: "KEEP*",
                InclusionState.MANUAL_EXCLUDED: "FILTER*",
            }.get(projected.decision.state, "?")
            knowledge = {
                KnowledgeLevel.CONFIRMED: "Exact species",
                KnowledgeLevel.GENUS_CONFIRMED: "Genus only",
                KnowledgeLevel.PREDICTED: "Predicted",
                KnowledgeLevel.UNKNOWN: "Unknown",
            }.get(projected.knowledge_level, projected.knowledge_level)
            base = _value_or_range(projected.value_exact, projected.value_min, projected.value_max)
            active_value = _credits(projected.value_exact) if projected.included and projected.value_exact is not None else ("Excluded" if projected.excluded else "Unknown")
            source = projected.source
        else:
            use = "KEEP"
            knowledge = "Task"
            base = _credits(task.base_value) if task.is_organic else "-"
            active_value = base
            source = str(task.metadata.get("source") or "route")
        selected = task.id == engine.selected_task_id
        organism = task.display_organism or task.label
        decision = "COMPLETE" if task.complete else ("SKIP" if task.status == TaskStatus.SKIPPED else use)
        variant = task.variant or ("Species exact" if task.species else ("Genus only" if task.genus else "Unknown"))
        species_tip = "\r\n".join(
            [
                organism,
                f"Certainty: {knowledge}",
                f"Variant: {variant}",
                f"Value: {base} (active: {active_value})",
                f"Difficulty: {task.search_difficulty.replace('-', ' ').title()}",
                f"Scans: {task.quantity_completed}/{task.quantity_required}",
                f"Source: {source}",
            ]
        )
        rows.append(
            {
                "row": -2,
                "cells": [
                    {"type": "text", "value": ("> " if selected else "") + decision},
                    {"type": "text", "value": knowledge},
                    {"type": "text", "value": organism, "tooltip": species_tip},
                    {"type": "text", "value": variant},
                    {"type": "text", "value": f"{task.quantity_completed}/{task.quantity_required}"},
                    {"type": "text", "value": base},
                    {"type": "text", "value": task.search_difficulty.replace("-", " ").title()},
                    {"type": "text", "value": source},
                ],
            }
        )
    return rows


def render_task_rows(engine: RouteEngine) -> list[dict[str, Any]]:
    """Compatibility organism grid used by the v0.4 regression suite."""
    stop = engine.selected_stop
    if not stop:
        return []
    body = engine.projection.body_for(stop)
    projected_by_id = {item.task_id: item for item in body.tasks} if body else {}
    rows: list[dict[str, Any]] = []
    for task in engine.visible_tasks(stop):
        projected = projected_by_id.get(task.id)
        if projected:
            use = {
                InclusionState.INCLUDED: "YES",
                InclusionState.EXCLUDED: "NO",
                InclusionState.UNRESOLVED: "?",
                InclusionState.MANUAL_INCLUDED: "YES*",
                InclusionState.MANUAL_EXCLUDED: "NO*",
            }.get(projected.decision.state, "?")
            knowledge = {
                KnowledgeLevel.CONFIRMED: "Confirmed",
                KnowledgeLevel.GENUS_CONFIRMED: "Genus",
                KnowledgeLevel.PREDICTED: "Predicted",
                KnowledgeLevel.UNKNOWN: "Unknown",
            }.get(projected.knowledge_level, projected.knowledge_level)
            base = _value_or_range(projected.value_exact, projected.value_min, projected.value_max)
            active_value = _credits(projected.value_exact) if projected.included and projected.value_exact is not None else ("Excluded" if projected.excluded else "Unknown")
            source = projected.source
        else:
            use = "YES"
            knowledge = "Task"
            base = _credits(task.base_value) if task.is_organic else "-"
            active_value = base
            source = str(task.metadata.get("source") or "route")
        selected = task.id == engine.selected_task_id
        organism = task.display_organism or task.label
        rows.append({
            "row": -2,
            "cells": [
                {"type": "text", "value": ("▶ " if selected else "") + use},
                {"type": "text", "value": knowledge},
                {"type": "text", "value": organism},
                {"type": "text", "value": f"{task.quantity_completed}/{task.quantity_required}"},
                {"type": "text", "value": base},
                {"type": "text", "value": active_value},
                {"type": "text", "value": source},
            ],
        })
    return rows
