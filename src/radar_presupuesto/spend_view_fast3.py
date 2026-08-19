from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import duckdb
import pandas as pd

from .ids import normalize_rut, provider_id
from . import spend_view as _spend

_ORIGINAL_RECORDS = _spend._records
_TRUE = "('1','TRUE','T','SI','SÍ','YES','Y')"


def _records_compatible(con, sql: str, params=None):
    """Evita el LEFT JOIN correlacionado que algunas versiones de DuckDB rechazan."""
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
               count(*) FILTER (WHERE l.organization_id IS NOT NULL) AS transactions
        FROM calendar c
        LEFT JOIN l12 l ON l.month_date = c.month_date
        GROUP BY c.i, c.month_date
        ORDER BY c.i
        """
    return _ORIGINAL_RECORDS(con, sql, params)


def _clean(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        if c not in out:
            out[c] = ""
        out[c] = out[c].fillna("").astype(str)
    return out


def _service_id(partida: object, capitulo: object, name: object = "") -> str:
    p = str(partida or "").strip().zfill(2)
    c = str(capitulo or "").strip().zfill(2)
    if p.strip("0") or c.strip("0"):
        return f"ORG-PA-{p}-{c}"
    h = hashlib.sha256(str(name or "").strip().upper().encode("utf-8")).hexdigest()[:18].upper()
    return f"ORG-PA-{h}"


def materialize_light_facts_v3(raw_paths: list[str], output: str) -> dict:
    """Materializa hechos de UI con semántica oficial y flags de fuente.

    - `organization_id` usa Partida+Capítulo: Capítulo es el servicio/organismo.
    - `is_provider_source` conserva PROVEEDOR tal como viene del bulk.
    - `is_provider` es el universo analítico inicial: PROVEEDOR=1 e INTRAESTADO=0.
    - El RUT se normaliza para TODO beneficiario/receptor, no sólo PROVEEDOR=1,
      porque la vista oficial Proveedor/Receptor también incluye otros receptores.
    - `provider_id` sólo se habilita para contrapartes que aparecen con PROVEEDOR=1.
    - `is_aggregated` conserva AGREGADO para la cuadratura con instituciones
      transaccionales de Presupuesto Abierto.
    """
    if not raw_paths:
        raise ValueError("raw_paths no puede estar vacío")
    for path in raw_paths:
        if not Path(path).exists():
            raise FileNotFoundError(path)

    con = duckdb.connect()
    paths_sql = "[" + ",".join("'" + p.replace("'", "''") + "'" for p in raw_paths) + "]"
    con.execute(f"""
        CREATE OR REPLACE VIEW raw_spend AS
        SELECT * FROM read_csv(
          {paths_sql}, delim='\\t', header=true, auto_detect=true,
          all_varchar=true, union_by_name=true, ignore_errors=true
        )
    """)

    svc_cols = ["partida", "capitulo", "nombre_capitulo"]
    svc = _clean(con.execute(
        "SELECT DISTINCT partida,capitulo,nombre_capitulo FROM raw_spend"
    ).df(), svc_cols)
    svc["organization_id"] = [
        _service_id(r.partida, r.capitulo, r.nombre_capitulo)
        for r in svc.itertuples(index=False)
    ]
    con.register("svc_map_df", svc)
    con.execute("CREATE OR REPLACE TEMP TABLE svc_map AS SELECT * FROM svc_map_df")

    # Mapa universal de beneficiarios/receptores. La marca source_provider_any
    # permite mantener provider_id restringido al universo PROVEEDOR de la fuente,
    # pero rut_beneficiario queda disponible también para otros receptores.
    prov_cols = ["beneficiario", "nombre_beneficiario", "partida", "capitulo", "nombre_capitulo"]
    prov = _clean(con.execute(f"""
        SELECT beneficiario,nombre_beneficiario,partida,capitulo,nombre_capitulo,
               max(CASE WHEN upper(trim(coalesce(proveedor,''))) IN {_TRUE} THEN 1 ELSE 0 END) AS source_provider_any
        FROM raw_spend
        GROUP BY 1,2,3,4,5
    """).df(), prov_cols)
    prov["organization_id"] = [
        _service_id(r.partida, r.capitulo, r.nombre_capitulo)
        for r in prov.itertuples(index=False)
    ]
    prov["provider_id"] = [
        provider_id(raw, name, bool(flag), org)
        for raw, name, flag, org in zip(
            prov["beneficiario"], prov["nombre_beneficiario"],
            prov["source_provider_any"], prov["organization_id"]
        )
    ]
    rut_by_raw = {raw: normalize_rut(raw) for raw in prov["beneficiario"].drop_duplicates()}
    prov["rut_beneficiario"] = prov["beneficiario"].map(rut_by_raw).fillna("")
    con.register("provider_map_df", prov)
    con.execute("CREATE OR REPLACE TEMP TABLE provider_map AS SELECT * FROM provider_map_df")

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    q = str(out).replace("'", "''")
    con.execute(f"""
        COPY (
          SELECT
            try_cast(r.periodo AS INTEGER) AS periodo,
            try_cast(r.mes AS INTEGER) AS mes,
            try_cast(r.devengo AS DOUBLE) AS monto_devengado,
            try_cast(r.monto AS DOUBLE) AS monto_pago,
            coalesce(r.fecha_pago,'') AS fecha_pago,
            upper(trim(coalesce(r.proveedor,''))) IN {_TRUE} AS is_provider_source,
            (
              upper(trim(coalesce(r.proveedor,''))) IN {_TRUE}
              AND NOT (upper(trim(coalesce(r.intraestado,''))) IN {_TRUE})
            ) AS is_provider,
            upper(trim(coalesce(r.intraestado,''))) IN {_TRUE} AS is_intra_state,
            upper(trim(coalesce(r.agregado,''))) IN {_TRUE} AS is_aggregated,
            coalesce(pm.provider_id,'') AS provider_id,
            coalesce(r.beneficiario,'') AS beneficiario_source_id,
            '' AS transaction_id,
            sm.organization_id,
            coalesce(r.partida,'') AS partida,
            coalesce(r.capitulo,'') AS capitulo,
            coalesce(r.area,'') AS area,
            coalesce(r.nombre_capitulo,'') AS nombre_area,
            coalesce(r.nombre_capitulo,'') AS nombre_capitulo,
            coalesce(r.nombre_area,'') AS area_name,
            coalesce(r.nombre_partida,'') AS nombre_partida,
            coalesce(r.region,'') AS region,
            coalesce(r.nombre_subtitulo,'') AS nombre_subtitulo,
            coalesce(r.subtitulo,'') AS subtitulo,
            coalesce(r.nombre_beneficiario,'') AS nombre_beneficiario,
            coalesce(pm.rut_beneficiario,'') AS rut_beneficiario,
            coalesce(r.orden_de_compra,'') AS orden_compra
          FROM raw_spend r
          JOIN svc_map sm
            ON coalesce(r.partida,'')=sm.partida
           AND coalesce(r.capitulo,'')=sm.capitulo
           AND coalesce(r.nombre_capitulo,'')=sm.nombre_capitulo
          LEFT JOIN provider_map pm
            ON coalesce(r.beneficiario,'')=pm.beneficiario
           AND coalesce(r.nombre_beneficiario,'')=pm.nombre_beneficiario
           AND sm.organization_id=pm.organization_id
          WHERE try_cast(r.periodo AS INTEGER) IS NOT NULL
            AND try_cast(r.mes AS INTEGER) BETWEEN 1 AND 12
        ) TO '{q}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    meta = con.execute(f"""
      SELECT count(*) AS row_count,
             count(DISTINCT organization_id) AS service_count,
             count(DISTINCT concat(partida,'|',capitulo,'|',area)) AS area_count,
             count(DISTINCT provider_id) FILTER (WHERE is_provider AND provider_id<>'') AS provider_count,
             count(DISTINCT provider_id) FILTER (WHERE is_provider_source AND provider_id<>'') AS source_provider_count,
             count(DISTINCT rut_beneficiario) FILTER (WHERE rut_beneficiario<>'') AS recipient_rut_count,
             max(make_date(periodo,mes,1)) FILTER (WHERE coalesce(monto_devengado,0)<>0) AS latest_devengo_month
      FROM read_parquet('{q}')
    """).fetchone()
    con.close()
    return {
        "path": str(out), "rows": int(meta[0]), "services": int(meta[1]),
        "areas": int(meta[2]), "providers": int(meta[3]), "source_providers": int(meta[4]),
        "recipient_ruts": int(meta[5]),
        "latest_devengo_month": str(meta[6]) if meta[6] else None,
        "organization_grain": "PARTIDA_CAPITULO",
    }


def build_fast_spend_view_v3(raw_paths: list[str], output: str = "docs/data/spend_view_v2.json") -> dict:
    light = "data/processed/spend_view_light.parquet"
    meta = materialize_light_facts_v3(raw_paths, light)
    _spend._records = _records_compatible
    try:
        payload = _spend.build_spend_view_v2(
            light, output=output, prioritized_path=None,
            service_limit=400, provider_limit=1500, flow_limit=5000, flows_per_service=6,
        )
    finally:
        _spend._records = _ORIGINAL_RECORDS
    payload.setdefault("source", {}).update({
        "ui_staging": "LIGHT_CANONICAL_FACT_V3",
        "ui_staging_rows": meta["rows"],
        "source_services": meta["services"],
        "source_areas": meta["areas"],
        "source_provider_ids": meta["source_providers"],
        "analytic_provider_ids_pre_name_filter": meta["providers"],
        "recipient_ruts_normalized": meta["recipient_ruts"],
        "organization_grain": "PARTIDA_CAPITULO",
        "area_grain_preserved": True,
        "payment_fields_preserved": True,
        "recipient_rut_scope": "ALL_BENEFICIARIES_AND_RECIPIENTS",
        "source_flags_preserved": ["PROVEEDOR", "INTRAESTADO", "AGREGADO"],
        "provider_base_rule": "PROVEEDOR_SOURCE_TRUE_AND_NOT_INTRAESTADO",
        "calendar_join_compat": "DUCKDB_NON_CORRELATED_V3",
        "ui_note": "Servicio se modela a nivel Partida+Capítulo; Área queda como detalle. Pago y devengo están separados. RUT se normaliza para todo receptor; proveedor AML excluye INTRAESTADO.",
    })
    return payload


def main() -> None:
    p = argparse.ArgumentParser(description="Corrected fast Spend View builder v3")
    p.add_argument("raw_paths", nargs="+")
    p.add_argument("--output", default="docs/data/spend_view_v2.json")
    args = p.parse_args()
    payload = build_fast_spend_view_v3(args.raw_paths, args.output)
    print("[OK] ventana", payload.get("window"))
    print("[OK] publicados", payload.get("published"))
    print("[OK] source", payload.get("source"))


if __name__ == "__main__":
    main()
