from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb


def audit_quality(parquet_glob: str, output: str = "docs/data/quality.json") -> dict:
    con = duckdb.connect()
    con.execute(
        f"CREATE OR REPLACE VIEW facts AS SELECT * FROM read_parquet('{parquet_glob}', union_by_name=true)"
    )
    row = con.execute(
        """
        SELECT
          count(*) AS rows,
          count(DISTINCT transaction_id) AS distinct_transaction_ids,
          count(*) FILTER (WHERE periodo IS NULL OR mes IS NULL OR mes NOT BETWEEN 1 AND 12) AS invalid_period_rows,
          count(*) FILTER (WHERE coalesce(rut_beneficiario_normalizado,'') <> '') AS rut_rows,
          count(*) FILTER (WHERE coalesce(nombre_beneficiario,'') <> '') AS beneficiary_name_rows,
          count(*) FILTER (WHERE try_cast(monto_devengado AS DOUBLE) IS NOT NULL) AS devengado_rows,
          count(*) FILTER (WHERE try_cast(monto_pago AS DOUBLE) IS NOT NULL) AS pago_rows,
          count(*) FILTER (WHERE fecha_documento IS NOT NULL) AS document_date_rows,
          count(*) FILTER (WHERE fecha_pago IS NOT NULL) AS payment_date_rows,
          count(*) FILTER (WHERE coalesce(orden_compra,'') <> '') AS purchase_order_rows,
          count(*) FILTER (WHERE coalesce(codigo_bip,'') <> '') AS bip_rows,
          count(*) FILTER (WHERE coalesce(region,'') <> '') AS region_rows,
          count(*) FILTER (WHERE coalesce(sector,'') <> '') AS sector_rows,
          count(*) FILTER (WHERE try_cast(monto_devengado AS DOUBLE) < 0) AS negative_devengado_rows,
          min(periodo) AS first_year,
          max(periodo) AS last_year,
          coalesce(sum(try_cast(monto_devengado AS DOUBLE)),0) AS devengado_total
        FROM facts
        """
    ).fetchone()
    cols = [d[0] for d in con.description]
    metrics = dict(zip(cols, row))
    total = int(metrics["rows"] or 0)

    def pct(key: str) -> float:
        return round((int(metrics[key] or 0) / total), 6) if total else 0.0

    coverage = {
        "rut": pct("rut_rows"),
        "beneficiary_name": pct("beneficiary_name_rows"),
        "monto_devengado": pct("devengado_rows"),
        "monto_pago": pct("pago_rows"),
        "fecha_documento": pct("document_date_rows"),
        "fecha_pago": pct("payment_date_rows"),
        "orden_compra": pct("purchase_order_rows"),
        "bip": pct("bip_rows"),
        "region": pct("region_rows"),
        "sector": pct("sector_rows"),
    }
    warnings: list[str] = []
    if total == 0:
        warnings.append("EMPTY_DATASET")
    if total and coverage["monto_devengado"] < 0.50:
        warnings.append("LOW_DEVENGADO_COVERAGE")
    duplicate_ratio = (
        1 - (int(metrics["distinct_transaction_ids"] or 0) / total)
        if total
        else 0.0
    )
    if duplicate_ratio > 0.01:
        warnings.append("TRANSACTION_ID_COLLISIONS_GT_1PCT")
    if int(metrics["invalid_period_rows"] or 0) > 0:
        warnings.append("INVALID_PERIOD_ROWS")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "PASS" if not warnings else "WARN",
        "rows": total,
        "distinct_transaction_ids": int(metrics["distinct_transaction_ids"] or 0),
        "duplicate_transaction_id_ratio": round(duplicate_ratio, 8),
        "invalid_period_rows": int(metrics["invalid_period_rows"] or 0),
        "negative_devengado_rows": int(metrics["negative_devengado_rows"] or 0),
        "first_year": None if metrics["first_year"] is None else int(metrics["first_year"]),
        "last_year": None if metrics["last_year"] is None else int(metrics["last_year"]),
        "devengado_total": float(metrics["devengado_total"] or 0),
        "coverage": coverage,
        "warnings": warnings,
        "interpretation": "Coberturas describen disponibilidad del dato, no calidad institucional ni riesgo. Valores negativos pueden corresponder a ajustes contables y no se tratan como error automático.",
    }
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    con.close()
    return payload
