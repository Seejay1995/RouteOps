from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable

from exobiology_catalog import DEFAULT_CATALOG, normalize_organic_name


class KnowledgeLevel:
    CONFIRMED = "confirmed"
    GENUS_CONFIRMED = "genus-confirmed"
    PREDICTED = "predicted"
    UNKNOWN = "unknown"


class InclusionState:
    INCLUDED = "included"
    EXCLUDED = "excluded"
    UNRESOLVED = "unresolved"
    MANUAL_INCLUDED = "manual-included"
    MANUAL_EXCLUDED = "manual-excluded"


# Canonical taxonomy is data-driven so journal aliases can be updated without
# changing the filter engine. A small built-in fallback protects startup if the
# data file is damaged or missing.
_DEFAULT_GENUS_DISPLAY = {
    "aleoida": "Aleoida", "bacterium": "Bacterium", "cactoida": "Cactoida",
    "clypeus": "Clypeus", "concha": "Concha", "electricae": "Electricae",
    "fonticulua": "Fonticulua", "frutexa": "Frutexa", "fumerola": "Fumerola",
    "fungoida": "Fungoida", "osseus": "Osseus", "recepta": "Recepta",
    "stratum": "Stratum", "tubus": "Tubus", "tussock": "Tussock",
}


def _load_taxonomy() -> tuple[dict[str, str], dict[str, str]]:
    display = dict(_DEFAULT_GENUS_DISPLAY)
    aliases: dict[str, str] = {}
    path = Path(__file__).resolve().parent / "Data" / "exobiology_taxonomy.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in payload.get("genera", []):
            genus_id = str(item.get("id") or "").casefold().strip()
            name = str(item.get("displayName") or "").strip()
            if not genus_id or not name:
                continue
            display[genus_id] = name
            for alias in [name, f"{name} genus", *list(item.get("aliases", []))]:
                normalized = normalize_organic_name(str(alias or ""))
                if normalized:
                    aliases[normalized] = genus_id
    except (OSError, ValueError, TypeError):
        pass
    for genus_id, name in display.items():
        aliases.setdefault(normalize_organic_name(name), genus_id)
        aliases.setdefault(normalize_organic_name(f"{name} genus"), genus_id)
    # Critical compatibility aliases remain guaranteed even if the JSON file is
    # unavailable. Frontier uses Bacterial internally and Bacterium in the UI.
    for alias in (
        "Bacterium", "Bacterial", "Bacteria", "Bacterial genus",
        "$Codex_Ent_Bacterial_Genus_Name;", "Codex_Ent_Bacterial_Genus_Name",
        "$Codex_Ent_Bacterium_Genus_Name;", "Codex_Ent_Bacterium_Genus_Name",
    ):
        aliases[normalize_organic_name(alias)] = "bacterium"
    return display, aliases


_GENUS_DISPLAY, _GENUS_ALIASES = _load_taxonomy()


@dataclass(frozen=True)
class TaxonomyResolution:
    genus_id: str = ""
    genus_name: str = ""
    species_id: str = ""
    species_name: str = ""
    variant_id: str = ""
    variant_name: str = ""
    knowledge_level: str = KnowledgeLevel.UNKNOWN
    confidence: str = "unresolved"
    matched_from: str = ""
    raw_value: str = ""

    @property
    def resolved(self) -> bool:
        return bool(self.genus_id or self.species_id or self.variant_id)


@dataclass(frozen=True)
class InclusionDecision:
    state: str
    reason: str
    matched_filter: str = ""
    confidence: str = ""

    @property
    def included(self) -> bool:
        return self.state in {
            InclusionState.INCLUDED,
            InclusionState.MANUAL_INCLUDED,
            InclusionState.UNRESOLVED,
        }

    @property
    def excluded(self) -> bool:
        return self.state in {
            InclusionState.EXCLUDED,
            InclusionState.MANUAL_EXCLUDED,
        }


def canonical_genus_id(*values: Any) -> str:
    """Resolve localised names and journal symbols to one stable genus ID."""
    for value in values:
        normalized = normalize_organic_name(str(value or ""))
        if not normalized:
            continue
        direct = _GENUS_ALIASES.get(normalized)
        if direct:
            return direct
        # Exact species names are safe to resolve through the bundled catalogue.
        match = DEFAULT_CATALOG.resolve(str(value))
        if match:
            match_key = normalize_organic_name(match.genus)
            if match_key in _GENUS_ALIASES:
                return _GENUS_ALIASES[match_key]
        # Internal symbols sometimes retain a leading entity category after the
        # generic normalizer strips Codex_Ent_. Match exact token shapes only.
        tokens = normalized.split()
        for token in tokens:
            if token in _GENUS_ALIASES:
                return _GENUS_ALIASES[token]
            if token == "bacterial":
                return "bacterium"
    return ""


def display_genus_name(genus_id: str, fallback: str = "") -> str:
    return _GENUS_DISPLAY.get(genus_id, fallback or genus_id.title())


