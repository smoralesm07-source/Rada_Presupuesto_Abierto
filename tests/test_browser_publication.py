import json
from pathlib import Path

from radar_presupuesto.browser_publication import compact_browser_publication


def _relation(i: int) -> dict:
    pattern = {
        "pattern_code": "CONCENTRACION_COMPETENCIA",
        "pattern_label": "Concentración y competencia",
        "pattern_description": "texto largo repetido",
        "compatibility_score": 75,
        "matched_signals": ["PROVIDER_CONCENTRATION", "AMOUNT_OUTLIER"],
        "review_question": "¿La concentración se explica por condiciones normales?",
        "guardrail": "guardrail repetido",
    }
    return {
        "finding_id": f"HAL-{i}",
        "organization_id": "ORG-1",
        "provider_id": f"P-{i}",
        "periodo": 2026,
        "signal_types": ["PROVIDER_CONCENTRATION", "AMOUNT_OUTLIER"],
        "max_priority_score": 80,
        "attention_level": "REVISION_PRIORITARIA",
        "review_steps": ["uno", "dos", "tres"],
        "guardrail": "guardrail repetido",
        "review_priority": {"score": 80, "attention_level": "REVISION_PRIORITARIA", "guardrail": "x"},
        "primary_pattern": pattern,
        "pattern_compatibility": [pattern, dict(pattern, pattern_code="IRRUPCION_CAMBIO_ESCALA")],
        "peer_context": {"peer_provider_count": 9, "peer_percentile_pct": 98.0, "guardrail": "x"},
    }


def test_browser_compaction_preserves_analysis_and_bounds_context(tmp_path: Path):
    path = tmp_path / "findings.json"
    payload = {
        "guardrail": "guardrail raíz",
        "interpretation_contract": {"separation_rule": "prioridad != delito"},
        "relation_findings": [_relation(i) for i in range(6)],
        "service_hotspots": [{"organization_id": str(i), "guardrail": "x"} for i in range(10)],
        "provider_hotspots": [{"provider_id": str(i), "guardrail": "x"} for i in range(10)],
        "network_candidates": [{"provider_id": str(i), "guardrail": "x"} for i in range(10)],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    before = path.stat().st_size

    result = compact_browser_publication(str(path), max_hotspots=3)
    out = json.loads(path.read_text(encoding="utf-8"))

    assert result["schema"] == "RIGP-BROWSER-PUBLICATION-v1"
    assert result["analytical_effect"] == "NONE"
    assert out["guardrail"] == "guardrail raíz"
    assert len(out["relation_findings"]) == 6
    assert len(out["service_hotspots"]) == 3
    assert len(out["provider_hotspots"]) == 3
    assert len(out["network_candidates"]) == 3

    row = out["relation_findings"][0]
    assert row["max_priority_score"] == 80
    assert row["signal_types"] == ["PROVIDER_CONCENTRATION", "AMOUNT_OUTLIER"]
    assert "review_steps" not in row
    assert "guardrail" not in row
    assert "guardrail" not in row["review_priority"]
    assert "guardrail" not in row["peer_context"]
    assert row["primary_pattern"]["review_question"].startswith("¿La concentración")
    assert "pattern_description" not in row["primary_pattern"]
    assert len(row["pattern_compatibility"]) == 2
    assert path.stat().st_size < before
