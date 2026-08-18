from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

from .ids import normalize_rut, organization_id, provider_id
from .spend_view import build_spend_view_v2


def _clean_frame(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        if c not in out:
            out[c] = ""
        out[c] = out[c].fillna("").astype(str)
    return out


def materialize_light_facts(raw_paths: list[str], output: str) -> dict:
    """Build the minimal normalized fact surface needed by Spend View v2.

    This deliberately reuses the canonical ID helpers from the radar while
    skipping transaction fingerprints, documentary dates and other fields that
    are irrelevant to the L12 visualization. The resulting parquet is an
    internal UI staging artifact, not a replacement for NORMALIZED_FACT.
    """
    if not raw_paths:
        raise ValueError("raw_paths no puede estar vacío")
    for path in raw_paths:
        if not Path(path).exists():
            raise FileNotFoundError(path)

    con = duckdb.connect()
    paths_sql = "[" + ",".join("'" + p.replace("'", "''") + "'" for p in raw_paths) + "]"
    con.execute(
        f"""
        CREATE OR REPLACE VIEW raw_spend AS
        SELECT * FROM read_csv(
          {paths_sql},
          delim='\t', header=true, auto_detect=true,
          all_varchar=true, union_by_name=true,
          ignore_errors=true
        )
        """
    )

    org_cols = ["partida", "capitulo", "area", "nombre_area"]
    orgs = _clean_frame(
        con.execute(
            "SELECT DISTINCT partida,capitulo,area,nombre_area FROM raw_spend"
        ).df(),
        org_cols,
    )
    orgs["organization_id"] = [
        organization_id(r.partida, r.capitulo, r.area, r.nombre_area)
        for r in orgs.itertuples(index=False)
    ]
    con.register("org_map_df", orgs)
    con.execute("CREATE OR REPLACE TEMP TABLE org_map AS SELECT * FROM org_map_df")

    provider_cols = [
        "beneficiario", "nombre_beneficiario", "partida", "capitulo", "area", "nombre_area"
    ]
    prov = _clean_frame(
        con.execute(
            """
            SELECT DISTINCT beneficiario,nombre_beneficiario,partida,capitulo,area,nombre_area
            FROM raw_spend
            WHERE upper(trim(coalesce(proveedor,''))) IN ('1','TRUE','T','SI','SÍ','YES','Y')
            """
        ).df(),
        provider_cols,
    )
    prov["organization_id"] = [
        organization_id(r.partida, r.capitulo, r.area, r.nombre_area)
        for r in prov.itertuples(index=False)
    ]
    prov["provider_id"] = [
        provider_id(raw, name, True, org)
        for raw, name, org in zip(
            prov["beneficiario"], prov["nombre_beneficiario"], prov["organization_id"]
        )
    ]
    rut_by_raw = {raw: normalize_rut(raw) for raw in prov["beneficiario"].drop_duplicates()}
    prov["rut_beneficiario"] = prov["beneficiario"].map(rut_by_raw).fillna("")
    con.register("provider_map_df", prov)
    con.execute("CREATE OR REPLACE TEMP TABLE provider_map AS SELECT * FROM provider_map_df")

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out_sql = str(out).replace("'", "''")
    con.execute(
        f"""
        COPY (
          SELECT
            try_cast(r.periodo AS INTEGER) AS periodo,
            try_cast(r.mes AS INTEGER) AS mes,
            try_cast(r.devengo AS DOUBLE) AS monto_devengado,
            upper(trim(coalesce(r.proveedor,''))) IN ('1','TRUE','T','SI','SÍ','YES','Y') AS is_provider,
            coalesce(pm.provider_id,'') AS provider_id,
            '' AS transaction_id,
            om.organization_id,
            coalesce(r.nombre_area,'') AS nombre_area,
            coalesce(r.nombre_capitulo,'') AS nombre_capitulo,
            coalesce(r.nombre_partida,'') AS nombre_partida,
            coalesce(r.region,'') AS region,
            coalesce(r.nombre_subtitulo,'') AS nombre_subtitulo,
            coalesce(r.subtitulo,'') AS subtitulo,
            coalesce(r.nombre_beneficiario,'') AS nombre_beneficiario,
            coalesce(pm.rut_beneficiario,'') AS rut_beneficiario,
            coalesce(r.orden_de_compra,'') AS orden_compra
          FROM raw_spend r
          JOIN org_map om
            ON coalesce(r.partida,'')=om.partida
           AND coalesce(r.capitulo,'')=om.capitulo
           AND coalesce(r.area,'')=om.area
           AND coalesce(r.nombre_area,'')=om.nombre_area
          LEFT JOIN provider_map pm
            ON coalesce(r.beneficiario,'')=pm.beneficiario
           AND coalesce(r.nombre_beneficiario,'')=pm.nombre_beneficiario
           AND om.organization_id=pm.organization_id
          WHERE try_cast(r.periodo AS INTEGER) IS NOT NULL
            AND try_cast(r.mes AS INTEGER) BETWEEN 1 AND 12
        ) TO '{out_sql}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    rows = int(con.execute(f"SELECT count(*) FROM read_parquet('{out_sql}')").fetchone()[0])
    providers = int(
        con.execute(
            f"SELECT count(DISTINCT provider_id) FROM read_parquet('{out_sql}') WHERE is_provider AND provider_id<>''"
        ).fetchone()[0]
    )
    organizations = int(
        con.execute(f"SELECT count(DISTINCT organization_id) FROM read_parquet('{out_sql}')").fetchone()[0]
    )
    con.close()
    return {"path": str(out), "rows": rows, "providers": providers, "organizations": organizations}


def build_fast_spend_view(raw_paths: list[str], output: str = "docs/data/spend_view_v2.json") -> dict:
    light = "data/processed/spend_view_light.parquet"
    meta = materialize_light_facts(raw_paths, light)
    payload = build_spend_view_v2(light, output=output, prioritized_path=None)
    payload.setdefault("source", {})["ui_staging"] = "LIGHT_CANONICAL_FACT"
    payload["source"]["ui_staging_rows"] = meta["rows"]
    Path(output).write_text(
        __import__("json").dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str),
        encoding="utf-8",
    )
    return payload


def main() -> None:
    p = argparse.ArgumentParser(description="Fast real Spend View v2 builder")
    p.add_argument("raw_paths", nargs="+")
    p.add_argument("--output", default="docs/data/spend_view_v2.json")
    args = p.parse_args()
    payload = build_fast_spend_view(args.raw_paths, args.output)
    print("[OK]", payload["window"], payload["published"])


if __name__ == "__main__":
    main()