def canonical_species_id(value: str) -> str:
    match = DEFAULT_CATALOG.resolve(value)
    if match:
        return normalize_organic_name(match.name).replace(" ", "-")
    normalized = normalize_organic_name(value)
    return normalized.replace(" ", "-") if normalized else ""


def resolve_taxonomy(
    *,
    genus: str = "",
    genus_internal: str = "",
    species: str = "",
    species_internal: str = "",
    variant: str = "",
    variant_internal: str = "",
    target: str = "",
    label: str = "",
    metadata: dict[str, Any] | None = None,
    unresolved: bool = False,
    predicted: bool = False,
) -> TaxonomyResolution:
    metadata = metadata or {}
    values_by_source: list[tuple[str, str]] = [
        ("variant", variant),
        ("variant-internal", variant_internal),
        ("species", species),
        ("species-internal", species_internal),
        ("genus", genus),
        ("genus-internal", genus_internal),
        ("metadata-variant", str(metadata.get("variant") or metadata.get("variantName") or "")),
        ("metadata-species", str(metadata.get("species") or metadata.get("speciesName") or "")),
        ("metadata-genus", str(metadata.get("genus") or metadata.get("genusName") or "")),
        ("target", target),
        ("label", label),
    ]

    exact_match = DEFAULT_CATALOG.resolve(
        variant,
        variant_internal,
        species,
        species_internal,
        str(metadata.get("variant") or ""),
        str(metadata.get("species") or ""),
        target,
        label,
    ) or DEFAULT_CATALOG.resolve_contained(target, label)
    if exact_match:
        genus_id = canonical_genus_id(exact_match.genus)
        raw_source, raw_value = next(
            ((source, value) for source, value in values_by_source if value and DEFAULT_CATALOG.resolve(value)),
            ("catalog", exact_match.name),
        )
        return TaxonomyResolution(
            genus_id=genus_id,
            genus_name=display_genus_name(genus_id, exact_match.genus),
            species_id=canonical_species_id(exact_match.name),
            species_name=exact_match.name,
            variant_id=normalize_organic_name(variant or variant_internal).replace(" ", "-"),
            variant_name=variant or variant_internal,
            knowledge_level=KnowledgeLevel.PREDICTED if predicted else KnowledgeLevel.CONFIRMED,
            confidence="exact",
            matched_from=raw_source,
            raw_value=raw_value,
        )

    for source, value in values_by_source:
        genus_id = canonical_genus_id(value)
        if genus_id:
            return TaxonomyResolution(
                genus_id=genus_id,
                genus_name=display_genus_name(genus_id, genus or value),
                knowledge_level=(
                    KnowledgeLevel.PREDICTED
                    if predicted
                    else KnowledgeLevel.GENUS_CONFIRMED
                ),
                confidence="exact-alias",
                matched_from=source,
                raw_value=value,
            )

    return TaxonomyResolution(
        knowledge_level=KnowledgeLevel.PREDICTED if predicted else KnowledgeLevel.UNKNOWN,
        confidence="unresolved",
        matched_from="unresolved-slot" if unresolved else "",
        raw_value=target or label,
    )


def task_taxonomy(task: Any) -> TaxonomyResolution:
    metadata = task.metadata if isinstance(getattr(task, "metadata", None), dict) else {}
    resolution = resolve_taxonomy(
        genus=getattr(task, "genus", ""),
        genus_internal=str(metadata.get("genusInternal") or ""),
        species=getattr(task, "species", ""),
        species_internal=str(metadata.get("speciesInternal") or ""),
        variant=getattr(task, "variant", ""),
        variant_internal=str(metadata.get("variantInternal") or ""),
        target=getattr(task, "target", ""),
        label=getattr(task, "label", ""),
        metadata=metadata,
        unresolved=bool(metadata.get("unresolvedSlot", False)),
        predicted=bool(metadata.get("predicted", False)),
    )
    return resolution


def normalize_filter_ids(values: Iterable[str]) -> set[str]:
    result: set[str] = set()
    for value in values:
        genus_id = canonical_genus_id(value)
        if genus_id:
            result.add(genus_id)
    return result


def inclusion_decision(task: Any, excluded_genus_ids: set[str]) -> InclusionDecision:
    override = str(getattr(task, "manual_inclusion", "default") or "default").casefold()
    if override == "include":
        return InclusionDecision(InclusionState.MANUAL_INCLUDED, "manual-include")
    if override == "exclude":
        return InclusionDecision(InclusionState.MANUAL_EXCLUDED, "manual-exclude")

    taxonomy = task_taxonomy(task)
    if taxonomy.genus_id and taxonomy.genus_id in excluded_genus_ids:
        return InclusionDecision(
            InclusionState.EXCLUDED,
            "genus-filter",
            matched_filter=taxonomy.genus_id,
            confidence=taxonomy.confidence,
        )
    if taxonomy.knowledge_level == KnowledgeLevel.UNKNOWN:
        return InclusionDecision(InclusionState.UNRESOLVED, "taxonomy-unresolved")
    return InclusionDecision(InclusionState.INCLUDED, "default")
