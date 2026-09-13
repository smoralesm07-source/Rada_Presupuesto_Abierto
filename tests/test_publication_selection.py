import json
from pathlib import Path

import pandas as pd

from radar_presupuesto.publication_selection import rebalance_findings_publication


def _row(i: int, signal: str, score: int = 80) -> dict:
    return {
        "finding_id": f"HAL-{i:04d}",
        "organization_id": f"ORG-{i%5}",
        "provider_id": f"PRV-{i}",
        "periodo": 2026,
        "organization_name": f"Servicio {i%5}",
        "provider_name": f"Proveedor {i}",
        "signal_count": 1,
        "signal_type_count": 1,
        "signal_family_count": 1,
        "signal_types": signal,
        "signal_families": "MAGNITUD_ATIPICA",
        "max_priority_score": score,
        "p1_signals": 1,
        "p2_signals": 0,
        "cgr_match_count": 0,
        "cgr_max_confidence": 0.0,
        "max_transaction_amount": 100_000_000 + i,
        "finding_family": "PATRON_ATIPICO",
        "attention_level": "REVISION_PRIORITARIA",
        "finding_title": "Hallazgo de prueba",
        "why_review": "Prueba de selección",
    }


def test_diversity_reserve_keeps_rare_signal_types(tmp_path: Path):
    rows = [_row(i, "AMOUNT_OUTLIER", 95 - (i % 10)) for i in range(80)]
    rows += [_row(100 + i, "POTENTIAL_FRAGMENTATION", 45) for i in range(3)]
    rows += [_row(200 + i, "EXACT_DUPLICATE_CANDIDATE", 44) for i in range(2)]
    rows += [_row(300 + i, "YEAR_END_SPIKE", 43) for i in range(2)]

    parquet = tmp_path / "findings.parquet"
    payload_path = tmp_path / "findings.json"
    pd.DataFrame(rows).to_parquet(parquet, index=False)
    payload_path.write_text(
        json.dumps(
            {
                "methodology_version": "RIGP-FINDINGS-v1",
                "counts": {},
                "relation_findings": [],
                "guardrail": "test",
            }
        ),
        encoding="utf-8",
    )

    result = rebalance_findings_publication(
        findings_parquet=str(parquet),
        payload_json=str(payload_path),
        max_rows=12,
        reserve_per_signal=2,
    )
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    signals = [set(x["signal_types"]) for x in payload["relation_findings"]]

    assert result["relations_published"] == 12
    assert sum("POTENTIAL_FRAGMENTATION" in x for x in signals) >= 2
    assert sum("EXACT_DUPLICATE_CANDIDATE" in x for x in signals) >= 2
    assert sum("YEAR_END_SPIKE" in x for x in signals) >= 2
    assert payload["publication_selection"]["method"] == "priority_with_signal_diversity_reserve"


def test_reserve_never_invents_missing_signals(tmp_path: Path):
    rows = [_row(i, "AMOUNT_OUTLIER", 80) for i in range(5)]
    parquet = tmp_path / "findings.parquet"
    payload_path = tmp_path / "findings.json"
    pd.DataFrame(rows).to_parquet(parquet, index=False)
    payload_path.write_text(
        json.dumps({"methodology_version": "RIGP-FINDINGS-v1", "counts": {}, "relation_findings": []}),
        encoding="utf-8",
    )

    rebalance_findings_publication(
        findings_parquet=str(parquet),
        payload_json=str(payload_path),
        max_rows=5,
        reserve_per_signal=2,
    )
    payload = json.loads(payload_path.read_text(encoding="utf-8"))

    assert len(payload["relation_findings"]) == 5
    assert payload["publication_selection"]["available_by_signal"]["POTENTIAL_FRAGMENTATION"] == 0
    assert payload["publication_selection"]["published_by_signal"]["POTENTIAL_FRAGMENTATION"] == 0
