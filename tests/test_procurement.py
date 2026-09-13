from __future__ import annotations

from pathlib import Path

import pandas as pd

from radar_presupuesto.procurement import (
    CANONICAL_COLUMNS,
    ProcurementThresholds,
    build_procurement_signals,
    coverage,
    join_payments,
    normalize_purchase_orders,
    write_status,
)

UTM_2026 = {2026: 70_000.0}
THRESHOLDS = ProcurementThresholds(utm_clp_by_year=UTM_2026)


def _payments(tmp_path: Path, rows: list[dict]) -> str:
    path = tmp_path / "transactions.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    return str(path)


def _payment(oc: str, amount: float, provider: str = "PRV-RUT-76071943-9") -> dict:
    return {
        "organization_id": "ORG-1",
        "provider_id": provider,
        "periodo": 2026,
        "orden_compra": oc,
        "monto_devengado": amount,
        "fecha_documento": pd.Timestamp("2026-03-01"),
        "nombre_beneficiario": "PROVEEDOR",
        "is_aggregated": False,
    }


def _orders(tmp_path: Path, records: list[dict]) -> str:
    frame = normalize_purchase_orders(records)
    path = tmp_path / "procurement.parquet"
    frame.to_parquet(path, index=False)
    return str(path)


def test_normalizer_accepts_the_native_source_shape():
    frame = normalize_purchase_orders(
        [
            {
                "Codigo": "1234-56-SE26",
                "CodigoLicitacion": "1234-5-LP26",
                "TipoLicitacion": "LP",
                "CantidadOferentes": "3",
                "MontoAdjudicado": "12000000",
                "FechaAdjudicacion": "2026-02-10",
                "NombreProveedor": "ACME SPA",
                "RutProveedor": "76071943-9",
            }
        ]
    )
    assert list(frame.columns) == CANONICAL_COLUMNS
    row = frame.iloc[0]
    assert row["purchase_order_id"] == "1234-56-SE26"
    assert row["modality"] == "LICITACION_PUBLICA"
    assert int(row["bidders_count"]) == 3
    assert float(row["awarded_amount_clp"]) == 12_000_000.0


def test_normalizer_maps_direct_award_and_drops_orders_without_key():
    frame = normalize_purchase_orders(
        [
            {"Codigo": "OC-1", "TipoLicitacion": "TD"},
            {"TipoLicitacion": "LP"},  # sin llave de unión
        ]
    )
    assert len(frame) == 1
    assert frame.iloc[0]["modality"] == "TRATO_DIRECTO"


def test_join_uses_orden_compra_as_the_key(tmp_path):
    payments = _payments(tmp_path, [_payment("OC-1", 5_000_000), _payment("OC-HUERFANA", 1_000)])
    orders = _orders(tmp_path, [{"Codigo": "OC-1", "TipoLicitacion": "LP", "MontoAdjudicado": 5_000_000}])
    joined = join_payments(payments, orders)
    assert len(joined) == 1
    assert joined.iloc[0]["purchase_order_id"] == "OC-1"
    assert joined.iloc[0]["paid_amount"] == 5_000_000


def test_coverage_reports_the_traceability_gap(tmp_path):
    payments = _payments(
        tmp_path,
        [_payment("OC-1", 6_000_000), _payment("", 4_000_000)],
    )
    orders = _orders(tmp_path, [{"Codigo": "OC-1", "TipoLicitacion": "LP"}])
    result = coverage(payments, orders)
    assert result["purchase_order_amount_share"] == 0.6
    assert result["procurement_match_share"] == 1.0
    assert result["snapshot_available"] is True


def test_single_bidder_and_inflation(tmp_path):
    payments = _payments(tmp_path, [_payment("OC-1", 90_000_000)])
    orders = _orders(
        tmp_path,
        [
            {
                "Codigo": "OC-1",
                "TipoLicitacion": "LP",
                "CantidadOferentes": 1,
                "OferentesAdmisibles": 1,
                "MontoAdjudicado": 60_000_000,
                "FechaPublicacion": "2026-01-01",
                "FechaAdjudicacion": "2026-01-20",
            }
        ],
    )
    result = build_procurement_signals(
        payments, orders, THRESHOLDS, output_parquet=tmp_path / "sig.parquet"
    )
    kinds = set(result["by_type"])
    assert "SINGLE_BIDDER" in kinds
    assert "AWARD_TO_PAYMENT_INFLATION" in kinds
    frame = pd.read_parquet(result["path"])
    inflation = frame[frame["signal_type"] == "AWARD_TO_PAYMENT_INFLATION"].iloc[0]
    assert inflation["deviation"] == 1.5
    assert "Ninguna de estas señales acredita irregularidad" in inflation["guardrail"]


