from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "Plugin" / "RouteOps"
sys.path.insert(0, str(PLUGIN))

from exobio_taxonomy import KnowledgeLevel  # noqa: E402
from journal_normalizer import normalize_journal_event  # noqa: E402
from route_engine import RouteEngine  # noqa: E402
from route_importer import import_route  # noqa: E402
from route_models import RouteTask  # noqa: E402
from spansh_exobiology_importer import rows_to_routeops_v3  # noqa: E402


def _engine(rows: list[dict]) -> RouteEngine:
    route = rows_to_routeops_v3(rows, "DedupTest", "spansh-exobiology-api")
    folder = Path(tempfile.mkdtemp())
    path = folder / "route.json"
    path.write_text(json.dumps(route), encoding="utf-8")
    engine = RouteEngine(import_route(path).route)
    engine._rebuild_projection(repair_current=True)
    return engine


class SaaGenusDedupTests(unittest.TestCase):
    """A live SAA genus scan must reconcile against Spansh exact species, not duplicate."""

    def test_saa_scan_does_not_duplicate_exact_species(self) -> None:
        engine = _engine(
            [
                {"system": "S", "body": "B 1", "species": "Stratum Tectonicas", "genus": "Stratum", "value": 19_000_000},
                {"system": "S", "body": "B 1", "species": "Aleoida Gravis", "genus": "Aleoida", "value": 12_900_000},
            ]
        )
        stop = next(s for s in engine.route.stops if s.organic_tasks)
        event = normalize_journal_event(
            {
                "event": "SAASignalsFound",
                "BodyName": "B 1",
                "Signals": [{"Type": "$SAA_SignalType_Biological;", "Count": 3}],
                "Genuses": [
                    {"Genus_Localised": "Stratum"},
                    {"Genus_Localised": "Aleoida"},
                    {"Genus_Localised": "Bacterium"},
                ],
            }
        )
        engine._handle_saa_signals(stop, event, [])

        organic = stop.organic_tasks
        names = [task.display_organism for task in organic]
        # 2 exact species + 1 genuinely-new genus (Bacterium) == 3, no genus dupes
        self.assertEqual(len(organic), 3, names)
        self.assertNotIn("Stratum", names)
        self.assertNotIn("Aleoida", names)
        self.assertIn("Bacterium", names)
        # exact species keep CONFIRMED, and record that SAA confirmed their genus
        stratum = next(t for t in organic if t.display_organism == "Stratum Tectonicas")
        self.assertEqual(stratum.knowledge_level, KnowledgeLevel.CONFIRMED)
        self.assertTrue(stratum.metadata.get("saaGenusConfirmed"))
        # no phantom "Unknown biological signal" placeholders (3 classified == 3 signals)
        self.assertFalse([t for t in organic if t.metadata.get("unresolvedSlot")])

    def test_reconcile_removes_redundant_genus_but_keeps_progress(self) -> None:
        engine = _engine(
            [{"system": "S", "body": "B 1", "species": "Stratum Tectonicas", "genus": "Stratum", "value": 19_000_000}]
        )
        stop = next(s for s in engine.route.stops if s.organic_tasks)
        stop.tasks.append(
            RouteTask(
                id="dup-zero", task_type="scanOrganic", label="Stratum — species unresolved",
                target="Stratum", genus="Stratum", genus_id="stratum",
                knowledge_level=KnowledgeLevel.GENUS_CONFIRMED, quantity_required=3, quantity_completed=0,
                metadata={"source": "SAASignalsFound"},
            )
        )
        stop.tasks.append(
            RouteTask(
                id="dup-progress", task_type="scanOrganic", label="Stratum — species unresolved",
                target="Stratum", genus="Stratum", genus_id="stratum",
                knowledge_level=KnowledgeLevel.GENUS_CONFIRMED, quantity_required=3, quantity_completed=1,
                metadata={"source": "SAASignalsFound"},
            )
        )
        engine._reconcile_genus_duplicates()
        ids = [task.id for task in stop.organic_tasks]
        self.assertNotIn("dup-zero", ids)          # redundant, no progress -> removed
        self.assertIn("dup-progress", ids)          # has sampling progress -> preserved
        self.assertTrue(any(t.species == "Stratum Tectonicas" for t in stop.organic_tasks))


if __name__ == "__main__":
    unittest.main()
