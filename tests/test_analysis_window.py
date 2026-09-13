import json
from pathlib import Path

import pytest

from radar_presupuesto.analysis_window import describe_window, resolve_analysis_years


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


def test_default_uses_latest_seven_confirmed_years(tmp_path: Path):
    path = _catalog(tmp_path, range(2016, 2027))
    years = resolve_analysis_years(str(path))
    assert years == [2020, 2021, 2022, 2023, 2024, 2025, 2026]
    assert describe_window(years)["historical_depth_years"] == 7


def test_default_refuses_shallow_history(tmp_path: Path):
    path = _catalog(tmp_path, [2024, 2025, 2026])
    with pytest.raises(RuntimeError):
        resolve_analysis_years(str(path))


def test_explicit_operator_request_can_be_narrower(tmp_path: Path):
    path = _catalog(tmp_path, range(2016, 2027))
    years = resolve_analysis_years(str(path), requested="2024 2026")
    assert years == [2024, 2026]
