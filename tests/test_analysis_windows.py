"""Dos horizontes: lo que todavía se puede trabajar y lo que sólo enseña.

«La info histórica ya no me permite actuar, sólo permitiría alimentar el modelo
en término de aprendizaje.» Esa frase es el criterio que estas pruebas fijan.
"""
import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from radar_presupuesto.analysis_window import (
    ACTIONABLE,
    EVIDENCE_AT_RISK,
    LEARNING_ONLY,
    WINDOW_ACTION,
    WINDOW_LEARNING,
    WINDOW_OUT_OF_SERIES,
    AnalysisWindows,
    describe_window,
    load_windows,
)

W = AnalysisWindows(action_from_year=2023, learning_from_year=2016)
HOY = date(2026, 9, 14)


def test_the_two_windows_sort_years_into_tray_baseline_and_outside():
    assert W.window_of(2026) == WINDOW_ACTION
    assert W.window_of(2023) == WINDOW_ACTION      # el borde pertenece a la acción
    assert W.window_of(2022) == WINDOW_LEARNING
    assert W.window_of(2016) == WINDOW_LEARNING
    assert W.window_of(2015) == WINDOW_OUT_OF_SERIES
    assert W.window_of(None) == WINDOW_OUT_OF_SERIES
    assert W.window_of("no es un año") == WINDOW_OUT_OF_SERIES


def test_history_feeds_the_baseline_and_never_the_tray():
    vieja = W.actionability(2019, last_activity="2019-06-01", reference=HOY)
    assert vieja["state"] == LEARNING_ONLY
    assert vieja["window"] == WINDOW_LEARNING
    assert "no la bandeja" in vieja["why"]

    assert W.in_learning(2019) is True
    assert W.is_actionable(2019) is False


def test_evidence_can_be_at_risk_inside_the_action_window():
    """Estar en la ventana no garantiza que el respaldo siga siendo obtenible."""
    reciente = W.actionability(2026, last_activity="2026-06-01", reference=HOY)
    assert reciente["state"] == ACTIONABLE

    # 2023 está en la ventana de acción, pero ya pasaron más de 42 meses.
    antigua = W.actionability(2023, last_activity="2023-01-15", reference=HOY)
    assert antigua["window"] == WINDOW_ACTION
    assert antigua["state"] == EVIDENCE_AT_RISK
    assert "horizonte de evidencia" in antigua["why"]


def test_actionability_without_a_date_does_not_invent_risk():
    sin_fecha = W.actionability(2026, last_activity=None, reference=HOY)
    assert sin_fecha["state"] == ACTIONABLE
    assert sin_fecha["months_since_activity"] is None
    assert "sin fecha de última actividad" in sin_fecha["why"]


# ---------------------------------------------------------------------------
# Lo que la línea base respalda, y lo que no
# ---------------------------------------------------------------------------

def test_baseline_depth_is_what_makes_a_new_supplier_claim_worth_anything():
    # Ventana procesada de 7 años terminando en 2026: sólo 3 quedan como base.
    assert W.baseline_years(range(2020, 2027)) == 3
    # Con la serie completa del catálogo, la base se triplica.
    assert W.baseline_years(range(2016, 2027)) == 7
    # Sin historia previa, la afirmación de novedad queda sin respaldo.
    assert W.baseline_years(range(2023, 2027)) == 0


def test_an_empty_baseline_is_declared_not_assumed():
    sin_base = W.describe(range(2023, 2027))
    assert sin_base["baseline_years_available"] == 0
    assert sin_base["baseline_status"] == "SIN_LINEA_BASE"

    con_base = W.describe(range(2016, 2027))
    assert con_base["baseline_years_available"] == 7
    assert con_base["baseline_status"] == "CON_LINEA_BASE"


def test_the_description_says_the_evidence_horizon_is_operational_not_legal():
    d = W.describe()
    assert "no es un plazo" in d["evidence_horizon_note"].lower()
    assert "prescripción" in d["evidence_horizon_note"]
    assert "no qué es más grave" in d["guardrail"]


# ---------------------------------------------------------------------------
# Configuración y contratos que no deben romperse
# ---------------------------------------------------------------------------

def test_windows_that_contradict_themselves_are_refused():
    with pytest.raises(ValueError, match="aprendizaje"):
        AnalysisWindows(action_from_year=2020, learning_from_year=2024)
    with pytest.raises(ValueError, match="aviso"):
        AnalysisWindows(evidence_horizon_months=24, evidence_warning_months=48)


def test_the_repository_config_is_loadable_and_coherent():
    w = load_windows()
    assert w.learning_from_year <= w.action_from_year
    assert w.evidence_warning_months <= w.evidence_horizon_months
    raw = yaml.safe_load(Path("config/analysis_windows.yaml").read_text(encoding="utf-8"))
    assert raw["windows"]["action_from_year"] == w.action_from_year


def test_missing_config_falls_back_to_the_declared_defaults(tmp_path: Path):
    w = load_windows(str(tmp_path / "no_existe.yaml"))
    assert w == AnalysisWindows()


def test_sql_filters_are_usable_and_distinct():
    assert W.sql_action_filter() == "try_cast(periodo AS INTEGER) >= 2023"
    assert W.sql_learning_filter("anio") == "try_cast(anio AS INTEGER) >= 2016"


def test_describe_window_keeps_its_existing_contract():
    """El CI afirma `year_count >= 5` sobre esta función: no debe cambiar de forma."""
    meta = describe_window([2020, 2021, 2022, 2023, 2024])
    assert meta["year_count"] == 5
    assert meta["first_year"] == 2020
    assert meta["last_year"] == 2024
    assert meta["historical_depth_years"] == 5
