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

SCHEMA = "PRESUPUESTO_SPEND_YEARS_V1"  # compatibilidad frontend
BUILD_VERSION = "2.0-corrected"

PUBLIC_PATTERNS = (
    "TESORERIA GENERAL DE LA REPUBLICA", "SERVICIO DE IMPUESTOS INTERNOS",
    "SERVICIO DE REGISTRO CIVIL", "SERVICIO MEDICO LEGAL", "SERVICIO NACIONAL DE",
    "SERVICIO DE SALUD", "SUBSECRETARIA DE", "MINISTERIO DE", "MUNICIPALIDAD DE",
    "ILUSTRE MUNICIPALIDAD", "GOBIERNO REGIONAL", "CONTRALORIA GENERAL DE LA REPUBLICA",
    "FONDO NACIONAL DE SALUD", "INSTITUTO DE PREVISION SOCIAL", "DEFENSORIA PENAL PUBLICA",
    "JUNTA NACIONAL DE", "DIRECCION GENERAL DE", "DIRECCION NACIONAL DE",
    "POLICIA DE INVESTIGACIONES DE CHILE", "CARABINEROS DE CHILE", "EJERCITO DE CHILE",
    "ARMADA DE CHILE", "FUERZA AEREA DE CHILE",
)


def norm(v: object) -> str:
    x = unicodedata.normalize("NFKD", str(v or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", x.upper())).strip()


def strict(v):
    if isinstance(v, dict): return {str(k): strict(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [strict(x) for x in v]
    if isinstance(v, float) and not math.isfinite(v): return None
    return v


def rec(con, sql: str, params=None) -> list[dict]:
    df = con.execute(sql, params or []).df()
    if df.empty: return []
    return df.where(df.notna(), None).to_dict("records")


def is_public(name: object, service_names: set[str]) -> bool:
    n = norm(name)
    return bool(n and (n in service_names or any(p in n for p in PUBLIC_PATTERNS)))


def parse_payment_expr() -> str:
    # El bulk ha usado fechas día/mes/año e ISO en distintas etapas.
    return "coalesce(try_strptime(fecha_pago,'%d/%m/%Y'),try_strptime(fecha_pago,'%d-%m-%Y'),try_strptime(fecha_pago,'%Y-%m-%d'))"


def build(parquet_path: str, output: str, max_seed_providers: int = 1400, max_flows: int = 24000) -> dict:
    con = duckdb.connect()
    p = parquet_path.replace("'", "''")
    con.execute(f"CREATE OR REPLACE VIEW facts AS SELECT * FROM read_parquet('{p}', union_by_name=true)")
    years = [int(x[0]) for x in con.execute("SELECT DISTINCT periodo FROM facts WHERE periodo IS NOT NULL ORDER BY 1").fetchall()]
    if not years: raise RuntimeError("No hay años disponibles")

    service_rows = rec(con, """
      SELECT organization_id,
             arg_max(coalesce(nullif(trim(nombre_capitulo),''),organization_id),abs(monto_devengado)) organization_name,
             arg_max(nullif(trim(region),''),abs(monto_devengado)) main_region,
             arg_max(nullif(trim(partida),''),abs(monto_devengado)) partida,
             arg_max(nullif(trim(capitulo),''),abs(monto_devengado)) capitulo,
             periodo year, sum(coalesce(monto_devengado,0)) amount_clp, count(*) transactions
      FROM facts GROUP BY 1,6 ORDER BY 6,7 DESC
    """)
    service_names = {norm(r.get("organization_name")) for r in service_rows if norm(r.get("organization_name"))}

    area_rows = rec(con, """
      SELECT organization_id, area, arg_max(nullif(trim(area_name),''),abs(monto_devengado)) area_name,
             sum(coalesce(monto_devengado,0)) amount_clp
      FROM facts GROUP BY 1,2 HAVING sum(coalesce(monto_devengado,0))<>0
      ORDER BY 1,4 DESC
    """)
    areas_by_service: dict[str,list[dict]] = defaultdict(list)
    for r in area_rows:
        areas_by_service[str(r["organization_id"])].append({"area":r.get("area") or "","area_name":r.get("area_name") or "","amount_clp":r.get("amount_clp")})

    raw_flows = rec(con, """
      SELECT organization_id,
             arg_max(coalesce(nullif(trim(nombre_capitulo),''),organization_id),abs(monto_devengado)) organization_name,
             provider_id,
             arg_max(coalesce(nullif(trim(nombre_beneficiario),''),provider_id),abs(monto_devengado)) provider_name,
             arg_max(nullif(trim(rut_beneficiario),''),abs(monto_devengado)) rut,
             periodo year, sum(coalesce(monto_devengado,0)) amount_clp, count(*) transactions
      FROM facts
      WHERE is_provider=TRUE AND coalesce(provider_id,'')<>''
      GROUP BY 1,3,6 HAVING sum(coalesce(monto_devengado,0))<>0
    """)
    source_flag_flow_count = len(raw_flows)
    raw_flows = [r for r in raw_flows if not is_public(r.get("provider_name"), service_names)]

    # Agregados COMPLETOS. Nunca se calculan métricas sobre el recorte visual.
    py: dict[tuple[str,int],dict] = {}
    first_year: dict[str,int] = {}
    ptotal: dict[str,float] = defaultdict(float)
    sy_total: dict[tuple[str,int],float] = defaultdict(float)
    sy_provider: dict[tuple[str,int],dict[str,float]] = defaultdict(dict)
    for r in raw_flows:
        pid, y = str(r["provider_id"]), int(r["year"]); a = float(r.get("amount_clp") or 0)
        first_year[pid] = min(y, first_year.get(pid,y)); ptotal[pid] += a
        sy_total[(str(r["organization_id"]),y)] += a
        sy_provider[(str(r["organization_id"]),y)][pid] = a
        cur = py.setdefault((pid,y), {"provider_id":pid,"provider_name":r.get("provider_name") or pid,"rut":r.get("rut") or "","year":y,"amount_clp":0.0,"transactions":0,"organizations":set()})
        cur["amount_clp"] += a; cur["transactions"] += int(r.get("transactions") or 0); cur["organizations"].add(str(r["organization_id"]))

    provider_rows_full=[]
    for x in py.values(): provider_rows_full.append({**x,"organizations":len(x["organizations"])})

    marks=[]
    max_year=max(years)
    monthly_org=rec(con,"""SELECT organization_id,periodo year,mes,sum(coalesce(monto_devengado,0)) amount FROM facts GROUP BY 1,2,3""")
    buckets=defaultdict(lambda:{"base":[],"end":[]})
    for r in monthly_org:
        b=buckets[(str(r["organization_id"]),int(r["year"]))]
        (b["base"] if int(r["mes"])<=10 else b["end"]).append(float(r.get("amount") or 0))
    for (sid,y),b in buckets.items():
        if b["base"] and b["end"]:
            base=sum(b["base"])/len(b["base"]); end=sum(b["end"])/len(b["end"])
            if base>0 and end/base>=2.5: marks.append({"scope":"service","entity_id":sid,"year":y,"signal_type":"YEAR_END_SPIKE","severity":"MEDIUM","metric":end/base,"why":"Promedio mensual nov-dic es al menos 2,5x el promedio ene-oct."})

    for (sid,y),pm in sy_provider.items():
        total=sy_total[(sid,y)]
        if total<=0 or len(pm)<8: continue
        vals=sorted(pm.items(),key=lambda z:z[1],reverse=True); pid,a=vals[0]; share=a/total; hhi=sum((v/total)**2 for _,v in vals)
        if share>=.45 and hhi>=.25 and a>=10_000_000:
            marks.append({"scope":"provider","entity_id":pid,"organization_id":sid,"year":y,"signal_type":"PROVIDER_CONCENTRATION","severity":"HIGH" if share>=.65 or hhi>=.40 else "MEDIUM","metric":share,"hhi":hhi,"why":"Proveedor dominante con concentración material dentro del servicio/año."})

    new_rows=[r for r in provider_rows_full if int(r["year"])==max_year and first_year.get(str(r["provider_id"]))==max_year and int(r.get("transactions") or 0)>=3]
    amts=sorted(float(r.get("amount_clp") or 0) for r in new_rows); q99=amts[max(0,math.ceil(len(amts)*.99)-1)] if amts else 0; threshold=max(50_000_000,q99)
    for r in new_rows:
        if float(r.get("amount_clp") or 0)>=threshold:
            marks.append({"scope":"provider","entity_id":str(r["provider_id"]),"year":max_year,"signal_type":"NEW_TO_SERIES_HIGH_SPEND","severity":"HIGH" if int(r.get("organizations") or 0)>=3 else "MEDIUM","metric":float(r.get("amount_clp") or 0),"why":"Proveedor no observado en años anteriores entra con gasto acumulado material."})

    # Selección de publicación: top material + proveedores con marca + vinculados a UAF.
    uaf_ids={str(r["organization_id"]) for r in service_rows if "UNIDAD DE ANALISIS FINANCIERO" in norm(r.get("organization_name"))}
    seed={pid for pid,_ in sorted(ptotal.items(),key=lambda z:abs(z[1]),reverse=True)[:max_seed_providers]}
    seed.update(str(m["entity_id"]) for m in marks if m.get("scope")=="provider")
    seed.update(str(r["provider_id"]) for r in raw_flows if str(r["organization_id"]) in uaf_ids)

    # Todas las relaciones de los proveedores publicados -> dependencia/influencia exactas para ellos.
    keep=[r for r in raw_flows if str(r["provider_id"]) in seed]
    # Asegura cobertura de los 3 principales flujos de cada servicio/año.
    by_sy=defaultdict(list)
    for r in raw_flows: by_sy[(str(r["organization_id"]),int(r["year"]))].append(r)
    keys={(str(r["organization_id"]),str(r["provider_id"]),int(r["year"])) for r in keep}
    for rows in by_sy.values():
        for r in sorted(rows,key=lambda x:abs(float(x.get("amount_clp") or 0)),reverse=True)[:3]:
            k=(str(r["organization_id"]),str(r["provider_id"]),int(r["year"]))
            if k not in keys: keep.append(r); keys.add(k); seed.add(str(r["provider_id"]))
    if len(keep)>max_flows:
        # No cortar relaciones de top proveedores arbitrariamente: reduce seeds materiales y reconstruye.
        core={pid for pid,_ in sorted(ptotal.items(),key=lambda z:abs(z[1]),reverse=True)[:900]}
        core.update(str(m["entity_id"]) for m in marks if m.get("scope")=="provider")
        core.update(str(r["provider_id"]) for r in raw_flows if str(r["organization_id"]) in uaf_ids)
        keep=[r for r in raw_flows if str(r["provider_id"]) in core]; seed=core

    selected=sorted(seed)
    con.execute("CREATE OR REPLACE TEMP TABLE selected_providers(provider_id VARCHAR)")
    if selected: con.executemany("INSERT INTO selected_providers VALUES (?)",[(x,) for x in selected])

    # Meses de PAGO real, separados de meses de devengo.
    pay_expr=parse_payment_expr()
    pay_month_rows=rec(con,f"""
      SELECT f.provider_id, year({pay_expr}) year, month({pay_expr}) month,
             strftime({pay_expr},'%Y-%m') period,
             sum(coalesce(f.monto_pago,0)) amount_clp, count(*) transactions
      FROM facts f JOIN selected_providers s USING(provider_id)
      WHERE f.is_provider=TRUE AND {pay_expr} IS NOT NULL AND coalesce(f.monto_pago,0)<>0
      GROUP BY 1,2,3,4 ORDER BY 1,2,3
    """)
    pay_by=defaultdict(list)
    for r in pay_month_rows:
        pay_by[str(r["provider_id"])].append({"year":int(r["year"]),"month":int(r["month"]),"period":r["period"],"amount_clp":r.get("amount_clp"),"transactions":r.get("transactions")})

    dev_month_rows=rec(con,"""
      SELECT f.provider_id,f.periodo year,f.mes,printf('%04d-%02d',f.periodo,f.mes) period,
             sum(coalesce(f.monto_devengado,0)) amount_clp,count(*) transactions
      FROM facts f JOIN selected_providers s USING(provider_id)
      WHERE f.is_provider=TRUE GROUP BY 1,2,3 HAVING sum(coalesce(f.monto_devengado,0))<>0 ORDER BY 1,2,3
    """)
    dev_by=defaultdict(list)
    for r in dev_month_rows: dev_by[str(r["provider_id"])].append({"year":int(r["year"]),"month":int(r["mes"]),"period":r["period"],"amount_clp":r.get("amount_clp"),"transactions":r.get("transactions")})

    service_map={}
    private_service_year=defaultdict(lambda:{"amount":0.0,"providers":set()})
    for r in raw_flows:
        k=(str(r["organization_id"]),int(r["year"])); private_service_year[k]["amount"]+=float(r.get("amount_clp") or 0); private_service_year[k]["providers"].add(str(r["provider_id"]))
    for r in service_rows:
        sid=str(r["organization_id"]); y=int(r["year"]); priv=private_service_year[(sid,y)]
        s=service_map.setdefault(sid,{"organization_id":sid,"organization_name":r.get("organization_name") or sid,"main_region":r.get("main_region") or "","partida":r.get("partida") or "","capitulo":r.get("capitulo") or "","areas":areas_by_service.get(sid,[])[:12],"yearly":[]})
        s["yearly"].append({"year":y,"amount_clp":r.get("amount_clp"),"transactions":r.get("transactions"),"provider_amount_clp":priv["amount"],"providers":len(priv["providers"])})

    provider_map={}
    for r in provider_rows_full:
        pid=str(r["provider_id"])
        if pid not in seed: continue
        x=provider_map.setdefault(pid,{"provider_id":pid,"provider_name":r.get("provider_name") or pid,"rut":r.get("rut") or "","first_year":first_year.get(pid),"yearly":[],"monthly":pay_by.get(pid,[]),"payment_monthly":pay_by.get(pid,[]),"devengo_monthly":dev_by.get(pid,[])})
        x["yearly"].append({k:r.get(k) for k in ("year","amount_clp","transactions","organizations")})

    flow_map={}
    for r in keep:
        k=(str(r["organization_id"]),str(r["provider_id"])); f=flow_map.setdefault(k,{"organization_id":k[0],"organization_name":r.get("organization_name") or k[0],"provider_id":k[1],"provider_name":r.get("provider_name") or k[1],"rut":r.get("rut") or "","yearly":[]})
        f["yearly"].append({"year":int(r["year"]),"amount_clp":r.get("amount_clp"),"transactions":r.get("transactions")})

    month_rows=rec(con,f"""
      SELECT periodo year,mes,printf('%04d-%02d',periodo,mes) period,
             sum(coalesce(monto_devengado,0)) amount_clp,count(*) transactions,
             sum(coalesce(monto_pago,0)) payment_amount_clp
      FROM facts GROUP BY 1,2 ORDER BY 1,2
    """)
    latest_dev=con.execute("SELECT max(make_date(periodo,mes,1)) FROM facts WHERE coalesce(monto_devengado,0)<>0").fetchone()[0]
    latest_pay=con.execute(f"SELECT max({pay_expr}) FROM facts WHERE coalesce(monto_pago,0)<>0").fetchone()[0]

    reference=[]
    for sid in sorted(uaf_ids):
        s=service_map.get(sid); reference.append({"role":"UAF_REFERENCE","organization_id":sid,"organization_name":s.get("organization_name") if s else "Unidad de Análisis Financiero"})

    payload=strict({
      "schema":SCHEMA,"generated_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),"build_version":BUILD_VERSION,
      "years":years,"default_years":years,"reference_entities":reference,
      "services":list(service_map.values()),"providers":list(provider_map.values()),"flows":list(flow_map.values()),"months":month_rows,"uaf_months":[],"marks":marks,
      "coverage":{"latest_devengo_month":str(latest_dev) if latest_dev else None,"latest_payment_date":str(latest_pay) if latest_pay else None,"service_count_transactional":len(service_map),"area_count_transactional":sum(len(s.get("areas",[])) for s in service_map.values()),"source_provider_flag_relations":source_flag_flow_count,"private_relations_full":len(raw_flows),"published_provider_profiles":len(provider_map),"published_relations":len(flow_map)},
      "method":{"organization_grain":"PARTIDA_CAPITULO","organization_definition":"Capítulo = organismo/servicio; Área se conserva como drill-down.","provider_source_scope":"PROVEEDOR_FLAG_SOURCE","provider_analytic_scope":"PRIVATE_OR_NON_PUBLIC_COUNTERPARTIES","provider_metrics_basis":"FULL_PRIVATE_RELATION_UNIVERSE","flow_publication":"COMPLETE_RELATIONS_FOR_PUBLISHED_PROVIDERS_PLUS_SERVICE_COVERAGE","payment_months_basis":"FECHA_PAGO_AND_MONTO_PAGO","devengo_basis":"PERIODO_MES_AND_DEVENGO","source_comparison_note":"Proveedor privado analítico no equivale a Proveedor/Receptor de la web; la paridad se audita por separado."}
    })
    Path(output).write_text(json.dumps(payload,ensure_ascii=False,separators=(",",":"),allow_nan=False),encoding="utf-8")
    con.close()
    return payload


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--parquet",required=True); ap.add_argument("--output",required=True); ap.add_argument("--max-seed-providers",type=int,default=1400); ap.add_argument("--max-flows",type=int,default=24000); a=ap.parse_args()
    d=build(a.parquet,a.output,a.max_seed_providers,a.max_flows)
    print('[OK] corrected multiyear',d['coverage']); print('[OK] method',d['method'])

if __name__=='__main__': main()
