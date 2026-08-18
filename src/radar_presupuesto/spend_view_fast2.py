from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import spend_view as _spend
from .spend_view_fast import materialize_light_facts

_ORIGINAL_RECORDS = _spend._records


def _records_compatible(con, sql: str, params=None):
    """DuckDB-compatible rewrite for the only correlated calendar join in v2.

    Kept here so the deployment path can be corrected without changing the
    full analytical pipeline while it may still be running. The common builder
    will be folded back to this form after the production view is published.
    """
    if "FROM bounds b, range(12) t(i)" in sql:
        sql = """
        WITH calendar AS (
          SELECT i,
                 (b.start_month + i * INTERVAL '1 month')::DATE AS month_date
          FROM bounds b CROSS JOIN range(12) t(i)
        )
        SELECT strftime(c.month_date,'%Y-%m') AS period,
               coalesce(sum(l.amount),0) AS amount_clp,
               coalesce(sum(l.amount) FILTER (
                 WHERE l.is_provider=TRUE AND coalesce(l.provider_id,'')<>''
               ),0) AS provider_amount_clp,
               count(l.organization_id) AS transactions
        FROM calendar c
        LEFT JOIN l12 l ON l.month_date = c.month_date
        GROUP BY c.i, c.month_date
        ORDER BY c.i
        """
    return _ORIGINAL_RECORDS(con, sql, params)


def build_fast_spend_view_v2(raw_paths: list[str], output: str) -> dict:
    light = "data/processed/spend_view_light.parquet"
    meta = materialize_light_facts(raw_paths, light)
    _spend._records = _records_compatible
    try:
        payload = _spend.build_spend_view_v2(
            light,
            output=output,
            prioritized_path=None,
        )
    finally:
        _spend._records = _ORIGINAL_RECORDS
    payload.setdefault("source", {})["ui_staging"] = "LIGHT_CANONICAL_FACT"
    payload["source"]["ui_staging_rows"] = meta["rows"]
    payload["source"]["calendar_join_compat"] = "DUCKDB_NON_CORRELATED_V2"
    Path(output).write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str),
        encoding="utf-8",
    )
    return payload


def main() -> None:
    p = argparse.ArgumentParser(description="Fast real Spend View v2 builder (DuckDB compatible)")
    p.add_argument("raw_paths", nargs="+")
    p.add_argument("--output", default="docs/data/spend_view_v2.json")
    args = p.parse_args()
    payload = build_fast_spend_view_v2(args.raw_paths, args.output)
    print("[OK] ventana", payload["window"])
    print("[OK] publicados", payload["published"])
    print("[OK] overview", payload["overview"])


if __name__ == "__main__":
    main()
