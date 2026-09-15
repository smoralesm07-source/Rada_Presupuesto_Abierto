"""Opacidad es lo que no se puede verificar, no lo que es sospechoso.

La distinción no es cosmética: leer pseudonimización como señal de
irregularidad sería exactamente el error contrario al que el radar existe para
evitar. La mayor parte protege datos de personas naturales.
"""
from pathlib import Path

import pandas as pd
import pytest

from radar_presupuesto.opacity_index import (
    GUARDRAIL,
    OPACITY_LABEL,
    SCHEMA,
    build_opacity_index,
    classify_opacity,
)


def _fact(partida, capitulo, capitulo_name, amount, hashed=False, person=False):
    return {
        "partida": partida, "capitulo": capitulo,
        "nombre_capitulo": capitulo_name, "nombre_partida": f"MINISTERIO {partida}",
        "monto_devengado": float(amount),
        "beneficiario_id_type": "HASH_SHA1" if hashed else "RUT",
        "is_person": bool(person),
    }


def _build(tmp_path: Path, facts):
    p = tmp_path / "facts.parquet"
    pd.DataFrame(facts).to_parquet(p, index=False)
    return build_opacity_index(str(p), output_json=str(tmp_path / "opacity.json"))


def test_a_service_paying_only_identified_counterparties_is_traceable(tmp_path: Path):
    payload = _build(tmp_path, [_fact(13, 1, "SERVICIO CLARO", 100) for _ in range(5)])
    servicio = payload["services"][0]
    assert servicio["opacity_level"] == "TRAZABLE"
    assert servicio["opaque_share"] == 0.0


def test_a_service_with_most_spend_pseudonymised_is_declared_opaque(tmp_path: Path):
    payload = _build(tmp_path, [
        _fact(13, 2, "SERVICIO OPACO", 900, hashed=True, person=True),
        _fact(13, 2, "SERVICIO OPACO", 100),
    ])
    servicio = payload["services"][0]
    assert servicio["opacity_level"] == "OPACA"
    assert servicio["opaque_share"] == pytest.approx(0.9)
    # Y se dice cuánto de esa opacidad son pagos a personas, que es lo esperable.
    assert servicio["opaque_person_share_of_opaque"] == pytest.approx(1.0)


def test_partial_opacity_is_not_rounded_away(tmp_path: Path):
    payload = _build(tmp_path, [
        _fact(13, 3, "SERVICIO MIXTO", 10, hashed=True),
        _fact(13, 3, "SERVICIO MIXTO", 990),
    ])
    assert payload["services"][0]["opacity_level"] == "PARCIAL"


def test_services_are_ordered_by_how_much_money_is_unverifiable(tmp_path: Path):
    payload = _build(tmp_path, [
        _fact(13, 1, "POCO OPACO", 100, hashed=True),
        _fact(13, 2, "MUY OPACO", 5000, hashed=True),
        _fact(13, 3, "NADA OPACO", 9000),
    ])
    assert [s["service_name"] for s in payload["services"]][:2] == ["MUY OPACO", "POCO OPACO"]


def test_the_measure_is_money_not_row_count(tmp_path: Path):
    """Cien pagos chicos opacos pesan menos que uno grande claro.

    El nivel se decide por monto, no por cantidad de filas: si contara filas,
    este servicio saldría opaco por 99 pagos de mil pesos.
    """
    facts = [_fact(13, 1, "MUCHAS FILAS CHICAS", 1, hashed=True) for _ in range(100)]
    facts.append(_fact(13, 1, "MUCHAS FILAS CHICAS", 10_000))
    servicio = _build(tmp_path, facts)["services"][0]

    assert servicio["opaque_rows"] == 100, "la mayoría de las filas es opaca..."
    assert servicio["opaque_share"] < 0.01, "...pero es menos del 1% del dinero"
    assert servicio["opacity_level"] != "OPACA"


# ---------------------------------------------------------------------------
# El encuadre, que es la mitad del valor de esta capa
# ---------------------------------------------------------------------------

def test_the_guardrail_refuses_to_equate_opacity_with_suspicion(tmp_path: Path):
    payload = _build(tmp_path, [_fact(13, 1, "X", 10, hashed=True)])
    assert payload["guardrail"] == GUARDRAIL
    assert "no es una conducta" in GUARDRAIL or "límite de la fuente" in GUARDRAIL
    assert "no es más sospechoso" in GUARDRAIL
    assert "personas naturales" in GUARDRAIL


def test_the_interpretation_warns_that_absence_is_not_reassurance(tmp_path: Path):
    payload = _build(tmp_path, [_fact(13, 1, "X", 10, hashed=True)])
    assert "no es tranquilidad" in payload["interpretation"]
    assert OPACITY_LABEL["OPACA"].endswith("para este servicio.")


def test_classification_boundaries():
    assert classify_opacity(0) == "TRAZABLE"
    assert classify_opacity(None) == "TRAZABLE"
    assert classify_opacity(0.0001) == "PARCIAL"
    assert classify_opacity(0.49) == "PARCIAL"
    assert classify_opacity(0.5) == "OPACA"
    assert classify_opacity(1.0) == "OPACA"


def test_the_payload_declares_its_schema_and_totals(tmp_path: Path):
    payload = _build(tmp_path, [
        _fact(13, 1, "A", 100, hashed=True), _fact(13, 2, "B", 300),
    ])
    assert payload["schema"] == SCHEMA
    assert payload["overall"]["services"] == 2
    assert payload["overall"]["opaque_share"] == pytest.approx(0.25)
    assert payload["overall"]["services_by_level"] == {"TRAZABLE": 1, "PARCIAL": 0, "OPACA": 1}
