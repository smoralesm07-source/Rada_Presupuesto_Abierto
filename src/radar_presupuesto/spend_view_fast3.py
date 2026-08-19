from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import duckdb
import pandas as pd

from .ids import normalize_rut, provider_id
from .spend_view import build_spend_view_v2


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
    """Materializa hechos de UI preservando la semántica oficial.

    - organization_id se fija a Partida+Capítulo (servicio/organismo oficial).
    - Área se conserva como dimensión de detalle, no como servicio.
    - Se preservan fecha_pago y monto_pago para no confundir devengo con pago.
    - provider_id sigue requiriendo PROVEEDOR=1; los universos comparables con la
      web oficial se calculan por separado en build_spend_years_v2.py.
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

    prov_cols = ["beneficiario", "nombre_beneficiario", "partida", "capitulo", "nombre_capitulo"]
    prov = _clean(con.execute("""
        SELECT DISTINCT beneficiario,nombre_beneficiario,partida,capitulo,nombre_capitulo
        FROM raw_spend
        WHERE upper(trim(coalesce(proveedor,''))) IN ('1','TRUE','T','SI','SÍ','YES','Y')
    """).df(), prov_cols)
    prov["organization_id"] = [
        _service_id(r.partida, r.capitulo, r.nombre_capitulo)
        for r in prov.itertuples(index=False)
    ]
    prov["provider_id"] = [
        provider_id(raw, name, True, org)
        for raw, name, org in zip(prov["beneficiario"], prov["nombre_beneficiario"], prov["organization_id"])
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
            upper(trim(coalesce(r.proveedor,''))) IN ('1','TRUE','T','SI','SÍ','YES','Y') AS is_provider,
            upper(trim(coalesce(r.intraestado,''))) IN ('1','TRUE','T','SI','SÍ','YES','Y') AS is_intra_state,
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
      SELECT count(*) rows,
             count(DISTINCT organization_id) services,
             count(DISTINCT concat(partida,'|',capitulo,'|',area)) areas,
             count(DISTINCT provider_id) FILTER (WHERE is_provider AND provider_id<>'') providers,
             max(make_date(periodo,mes,1)) FILTER (WHERE coalesce(monto_devengado,0)<>0) latest_devengo_month
      FROM read_parquet('{q}')
    """).fetchone()
    con.close()
    return {
        "path": str(out), "rows": int(meta[0]), "services": int(meta[1]),
        "areas": int(meta[2]), "providers": int(meta[3]),
        "latest_devengo_month": str(meta[4]) if meta[4] else None,
        "organization_grain": "PARTIDA_CAPITULO",
    }


def build_fast_spend_view_v3(raw_paths: list[str], output: str = "docs/data/spend_view_v2.json") -> dict:
    light = "data/processed/spend_view_light.parquet"
    meta = materialize_light_facts_v3(raw_paths, light)
    payload = build_spend_view_v2(
        light, output=output, prioritized_path=None,
        service_limit=400, provider_limit=1500, flow_limit=5000, flows_per_service=6,
    )
    payload.setdefault("source", {}).update({
        "ui_staging": "LIGHT_CANONICAL_FACT_V3",
        "ui_staging_rows": meta["rows"],
        "organization_grain": "PARTIDA_CAPITULO",
        "area_grain_preserved": True,
        "payment_fields_preserved": True,
        "ui_note": "Servicio se modela a nivel Partida+Capítulo; Área queda como detalle. Fecha y monto de pago se preservan separadamente del devengo.",
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
