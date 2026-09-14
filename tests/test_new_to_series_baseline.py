from __future__ import annotations

from pathlib import Path

import pandas as pd

from radar_presupuesto.advanced_signals import extend_signals
from radar_presupuesto.windows import AnalysisWindows

SIGNAL_COLUMNS = [
    "signal_id", "signal_type", "transaction_id", "organization_id", "recipient_id",
    "provider_id", "periodo", "mes", "observed_value", "expected_value", "deviation",
    "severity", "confidence", "record_class", "why_flagged", "investigation_hypothesis",
    "recommended_checks",
]


def _seed(tmp_path: Path) -> str:
    row = {
        "signal_id": "SEED", "signal_type": "SEED", "transaction_id": "T0",
        "organization_id": "ORG-1", "recipient_id": "RCV-1", "provider_id": "PRV-RUT-1",
        "periodo": 2026, "mes": 3, "observed_value": 1.0, "expected_value": 1.0,
        "deviation": 1.0, "severity": "LOW", "confidence": "LOW",
        "record_class": "DERIVED_SIGNAL", "why_flagged": "seed",
        "investigation_hypothesis": "seed", "recommended_checks": "[]",
    }
    path = tmp_path / "risk_signals.parquet"
    pd.DataFrame([row], columns=SIGNAL_COLUMNS).to_parquet(path, index=False)
    return str(path)


def _payment(provider: str, year: int, amount: float, i: int = 0) -> dict:
    return {
        "transaction_id": f"T-{provider}-{year}-{i}",
        "organization_id": f"ORG-{i % 4}",
        "recipient_id": provider.replace("PRV", "RCV"),
        "provider_id": provider,
        "periodo": year,
        "mes": 6,
        "is_provider": True,
        "is_aggregated": False,
        "monto_devengado": amount,
        "dias_de_pago": "10",
        "fecha_documento": pd.Timestamp(f"{year}-06-01"),
        "fecha_recepcion_conforme": pd.Timestamp(f"{year}-06-01"),
        "fecha_pago": pd.Timestamp(f"{year}-06-11"),
    }


def _facts(rows: list[dict], tmp_path: Path) -> str:
    path = tmp_path / "transactions.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    return str(path)


def test_long_standing_supplier_is_not_new_when_history_exists(tmp_path):
    """El proveedor activo desde 2016 no puede aparecer como irrupción en 2024."""
    rows = []
    for year in range(2016, 2027):
        for i in range(4):
            rows.append(_payment("PRV-RUT-VIEJO", year, 400_000_000, i))
    windows = AnalysisWindows(action_from_year=2023, learning_from_year=2016)
    result = extend_signals(_facts(rows, tmp_path), signals_path=_seed(tmp_path), windows=windows)

    assert result["by_type"].get("NEW_TO_SERIES_HIGH_SPEND", 0) == 0
    assert result["baseline_years"] == 7


def test_genuinely_new_supplier_inside_the_action_window_fires(tmp_path):
    rows = []
    for year in range(2016, 2027):
        for i in range(4):
            rows.append(_payment("PRV-RUT-VIEJO", year, 400_000_000, i))
    for i in range(4):
        rows.append(_payment("PRV-RUT-NUEVO", 2025, 900_000_000, i))

    windows = AnalysisWindows(action_from_year=2023, learning_from_year=2016)
    result = extend_signals(_facts(rows, tmp_path), signals_path=_seed(tmp_path), windows=windows)
    frame = pd.read_parquet(result["path"])
    new = frame[frame["signal_type"] == "NEW_TO_SERIES_HIGH_SPEND"]

    assert len(new) == 1
    row = new.iloc[0]
    assert row["provider_id"] == "PRV-RUT-NUEVO"
    assert row["periodo"] == 2025
    assert "Primera aparición del proveedor en 2025" in row["why_flagged"]
    assert "Línea base: 7 año(s)" in row["why_flagged"]
    assert row["confidence"] == "MEDIUM"


def test_without_baseline_the_novelty_claim_is_marked_unsupported(tmp_path):
    """Sin años previos, 'nuevo' no está acreditado y la señal debe decirlo."""
    rows = []
    for year in (2024, 2025, 2026):
        for i in range(4):
            rows.append(_payment("PRV-RUT-VIEJO", year, 400_000_000, i))
    for i in range(4):
        rows.append(_payment("PRV-RUT-APARENTE", 2025, 900_000_000, i))

    windows = AnalysisWindows(action_from_year=2023, learning_from_year=2016)
    result = extend_signals(_facts(rows, tmp_path), signals_path=_seed(tmp_path), windows=windows)
    frame = pd.read_parquet(result["path"])
    new = frame[frame["signal_type"] == "NEW_TO_SERIES_HIGH_SPEND"]

    assert result["baseline_years"] == 0
    assert len(new) >= 1
    row = new.iloc[0]
    assert row["confidence"] == "LOW", "sin línea base la confianza no puede ser media"
    assert "línea base disponible es corta" in row["investigation_hypothesis"]
    assert "no está acreditada" in row["investigation_hypothesis"]


def test_novelty_before_the_action_window_never_becomes_a_signal(tmp_path):
    """Una irrupción de 2019 alimenta la línea base, no la bandeja."""
    rows = []
    for year in range(2016, 2027):
        for i in range(4):
            rows.append(_payment("PRV-RUT-VIEJO", year, 400_000_000, i))
    for i in range(4):
        rows.append(_payment("PRV-RUT-IRRUPCION-2019", 2019, 900_000_000, i))

    windows = AnalysisWindows(action_from_year=2023, learning_from_year=2016)
    result = extend_signals(_facts(rows, tmp_path), signals_path=_seed(tmp_path), windows=windows)
    frame = pd.read_parquet(result["path"])
    new = frame[frame["signal_type"] == "NEW_TO_SERIES_HIGH_SPEND"]

    assert "PRV-RUT-IRRUPCION-2019" not in set(new["provider_id"])


def test_moving_the_action_window_changes_what_is_reported(tmp_path):
    rows = []
    for year in range(2016, 2027):
        for i in range(4):
            rows.append(_payment("PRV-RUT-VIEJO", year, 400_000_000, i))
    for i in range(4):
        rows.append(_payment("PRV-RUT-2023", 2023, 900_000_000, i))
    facts = _facts(rows, tmp_path)

    wide = extend_signals(facts, signals_path=_seed(tmp_path),
                          windows=AnalysisWindows(action_from_year=2023, learning_from_year=2016))
    assert wide["by_type"].get("NEW_TO_SERIES_HIGH_SPEND", 0) == 1

    narrow = extend_signals(facts, signals_path=_seed(tmp_path),
                            windows=AnalysisWindows(action_from_year=2024, learning_from_year=2016))
    assert narrow["by_type"].get("NEW_TO_SERIES_HIGH_SPEND", 0) == 0
    assert narrow["baseline_years"] == 8