def test_threshold_hugging_detects_bunching_below_the_boundary(tmp_path):
    """El equivalente al structuring: densidad anómala justo bajo el umbral."""
    boundary = 100 * UTM_2026[2026]  # 100 UTM
    payments, orders = [], []
    for i in range(12):  # justo por debajo
        payments.append(_payment(f"OC-LOW-{i}", boundary * 0.95))
        orders.append({"Codigo": f"OC-LOW-{i}", "TipoLicitacion": "CA", "MontoAdjudicado": boundary * 0.95})
    for i in range(2):  # justo por encima
        payments.append(_payment(f"OC-HIGH-{i}", boundary * 1.05))
        orders.append({"Codigo": f"OC-HIGH-{i}", "TipoLicitacion": "LE", "MontoAdjudicado": boundary * 1.05})

    result = build_procurement_signals(
        _payments(tmp_path, payments), _orders(tmp_path, orders), THRESHOLDS,
        output_parquet=tmp_path / "sig.parquet",
    )
    assert result["by_type"].get("THRESHOLD_HUGGING", 0) >= 1
    frame = pd.read_parquet(result["path"])
    hugging = frame[frame["signal_type"] == "THRESHOLD_HUGGING"].iloc[0]
    assert "100 UTM" in hugging["why_flagged"]


def test_misconfigured_threshold_finds_nothing_instead_of_inventing(tmp_path):
    boundary = 100 * UTM_2026[2026]
    payments, orders = [], []
    for i in range(12):
        payments.append(_payment(f"OC-{i}", boundary * 0.95))
        orders.append({"Codigo": f"OC-{i}", "TipoLicitacion": "CA", "MontoAdjudicado": boundary * 0.95})
    empty_utm = ProcurementThresholds(utm_clp_by_year={})
    result = build_procurement_signals(
        _payments(tmp_path, payments), _orders(tmp_path, orders), empty_utm,
        output_parquet=tmp_path / "sig.parquet",
    )
    assert result["by_type"].get("THRESHOLD_HUGGING", 0) == 0


def test_split_procurement_requires_the_sum_to_cross_what_no_order_reaches(tmp_path):
    boundary = 100 * UTM_2026[2026]
    payments, orders = [], []
    for i in range(4):
        payments.append(_payment(f"OC-S{i}", boundary * 0.4))
        orders.append(
            {
                "Codigo": f"OC-S{i}",
                "TipoLicitacion": "CA",
                "MontoAdjudicado": boundary * 0.4,
                "FechaCreacion": f"2026-03-0{i + 1}",
            }
        )
    result = build_procurement_signals(
        _payments(tmp_path, payments), _orders(tmp_path, orders), THRESHOLDS,
        output_parquet=tmp_path / "sig.parquet",
    )
    assert result["by_type"].get("SPLIT_PROCUREMENT", 0) == 1
    frame = pd.read_parquet(result["path"])
    split = frame[frame["signal_type"] == "SPLIT_PROCUREMENT"].iloc[0]
    assert "ninguna lo alcanza por separado" in split["why_flagged"]


def test_direct_award_dependence_and_recurrence(tmp_path):
    payments, orders = [], []
    for i in range(6):
        payments.append(_payment(f"OC-TD{i}", 30_000_000))
        orders.append(
            {"Codigo": f"OC-TD{i}", "TipoLicitacion": "TD", "MontoAdjudicado": 30_000_000}
        )
    result = build_procurement_signals(
        _payments(tmp_path, payments), _orders(tmp_path, orders), THRESHOLDS,
        output_parquet=tmp_path / "sig.parquet",
    )
    assert result["by_type"].get("DIRECT_AWARD_DEPENDENCE", 0) == 1
    assert result["by_type"].get("DIRECT_AWARD_RECURRENCE", 0) == 1


def test_status_is_honest_when_no_snapshot_exists(tmp_path):
    payments = _payments(tmp_path, [_payment("OC-1", 1_000_000)])
    payload = write_status(
        payments,
        procurement_path=tmp_path / "missing.parquet",
        output_json=tmp_path / "status.json",
    )
    assert payload["integration_state"] == "ADAPTER_READY_SOURCE_PENDING"
    assert payload["join_key"] == "orden_compra"
    assert payload["coverage"]["snapshot_available"] is False
    assert "Ley 19.886" in payload["threshold_note"]
    assert len(payload["detectors"]) == 8


def test_no_snapshot_yields_no_signals_and_no_crash(tmp_path):
    payments = _payments(tmp_path, [_payment("OC-1", 1_000_000)])
    result = build_procurement_signals(
        payments, tmp_path / "missing.parquet", THRESHOLDS,
        output_parquet=tmp_path / "sig.parquet",
    )
    assert result["signals"] == 0
    assert result["snapshot_available"] is False
