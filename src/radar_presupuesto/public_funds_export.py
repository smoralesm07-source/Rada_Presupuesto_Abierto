from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

SCHEMA = "ATLAS_PUBLIC_FUNDS_V1"


def _records(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    df = con.execute(sql).df()
    if df.empty:
        return []
    return df.where(df.notna(), None).to_dict("records")


def build_public_funds_export(parquet_path: str, output: str, snapshot_id: str) -> dict:
    """Materializa la relación transversal con fondos públicos por RUT.

    Sólo pagos efectivos positivos, con RUT resuelto y fuera de intra-Estado.
    Conserva proveedor y receptor como roles distintos y publica únicamente
    agregados para ATLAS, nunca hechos transaccionales individuales.
    """
    path = Path(parquet_path)
    if not path.exists():
        raise FileNotFoundError(path)
    if not snapshot_id.startswith("PF-"):
        raise ValueError("snapshot_id debe comenzar con PF-")

    con = duckdb.connect()
    q = str(path).replace("'", "''")
    con.execute(f"""
      CREATE OR REPLACE VIEW paid AS
      SELECT
        upper(trim(rut_beneficiario)) AS rut,
        'ENT-RUT-' || upper(trim(rut_beneficiario)) AS entity_id,
        try_cast(periodo AS INTEGER) AS period_year,
        try_cast(mes AS INTEGER) AS period_month,
        make_date(try_cast(periodo AS INTEGER), try_cast(mes AS INTEGER), 1) AS period_date,
        organization_id AS payer_key,
        coalesce(nullif(trim(nombre_capitulo),''), nullif(trim(nombre_area),''),
                 nullif(trim(nombre_partida),''), organization_id) AS payer_name,
        CASE WHEN coalesce(is_provider,false) THEN 'SUPPLIER' ELSE 'RECIPIENT' END AS role,
        try_cast(monto_pago AS DOUBLE) AS amount
      FROM read_parquet('{q}')
      WHERE coalesce(trim(rut_beneficiario),'') <> ''
        AND try_cast(periodo AS INTEGER) IS NOT NULL
        AND try_cast(mes AS INTEGER) BETWEEN 1 AND 12
        AND coalesce(is_intra_state,false) = false
        AND coalesce(try_cast(monto_pago AS DOUBLE),0) > 0
        AND coalesce(trim(organization_id),'') <> ''
    """)

    latest = con.execute("SELECT max(period_date) FROM paid").fetchone()[0]
    if latest is None:
        raise RuntimeError("No hay pagos públicos con RUT resuelto")
    con.execute(
        "CREATE OR REPLACE TEMP TABLE bounds AS SELECT ?::DATE latest_month, "
        "(?::DATE - INTERVAL '11 months')::DATE l12_start, "
        "(?::DATE - INTERVAL '35 months')::DATE l36_start",
        [latest, latest, latest],
    )

    payer_years = _records(con, """
      SELECT rut, entity_id, payer_key, arg_max(payer_name, amount) AS payer_name,
             period_year, role, sum(amount) AS amount,
             count(*)::BIGINT AS transaction_count,
             min(period_date)::DATE AS first_seen, max(period_date)::DATE AS last_seen
      FROM paid
      GROUP BY 1,2,3,5,6
      HAVING sum(amount) > 0
      ORDER BY rut, period_year DESC, amount DESC
    """)

    years = _records(con, """
      WITH py AS (
        SELECT rut, entity_id, period_year, payer_key,
               arg_max(payer_name, amount) AS payer_name,
               sum(amount) AS payer_amount,
               sum(amount) FILTER (WHERE role='RECIPIENT') AS transfer_amount,
               sum(amount) FILTER (WHERE role='SUPPLIER') AS supplier_amount,
               count(*)::BIGINT AS transaction_count
        FROM paid GROUP BY 1,2,3,4
      ), ranked AS (
        SELECT *, row_number() OVER(PARTITION BY rut,period_year ORDER BY payer_amount DESC,payer_key) rn
        FROM py
      )
      SELECT rut, entity_id, period_year, sum(payer_amount) AS amount_total,
             coalesce(sum(transfer_amount),0) AS amount_transfer,
             coalesce(sum(supplier_amount),0) AS amount_supplier,
             count(*)::INTEGER AS payer_count,
             sum(transaction_count)::BIGINT AS transaction_count,
             max(payer_key) FILTER (WHERE rn=1) AS top_payer_key,
             max(payer_name) FILTER (WHERE rn=1) AS top_payer_name,
             max(payer_amount) FILTER (WHERE rn=1) AS top_payer_amount
      FROM ranked GROUP BY 1,2,3
      HAVING sum(payer_amount) > 0
      ORDER BY rut, period_year DESC
    """)

    entities = _records(con, """
      WITH by_payer AS (
        SELECT rut, entity_id, payer_key, arg_max(payer_name, amount) AS payer_name,
               sum(amount) AS payer_amount
        FROM paid GROUP BY 1,2,3
      ), top_payer AS (
        SELECT *, row_number() OVER(PARTITION BY rut ORDER BY payer_amount DESC,payer_key) rn
        FROM by_payer
      ), totals AS (
        SELECT p.rut, p.entity_id, sum(p.amount) AS amount_total,
               coalesce(sum(p.amount) FILTER (WHERE p.period_date BETWEEN b.l12_start AND b.latest_month),0) AS amount_12m,
               coalesce(sum(p.amount) FILTER (WHERE p.period_date BETWEEN b.l36_start AND b.latest_month),0) AS amount_36m,
               count(*)::BIGINT AS transaction_count,
               count(DISTINCT p.payer_key)::INTEGER AS payer_count,
               min(p.period_date)::DATE AS first_seen, max(p.period_date)::DATE AS last_seen
        FROM paid p CROSS JOIN bounds b GROUP BY 1,2
      )
      SELECT t.*, x.payer_key AS top_payer_key, x.payer_name AS top_payer_name,
             x.payer_amount AS top_payer_amount, 'READY' AS source_status
      FROM totals t LEFT JOIN top_payer x ON x.rut=t.rut AND x.rn=1
      WHERE t.amount_total > 0
      ORDER BY t.amount_total DESC, t.rut
    """)

    meta = con.execute("""
      SELECT count(*)::BIGINT, count(DISTINCT rut)::BIGINT, count(DISTINCT payer_key)::BIGINT,
             sum(amount), min(period_date), max(period_date),
             count(*) FILTER (WHERE role='SUPPLIER')::BIGINT,
             count(*) FILTER (WHERE role='RECIPIENT')::BIGINT
      FROM paid
    """).fetchone()
    con.close()

    payload = {
        "schema": SCHEMA, "snapshot_id": snapshot_id, "source": "PRESUPUESTO_ABIERTO",
        "semantics": {
            "amount_basis": "POSITIVE_MONTO_PAGO", "identity_basis": "RUT_EXACT_NORMALIZED",
            "payer_grain": "PARTIDA_CAPITULO", "recipient_scope": "ALL_BENEFICIARIES_AND_RECIPIENTS",
            "intra_state": "EXCLUDED", "roles": ["RECIPIENT", "SUPPLIER"],
            "risk_score_mutation": False,
        },
        "coverage": {
            "paid_rows": int(meta[0] or 0), "recipient_ruts": int(meta[1] or 0),
            "payers": int(meta[2] or 0), "amount_total": float(meta[3] or 0),
            "first_month": str(meta[4]) if meta[4] else None,
            "last_month": str(meta[5]) if meta[5] else None,
            "supplier_rows": int(meta[6] or 0), "recipient_rows": int(meta[7] or 0),
        },
        "entity": entities, "year": years, "payer_year": payer_years,
    }
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str, allow_nan=False), encoding="utf-8")
    return payload


def main() -> None:
    p = argparse.ArgumentParser(description="Exporta agregados universales de fondos públicos para ATLAS")
    p.add_argument("--parquet", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--snapshot-id", required=True)
    args = p.parse_args()
    payload = build_public_funds_export(args.parquet, args.output, args.snapshot_id)
    print(json.dumps({"schema":payload["schema"],"snapshot_id":payload["snapshot_id"],
                      "coverage":payload["coverage"],"entity":len(payload["entity"]),
                      "year":len(payload["year"]),"payer_year":len(payload["payer_year"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
