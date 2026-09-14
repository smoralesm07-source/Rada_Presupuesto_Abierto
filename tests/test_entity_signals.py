"""La capa de contraparte: qué detecta, qué no, y a qué relaciones alcanza.

El valor de esta capa no está sólo en sus cinco detectores. Está en que aporta
patrones de *otra naturaleza*: hasta ahora las siete señales del radar miraban
todas el mismo pago, y una hipótesis que exige dos patrones concurrentes casi
nunca se sostenía.
"""
import json
from pathlib import Path

import pandas as pd
import pytest

from radar_presupuesto.entity_signals import (
    build_entity_signals,
    is_placeholder_rut,
    merge_into_risk_signals,
)

UF = 39_000.0


def _dv(body: int) -> str:
    """Dígito verificador chileno: las pruebas usan RUT válidos, como el motor exige."""
    total, factor = 0, 2
    for digit in reversed(str(body)):
        total += int(digit) * factor
        factor = 2 if factor == 7 else factor + 1
    rest = 11 - (total % 11)
    return {11: "0", 10: "K"}.get(rest, str(rest))


def rut(body: int) -> str:
    return f"{body}-{_dv(body)}"


def provider_id(body: int) -> str:
    return f"PRV-RUT-{rut(body)}"


def _fact(tx, org, body, periodo, amount, subtitulo="22", fecha="2026-06-15"):
    return {
        "transaction_id": tx,
        "organization_id": org,
        "provider_id": provider_id(body),
        "recipient_id": provider_id(body),
        "periodo": periodo,
        "mes": 6,
        "subtitulo": subtitulo,
        "item": "08",
        "nombre_beneficiario": f"Proveedor {body}",
        "monto_devengado": float(amount),
        "fecha_documento": fecha,
        "is_provider": True,
        "is_aggregated": False,
    }


def _entity(body, **kw):
    base = {
        "entity_id": f"ENT-{body}",
        "rut": rut(body),
        "legal_name": f"Proveedor {body}",
        "start_date": "2000-01-01",
        "termination_date": "",
        "sales_band_code": 13,
        "commercial_year": 2025,
        "acteco": [{"codigo": "4711"}],
    }
    base.update(kw)
    return base


@pytest.fixture
def workspace(tmp_path: Path):
    def build(facts: list[dict], entities: list[dict]):
        facts_path = tmp_path / "facts.parquet"
        enr_path = tmp_path / "enrichment.json"
        pd.DataFrame(facts).to_parquet(facts_path, index=False)
        enr_path.write_text(
            json.dumps({"entities": {e["rut"]: e for e in entities}}, ensure_ascii=False),
            encoding="utf-8",
        )
        return build_entity_signals(
            str(facts_path),
            enrichment_path=str(enr_path),
            output_parquet=str(tmp_path / "entity.parquet"),
            output_json=str(tmp_path / "entity.json"),
            config={"uf_clp_reference": UF},
        ), facts_path, tmp_path / "entity.parquet"
    return build


def _types(result, tmp_parquet):
    return set(pd.read_parquet(tmp_parquet)["signal_type"]) if result["signals"] else set()


def test_newborn_supplier_fires_only_when_the_money_is_material(workspace):
    # Empresa creada en marzo, primer pago en junio del mismo año.
    result, _, parquet = workspace(
        [_fact("TX-1", "ORG-A", 77111222, 2026, 80_000_000, fecha="2026-06-15")],
        [_entity(77111222, start_date="2026-03-01")],
    )
    assert "NEWBORN_SUPPLIER" in _types(result, parquet)

    # Misma empresa joven, pero cobra una cifra irrelevante: no es un hallazgo.
    small, _, small_parquet = workspace(
        [_fact("TX-2", "ORG-A", 77111222, 2026, 200_000, fecha="2026-06-15")],
        [_entity(77111222, start_date="2026-03-01")],
    )
    assert "NEWBORN_SUPPLIER" not in _types(small, small_parquet)


