from __future__ import annotations

from pathlib import Path

import pandas as pd

from radar_presupuesto.advanced_signals import extend_signals
from radar_presupuesto.relation_context import (
    build_opacity_index,
    build_relation_context,
    classify_opacity,
    relation_patterns,
)

SIGNAL_COLUMNS = [
    "signal_id", "signal_type", "transaction_id", "organization_id", "recipient_id",
    "provider_id", "periodo", "mes", "observed_value", "expected_value", "deviation",
    "severity", "confidence", "record_class", "why_flagged", "investigation_hypothesis",
    "recommended_checks",
]


def _seed_signals(tmp_path: Path) -> str:
    seed = [
        {
            "signal_id": "SEED", "signal_type": "SEED", "transaction_id": "T0",
            "organization_id": "ORG-1", "recipient_id": "RCV-1", "provider_id": "PRV-RUT-1",
            "periodo": 2026, "mes": 3, "observed_value": 1.0, "expected_value": 1.0,
            "deviation": 1.0, "severity": "LOW", "confidence": "LOW",
            "record_class": "DERIVED_SIGNAL", "why_flagged": "seed",
            "investigation_hypothesis": "seed", "recommended_checks": "[]",
        }
    ]
    path = tmp_path / "risk_signals.parquet"
    pd.DataFrame(seed, columns=SIGNAL_COLUMNS).to_parquet(path, index=False)
    return str(path)


def _facts(rows: list[dict], tmp_path: Path) -> str:
    path = tmp_path / "transactions.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    return str(path)


def _payment_row(i: int, days, **over) -> dict:
    row = {
        "transaction_id": f"T{i}", "organization_id": "ORG-1", "recipient_id": "RCV-1",
        "provider_id": f"PRV-RUT-{i}", "periodo": 2026, "mes": 3, "is_provider": True,
        "is_aggregated": False, "monto_devengado": 1_000_000.0, "dias_de_pago": days,
        "fecha_documento": pd.NaT, "fecha_recepcion_conforme": pd.NaT, "fecha_pago": pd.NaT,
    }
    row.update(over)
    return row


def test_delay_signal_fires_from_the_source_field(tmp_path):
    rows = [_payment_row(i, str(5 + i % 15)) for i in range(60)]
    rows += [_payment_row(100 + i, "200") for i in range(3)]
    result = extend_signals(_facts(rows, tmp_path), signals_path=_seed_signals(tmp_path))
    assert result["by_type"].get("PAYMENT_DELAY_OUTLIER", 0) == 3
    assert result["input_coverage"].get("CAMPO_FUENTE") == 63


def test_delay_signal_survives_when_the_optional_field_is_absent(tmp_path):
    """El bulk oficial no siempre trae DIAS_DE_PAGO; la señal no puede depender de él."""
    rows = []
    for i in range(60):
        doc = pd.Timestamp("2026-01-01")
        rows.append(
            _payment_row(
                i, None,
                fecha_documento=doc,
                fecha_recepcion_conforme=doc,
                fecha_pago=doc + pd.Timedelta(days=5 + i % 15),
            )
        )
    for i in range(3):
        doc = pd.Timestamp("2026-01-01")
        rows.append(
            _payment_row(
                100 + i, None,
                fecha_documento=doc,
                fecha_recepcion_conforme=doc,
                fecha_pago=doc + pd.Timedelta(days=200),
            )
        )
    result = extend_signals(_facts(rows, tmp_path), signals_path=_seed_signals(tmp_path))
    assert result["by_type"].get("PAYMENT_DELAY_OUTLIER", 0) == 3, (
        "sin dias_de_pago la señal debe reconstruirse desde las fechas"
    )
    assert result["input_coverage"].get("RECEPCION_A_PAGO") == 63
    frame = pd.read_parquet(result["path"])
    delay = frame[frame["signal_type"] == "PAYMENT_DELAY_OUTLIER"].iloc[0]
    assert "RECEPCION_A_PAGO" in delay["why_flagged"]


def test_a_detector_that_cannot_fire_is_reported(tmp_path):
    """Un detector que produce cero debe decirlo, no desaparecer en silencio."""
    rows = [_payment_row(i, None) for i in range(30)]
    result = extend_signals(_facts(rows, tmp_path), signals_path=_seed_signals(tmp_path))
    assert result["by_type"].get("PAYMENT_DELAY_OUTLIER", 0) == 0
    assert "PAYMENT_DELAY_OUTLIER" in result["silent_detectors"]
    assert result["input_coverage"].get("NO_DETERMINABLE") == 30


def _opacity_row(org: str, provider: str, id_type: str, amount: float, **over) -> dict:
    row = {
        "organization_id": org, "provider_id": provider, "periodo": 2026,
        "monto_devengado": amount, "beneficiario_id_type": id_type,
        "is_person": id_type == "HASH_SHA1", "is_honorarium": False,
        "is_aggregated": False, "orden_compra": "OC-1",
        "nombre_area": org, "nombre_capitulo": org, "nombre_partida": org,
        "nombre_beneficiario": provider,
    }
    row.update(over)
    return row


def test_opacity_index_separates_traceable_from_unverifiable(tmp_path):
    rows = [
        _opacity_row("ORG-CLARO", "PRV-RUT-1", "RUT", 100_000_000),
        _opacity_row("ORG-OPACO", "", "HASH_SHA1", 900_000_000),
        _opacity_row("ORG-OPACO", "PRV-RUT-2", "RUT", 100_000_000),
    ]
    payload = build_opacity_index(_facts(rows, tmp_path))
    services = {s["organization_id"]: s for s in payload["services"]}
    assert services["ORG-CLARO"]["opacity_level"] == "TRAZABLE"
    assert services["ORG-OPACO"]["opacity_level"] == "OPACA"
    assert services["ORG-OPACO"]["opaque_share"] > 0.8
    assert "no es más sospechoso" in payload["guardrail"]
    assert payload["overall"]["opaque_share"] > 0


def test_relation_patterns_flag_missing_purchase_order(tmp_path):
    rows = [
        _opacity_row("ORG-1", "PRV-RUT-1", "RUT", 500_000_000, orden_compra=""),
        _opacity_row("ORG-1", "PRV-RUT-2", "RUT", 500_000_000, orden_compra="OC-9"),
    ]
    context = build_relation_context(_facts(rows, tmp_path))
    by_provider = {r.provider_id: r for r in context.itertuples()}
    sin_oc = relation_patterns(pd.Series(by_provider["PRV-RUT-1"]._asdict()))
    con_oc = relation_patterns(pd.Series(by_provider["PRV-RUT-2"]._asdict()))
    assert "NO_PURCHASE_ORDER_TRAIL" in sin_oc
    assert "NO_PURCHASE_ORDER_TRAIL" not in con_oc


def test_opacity_classification_boundaries():
    assert classify_opacity(0) == "TRAZABLE"
    assert classify_opacity(0.2) == "PARCIAL"
    assert classify_opacity(0.5) == "OPACA"
    assert classify_opacity(None) == "TRAZABLE"
