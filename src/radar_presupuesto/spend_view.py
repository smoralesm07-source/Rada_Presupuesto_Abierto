from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

SCHEMA = "PRESUPUESTO_SPEND_VIEW_V2"


def _records(con: duckdb.DuckDBPyConnection, sql: str, params=None):
    df = con.execute(sql, params or []).df()
    if df.empty:
        return []
    return df.where(df.notna(), None).to_dict("records")


def build_spend_view_v2(
    parquet_glob: str,
    output: str = "docs/data/spend_view_v2.json",
    prioritized_path: str | None = "data/signals/prioritized_signals.parquet",
    service_limit: int = 2000,
    provider_limit: int = 1500,
    flow_limit: int = 12000,
    flows_per_service: int = 8,
) -> dict:
    """Materializa agregados UI de gasto real para el módulo de flujos.

    La ventana L12 es fija y termina en el último mes disponible en los hechos.
    No publica hechos transaccionales individuales; sólo agregados suficientes
    para interacción Servicio Público -> Proveedor, magnitud, concentración y
    temporalidad.
    """
    con = duckdb.connect()
    con.execute(
        f"CREATE OR REPLACE VIEW facts AS "
        f"SELECT *, make_date(try_cast(periodo AS INTEGER), try_cast(mes AS INTEGER), 1) AS month_date, "
        f"       coalesce(try_cast(monto_devengado AS DOUBLE),0.0) AS amount "
        f"FROM read_parquet('{parquet_glob}', union_by_name=true) "
        f"WHERE try_cast(periodo AS INTEGER) IS NOT NULL AND try_cast(mes AS INTEGER) BETWEEN 1 AND 12"
    )
    latest = con.execute("SELECT max(month_date) FROM facts WHERE amount<>0").fetchone()[0]
    if latest is None:
        raise RuntimeError("No hay meses con monto_devengado en los hechos normalizados")

    con.execute("CREATE OR REPLACE TEMP TABLE bounds AS SELECT ?::DATE AS end_month, (?::DATE - INTERVAL '11 months')::DATE AS start_month, (?::DATE - INTERVAL '23 months')::DATE AS prev_start, (?::DATE - INTERVAL '12 months')::DATE AS prev_end", [latest, latest, latest, latest])
    con.execute("CREATE OR REPLACE VIEW l12 AS SELECT * FROM facts, bounds WHERE month_date BETWEEN start_month AND end_month")
    con.execute("CREATE OR REPLACE VIEW prev12 AS SELECT * FROM facts, bounds WHERE month_date BETWEEN prev_start AND prev_end")

    # Display names preserve source nomenclature and avoid inventing institution RUTs.
    name_expr = "coalesce(nullif(trim(nombre_area),''), nullif(trim(nombre_capitulo),''), nullif(trim(nombre_partida),''), organization_id)"
    provider_name_expr = "coalesce(nullif(trim(nombre_beneficiario),''), provider_id)"

    months = _records(con, """
        SELECT strftime(b.start_month + i * INTERVAL '1 month','%Y-%m') AS period,
               coalesce(sum(l.amount),0) AS amount_clp,
               coalesce(sum(l.amount) FILTER (WHERE l.is_provider=TRUE AND coalesce(l.provider_id,'')<>''),0) AS provider_amount_clp,
               count(l.transaction_id) AS transactions
        FROM bounds b, range(12) t(i)
        LEFT JOIN l12 l ON l.month_date = (b.start_month + i * INTERVAL '1 month')::DATE
        GROUP BY 1, i ORDER BY i
    """)

    overview = con.execute("""
        SELECT coalesce(sum(amount),0), count(*), count(DISTINCT organization_id),
               count(DISTINCT provider_id) FILTER (WHERE is_provider=TRUE AND coalesce(provider_id,'')<>''),
               coalesce(sum(amount) FILTER (WHERE is_provider=TRUE AND coalesce(provider_id,'')<>''),0)
        FROM l12
    """).fetchone()
    prev_total = con.execute("SELECT coalesce(sum(amount),0) FROM prev12").fetchone()[0]

    start_month, end_month = con.execute("SELECT start_month,end_month FROM bounds").fetchone()

    # Top services by all devengado in the rolling 12-month window.
    service_base = _records(con, f"""
        WITH cur AS (
          SELECT organization_id,
                 arg_max({name_expr}, abs(amount)) AS organization_name,
                 arg_max(nullif(trim(region),''), abs(amount)) AS main_region,
                 sum(amount) AS amount_l12,
                 count(*) AS transactions_l12,
                 count(DISTINCT provider_id) FILTER (WHERE is_provider=TRUE AND coalesce(provider_id,'')<>'') AS providers_l12,
                 sum(amount) FILTER (WHERE is_provider=TRUE AND coalesce(provider_id,'')<>'') AS provider_amount_l12,
                 sum(amount) FILTER (WHERE month(month_date) IN (10,11,12)) AS q4_amount
          FROM l12 GROUP BY 1
        ), prev AS (
          SELECT organization_id, sum(amount) AS amount_prev12 FROM prev12 GROUP BY 1
        ), subtitle AS (
          SELECT organization_id, arg_max(coalesce(nullif(trim(nombre_subtitulo),''), subtitulo), amount_sum) AS dominant_subtitle
          FROM (SELECT organization_id, nombre_subtitulo, subtitulo, sum(amount) amount_sum FROM l12 GROUP BY 1,2,3)
          GROUP BY 1
        )
        SELECT c.*, p.amount_prev12, s.dominant_subtitle,
               CASE WHEN p.amount_prev12 IS NULL OR p.amount_prev12=0 THEN NULL ELSE c.amount_l12/p.amount_prev12-1 END AS variation_l12,
               CASE WHEN c.amount_l12=0 THEN NULL ELSE c.q4_amount/c.amount_l12 END AS q4_share
        FROM cur c LEFT JOIN prev p USING(organization_id) LEFT JOIN subtitle s USING(organization_id)
        ORDER BY c.amount_l12 DESC LIMIT {int(service_limit)}
    """)
    service_ids = [r["organization_id"] for r in service_base]
    if not service_ids:
        raise RuntimeError("No se obtuvieron servicios para la vista L12")
    placeholders = ",".join("?" for _ in service_ids)

    service_months = _records(con, f"""
        SELECT organization_id, strftime(month_date,'%Y-%m') AS period, sum(amount) AS amount_clp,
               sum(amount) FILTER (WHERE is_provider=TRUE AND coalesce(provider_id,'')<>'') AS provider_amount_clp
        FROM l12 WHERE organization_id IN ({placeholders}) GROUP BY 1,2 ORDER BY 1,2
    """, service_ids)

    flow_rows = _records(con, f"""
        WITH pairs AS (
          SELECT organization_id, provider_id,
                 arg_max({name_expr}, abs(amount)) AS organization_name,
                 arg_max({provider_name_expr}, abs(amount)) AS provider_name,
                 arg_max(nullif(trim(rut_beneficiario),''), abs(amount)) AS rut,
                 sum(amount) AS amount_clp, count(*) AS transactions,
                 count(DISTINCT month_date) AS months_active, max(month_date) AS last_month
          FROM l12
          WHERE is_provider=TRUE AND coalesce(provider_id,'')<>''
          GROUP BY 1,2
        ), svc AS (
          SELECT organization_id, sum(amount_clp) AS service_provider_amount FROM pairs GROUP BY 1
        ), prv AS (
          SELECT provider_id, sum(amount_clp) AS provider_amount FROM pairs GROUP BY 1
        ), enriched AS (
          SELECT p.*, s.service_provider_amount, v.provider_amount,
                 CASE WHEN s.service_provider_amount=0 THEN NULL ELSE p.amount_clp/s.service_provider_amount END AS share_of_service,
                 CASE WHEN v.provider_amount=0 THEN NULL ELSE p.amount_clp/v.provider_amount END AS share_of_provider,
                 row_number() OVER (PARTITION BY p.organization_id ORDER BY p.amount_clp DESC) AS service_rank
          FROM pairs p JOIN svc s USING(organization_id) JOIN prv v USING(provider_id)
          WHERE p.organization_id IN ({placeholders})
        )
        SELECT * EXCLUDE(service_rank) FROM enriched
        WHERE service_rank <= {int(flows_per_service)}
        ORDER BY amount_clp DESC LIMIT {int(flow_limit)}
    """, service_ids)

    # Monthly detail for the published flow edges enables reversible month filtering in the UI.
    flow_keys = {(r["organization_id"], r["provider_id"]) for r in flow_rows}
    flow_month_rows = _records(con, f"""
        SELECT organization_id, provider_id, strftime(month_date,'%Y-%m') AS period, sum(amount) AS amount_clp, count(*) AS transactions
        FROM l12
        WHERE is_provider=TRUE AND coalesce(provider_id,'')<>'' AND organization_id IN ({placeholders})
        GROUP BY 1,2,3 ORDER BY 1,2,3
    """, service_ids)
    fm: dict[tuple[str,str], list[dict]] = {}
    for r in flow_month_rows:
        key = (r["organization_id"], r["provider_id"])
        if key in flow_keys:
            fm.setdefault(key, []).append({"period": r["period"], "amount_clp": r["amount_clp"], "transactions": r["transactions"]})
    for r in flow_rows:
        r["monthly"] = fm.get((r["organization_id"], r["provider_id"]), [])

    # Provider profiles from the same L12 window, independently of the top-service cut.
    provider_base = _records(con, f"""
        WITH cur AS (
          SELECT provider_id,
                 arg_max({provider_name_expr}, abs(amount)) AS provider_name,
                 arg_max(nullif(trim(rut_beneficiario),''), abs(amount)) AS rut,
                 sum(amount) AS amount_l12, count(*) AS transactions_l12,
                 count(DISTINCT organization_id) AS organizations_l12,
                 count(DISTINCT month_date) AS months_active,
                 sum(amount) FILTER (WHERE month(month_date) IN (10,11,12)) AS q4_amount,
                 avg(CASE WHEN coalesce(trim(orden_compra),'')='' THEN 1.0 ELSE 0.0 END) AS missing_oc_share
          FROM l12 WHERE is_provider=TRUE AND coalesce(provider_id,'')<>'' GROUP BY 1
        ), prev AS (
          SELECT provider_id, sum(amount) AS amount_prev12 FROM prev12
          WHERE is_provider=TRUE AND coalesce(provider_id,'')<>'' GROUP BY 1
        ), firstseen AS (
          SELECT provider_id, min(month_date) AS first_seen FROM facts
          WHERE is_provider=TRUE AND coalesce(provider_id,'')<>'' GROUP BY 1
        ), pair AS (
          SELECT provider_id, organization_id, arg_max({name_expr}, abs(amount)) AS organization_name, sum(amount) AS pair_amount
          FROM l12 WHERE is_provider=TRUE AND coalesce(provider_id,'')<>'' GROUP BY 1,2
        ), topbuyer AS (
          SELECT provider_id, arg_max(organization_id,pair_amount) AS top_client_id,
                 arg_max(organization_name,pair_amount) AS top_client_name, max(pair_amount) AS top_client_amount
          FROM pair GROUP BY 1
        )
        SELECT c.*, p.amount_prev12, f.first_seen, t.top_client_id, t.top_client_name, t.top_client_amount,
               CASE WHEN p.amount_prev12 IS NULL OR p.amount_prev12=0 THEN NULL ELSE c.amount_l12/p.amount_prev12-1 END AS variation_l12,
               CASE WHEN c.amount_l12=0 THEN NULL ELSE c.q4_amount/c.amount_l12 END AS q4_share,
               CASE WHEN c.amount_l12=0 THEN NULL ELSE t.top_client_amount/c.amount_l12 END AS dependence_top_client
        FROM cur c LEFT JOIN prev p USING(provider_id) LEFT JOIN firstseen f USING(provider_id) LEFT JOIN topbuyer t USING(provider_id)
        ORDER BY c.amount_l12 DESC LIMIT {int(provider_limit)}
    """)
    provider_ids = [r["provider_id"] for r in provider_base]
    pp = ",".join("?" for _ in provider_ids) if provider_ids else "''"
    provider_months = _records(con, f"""
        SELECT provider_id, strftime(month_date,'%Y-%m') AS period, sum(amount) AS amount_clp
        FROM l12 WHERE is_provider=TRUE AND provider_id IN ({pp}) GROUP BY 1,2 ORDER BY 1,2
    """, provider_ids) if provider_ids else []

    # Concentration metrics over all provider flows in L12.
    concentration = con.execute("""
        WITH p AS (
          SELECT provider_id, sum(amount) a FROM l12
          WHERE is_provider=TRUE AND coalesce(provider_id,'')<>'' GROUP BY 1
        ), r AS (
          SELECT a, row_number() OVER (ORDER BY a DESC) rn, sum(a) OVER() total FROM p
        )
        SELECT coalesce(sum(a) FILTER (WHERE rn<=10)/max(total),0),
               coalesce(sum(power(a/nullif(total,0),2)),0), max(total)
        FROM r
    """).fetchone()

    # Top-provider and HHI inside each published service.
    svc_provider_stats = _records(con, f"""
        WITH p AS (
          SELECT organization_id, provider_id, arg_max({provider_name_expr}, abs(amount)) provider_name, sum(amount) a
          FROM l12 WHERE is_provider=TRUE AND coalesce(provider_id,'')<>'' AND organization_id IN ({placeholders})
          GROUP BY 1,2
        ), x AS (
          SELECT *, sum(a) OVER(PARTITION BY organization_id) total,
                 row_number() OVER(PARTITION BY organization_id ORDER BY a DESC) rn
          FROM p
        )
        SELECT organization_id,
               max(provider_id) FILTER (WHERE rn=1) AS top_provider_id,
               max(provider_name) FILTER (WHERE rn=1) AS top_provider_name,
               max(CASE WHEN rn=1 AND total<>0 THEN a/total END) AS top_provider_share,
               sum(power(a/nullif(total,0),2)) AS provider_hhi
        FROM x GROUP BY 1
    """, service_ids)

    # Optional analytic priority counts; they remain signals, not findings.
    signal_by_service: dict[str, dict] = {}
    signal_by_provider: dict[str, dict] = {}
    if prioritized_path and Path(prioritized_path).exists():
        con.execute(f"CREATE OR REPLACE VIEW pri AS SELECT * FROM read_parquet('{prioritized_path}')")
        ss = _records(con, """
            SELECT organization_id, count(*) signal_count,
                   count(*) FILTER (WHERE priority_tier='P1') p1_count,
                   max(investigation_priority_score) max_priority_score
            FROM pri, bounds
            WHERE make_date(try_cast(periodo AS INTEGER), coalesce(try_cast(mes AS INTEGER),1), 1) BETWEEN start_month AND end_month
            GROUP BY 1
        """)
        sp = _records(con, """
            SELECT provider_id, count(*) signal_count,
                   count(*) FILTER (WHERE priority_tier='P1') p1_count,
                   max(investigation_priority_score) max_priority_score
            FROM pri, bounds
            WHERE coalesce(provider_id,'')<>'' AND make_date(try_cast(periodo AS INTEGER), coalesce(try_cast(mes AS INTEGER),1), 1) BETWEEN start_month AND end_month
            GROUP BY 1
        """)
        signal_by_service = {r["organization_id"]: r for r in ss}
        signal_by_provider = {r["provider_id"]: r for r in sp}

    smap: dict[str, list] = {}
    for r in service_months:
        smap.setdefault(r["organization_id"], []).append({"period": r["period"], "amount_clp": r["amount_clp"], "provider_amount_clp": r["provider_amount_clp"]})
    pmap: dict[str, list] = {}
    for r in provider_months:
        pmap.setdefault(r["provider_id"], []).append({"period": r["period"], "amount_clp": r["amount_clp"]})
    spmap = {r["organization_id"]: r for r in svc_provider_stats}

    for s in service_base:
        s["monthly"] = smap.get(s["organization_id"], [])
        s.update({k:v for k,v in spmap.get(s["organization_id"], {}).items() if k != "organization_id"})
        sig = signal_by_service.get(s["organization_id"], {})
        s["signal_count"] = int(sig.get("signal_count") or 0)
        s["p1_count"] = int(sig.get("p1_count") or 0)
        s["max_priority_score"] = sig.get("max_priority_score")

    for p in provider_base:
        p["monthly"] = pmap.get(p["provider_id"], [])
        sig = signal_by_provider.get(p["provider_id"], {})
        p["signal_count"] = int(sig.get("signal_count") or 0)
        p["p1_count"] = int(sig.get("p1_count") or 0)
        p["max_priority_score"] = sig.get("max_priority_score")

    payload = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "REAL",
        "source": {
            "system": "PRESUPUESTO_ABIERTO",
            "publisher": "DIPRES",
            "record_class": "AGGREGATED_FROM_NORMALIZED_FACT",
            "note": "Agregados UI derivados de hechos normalizados; no modifica la fuente ni reinterpreta señales como hallazgos."
        },
        "window": {
            "start_month": str(start_month),
            "end_month": str(end_month),
            "months": [m["period"] for m in months],
            "label": "últimos 12 meses disponibles"
        },
        "overview": {
            "amount_l12_clp": float(overview[0] or 0),
            "transactions_l12": int(overview[1] or 0),
            "organizations_l12": int(overview[2] or 0),
            "providers_l12": int(overview[3] or 0),
            "provider_amount_l12_clp": float(overview[4] or 0),
            "amount_prev12_clp": float(prev_total or 0),
            "variation_l12": None if not prev_total else float(overview[0] / prev_total - 1),
            "top10_provider_share": float(concentration[0] or 0),
            "provider_hhi": float(concentration[1] or 0),
        },
        "monthly": months,
        "services": service_base,
        "providers": provider_base,
        "flows": flow_rows,
        "published": {
            "services": len(service_base),
            "providers": len(provider_base),
            "flows": len(flow_rows),
            "flows_per_service_cap": int(flows_per_service),
        },
        "guardrails": [
            "Magnitud de gasto mide exposición, no irregularidad.",
            "Dependencia e influencia son relaciones económicas observadas dentro de la fuente, no vínculos societarios.",
            "Las señales P1/P2/P3 sólo priorizan revisión y no constituyen hallazgos ni probabilidad de delito.",
            "La ventana L12 termina en el último mes disponible de la fuente; puede existir rezago de publicación mensual."
        ]
    }

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")
    con.close()
    return payload


def main():
    p = argparse.ArgumentParser(description="Build Presupuesto Abierto spend-view v2")
    p.add_argument("parquet_glob")
    p.add_argument("--output", default="docs/data/spend_view_v2.json")
    p.add_argument("--prioritized", default="data/signals/prioritized_signals.parquet")
    p.add_argument("--service-limit", type=int, default=2000)
    p.add_argument("--provider-limit", type=int, default=1500)
    p.add_argument("--flow-limit", type=int, default=12000)
    p.add_argument("--flows-per-service", type=int, default=8)
    args = p.parse_args()
    payload = build_spend_view_v2(args.parquet_glob, args.output, args.prioritized, args.service_limit, args.provider_limit, args.flow_limit, args.flows_per_service)
    print(json.dumps({"schema": payload["schema"], "window": payload["window"], "overview": payload["overview"], "services": len(payload["services"]), "providers": len(payload["providers"]), "flows": len(payload["flows"])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
