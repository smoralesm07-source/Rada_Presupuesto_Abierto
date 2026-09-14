from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from radar_presupuesto.prioritization import prioritize_signals
from radar_presupuesto.windows import AnalysisWindows

SIGNAL_COLUMNS = [
    "signal_id", "signal_type", "transaction_id", "organization_id", "recipient_id",
    "provider_id", "periodo", "mes", "observed_value", "expected_value", "deviation",
    "severity", "confidence", "record_class", "why_flagged", "investigation_hypothesis",
    "recommended_checks",
]

WINDOWS = AnalysisWindows(action_from_year=2023, learning_from_year=2016)


def _fact(org: str, provider: str, year: int, amount: float, tx: str) -> dict:
    return {
        "transaction_id": tx, "organization_id": org, "provider_id": provider,
        "recipient_id": provider.replace("PRV", "RCV"), "periodo": year, "mes": 6,
        "subtitulo": "22", "monto_devengado": amount, "nombre_beneficiario": provider,
        "nombre_area": org, "nombre_capitulo": org, "nombre_partida": org,
        "orden_compra": "", "codigo_bip": "", "region": "13", "is_aggregated": False,
        "fecha_documento": pd.Timestamp(f"{year}-06-01"),
        "fecha_pago": pd.Timestamp(f"{year}-06-20"),
    }


def _signal(kind: str, org: str, provider: str, year: int, tx: str) -> dict:
    return {
        "signal_id": f"SIG-{kind}-{org}-{provider}-{year}", "signal_type": kind,
        "transaction_id": tx, "organization_id": org,
        "recipient_id": provider.replace("PRV", "RCV"), "provider_id": provider,
        "periodo": year, "mes": 6, "observed_value": 1.0, "expected_value": 1.0,
        "deviation": 1.0, "severity": "HIGH", "confidence": "MEDIUM",
        "record_class": "DERIVED_SIGNAL", "why_flagged": "t",
        "investigation_hypothesis": "t", "recommended_checks": "[]",
    }


def _world(tmp_path: Path):
    facts, signals = [], []
    # Historia larga: muchos proveedores por año, unos pocos marcados.
    for year in range(2016, 2027):
        for i in range(20):
            provider = f"PRV-RUT-P{i:02d}"
            tx = f"TRX-{year}-{i:02d}"
            facts.append(_fact("ORG-1", provider, year, 100_000_000, tx))
            if i < 2:
                signals.append(_signal("AMOUNT_OUTLIER", "ORG-1", provider, year, tx))
    facts_path = tmp_path / "f.parquet"
    pd.DataFrame(facts).to_parquet(facts_path, index=False)
    signals_path = tmp_path / "s.parquet"
    pd.DataFrame(signals, columns=SIGNAL_COLUMNS).to_parquet(signals_path, index=False)
    return str(facts_path), str(signals_path)


def _run(tmp_path, windows=WINDOWS, **kwargs):
    facts, signals = _world(tmp_path)
    result = prioritize_signals(
        facts,
        signals_path=signals,
        cgr_links_path=str(tmp_path / "nope.parquet"),
        entity_signals_path=str(tmp_path / "nope2.parquet"),
        output_parquet=str(tmp_path / "p.parquet"),
        output_json=str(tmp_path / "q.json"),
        windows=windows,
        **kwargs,
    )
    queue = json.loads((tmp_path / "q.json").read_text(encoding="utf-8"))
    frame = pd.read_parquet(tmp_path / "p.parquet")
    return result, queue, frame


def test_only_the_action_window_reaches_the_queue(tmp_path):
    result, queue, frame = _run(tmp_path)

    published_years = {row["periodo"] for row in queue["queue"]}
    assert published_years and min(published_years) >= 2023, published_years
    assert all(row["analysis_window"] == "ACCION" for row in queue["queue"])

    # Lo anterior no se descarta: sigue puntuado en el parquet.
    assert set(frame["analysis_window"]) == {"ACCION", "APRENDIZAJE"}
    assert result["signals_by_window"]["APRENDIZAJE"] > 0
    assert result["actionable_signals"] < result["signals"]


def test_history_feeds_the_baseline_it_no_longer_feeds_the_queue(tmp_path):
    result, queue, _ = _run(tmp_path)

    assert queue["baseline"]["years_before_action_window"] == 7
    assert queue["baseline"]["relations_in_learning_window"] == 11 * 20
    assert result["baseline_years"] == 7
    assert "no se descarta" in queue["window_policy"]


def test_prevalence_is_measured_against_the_whole_learning_window(tmp_path):
    """2 de 20 proveedores marcados por año: la prevalencia debe reflejar eso."""
    _, _, frame = _run(tmp_path)
    prevalence = frame["pattern_prevalence"].dropna().unique()
    assert len(prevalence) == 1
    assert abs(float(prevalence[0]) - 0.10) < 0.01, prevalence


def test_moving_the_window_moves_only_what_is_published(tmp_path):
    wide, wide_queue, _ = _run(tmp_path)
    narrow, narrow_queue, _ = _run(
        tmp_path, windows=AnalysisWindows(action_from_year=2025, learning_from_year=2016)
    )

    assert narrow["actionable_signals"] < wide["actionable_signals"]
    # El universo analizado no cambia: cambia qué se publica.
    assert narrow["signals"] == wide["signals"]
    assert narrow_queue["baseline"]["years_before_action_window"] == 9
    assert min(row["periodo"] for row in narrow_queue["queue"]) >= 2025


def test_queue_declares_the_windows_it_used(tmp_path):
    _, queue, _ = _run(tmp_path)
    windows = queue["analysis_windows"]
    assert windows["action_from_year"] == 2023
    assert windows["learning_from_year"] == 2016
    assert "no es un plazo" in windows["evidence_horizon_note"].lower()
    assert "no es menos relevante" in windows["guardrail"]


def test_last_activity_travels_with_each_signal(tmp_path):
    _, _, frame = _run(tmp_path)
    assert "last_activity" in frame.columns
    assert frame["last_activity"].notna().any()
