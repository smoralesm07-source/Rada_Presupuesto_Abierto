from __future__ import annotations

import argparse
import glob
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

SCHEMA = "PRESUPUESTO_TERRITORIAL_CONTEXT_V1"


def _cols(con: duckdb.DuckDBPyConnection, view: str) -> set[str]:
    return {str(row[0]) for row in con.execute(f"DESCRIBE {view}").fetchall()}


def _rows_as_dicts(con: duckdb.DuckDBPyConnection, query: str) -> list[dict[str, Any]]:
    cur = con.execute(query)
    names = [x[0] for x in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def _region_expr(alias: str, has_region: bool) -> str:
    if not has_region:
        return "'UNKNOWN'"
    return f"coalesce(nullif(trim(cast({alias}.region as varchar)),''),'UNKNOWN')"


def build_territorial_context(
    parquet_glob: str = "data/processed/transactions_*.parquet",
    prioritized_path: str = "data/signals/prioritized_signals.parquet",
    output: str = "docs/data/territorial_context_v1.json",
) -> dict[str, Any]:
    files = sorted(Path(p) for p in glob.glob(parquet_glob)) if "*" in parquet_glob else [Path(parquet_glob)]
    files = [p for p in files if p.exists()]
    if not files:
        raise FileNotFoundError(f"No transaction parquet matched {parquet_glob}")

    con = duckdb.connect()
    con.execute(
        f"CREATE OR REPLACE VIEW facts AS "
        f"SELECT * FROM read_parquet('{parquet_glob}', union_by_name=true)"
    )
    fact_cols = _cols(con, "facts")
    has_region = "region" in fact_cols
    region_expr = _region_expr("f", has_region)

    priority_exists = Path(prioritized_path).exists()
    priority_cols: set[str] = set()
    if priority_exists:
        con.execute(
            f"CREATE OR REPLACE VIEW priority AS "
            f"SELECT * FROM read_parquet('{prioritized_path}', union_by_name=true)"
        )
        priority_cols = _cols(con, "priority")

    amount_col = "monto_devengado" if "monto_devengado" in fact_cols else None
    amount_expr = f"coalesce(sum(try_cast(f.{amount_col} AS DOUBLE)),0)" if amount_col else "0"
    org_expr = "count(distinct f.organization_id)" if "organization_id" in fact_cols else "0"
    provider_expr = "count(distinct f.provider_id) filter (where coalesce(cast(f.provider_id as varchar),'')<>'')" if "provider_id" in fact_cols else "0"

    regions = _rows_as_dicts(
        con,
        f"""
        SELECT {region_expr} AS region,
               count(*)::BIGINT AS transactions,
               {amount_expr}::DOUBLE AS amount_clp,
               {org_expr}::BIGINT AS organizations,
               {provider_expr}::BIGINT AS providers
        FROM facts f
        GROUP BY 1
        ORDER BY amount_clp DESC, transactions DESC
        """,
    )

    priority_regions: list[dict[str, Any]] = []
    if priority_exists and "transaction_id" in priority_cols and "transaction_id" in fact_cols:
        p_region = _region_expr("p", "region" in priority_cols)
        join_needed = "region" not in priority_cols
        from_clause = "priority p"
        region_from = p_region
        if join_needed:
            # A single transaction may appear in multiple anomaly rows, so only attach
            # the source fact needed to recover its geographic context.
            con.execute(
                f"""
                CREATE OR REPLACE VIEW fact_geo AS
                SELECT transaction_id,
                       {_region_expr('x', has_region)} AS region,
                       max(cast(codigo_ubicacion_geografica as varchar)) AS codigo_ubicacion_geografica,
                       max(cast(nombre_ubicacion_geografica as varchar)) AS nombre_ubicacion_geografica
                FROM facts x
                GROUP BY transaction_id, 2
                """ if {"codigo_ubicacion_geografica", "nombre_ubicacion_geografica"}.issubset(fact_cols)
                else f"""
                CREATE OR REPLACE VIEW fact_geo AS
                SELECT transaction_id, {_region_expr('x', has_region)} AS region
                FROM facts x
                GROUP BY transaction_id, 2
                """
            )
            from_clause = "priority p left join fact_geo g using(transaction_id)"
            region_from = "coalesce(nullif(trim(cast(g.region as varchar)),''),'UNKNOWN')"

        score_expr = "try_cast(p.investigation_priority_score AS DOUBLE)" if "investigation_priority_score" in priority_cols else "cast(NULL as DOUBLE)"
        tier_expr = "cast(p.priority_tier as varchar)" if "priority_tier" in priority_cols else "''"
        severity_expr = "upper(cast(p.severity as varchar))" if "severity" in priority_cols else "''"
        cgr_expr = "coalesce(try_cast(p.cgr_match_count AS BIGINT),0)" if "cgr_match_count" in priority_cols else "0"
        signal_type_expr = "cast(p.signal_type as varchar)" if "signal_type" in priority_cols else "NULL"
        priority_regions = _rows_as_dicts(
            con,
            f"""
            SELECT {region_from} AS region,
                   count(*)::BIGINT AS anomaly_signals,
                   count(*) FILTER (WHERE {tier_expr}='P1')::BIGINT AS p1_signals,
                   count(*) FILTER (WHERE {severity_expr}='HIGH')::BIGINT AS high_severity_signals,
                   round(avg({score_expr}),3) AS avg_investigation_priority,
                   count(*) FILTER (WHERE {cgr_expr}>0)::BIGINT AS cgr_linked_signals,
                   count(distinct {signal_type_expr})::BIGINT AS signal_type_count
            FROM {from_clause}
            GROUP BY 1
            ORDER BY p1_signals DESC, anomaly_signals DESC
            """,
        )

    p_by_region = {str(r["region"]): r for r in priority_regions}
    region_rows: list[dict[str, Any]] = []
    for row in regions:
        out = dict(row)
        p = p_by_region.get(str(row["region"]), {})
        out.update(
            anomaly_signals=int(p.get("anomaly_signals") or 0),
            p1_signals=int(p.get("p1_signals") or 0),
            high_severity_signals=int(p.get("high_severity_signals") or 0),
            avg_investigation_priority=p.get("avg_investigation_priority"),
            cgr_linked_signals=int(p.get("cgr_linked_signals") or 0),
            signal_type_count=int(p.get("signal_type_count") or 0),
        )
        out["p1_per_100k_transactions"] = round(100000.0 * out["p1_signals"] / out["transactions"], 4) if out["transactions"] else None
        out["signals_per_100k_transactions"] = round(100000.0 * out["anomaly_signals"] / out["transactions"], 4) if out["transactions"] else None
        out["amount_per_transaction"] = round(float(out["amount_clp"]) / out["transactions"], 2) if out["transactions"] else None
        region_rows.append(out)

    geo_units: list[dict[str, Any]] = []
    geo_cols = {"codigo_ubicacion_geografica", "nombre_ubicacion_geografica"}
    if geo_cols.issubset(fact_cols):
        geo_units = _rows_as_dicts(
            con,
            f"""
            SELECT {region_expr} AS region,
                   nullif(trim(cast(f.codigo_ubicacion_geografica as varchar)),'') AS geographic_unit_code,
                   nullif(trim(cast(f.nombre_ubicacion_geografica as varchar)),'') AS geographic_unit_name,
                   count(*)::BIGINT AS transactions,
                   {amount_expr}::DOUBLE AS amount_clp,
                   {org_expr}::BIGINT AS organizations,
                   {provider_expr}::BIGINT AS providers
            FROM facts f
            WHERE nullif(trim(cast(f.codigo_ubicacion_geografica as varchar)),'') IS NOT NULL
               OR nullif(trim(cast(f.nombre_ubicacion_geografica as varchar)),'') IS NOT NULL
            GROUP BY 1,2,3
            ORDER BY amount_clp DESC, transactions DESC
            """,
        )

        if priority_exists and "transaction_id" in priority_cols and "transaction_id" in fact_cols:
            geo_priority = _rows_as_dicts(
                con,
                f"""
                WITH pg AS (
                  SELECT p.*,
                         {_region_expr('f', has_region)} AS region,
                         nullif(trim(cast(f.codigo_ubicacion_geografica as varchar)),'') AS geographic_unit_code,
                         nullif(trim(cast(f.nombre_ubicacion_geografica as varchar)),'') AS geographic_unit_name
                  FROM priority p
                  LEFT JOIN facts f USING(transaction_id)
                )
                SELECT region, geographic_unit_code, geographic_unit_name,
                       count(*)::BIGINT AS anomaly_signals,
                       count(*) FILTER (WHERE {('cast(priority_tier as varchar)' if 'priority_tier' in priority_cols else "''")}='P1')::BIGINT AS p1_signals,
                       round(avg({('try_cast(investigation_priority_score AS DOUBLE)' if 'investigation_priority_score' in priority_cols else 'cast(NULL as DOUBLE)')}),3) AS avg_investigation_priority
                FROM pg
                GROUP BY 1,2,3
                """,
            )
            p_geo = {
                (str(x.get("region")), str(x.get("geographic_unit_code")), str(x.get("geographic_unit_name"))): x
                for x in geo_priority
            }
            for row in geo_units:
                p = p_geo.get((str(row.get("region")), str(row.get("geographic_unit_code")), str(row.get("geographic_unit_name"))), {})
                row["anomaly_signals"] = int(p.get("anomaly_signals") or 0)
                row["p1_signals"] = int(p.get("p1_signals") or 0)
                row["avg_investigation_priority"] = p.get("avg_investigation_priority")
                row["p1_per_100k_transactions"] = round(100000.0 * row["p1_signals"] / row["transactions"], 4) if row["transactions"] else None

    con.close()

    payload = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "RADAR_PRESUPUESTO",
        "grain": ["REGION", "SOURCE_GEOGRAPHIC_UNIT"],
        "regions": region_rows,
        "geographic_units": geo_units,
        "coverage": {
            "regions": len([x for x in region_rows if x.get("region") != "UNKNOWN"]),
            "source_geographic_units": len(geo_units),
            "priority_available": priority_exists,
            "commune_canonicalization_state": "PENDING_CONTEXT_HUB_VALIDATION",
        },
        "methodology": {
            "risk_semantics": "CONTEXT_AND_ANOMALY_INTENSITY_NOT_ILLEGALITY",
            "normalization_ready_metrics": ["p1_per_100k_transactions", "signals_per_100k_transactions"],
            "spend_is_exposure_not_adverse_signal": True,
            "source_geographic_unit_is_commune": False,
            "note": (
                "El código/nombre de ubicación geográfica se preserva como unidad de fuente. "
                "No se promueve a comuna CUT hasta validarlo contra Context Hub."
            ),
        },
        "guardrails": [
            "MISSING_IS_NOT_ZERO",
            "PUBLIC_SPEND_VOLUME_IS_NOT_RISK_BY_ITSELF",
            "ANOMALY_SIGNAL_IS_NOT_PROOF_OF_IRREGULARITY",
            "CGR_CANDIDATE_LINK_REQUIRES_DOCUMENTARY_CONFIRMATION",
            "SOURCE_GEOGRAPHIC_UNIT_IS_NOT_CANONICAL_COMMUNE_UNTIL_VALIDATED",
        ],
    }
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Build compact territorial context for Radar Presupuesto Abierto")
    parser.add_argument("--parquet-glob", default="data/processed/transactions_*.parquet")
    parser.add_argument("--priority", default="data/signals/prioritized_signals.parquet")
    parser.add_argument("--output", default="docs/data/territorial_context_v1.json")
    args = parser.parse_args()
    payload = build_territorial_context(args.parquet_glob, args.priority, args.output)
    print(json.dumps({"schema": payload["schema"], "regions": len(payload["regions"]), "geographic_units": len(payload["geographic_units"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
