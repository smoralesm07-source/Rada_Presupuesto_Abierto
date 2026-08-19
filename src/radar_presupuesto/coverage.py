from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

STATUS_URL="https://api.presupuestoabierto.gob.cl/status"


def fetch_service_coverage(timeout:int=30)->list[dict]:
    headers={"User-Agent":"RadarPresupuestoAbierto/3.1 (+public OSINT research)"}
    r=requests.get(STATUS_URL,timeout=timeout,headers=headers); r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser"); rows=[]
    for tr in soup.select("table tr"):
        cells=[c.get_text(" ",strip=True) for c in tr.find_all(["td","th"])]
        if len(cells)>=3 and cells[0].lower() not in {"servicio","institución","institucion"}:
            rows.append({"service":cells[0],"published":cells[1],"data_type":cells[2],"detail":cells[3] if len(cells)>3 else ""})
    return rows


def write_coverage(path:str="docs/data/coverage.json")->list[dict]:
    try:
        services=fetch_service_coverage(); error=None
        if not services:
            error="DYNAMIC_STATUS_NOT_PARSEABLE_WITH_STATIC_HTTP"
    except requests.RequestException as exc:
        services,error=[],type(exc).__name__
    payload={
        "generated_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source":STATUS_URL,
        "services":services,
        "services_count":len(services) if services else None,
        "parse_state":"SUCCESS" if services else "UNAVAILABLE_FROM_STATIC_HTTP",
        "error":error,
        "note":"Un valor nulo no significa cero servicios. La página oficial de estado puede renderizar su tabla dinámicamente; la paridad externa debe consultar la vista renderizada o una API oficial equivalente."
    }
    out=Path(path); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    return services
