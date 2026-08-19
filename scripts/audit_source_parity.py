from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import requests
from bs4 import BeautifulSoup

UA={"User-Agent":"RadarPresupuestoAbierto/3.3 (+public source parity audit)"}
BASE="https://api.presupuestoabierto.gob.cl"


def get(url: str) -> requests.Response:
    r=requests.get(url,headers=UA,timeout=60); r.raise_for_status(); return r


def money_int(text: str):
    s=re.sub(r"[^0-9-]","",text or "")
    try:return int(s)
    except:return None


def official_status():
    url=BASE+"/status"
    try:
        r=get(url)
    except requests.RequestException as exc:
        return {"url":url,"parse_status":"HTTP_ERROR","error":type(exc).__name__,"services_total":None,"services_transactional":None,"services_aggregated":None,"html_rows_parsed":0}
    soup=BeautifulSoup(r.text,"html.parser"); txt=soup.get_text(" ",strip=True)
    m=re.search(r"(\d+)\s+Servicios",txt,re.I)
    rows=[]
    for tr in soup.select("tr"):
        cells=[c.get_text(" ",strip=True) for c in tr.select("th,td")]
        if len(cells)>=3: rows.append(cells)
    trans=sum(1 for c in rows if any("Transaccional" in x for x in c))
    agg=sum(1 for c in rows if any("Agregado" in x for x in c))
    parsed=bool(m or rows)
    return {
      "url":url,"parse_status":"PARSED" if parsed else "DYNAMIC_HTML_UNAVAILABLE",
      "services_total":int(m.group(1)) if m else None,
      "services_transactional":trans or None,"services_aggregated":agg or None,
      "html_rows_parsed":len(rows)
    }


def official_providers(year: int):
    url=BASE+"/providers"
    try:
        r=get(url)
    except requests.RequestException as exc:
        return {"url":url,"year_requested":year,"parse_status":"HTTP_ERROR","error":type(exc).__name__,"total_displayed":None,"top":[]}
    soup=BeautifulSoup(r.text,"html.parser"); txt=soup.get_text(" ",strip=True)
    totals=[int(x) for x in re.findall(r"Total\s+(\d+)",txt,re.I)]
    top=[]
    for tr in soup.select("tr"):
        cells=[c.get_text(" ",strip=True) for c in tr.select("td")]
        if len(cells)>=5 and re.fullmatch(r"[0-9\.]+-[0-9Kk]",cells[2].replace(" ","")):
            top.append({"name":cells[1],"rut":cells[2],"amount_clp":money_int(cells[4])})
            if len(top)>=20: break
    # La página usa estado dinámico para el año seleccionado. Sin datos
    # renderizados en HTML no se presume que el año solicitado haya sido aplicado.
    parsed=bool(totals or top)
    return {
      "url":url,"year_requested":year,
      "parse_status":"PARSED_DEFAULT_PAGE" if parsed else "DYNAMIC_HTML_UNAVAILABLE",
      "year_selection_verified":False,
      "total_displayed":totals[-1] if totals else None,"top":top
    }


def bulk_head(year:int):
    url=f"{BASE}/data/pagos-{year}.gz"
    try:
        r=requests.head(url,headers=UA,timeout=60,allow_redirects=True)
        return {"url":url,"status":r.status_code,"content_length":int(r.headers.get("content-length",0) or 0) or None,"last_modified":r.headers.get("last-modified"),"etag":r.headers.get("etag"),"reachable":200 <= r.status_code < 400}
    except requests.RequestException as exc:
        return {"url":url,"status":None,"content_length":None,"last_modified":None,"etag":None,"reachable":False,"error":type(exc).__name__}


