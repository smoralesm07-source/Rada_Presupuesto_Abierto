from __future__ import annotations

from datetime import date

import pytest

from radar_presupuesto.windows import (
    ACTIONABLE,
    EVIDENCE_AT_RISK,
    LEARNING_ONLY,
    WINDOW_ACTION,
    WINDOW_LEARNING,
    WINDOW_OUT_OF_SERIES,
    AnalysisWindows,
    from_config,
)

W = AnalysisWindows(action_from_year=2023, learning_from_year=2016)
TODAY = date(2026, 9, 13)


def test_action_window_decides_what_can_become_a_case():
    assert W.window_of(2026) == WINDOW_ACTION
    assert W.window_of(2023) == WINDOW_ACTION
    assert W.window_of(2022) == WINDOW_LEARNING
    assert W.window_of(2016) == WINDOW_LEARNING
    assert W.window_of(2015) == WINDOW_OUT_OF_SERIES
    assert W.is_actionable(2024) and not W.is_actionable(2019)


def test_learning_window_includes_the_action_window():
    """La línea base tiene que incluir lo reciente, o compara contra un vacío."""
    assert W.in_learning(2026) and W.in_learning(2018)
    assert not W.in_learning(2014)


def test_baseline_years_counts_only_history_before_the_action_window():
    assert W.baseline_years([2024, 2025, 2026]) == 0, (
        "sin años previos a la ventana de acción no hay línea base que respalde 'nuevo'"
    )
    assert W.baseline_years(range(2016, 2027)) == 7
    assert W.baseline_years([2021, 2022, 2023, 2024]) == 2


def test_a_window_that_starts_before_its_baseline_is_refused():
    with pytest.raises(ValueError, match="antes o junto"):
        AnalysisWindows(action_from_year=2018, learning_from_year=2020)


def test_warning_cannot_come_after_the_horizon():
    with pytest.raises(ValueError, match="antes del horizonte"):
        AnalysisWindows(evidence_horizon_months=24, evidence_warning_months=36)


def test_recent_activity_inside_the_window_is_actionable():
    result = W.actionability(2026, date(2026, 6, 1), reference=TODAY)
    assert result["state"] == ACTIONABLE
    assert result["window"] == WINDOW_ACTION
    assert result["months_since_activity"] < 6


def test_old_activity_inside_the_window_flags_evidence_risk():
    result = W.actionability(2023, date(2023, 1, 10), reference=TODAY)
    assert result["state"] == EVIDENCE_AT_RISK
    assert "horizonte de evidencia" in result["why"]


def test_outside_the_action_window_is_never_actionable():
    result = W.actionability(2019, date(2019, 5, 1), reference=TODAY)
    assert result["state"] == LEARNING_ONLY
    assert "línea base" in result["why"]
    assert str(W.action_from_year) in result["why"]


def test_missing_activity_date_does_not_fabricate_a_verdict():
    result = W.actionability(2026, None, reference=TODAY)
    assert result["state"] == ACTIONABLE
    assert result["months_since_activity"] is None
    assert "sin fecha de última actividad" in result["why"]


def test_evidence_horizon_is_declared_as_operational_not_legal():
    described = W.describe()
    note = described["evidence_horizon_note"]
    assert "no es un plazo" in note.lower()
    assert "prescripción" in note.lower()
    assert "no es menos relevante" in described["guardrail"]


def test_sql_filters_target_the_right_window():
    assert "2023" in W.sql_action_filter()
    assert "2016" in W.sql_learning_filter()
    assert W.sql_action_filter("year").startswith("try_cast(year")


def test_config_reading_falls_back_to_defaults():
    assert from_config(None).action_from_year == 2023
    assert from_config({"analysis_windows": {"action_from_year": 2024}}).action_from_year == 2024
    # También acepta el bloque suelto, para no obligar a anidar en cada llamador.
    assert from_config({"action_from_year": 2025}).action_from_year == 2025
