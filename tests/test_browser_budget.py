import json

from radar_presupuesto.browser_publication import (
    BROWSER_BYTE_BUDGET,
    compact_browser_publication,
)


def _relation(index: int, *, learning_only: bool, score: float) -> dict:
    state = "SOLO_APRENDIZAJE" if learning_only else "ACCIONABLE"
    return {
        "finding_id": f"REL-{index:04d}",
        "organization_id": f"ORG-PA-{index % 40:02d}-01-001",
        "year": 2018 if learning_only else 2025,
        "review_priority": {"score": score, "attention_level": "SEGUIMIENTO"},
        "max_priority_score": score,
        "actionability": {"state": state, "window": "APRENDIZAJE" if learning_only else "ACCION"},
        "window": "APRENDIZAJE" if learning_only else "ACCION",
        # Relleno realista: el peso de una relación está en su prosa y su contexto.
        "review_steps": "x" * 400,
        "guardrail": "y" * 400,
        "peer_context": {"guardrail": "z" * 300, "peer_median_amount_clp": 1_000_000 + index},
        "signal_types": ["AMOUNT_OUTLIER"],
        "description": "d" * 900,
    }


def _write_payload(path, relations):
    path.write_text(
        json.dumps({"schema": "X", "relation_findings": relations}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_payload_under_budget_is_not_truncated(tmp_path):
    p = tmp_path / "findings.json"
    _write_payload(p, [_relation(i, learning_only=False, score=50) for i in range(5)])
    result = compact_browser_publication(str(p))
    assert result["budget_truncation"]["applied"] is False
    assert result["relation_count"] == 5
    assert "drop_relations_over_byte_budget" not in result["compaction"]


def test_oversized_payload_is_cut_to_fit_the_written_file(tmp_path):
    p = tmp_path / "findings.json"
    rows = [_relation(i, learning_only=False, score=100 - (i % 50)) for i in range(400)]
    _write_payload(p, rows)
    budget = 200_000
    result = compact_browser_publication(str(p), byte_budget=budget)
    assert result["budget_truncation"]["applied"] is True
    # Lo que importa es el archivo que se publica, no la medición intermedia.
    assert p.stat().st_size <= budget, f"archivo publicado {p.stat().st_size} > presupuesto {budget}"
    assert result["relation_count"] < 400


def test_learning_window_relations_are_sacrificed_first(tmp_path):
    p = tmp_path / "findings.json"
    # Las de aprendizaje puntúan MÁS alto: si sobrevivieran, sería por el score
    # y no por la regla. La regla dice que salen primero de todos modos.
    rows = [_relation(i, learning_only=True, score=99) for i in range(150)]
    rows += [_relation(500 + i, learning_only=False, score=10) for i in range(150)]
    _write_payload(p, rows)
    result = compact_browser_publication(str(p), byte_budget=200_000)
    survivors = json.loads(p.read_text(encoding="utf-8"))["relation_findings"]
    assert survivors, "no puede quedar vacía la bandeja"
    truncation = result["budget_truncation"]
    # La regla es de orden, no de cantidad: ninguna relación accionable se
    # sacrifica mientras sobreviva una que nadie puede trabajar.
    if truncation["dropped_actionable"]:
        assert truncation["dropped_learning_only"] == 150, (
            "se descartaron accionables quedando relaciones de sólo aprendizaje en la bandeja"
        )
        assert all(r["actionability"]["state"] == "ACCIONABLE" for r in survivors)
    else:
        assert truncation["dropped_learning_only"] == truncation["dropped"]
        assert sum(1 for r in survivors if r["actionability"]["state"] == "ACCIONABLE") == 150


def test_truncation_is_declared_not_silent(tmp_path):
    p = tmp_path / "findings.json"
    _write_payload(p, [_relation(i, learning_only=False, score=50) for i in range(400)])
    result = compact_browser_publication(str(p), byte_budget=200_000)
    note = result.get("truncation_note") or ""
    assert "parquet analítico" in note
    assert str(result["budget_truncation"]["dropped"]) in note


def test_default_budget_sits_under_the_workflow_guard():
    # La corrida mensual falla sobre 2_000_000 bytes. El presupuesto vive por
    # debajo para que la guarda sea red de seguridad y no el mecanismo.
    assert BROWSER_BYTE_BUDGET < 2_000_000


def _heavy_relation(index: int, *, learning_only: bool, score: float) -> dict:
    """Relación con el peso donde la compactación no llega.

    La corrida #31 no falló por prosa repetida —eso ya lo quitaba la
    compactación— sino por el contenido que la bandeja necesita leer: contexto
    de pares, detalle de señales, nombres. Una fila sintética que se comprime
    bien no reproduce el fallo.
    """
    state = "SOLO_APRENDIZAJE" if learning_only else "ACCIONABLE"
    return {
        "finding_id": f"REL-{index:05d}",
        "organization_id": f"ORG-PA-{index % 40:02d}-01-001",
        "organization_name": "SERVICIO DE SALUD METROPOLITANO ORIENTE ORIENTE ORIENTE ",
        "provider_name": f"COMERCIALIZADORA Y DISTRIBUIDORA DE INSUMOS {index} LIMITADA",
        "year": 2018 if learning_only else 2025,
        "review_priority": {"score": score, "attention_level": "SEGUIMIENTO"},
        "max_priority_score": score,
        "actionability": {
            "state": state,
            "window": "APRENDIZAJE" if learning_only else "ACCION",
            "reason": "r" * 180,
        },
        "review_steps": "x" * 600,
        "guardrail": "y" * 600,
        "peer_context": {
            "guardrail": "z" * 400,
            "peer_group": f"ORG-PA-{index % 40:02d}|2025|22|01",
            "peer_median_amount_clp": 1_000_000 + index,
            "notes": "n" * 700,
        },
        "signal_types": ["AMOUNT_OUTLIER", "NEW_TO_SERIES_HIGH_SPEND"],
        "signal_detail": [{"type": "AMOUNT_OUTLIER", "evidence": "e" * 500} for _ in range(3)],
        "description": "d" * 1800,
    }


def test_the_run_31_failure_no_longer_reaches_the_workflow_guard(tmp_path):
    # Regresión de la corrida #31: 2.396.263 bytes ya compactados contra una
    # guarda de 2 MB, descubierto tras 3h37m de cómputo y con la corrida perdida.
    p = tmp_path / "findings.json"
    rows = [
        _heavy_relation(i, learning_only=(i % 3 == 0), score=100 - (i % 70))
        for i in range(600)  # el tope de publication_selection.max_rows
    ]
    _write_payload(p, rows)
    result = compact_browser_publication(str(p))
    assert p.stat().st_size < 2_000_000, "el payload seguiría volteando la corrida mensual"
    assert result["budget_truncation"]["applied"] is True
    # Sacrificar primero lo no accionable es lo que deja la bandeja utilizable.
    assert result["budget_truncation"]["dropped_learning_only"] == 200
