import json
from pathlib import Path

import pytest

from radar_presupuesto.analysis_window import describe_window, load_windows, resolve_analysis_years


def _catalog(tmp_path: Path, years):
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            {
                "downloads": [
                    {"year": y, "status": "probed_available"}
                    for y in years
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def test_default_processes_everything_from_the_learning_window(tmp_path: Path):
    """El corte de la serie sigue a la configuración, no a un número escrito a mano.

    Antes eran «los últimos 7 años» fijos, y la línea base efectiva quedaba en
    tres aunque la configuración declarara que el aprendizaje empieza en 2016.
    """
    path = _catalog(tmp_path, range(2016, 2027))
    years = resolve_analysis_years(str(path))
    assert years == list(range(2016, 2027))
    assert load_windows().baseline_years(years) == 7


def test_an_operator_can_still_force_a_short_run(tmp_path: Path):
    path = _catalog(tmp_path, range(2016, 2027))
    years = resolve_analysis_years(str(path), window_years=7)
    assert years == [2020, 2021, 2022, 2023, 2024, 2025, 2026]
    assert describe_window(years)["historical_depth_years"] == 7


def test_a_catalog_shorter_than_the_learning_window_uses_what_it_has(tmp_path: Path):
    """Sin la historia configurada se procesa lo disponible; la profundidad se declara."""
    path = _catalog(tmp_path, range(2021, 2027))
    years = resolve_analysis_years(str(path))
    assert years == list(range(2021, 2027))


def test_default_refuses_shallow_history(tmp_path: Path):
    path = _catalog(tmp_path, [2024, 2025, 2026])
    with pytest.raises(RuntimeError):
        resolve_analysis_years(str(path))


def test_explicit_operator_request_can_be_narrower(tmp_path: Path):
    path = _catalog(tmp_path, range(2016, 2027))
    years = resolve_analysis_years(str(path), requested="2024 2026")
    assert years == [2024, 2026]