def test_capacity_mismatch_respects_the_uncapped_top_band(workspace):
    # Tramo 4: techo 2.400 UF ≈ $93,6M. Cobra $500M, muy por encima.
    result, _, parquet = workspace(
        [_fact("TX-1", "ORG-A", 77111222, 2026, 500_000_000)],
        [_entity(77111222, sales_band_code=4)],
    )
    assert "CAPACITY_MISMATCH" in _types(result, parquet)

    # Tramo 13 no tiene techo declarado: comparar sería inventar un límite.
    top, _, top_parquet = workspace(
        [_fact("TX-1", "ORG-A", 77111222, 2026, 500_000_000)],
        [_entity(77111222, sales_band_code=13)],
    )
    assert "CAPACITY_MISMATCH" not in _types(top, top_parquet)


def test_no_declared_sales_is_treated_as_high_severity(workspace):
    result, _, parquet = workspace(
        [_fact("TX-1", "ORG-A", 77111222, 2026, 300_000_000)],
        [_entity(77111222, sales_band_code=1)],
    )
    df = pd.read_parquet(parquet)
    row = df[df.signal_type == "CAPACITY_MISMATCH"].iloc[0]
    assert row.severity == "HIGH"
    assert "sin ventas declaradas" in row.why_flagged


def test_termination_after_payment_and_dormant_reactivation(workspace):
    result, _, parquet = workspace(
        [_fact("TX-1", "ORG-A", 77111222, 2026, 90_000_000, fecha="2026-06-15")],
        [_entity(77111222, termination_date="2026-11-30")],
    )
    assert "TERMINATION_AFTER_PAYMENT" in _types(result, parquet)

    gap, _, gap_parquet = workspace(
        [
            _fact("TX-A", "ORG-A", 77111222, 2020, 60_000_000, fecha="2020-06-15"),
            _fact("TX-B", "ORG-A", 77111222, 2026, 90_000_000, fecha="2026-06-15"),
        ],
        [_entity(77111222)],
    )
    assert "DORMANT_REACTIVATION" in _types(gap, gap_parquet)


def test_a_provider_without_registry_profile_produces_nothing_and_says_so(workspace):
    result, _, _ = workspace(
        [_fact("TX-1", "ORG-A", 77111222, 2026, 900_000_000)],
        [_entity(60000000)],  # otro RUT: el proveedor pagado no está en el registro
    )
    assert result["signals"] == 0
    assert result["providers_in_scope"] == 1
    assert result["providers_with_registry_profile"] == 0
    assert result["registry_coverage"] == 0.0


def test_placeholder_ruts_are_not_entities():
    assert is_placeholder_rut("11111111-1")
    assert is_placeholder_rut("99999999-9")
    assert not is_placeholder_rut("77111222-6")
    assert not is_placeholder_rut("")


RISK_COLUMNS = [
    "signal_id", "signal_type", "transaction_id", "organization_id", "recipient_id",
    "provider_id", "periodo", "mes", "observed_value", "expected_value", "deviation",
    "severity", "confidence", "record_class", "why_flagged",
    "investigation_hypothesis", "recommended_checks", "detected_at",
]


