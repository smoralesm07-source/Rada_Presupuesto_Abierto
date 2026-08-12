from __future__ import annotations

from pathlib import Path
import duckdb


def build_profiles(parquet_glob: str, output_dir: str = "data/processed") -> dict:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"CREATE OR REPLACE VIEW facts AS SELECT * FROM read_parquet('{parquet_glob}', union_by_name=true)")
    provider = out / "provider_profiles.parquet"
    recipient = out / "recipient_profiles.parquet"
    org = out / "organization_profiles.parquet"

    con.execute(f"""COPY (
        SELECT provider_id,
               any_value(rut_beneficiario) rut,
               any_value(beneficiario_source_id) source_identity_key,
               any_value(beneficiario_id_type) identity_key_type,
               any_value(nombre_beneficiario) nombre,
               min(make_date(cast(periodo AS INT),cast(mes AS INT),1)) first_seen,
               max(make_date(cast(periodo AS INT),cast(mes AS INT),1)) last_seen,
               count(*) transactions,
               count(DISTINCT organization_id) organizations,
               count(DISTINCT coalesce(subtitulo,'')||'-'||coalesce(item,'')) budget_categories,
               sum(try_cast(monto_devengado AS DOUBLE)) amount_devengado,
               avg(try_cast(monto_devengado AS DOUBLE)) avg_amount,
               stddev_pop(try_cast(monto_devengado AS DOUBLE)) sd_amount,
               count(DISTINCT coalesce(nombre_ubicacion_geografica,'')) geographic_destinations
        FROM facts
        WHERE is_provider = TRUE AND coalesce(provider_id,'') <> ''
        GROUP BY provider_id
    ) TO '{provider.as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)""")

    con.execute(f"""COPY (
        SELECT recipient_id,
               any_value(provider_id) provider_id,
               any_value(rut_beneficiario) rut,
               any_value(beneficiario_source_id) source_identity_key,
               any_value(beneficiario_id_type) identity_key_type,
               any_value(nombre_beneficiario) nombre,
               bool_or(is_provider) is_provider,
               bool_or(is_person) is_person,
               min(make_date(cast(periodo AS INT),cast(mes AS INT),1)) first_seen,
               max(make_date(cast(periodo AS INT),cast(mes AS INT),1)) last_seen,
               count(*) transactions,
               count(DISTINCT organization_id) organizations,
               sum(try_cast(monto_devengado AS DOUBLE)) amount_devengado
        FROM facts
        GROUP BY recipient_id
    ) TO '{recipient.as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)""")

    con.execute(f"""COPY (
        WITH supplier AS (
            SELECT organization_id,provider_id,sum(try_cast(monto_devengado AS DOUBLE)) amount
            FROM facts WHERE is_provider = TRUE AND coalesce(provider_id,'') <> '' GROUP BY 1,2
        ), st AS (SELECT organization_id,sum(amount) total FROM supplier GROUP BY 1),
        sh AS (SELECT s.organization_id,sum(power(s.amount/t.total,2)) hhi FROM supplier s JOIN st t USING(organization_id) WHERE t.total>0 GROUP BY 1),
        rec AS (
            SELECT organization_id,recipient_id,sum(try_cast(monto_devengado AS DOUBLE)) amount
            FROM facts GROUP BY 1,2
        ), rt AS (SELECT organization_id,sum(amount) total FROM rec GROUP BY 1),
        rh AS (SELECT r.organization_id,sum(power(r.amount/t.total,2)) hhi FROM rec r JOIN rt t USING(organization_id) WHERE t.total>0 GROUP BY 1)
        SELECT f.organization_id,
               any_value(f.nombre_partida) institucion,
               any_value(f.nombre_capitulo) servicio,
               any_value(f.nombre_area) area,
               count(*) transactions,
               count(DISTINCT f.recipient_id) recipients,
               count(DISTINCT f.provider_id) FILTER (WHERE f.is_provider = TRUE AND coalesce(f.provider_id,'') <> '') providers,
               sum(try_cast(f.monto_devengado AS DOUBLE)) amount_devengado,
               any_value(sh.hhi) supplier_hhi,
               any_value(rh.hhi) recipient_hhi
        FROM facts f LEFT JOIN sh USING(organization_id) LEFT JOIN rh USING(organization_id)
        GROUP BY f.organization_id
    ) TO '{org.as_posix()}' (FORMAT PARQUET,COMPRESSION ZSTD)""")
    con.close()
    return {"providers": str(provider), "recipients": str(recipient), "organizations": str(org)}