def local_metrics(parquet:str,year:int):
    con=duckdb.connect(); p=parquet.replace("'","''"); con.execute(f"CREATE VIEW f AS SELECT * FROM read_parquet('{p}',union_by_name=true)")
    latest=con.execute("SELECT max(make_date(periodo,mes,1)) FROM f WHERE coalesce(monto_devengado,0)<>0").fetchone()[0]
    payexpr="coalesce(try_strptime(fecha_pago,'%d/%m/%Y'),try_strptime(fecha_pago,'%d-%m-%Y'),try_strptime(fecha_pago,'%Y-%m-%d'))"
    latestpay=con.execute(f"SELECT max({payexpr}) FROM f WHERE coalesce(monto_pago,0)<>0").fetchone()[0]
    base=con.execute("""
      SELECT count(DISTINCT organization_id),
             count(DISTINCT organization_id) FILTER (WHERE NOT coalesce(is_aggregated,false)),
             count(DISTINCT concat(partida,'|',capitulo,'|',area)),
             sum(coalesce(monto_devengado,0)),sum(coalesce(monto_pago,0))
      FROM f WHERE periodo=?
    """,[year]).fetchone()

    # Paridad metodológica con la vista pública: receptor identificado por RUT,
    # sólo filas transaccionales y excluyendo Gastos en Personal (ST21).
    pr=con.execute("""
      SELECT count(DISTINCT rut_beneficiario),sum(coalesce(monto_devengado,0))
      FROM f
      WHERE periodo=? AND NOT coalesce(is_aggregated,false)
        AND coalesce(rut_beneficiario,'')<>'' AND ltrim(coalesce(subtitulo,''),'0')<>'21'
    """,[year]).fetchone()
    top=con.execute("""
      SELECT rut_beneficiario,arg_max(nombre_beneficiario,abs(monto_devengado)) name,
             sum(coalesce(monto_devengado,0)) amount_clp
      FROM f
      WHERE periodo=? AND NOT coalesce(is_aggregated,false)
        AND coalesce(rut_beneficiario,'')<>'' AND ltrim(coalesce(subtitulo,''),'0')<>'21'
      GROUP BY 1 ORDER BY 3 DESC LIMIT 30
    """,[year]).fetchall()

    source_provider=con.execute("""
      SELECT count(DISTINCT provider_id),sum(coalesce(monto_devengado,0))
      FROM f WHERE periodo=? AND is_provider_source=TRUE AND coalesce(provider_id,'')<>''
    """,[year]).fetchone()
    private=con.execute("""
      SELECT count(DISTINCT provider_id),sum(coalesce(monto_devengado,0))
      FROM f WHERE periodo=? AND is_provider=TRUE AND coalesce(provider_id,'')<>''
    """,[year]).fetchone()
    con.close()
    return {
      "year":year,"latest_devengo_month":str(latest) if latest else None,"latest_payment_date":str(latestpay) if latestpay else None,
      "services_with_rows":int(base[0] or 0),"transactional_services_with_rows":int(base[1] or 0),"areas":int(base[2] or 0),"devengo_clp":float(base[3] or 0),"payment_clp":float(base[4] or 0),
      "provider_receiver_proxy":{"definition":"institución transaccional (AGREGADO=0) + RUT de cualquier beneficiario/receptor válido + subtítulo != 21","distinct_ruts":int(pr[0] or 0),"devengo_clp":float(pr[1] or 0),"top":[{"rut":r[0],"name":r[1],"amount_clp":float(r[2] or 0)} for r in top]},
      "source_provider_flag":{"definition":"PROVEEDOR=1, sin exclusión INTRAESTADO","distinct_provider_ids":int(source_provider[0] or 0),"devengo_clp":float(source_provider[1] or 0)},
      "radar_provider_scope":{"definition":"PROVEEDOR=1 AND INTRAESTADO=0, antes del filtro nominal adicional","distinct_provider_ids":int(private[0] or 0),"devengo_clp":float(private[1] or 0)}
    }


def compare_top(local,official):
    if official.get("parse_status") != "PARSED_DEFAULT_PAGE":
        return []
    om={re.sub(r"[^0-9K]","",str(x.get("rut") or "").upper()):x for x in official.get("top",[])}
    out=[]
    for x in local.get("provider_receiver_proxy",{}).get("top",[]):
        k=re.sub(r"[^0-9K]","",str(x.get("rut") or "").upper()); o=om.get(k)
        if not o: continue
        la=float(x.get("amount_clp") or 0); oa=float(o.get("amount_clp") or 0); diff=la-oa
        out.append({"rut":x.get("rut"),"name":x.get("name"),"local_amount_clp":la,"official_amount_clp":oa,"difference_clp":diff,"difference_pct":diff/oa if oa else None})
    return out


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--parquet',required=True); ap.add_argument('--year',type=int,required=True); ap.add_argument('--output',default='docs/data/source_parity.json'); a=ap.parse_args()
    status=official_status(); providers=official_providers(a.year); local=local_metrics(a.parquet,a.year); head=bulk_head(a.year); matches=compare_top(local,providers)
    ui_live_verified=(status.get('parse_status')=='PARSED' and providers.get('parse_status')=='PARSED_DEFAULT_PAGE' and providers.get('year_selection_verified') is True)
    payload={
      "generated_at":datetime.now(timezone.utc).isoformat(timespec='seconds'),"source":"Presupuesto Abierto - DIPRES","year":a.year,
      "official":{"status":status,"providers":providers,"bulk":head},"local":local,"top_provider_matches":matches,
      "assessment":{
        "service_grain":"PARTIDA_CAPITULO","area_separated":True,"payments_use_fecha_pago_monto_pago":True,
        "provider_receiver_definition_aligned":True,"transactional_filter_aligned":True,"intra_state_separated":True,
        "recipient_rut_scope":"ALL_BENEFICIARIES_AND_RECIPIENTS",
        "bulk_reachable":bool(head.get('reachable')),
        "official_ui_live_verified":ui_live_verified,
        "official_ui_status":"VERIFIED" if ui_live_verified else "DYNAMIC_PAGE_NOT_AUTOMATICALLY_VERIFIED",
        "note":"La cuadratura local usa la metodología pública: filas transaccionales, receptor por RUT y exclusión de Subtítulo 21. Si la web dinámica no entrega su tabla al cliente HTTP de Actions, el archivo lo declara explícitamente y no presume una coincidencia visual."
      }
    }
    Path(a.output).parent.mkdir(parents=True,exist_ok=True); Path(a.output).write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('[OK] parity',json.dumps({"official_status_parse":status.get('parse_status'),"official_provider_parse":providers.get('parse_status'),"bulk_reachable":head.get('reachable'),"local_services":local.get('services_with_rows'),"local_transactional_services":local.get('transactional_services_with_rows'),"local_provider_receiver_ruts":local.get('provider_receiver_proxy',{}).get('distinct_ruts'),"radar_provider_ids":local.get('radar_provider_scope',{}).get('distinct_provider_ids'),"latest_devengo":local.get('latest_devengo_month'),"latest_payment":local.get('latest_payment_date'),"top_matches":len(matches)},ensure_ascii=False))

if __name__=='__main__': main()
