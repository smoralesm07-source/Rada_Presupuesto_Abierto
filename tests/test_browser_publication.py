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


def _fila(i, *, families=1, types=1, cgr=0, score=80, amount=100_000_000, window="ACCION"):
    return {
        "finding_id": f"HAL-{i:04d}",
        "organization_id": f"ORG-{i%7}", "provider_id": f"PRV-{i}",
        "organization_name": f"Servicio {i%7}", "provider_name": f"Proveedor {i}",
        "periodo": 2026, "window": window,
        "signal_family_count": families, "signal_type_count": types,
        "cgr_match_count": cgr, "max_priority_score": score,
        "max_transaction_amount": amount,
        "signal_types": ["AMOUNT_OUTLIER"],
        "attention_level": "ATENCION_INMEDIATA",
        "why_review": "R" * 900,          # prosa que la compactación no toca
        "finding_title": "T" * 900,
    }


def test_el_payload_no_se_contradice_despues_de_recortar(tmp_path):
    """La corrida #42 publicó tres cifras distintas en el mismo archivo.

    `counts` y `attention_calibration` describían las 600 relaciones
    seleccionadas, mientras las filas publicadas eran 353 tras el recorte por
    presupuesto de bytes. Quien leyera el payload veía una bandeja que no
    coincidía con su propio resumen.
    """
    rows = [_fila(i) for i in range(120)]
    rows += [_fila(500 + i, families=3, types=3, cgr=1) for i in range(10)]
    payload = {
        "methodology_version": "RIGP-FINDINGS-v1",
        "guardrail": "G" * 200,
        "counts": {"attention_levels": {"ATENCION_INMEDIATA": 130,
                                        "REVISION_PRIORITARIA": 0, "SEGUIMIENTO": 0}},
        "relation_findings": rows,
        "service_hotspots": [], "provider_hotspots": [], "network_candidates": [],
    }
    path = tmp_path / "findings.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    # Presupuesto apretado a propósito: obliga a recortar filas.
    compact_browser_publication(input_path=str(path), byte_budget=60_000)
    out = json.loads(path.read_text(encoding="utf-8"))
    rel = out["relation_findings"]

    assert len(rel) < 130, "el presupuesto debía recortar la bandeja"

    filas = {k: 0 for k in ("ATENCION_INMEDIATA", "REVISION_PRIORITARIA", "SEGUIMIENTO")}
    for r in rel:
        filas[r["attention_level"]] += 1

    assert out["counts"]["attention_levels"] == filas, "el resumen debe contar lo publicado"
    assert out["attention_calibration"]["levels"] == filas, "la calibración también"
    assert out["counts"]["relations_returned"] == len(rel)
    assert all("attention_marks" in r for r in rel)


def test_sin_recorte_la_coherencia_tambien_se_mantiene(tmp_path):
    rows = [_fila(i) for i in range(40)]
    payload = {"methodology_version": "RIGP-FINDINGS-v1", "guardrail": "g",
               "counts": {}, "relation_findings": rows,
               "service_hotspots": [], "provider_hotspots": [], "network_candidates": []}
    path = tmp_path / "findings.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    compact_browser_publication(input_path=str(path), byte_budget=5_000_000)
    out = json.loads(path.read_text(encoding="utf-8"))
    rel = out["relation_findings"]
    assert len(rel) == 40
    filas = {k: 0 for k in ("ATENCION_INMEDIATA", "REVISION_PRIORITARIA", "SEGUIMIENTO")}
    for r in rel:
        filas[r["attention_level"]] += 1
    assert out["counts"]["attention_levels"] == filas
    assert out["attention_calibration"]["levels"] == filas
