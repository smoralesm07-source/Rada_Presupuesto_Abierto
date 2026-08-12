import pytest

from radar_presupuesto.query_job import parse_years


def test_parse_years_single_list_and_range():
    assert parse_years("2026") == [2026]
    assert parse_years("2024 2026,2025") == [2024, 2025, 2026]
    assert parse_years("2024-2026") == [2024, 2025, 2026]
    assert parse_years("2026-2024") == [2024, 2025, 2026]


def test_parse_years_rejects_pre_bulk_and_invalid_tokens():
    with pytest.raises(ValueError):
        parse_years("2015")
    with pytest.raises(ValueError):
        parse_years("202x")
