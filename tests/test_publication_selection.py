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


def _tray_row(i, *, families=1, types=1, cgr=0, score=80, amount=100_000_000):
    """Fila con el nivel VIEJO puesto, como viene del parquet."""
    row = _row(i, "AMOUNT_OUTLIER", score)
    row.update({
        "signal_family_count": families, "signal_type_count": types,
        "cgr_match_count": cgr, "max_transaction_amount": amount,
        "attention_level": "ATENCION_INMEDIATA",   # lo que el SQL dejó en el parquet
    })
    return row


def test_el_nivel_se_recalibra_contra_la_bandeja_publicada(tmp_path: Path):
    """La corrida #41 publicó 582 de 600 en atención inmediata.

    `investigative_findings` recalibraba el nivel, pero esta selección reemplaza
    `relation_findings` con filas releídas del parquet —que traen el nivel del
    SQL— y pisaba el recálculo. El bloque de calibración decía 85/183/332
    mientras las filas publicadas decían 582/14/4: dos verdades distintas en el
    mismo payload.
    """
    rows = [_tray_row(i) for i in range(90)]
    rows += [_tray_row(500 + i, families=3, types=3, cgr=1) for i in range(5)]
    parquet = tmp_path / "findings.parquet"
    payload_path = tmp_path / "findings.json"
    pd.DataFrame(rows).to_parquet(parquet, index=False)
    payload_path.write_text(json.dumps(
        {"methodology_version": "RIGP-FINDINGS-v1", "counts": {},
         "relation_findings": [], "guardrail": "test"}), encoding="utf-8")

    rebalance_findings_publication(findings_parquet=str(parquet),
                                   payload_json=str(payload_path),
                                   max_rows=95, reserve_per_signal=2)
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    rel = payload["relation_findings"]

    # El nivel del parquet no sobrevive: se recalibra contra lo publicado.
    # El payload declara siempre los tres niveles, incluso en cero.
    niveles = {k: 0 for k in ("ATENCION_INMEDIATA", "REVISION_PRIORITARIA", "SEGUIMIENTO")}
    for r in rel:
        niveles[r["attention_level"]] += 1
    assert niveles["ATENCION_INMEDIATA"] < len(rel), \
        "el nivel superior no puede quedarse con la bandeja entera"

    # Y las tres cifras del payload cuentan la misma historia.
    assert payload["counts"]["attention_levels"] == niveles
    assert payload["attention_calibration"]["levels"] == niveles


def test_cada_fila_publicada_explica_su_nivel(tmp_path: Path):
    rows = [_tray_row(i) for i in range(60)]
    rows += [_tray_row(700 + i, families=3, cgr=1) for i in range(3)]
    parquet = tmp_path / "findings.parquet"
    payload_path = tmp_path / "findings.json"
    pd.DataFrame(rows).to_parquet(parquet, index=False)
    payload_path.write_text(json.dumps(
        {"methodology_version": "RIGP-FINDINGS-v1", "counts": {},
         "relation_findings": [], "guardrail": "test"}), encoding="utf-8")

    rebalance_findings_publication(findings_parquet=str(parquet),
                                   payload_json=str(payload_path),
                                   max_rows=63, reserve_per_signal=2)
    rel = json.loads(payload_path.read_text(encoding="utf-8"))["relation_findings"]

    assert all("attention_marks" in r for r in rel), "sin marcas el nivel es una etiqueta"
    for r in rel:
        if r["attention_level"] == "SEGUIMIENTO":
            assert r["attention_marks"] == []
        else:
            assert r["attention_marks"], "un nivel elevado debe nombrar sus marcas"
        assert r["attention_why"]