def test_entity_signal_reaches_every_relation_of_the_provider_that_year(tmp_path: Path):
    """Un hecho registral es del proveedor, no de un organismo.

    Si alcanzara sólo a uno, la corroboración dependería de a qué organismo le
    tocó el `any_value` en la agregación.
    """
    facts = [
        _fact("TX-A", "ORG-A", 77111222, 2026, 400_000_000),
        _fact("TX-B", "ORG-B", 77111222, 2026, 300_000_000),
        _fact("TX-C", "ORG-C", 77111222, 2026, 200_000_000),
    ]
    facts_path = tmp_path / "facts.parquet"
    enr_path = tmp_path / "enrichment.json"
    pd.DataFrame(facts).to_parquet(facts_path, index=False)
    enr_path.write_text(
        json.dumps({"entities": {rut(77111222): _entity(77111222, sales_band_code=4)}}),
        encoding="utf-8",
    )
    entity_parquet = tmp_path / "entity.parquet"
    build_entity_signals(
        str(facts_path), enrichment_path=str(enr_path),
        output_parquet=str(entity_parquet), output_json=None,
        config={"uf_clp_reference": UF},
    )
    # La capa propia guarda una fila por proveedor-año, no tres.
    assert len(pd.read_parquet(entity_parquet)) == 1

    risk = tmp_path / "risk.parquet"
    pd.DataFrame([{
        "signal_id": "SIG-BASE-1", "signal_type": "AMOUNT_OUTLIER", "transaction_id": "TX-A",
        "organization_id": "ORG-A", "recipient_id": provider_id(77111222),
        "provider_id": provider_id(77111222), "periodo": 2026, "mes": 6,
        "observed_value": 1.0, "expected_value": 1.0, "deviation": 1.0, "severity": "MEDIUM",
        "confidence": "MEDIUM", "record_class": "DERIVED_SIGNAL", "why_flagged": "fixture",
        "investigation_hypothesis": "fixture", "recommended_checks": "[]",
        "detected_at": "2026-01-01T00:00:00+00:00",
    }], columns=RISK_COLUMNS).to_parquet(risk, index=False)

    merged = merge_into_risk_signals(
        str(facts_path), entity_signals_path=str(entity_parquet), signals_path=str(risk)
    )
    assert merged["merged"] == 3, "la señal debe alcanzar las tres relaciones del proveedor"
    assert merged["relations_reached"] == 3
    assert merged["signals"] == merged["distinct_signal_ids"], "signal_id debe seguir siendo único"

    out = pd.read_parquet(risk)
    entity_rows = out[out.signal_type == "CAPACITY_MISMATCH"]
    assert set(entity_rows.organization_id) == {"ORG-A", "ORG-B", "ORG-C"}
    assert entity_rows.transaction_id.isna().all(), "una señal de entidad no cuelga de una transacción"
    # Los campos propios de la capa no se cuelan a la cola común.
    assert set(out.columns) == set(RISK_COLUMNS)
    assert {"rut", "entity_id", "assumption"} <= set(merged["dropped_columns"])


def test_merge_is_a_no_op_when_there_is_nothing_to_merge(tmp_path: Path):
    result = merge_into_risk_signals(
        str(tmp_path / "facts.parquet"),
        entity_signals_path=str(tmp_path / "absent.parquet"),
        signals_path=str(tmp_path / "absent_risk.parquet"),
    )
    assert result["merged"] == 0
    assert "ausente" in result["reason"]


# ---------------------------------------------------------------------------
# Para esto se portó la capa.
# ---------------------------------------------------------------------------

from radar_presupuesto.pattern_compatibility import best_pattern, score_pattern_compatibility
from radar_presupuesto.signal_health import SIGNAL_LAYER


def test_the_entity_layer_is_what_makes_corroboration_possible():
    """Dos patrones de la capa de transacción no siempre alcanzan; uno de otra capa sí.

    Una concentración de gasto, sola, describe un hecho del presupuesto. Con un
    proveedor recién creado al lado, hay dos observaciones independientes sobre
    la misma relación, y eso ya es una hipótesis que se puede revisar.
    """
    assert best_pattern(["PROVIDER_CONCENTRATION"]) is None

    cross_layer = best_pattern(["PROVIDER_CONCENTRATION", "NEWBORN_SUPPLIER"])
    assert cross_layer is not None
    assert cross_layer["corroborated"] is True
    assert {SIGNAL_LAYER[s] for s in cross_layer["matched_signals"]} == {"TRANSACCION", "ENTIDAD"}


def test_entity_patterns_alone_still_need_each_other():
    """La capa nueva no se autoriza a sí misma a proponer hipótesis con una señal."""
    assert best_pattern(["CAPACITY_MISMATCH"]) is None

    top = best_pattern(["CAPACITY_MISMATCH", "TERMINATION_AFTER_PAYMENT"])
    assert top is not None
    assert top["pattern_code"] == "CAPACIDAD_Y_TRAYECTORIA"
    assert top["corroborated"] is True
    assert top["discards"], "el perfil nuevo también declara qué lo descartaría"
    assert "intermediario o distribuidor" in " ".join(top["discards"])


def test_every_entity_signal_participates_in_at_least_one_profile():
    """Una señal que no entra a ningún perfil no puede corroborar nada."""
    entity_types = {k for k, v in SIGNAL_LAYER.items() if v == "ENTIDAD"}
    for signal in entity_types:
        rows = score_pattern_compatibility([signal])
        assert any(r["matched_signals"] == [signal] for r in rows), (
            f"{signal} no aparece en ningún perfil de compatibilidad"
        )
