from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import duckdb

SCHEMA = "PRESUPUESTO_SPEND_YEARS_V1"

PUBLIC_PATTERNS = (
    "TESORERIA GENERAL DE LA REPUBLICA",
    "SERVICIO DE IMPUESTOS INTERNOS",
    "SERVICIO DE REGISTRO CIVIL",
    "SERVICIO MEDICO LEGAL",
    "SERVICIO NACIONAL DE",
    "SERVICIO DE SALUD",
    "SUBSECRETARIA DE",
    "MINISTERIO DE",
    "MUNICIPALIDAD DE",
    "ILUSTRE MUNICIPALIDAD",
    "GOBIERNO REGIONAL",
    "CONTRALORIA GENERAL DE LA REPUBLICA",
    "FONDO NACIONAL DE SALUD",
    "INSTITUTO DE PREVISION SOCIAL",
    "DEFENSORIA PENAL PUBLICA",
    "JUNTA NACIONAL DE",
    "DIRECCION GENERAL DE",
    "DIRECCION NACIONAL DE",
    "POLICIA DE INVESTIGACIONES DE CHILE",
    "CARABINEROS DE CHILE",
    "EJERCITO DE CHILE",
    "ARMADA DE CHILE",
    "FUERZA AEREA DE CHILE",
)


