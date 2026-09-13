from __future__ import annotations

import json
from pathlib import Path

AVAILABLE_STATUSES = {"linked", "linked_available", "probed_available"}


def resolve_analysis_years(
    catalog_path: str = "docs/data/source_catalog.json",
    requested: str | None = None,
    window_years: int = 7,
    min_years: int = 5,
) -> list[int]:
    """Resolve a stable historical window for RIGP analytics.

    Three years are insufficient for labels such as ``NEW_TO_SERIES_HIGH_SPEND``
    and make historical concentration comparisons fragile. The default therefore
    uses the latest seven confirmed bulk years, while refusing to silently operate
    with fewer than five unless years were explicitly requested by an operator.
    """
    if requested and requested.strip():
        years = sorted({int(x) for x in requested.replace(",", " ").split() if x.strip()})
        if not years:
            raise ValueError("requested years is empty after parsing")
        return years

    catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    years = sorted(
        {
            int(row["year"])
            for row in catalog.get("downloads", [])
            if row.get("status") in AVAILABLE_STATUSES and row.get("year") is not None
        }
    )
    if len(years) < min_years:
        raise RuntimeError(
            f"RIGP requires at least {min_years} confirmed years for its default historical window; found {len(years)}"
        )
    if window_years <= 0:
        return years
    return years[-window_years:]


def describe_window(years: list[int]) -> dict:
    if not years:
        return {"years": [], "year_count": 0, "first_year": None, "last_year": None}
    ordered = sorted(set(int(y) for y in years))
    return {
        "years": ordered,
        "year_count": len(ordered),
        "first_year": ordered[0],
        "last_year": ordered[-1],
        "historical_depth_years": ordered[-1] - ordered[0] + 1,
    }
