import json
from pathlib import Path

import pandas as pd

from radar_presupuesto.investigative_findings import build_investigative_findings


def _row(org, provider, signal_type, score, tier, family_hint=None, cgr=0):
    return {
        "organization_id": org,
        "provider_id": provider,
        "periodo": 2026,
        "organization_name": f"Servicio {org}",
        "provider_or_recipient_name": f"Proveedor {provider}",
        "signal_type": signal_type,
        "investigation_priority_score": score,
        "priority_tier": tier,
        "cgr_match_count": cgr,
        "cgr_max_confidence": 0.9 if cgr else 0.0,
        "transaction_amount": 150_000_000,
    }


def test_convergent_relation_becomes_immediate_attention(tmp_path: Path):
    rows = [
        _row("A", "P1", "PROVIDER_CONCENTRATION", 72, "P1", cgr=1),
        _row("A", "P1", "NEW_TO_SERIES_HIGH_SPEND", 68, "P2", cgr=1),
        _row("A", "P1", "AMOUNT_OUTLIER", 75, "P1", cgr=1),
    ]
    src = tmp_path / "prioritized.parquet"
    out = tmp_path / "findings.parquet"
    payload_path = tmp_path / "findings.json"
    pd.DataFrame(rows).to_parquet(src, index=False)

    result = build_investigative_findings(
        prioritized_path=str(src),
        output_parquet=str(out),
        output_json=str(payload_path),
        top_n=20,
    )

    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    finding = payload["relation_findings"][0]
    assert result["relations"] == 1
    assert finding["attention_level"] == "ATENCION_INMEDIATA"
    assert finding["finding_family"] == "CONVERGENCIA_MULTIFACTOR"
    assert len(finding["signal_types"]) == 3
    assert "no acredita irregularidad" in finding["guardrail"].lower()


def test_provider_across_services_is_network_candidate(tmp_path: Path):
    rows = []
    for org in ("A", "B", "C"):
        rows.append(_row(org, "PX", "PROVIDER_CONCENTRATION", 65, "P2"))
        rows.append(_row(org, "PX", "AMOUNT_OUTLIER", 72, "P1"))
    src = tmp_path / "prioritized.parquet"
    out = tmp_path / "findings.parquet"
    payload_path = tmp_path / "findings.json"
    pd.DataFrame(rows).to_parquet(src, index=False)

    build_investigative_findings(
        prioritized_path=str(src),
        output_parquet=str(out),
        output_json=str(payload_path),
        top_n=20,
    )
    payload = json.loads(payload_path.read_text(encoding="utf-8"))

    assert len(payload["network_candidates"]) == 1
    network = payload["network_candidates"][0]
    assert network["service_count"] == 3
    assert network["signal_family_count"] >= 2
    assert "no implica coordinación indebida" in network["network_interpretation"].lower()
