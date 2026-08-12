from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb


def audit_quality(parquet_glob: str, output: str = "docs/data/quality.json") -> dict:
    con = duckdb.connect()
    con.execute(
        f"CREATE OR REPLACE VIEW facts AS "
        f"SELECT * FROM read_parquet('{parquet_glob}', union_by_name=true)"
    )
    row = con.execute(
        """
        SELECT
          count(*) AS row_count,
          count(DISTINCT transaction_id) AS distinct_transaction_ids,
          count(DISTINCT transaction_fingerprint) AS distinct_transaction_fingerprints,
          count(*) FILTER (
            WHERE periodo IS NULL OR mes IS NULL OR mes NOT BETWEEN 1 AND 12
          ) AS invalid_period_rows,
          count(*) FILTER (WHERE coalesce(rut_beneficiario,'') <> '') AS rut_rows,
          count(*) FILTER (WHERE beneficiario_id_type='HASH_SHA1') AS hashed_identity_rows,
          count(*) FILTER (WHERE is_provider=TRUE) AS provider_rows,
          count(*) FILTER (WHERE is_person=TRUE) AS person_rows,
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
    m = dict(zip(cols, row))
    total = int(m["row_count"] or 0)

    def pct(key: str) -> float:
        return round(int(m[key] or 0) / total, 6) if total else 0.0

    coverage = {
        "valid_rut": pct("rut_rows"),
        "hashed_source_identity": pct("hashed_identity_rows"),
        "provider_flag": pct("provider_rows"),
        "person_flag": pct("person_rows"),
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
    transaction_id_collision_ratio = (
        1 - (int(m["distinct_transaction_ids"] or 0) / total) if total else 0.0
    )
    fingerprint_repeat_ratio = (
        1 - (int(m["distinct_transaction_fingerprints"] or 0) / total)
        if total
        else 0.0
    )
    repeated_fingerprint_rows = max(
        0, total - int(m["distinct_transaction_fingerprints"] or 0)
    )

    warnings: list[str] = []
    if not total:
        warnings.append("EMPTY_DATASET")
    if total and coverage["monto_devengado"] < 0.50:
        warnings.append("LOW_DEVENGADO_COVERAGE")
    if transaction_id_collision_ratio > 0:
        warnings.append("TRANSACTION_ID_NOT_UNIQUE")
    if int(m["invalid_period_rows"] or 0) > 0:
        warnings.append("INVALID_PERIOD_ROWS")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "PASS" if not warnings else "WARN",
        "rows": total,
        "distinct_transaction_ids": int(m["distinct_transaction_ids"] or 0),
        "transaction_id_collision_ratio": round(transaction_id_collision_ratio, 8),
        "duplicate_transaction_id_ratio": round(transaction_id_collision_ratio, 8),
        "distinct_transaction_fingerprints": int(
            m["distinct_transaction_fingerprints"] or 0
        ),
        "repeated_fingerprint_rows": repeated_fingerprint_rows,
        "source_fact_repeat_ratio": round(fingerprint_repeat_ratio, 8),
        "invalid_period_rows": int(m["invalid_period_rows"] or 0),
        "negative_devengado_rows": int(m["negative_devengado_rows"] or 0),
        "first_year": None if m["first_year"] is None else int(m["first_year"]),
        "last_year": None if m["last_year"] is None else int(m["last_year"]),
        "devengado_total": float(m["devengado_total"] or 0),
        "coverage": coverage,
        "warnings": warnings,
        "interpretation": (
            "transaction_id identifica una fila física única del bulk; "
            "transaction_fingerprint identifica el mismo hecho documental/económico y "
            "puede repetirse legítimamente o constituir un candidato de duplicidad. "
            "RUT válido se informa solo tras validar dígito verificador. "
            "Identidades HASH_SHA1 se conservan como claves pseudónimas de fuente."
        ),
    }
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    con.close()
    return payload