def norm_name(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()
    return re.sub(r"\s+", " ", text)


def strict(value):
    if isinstance(value, dict):
        return {str(k): strict(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [strict(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def records(con: duckdb.DuckDBPyConnection, sql: str, params=None) -> list[dict]:
    df = con.execute(sql, params or []).df()
    if df.empty:
        return []
    return df.where(df.notna(), None).to_dict("records")


def is_public_provider(name: object, service_names: set[str]) -> bool:
    n = norm_name(name)
    return bool(n and (n in service_names or any(p in n for p in PUBLIC_PATTERNS)))


def build(parquet_path: str, output: str, flows_per_service_year: int = 3, global_flow_cap: int = 12000) -> dict:
    con = duckdb.connect()
    p = parquet_path.replace("'", "''")
    con.execute(f"CREATE OR REPLACE VIEW facts AS SELECT * FROM read_parquet('{p}', union_by_name=true)")
    years = [int(x[0]) for x in con.execute("SELECT DISTINCT periodo FROM facts WHERE periodo IS NOT NULL ORDER BY 1").fetchall()]
    if not years:
        raise RuntimeError("No hay años disponibles")

    service_rows = records(con, """
        SELECT organization_id,
               arg_max(coalesce(nullif(trim(nombre_area),''), nullif(trim(nombre_capitulo),''), nullif(trim(nombre_partida),''), organization_id), abs(monto_devengado)) AS organization_name,
               arg_max(nullif(trim(region),''), abs(monto_devengado)) AS main_region,
               periodo AS year,
               sum(coalesce(monto_devengado,0)) AS amount_clp,
               count(*) AS transactions,
               sum(coalesce(monto_devengado,0)) FILTER (WHERE is_provider=TRUE AND coalesce(provider_id,'')<>'') AS provider_amount_clp,
               count(DISTINCT provider_id) FILTER (WHERE is_provider=TRUE AND coalesce(provider_id,'')<>'') AS providers
        FROM facts GROUP BY 1,4 ORDER BY 4,5 DESC
    """)
    service_names = {norm_name(r.get("organization_name")) for r in service_rows if norm_name(r.get("organization_name"))}

    raw_flows = records(con, """
        SELECT organization_id,
               arg_max(coalesce(nullif(trim(nombre_area),''), nullif(trim(nombre_capitulo),''), nullif(trim(nombre_partida),''), organization_id), abs(monto_devengado)) AS organization_name,
               provider_id,
               arg_max(coalesce(nullif(trim(nombre_beneficiario),''), provider_id), abs(monto_devengado)) AS provider_name,
               arg_max(nullif(trim(rut_beneficiario),''), abs(monto_devengado)) AS rut,
               periodo AS year,
               sum(coalesce(monto_devengado,0)) AS amount_clp,
               count(*) AS transactions
        FROM facts
        WHERE is_provider=TRUE AND coalesce(provider_id,'')<>''
        GROUP BY 1,3,6
        HAVING sum(coalesce(monto_devengado,0))<>0
        ORDER BY 6,7 DESC
    """)
    raw_flows = [r for r in raw_flows if not is_public_provider(r.get("provider_name"), service_names)]

    by_sy: dict[tuple[str,int], list[dict]] = defaultdict(list)
    for r in raw_flows:
        by_sy[(str(r["organization_id"]), int(r["year"]))].append(r)
    keep: list[dict] = []
    seen: set[tuple[str,str,int]] = set()
    for rows in by_sy.values():
        rows.sort(key=lambda r: abs(float(r.get("amount_clp") or 0)), reverse=True)
        for r in rows[:flows_per_service_year]:
            key = (str(r["organization_id"]), str(r["provider_id"]), int(r["year"]))
            if key not in seen:
                seen.add(key); keep.append(r)
    if len(keep) < global_flow_cap:
        for r in sorted(raw_flows, key=lambda r: abs(float(r.get("amount_clp") or 0)), reverse=True):
            if len(keep) >= global_flow_cap:
                break
            key = (str(r["organization_id"]), str(r["provider_id"]), int(r["year"]))
            if key in seen:
                continue
            seen.add(key); keep.append(r)

    # Always preserve UAF reference flows, even when outside the global ranking.
    uaf_ids = {
        str(r["organization_id"])
        for r in service_rows
        if "UNIDAD DE ANALISIS FINANCIERO" in norm_name(r.get("organization_name"))
    }
    if not uaf_ids:
        uaf_ids = {str(r["organization_id"]) for r in service_rows if norm_name(r.get("organization_name")) == "UAF"}
    for r in raw_flows:
        if str(r["organization_id"]) not in uaf_ids:
            continue
        key = (str(r["organization_id"]), str(r["provider_id"]), int(r["year"]))
        if key not in seen:
            seen.add(key); keep.append(r)

    provider_year: dict[tuple[str,int], dict] = {}
    for r in keep:
        key=(str(r["provider_id"]), int(r["year"]))
        cur=provider_year.setdefault(key, {"provider_id":r["provider_id"],"provider_name":r["provider_name"],"rut":r.get("rut") or "","year":int(r["year"]),"amount_clp":0.0,"transactions":0,"organizations":set()})
        cur["amount_clp"] += float(r.get("amount_clp") or 0)
        cur["transactions"] += int(r.get("transactions") or 0)
        cur["organizations"].add(str(r["organization_id"]))
    provider_rows=[]
    for cur in provider_year.values():
        cur={**cur,"organizations":len(cur["organizations"])}
        provider_rows.append(cur)

    month_rows = records(con, """
        SELECT periodo AS year, mes,
               printf('%04d-%02d',periodo,mes) AS period,
               sum(coalesce(monto_devengado,0)) AS amount_clp,
               count(*) AS transactions,
               sum(coalesce(monto_devengado,0)) FILTER (WHERE is_provider=TRUE AND coalesce(provider_id,'')<>'') AS provider_amount_clp
        FROM facts GROUP BY 1,2 ORDER BY 1,2
    """)

    uaf_months=[]
    if uaf_ids:
        ph=','.join('?' for _ in uaf_ids)
        uaf_months=records(con, f"""
            SELECT periodo AS year, mes, printf('%04d-%02d',periodo,mes) AS period,
                   sum(coalesce(monto_devengado,0)) AS amount_clp,
                   sum(coalesce(monto_devengado,0)) FILTER (WHERE is_provider=TRUE AND coalesce(provider_id,'')<>'') AS provider_amount_clp
            FROM facts WHERE organization_id IN ({ph}) GROUP BY 1,2 ORDER BY 1,2
        """, list(uaf_ids))

    # Existing PA catalogue marks that can be reproduced from the light fact surface.
    marks=[]
    max_year=max(years)
    # YEAR_END_SPIKE
    monthly_by_org=records(con, """
        SELECT organization_id, periodo AS year, mes, sum(coalesce(monto_devengado,0)) amount
        FROM facts GROUP BY 1,2,3
    """)
    agg=defaultdict(lambda:{"base":[],"end":[]})
    for r in monthly_by_org:
        bucket=agg[(str(r["organization_id"]),int(r["year"]))]
        (bucket["base"] if int(r["mes"])<=10 else bucket["end"]).append(float(r.get("amount") or 0))
    for (sid,year),a in agg.items():
        if not a["base"] or not a["end"]: continue
        base=sum(a["base"])/len(a["base"]); end=sum(a["end"])/len(a["end"])
        if base>0 and end/base>=2.5:
            marks.append({"scope":"service","entity_id":sid,"year":year,"signal_type":"YEAR_END_SPIKE","severity":"MEDIUM","metric":end/base,"why":"Promedio mensual nov-dic es al menos 2,5x el promedio ene-oct."})

    # PROVIDER_CONCENTRATION (same thresholds as advanced_signals.py defaults).
    sy_tot=defaultdict(float); sy_providers=defaultdict(dict)
    for r in raw_flows:
        k=(str(r["organization_id"]),int(r["year"])); a=float(r.get("amount_clp") or 0); sy_tot[k]+=a; sy_providers[k][str(r["provider_id"])]=a
    for (sid,year),pm in sy_providers.items():
        total=sy_tot[(sid,year)]
        if total<=0 or len(pm)<8: continue
        vals=sorted(pm.items(),key=lambda x:x[1],reverse=True); pid,amount=vals[0]; share=amount/total; hhi=sum((v/total)**2 for _,v in vals)
        if share>=.45 and hhi>=.25 and amount>=10_000_000:
            marks.append({"scope":"provider","entity_id":pid,"organization_id":sid,"year":year,"signal_type":"PROVIDER_CONCENTRATION","severity":"HIGH" if share>=.65 or hhi>=.40 else "MEDIUM","metric":share,"hhi":hhi,"why":"Proveedor dominante con concentración material dentro del organismo/año."})

    # NEW_TO_SERIES_HIGH_SPEND.
    first_year={}
    for r in raw_flows:
        pid=str(r["provider_id"]); y=int(r["year"]); first_year[pid]=min(y,first_year.get(pid,y))
    new_rows=[]
    for r in provider_rows:
        if int(r["year"])==max_year and first_year.get(str(r["provider_id"]))==max_year and int(r.get("transactions") or 0)>=3:
            new_rows.append(r)
    amounts=sorted(float(r.get("amount_clp") or 0) for r in new_rows)
    q99=amounts[max(0,math.ceil(len(amounts)*.99)-1)] if amounts else 0
    threshold=max(50_000_000,q99)
    for r in new_rows:
        if float(r.get("amount_clp") or 0)>=threshold:
            marks.append({"scope":"provider","entity_id":str(r["provider_id"]),"year":max_year,"signal_type":"NEW_TO_SERIES_HIGH_SPEND","severity":"HIGH" if int(r.get("organizations") or 0)>=3 else "MEDIUM","metric":float(r.get("amount_clp") or 0),"why":"Proveedor no observado en años anteriores de la serie entra con gasto acumulado material."})

    service_map={}
    for r in service_rows:
        sid=str(r["organization_id"]); s=service_map.setdefault(sid,{"organization_id":sid,"organization_name":r.get("organization_name") or sid,"main_region":r.get("main_region") or "","yearly":[]})
        s["yearly"].append({k:r.get(k) for k in ("year","amount_clp","transactions","provider_amount_clp","providers")})

    provider_map={}
    for r in provider_rows:
        pid=str(r["provider_id"]); p0=provider_map.setdefault(pid,{"provider_id":pid,"provider_name":r.get("provider_name") or pid,"rut":r.get("rut") or "","first_year":first_year.get(pid),"yearly":[]})
        p0["yearly"].append({k:r.get(k) for k in ("year","amount_clp","transactions","organizations")})

    flow_map={}
    for r in keep:
        key=(str(r["organization_id"]),str(r["provider_id"])); f=flow_map.setdefault(key,{"organization_id":key[0],"organization_name":r.get("organization_name") or key[0],"provider_id":key[1],"provider_name":r.get("provider_name") or key[1],"rut":r.get("rut") or "","yearly":[]})
        f["yearly"].append({"year":int(r["year"]),"amount_clp":r.get("amount_clp"),"transactions":r.get("transactions")})

    reference=[]
    for sid in sorted(uaf_ids):
        s=service_map.get(sid)
        reference.append({"role":"UAF_REFERENCE","organization_id":sid,"organization_name":s.get("organization_name") if s else "Unidad de Análisis Financiero"})

    payload=strict({
        "schema":SCHEMA,
        "generated_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "years":years,
        "default_years":years,
        "reference_entities":reference,
        "services":list(service_map.values()),
        "providers":list(provider_map.values()),
        "flows":list(flow_map.values()),
        "months":month_rows,
        "uaf_months":uaf_months,
        "marks":marks,
        "method":{
            "provider_scope":"PRIVATE_OR_NON_PUBLIC_COUNTERPARTIES",
            "flow_selection":"top relationships by service/year plus global material flows; UAF relationships always retained",
            "marks_catalog":["YEAR_END_SPIKE","PROVIDER_CONCENTRATION","NEW_TO_SERIES_HIGH_SPEND"],
            "guardrail":"Marca analítica prioriza revisión; no acredita irregularidad, incumplimiento ni LA/FT."
        }
    })
    out=Path(output); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(payload,ensure_ascii=False,separators=(",",":"),allow_nan=False),encoding="utf-8")
    con.close()
    return {"years":years,"services":len(payload["services"]),"providers":len(payload["providers"]),"flows":len(payload["flows"]),"marks":len(marks),"uaf_references":len(reference),"bytes":out.stat().st_size}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--parquet",default="data/processed/spend_view_light.parquet")
    p.add_argument("--output",default="docs/data/spend_years_v1.json")
    p.add_argument("--flows-per-service-year",type=int,default=3)
    p.add_argument("--global-flow-cap",type=int,default=12000)
    a=p.parse_args()
    print(json.dumps(build(a.parquet,a.output,a.flows_per_service_year,a.global_flow_cap),ensure_ascii=False))


if __name__=="__main__":
    main()
