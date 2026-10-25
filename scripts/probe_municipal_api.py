from __future__ import annotations

import json
from pathlib import Path

import requests

BASE = "https://api.presupuestoabierto.gob.cl/api/v1/data/municipios"
OUT = Path("docs/data/municipal_api_probe.json")
UA = "ATLAS-UAF municipal-api-probe/1.1"


def call(params: dict) -> dict:
    r = requests.get(BASE, params=params, headers={"User-Agent": UA}, timeout=90)
    body = r.text
    item = {
        "url": r.url,
        "status": r.status_code,
        "content_type": r.headers.get("content-type"),
        "bytes": len(r.content),
        "sample_text": body[:16000],
    }
    try:
        data = r.json()
        item["json_type"] = type(data).__name__
        item["count"] = len(data) if isinstance(data, list) else None
        item["rows"] = data if isinstance(data, list) and len(data) <= 1000 else (data[:1000] if isinstance(data, list) else data)
    except Exception:
        pass
    return item


def j(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def main() -> None:
    out: dict[str, object] = {}
    out["periods"] = call({"distinct": j(["periodo"]), "order-by": j(["periodo"])})
    out["municipalities_2025"] = call({
        "group-by": j(["municipalidad"]),
        "select": j(["nombre_municipalidad", "region", "comuna"]),
        "where": j({"periodo": 2025}),
        "order-by": j(["nombre_municipalidad"]),
        "limit": 500,
    })

    municipalities = out["municipalities_2025"].get("rows") or []
    cholchol = next(
        (r for r in municipalities if "CHOLCHOL" in str(r.get("nombre_municipalidad") or r.get("nombre_comuna") or "").upper()),
        None,
    )
    if not cholchol:
        # Broader official search as a fallback; search syntax is used by the portal itself.
        out["cholchol_search"] = call({
            "where": j({"periodo": 2025}),
            "search": j("Cholchol*"),
            "limit": 100,
        })
        search_rows = out["cholchol_search"].get("rows") or []
        cholchol = next(
            (r for r in search_rows if "CHOLCHOL" in json.dumps(r, ensure_ascii=False).upper()),
            None,
        )
    if not cholchol:
        raise SystemExit("No fue posible resolver Cholchol en el catálogo municipal oficial 2025")

    region = str(cholchol["region"])
    comuna = str(cholchol["comuna"])
    municipality = str(cholchol.get("municipalidad") or "")
    out["cholchol_resolved"] = {"region": region, "comuna": comuna, "municipalidad": municipality, "row": cholchol}

    base_where = {"region": region, "comuna": comuna, "periodo": 2025}
    out["cholchol_2025_beneficiaries"] = call({
        "group-by": j(["beneficiario"]),
        "select": j(["nombre_beneficiario"]),
        "where": j(base_where),
        "order-by": j(["sum", "desc"]),
        "limit": 5000,
    })
    out["cholchol_flexing_2025_by_doc"] = call({
        "group-by": j(["tipo_documento"]),
        "select": j(["nombre_beneficiario", "municipalidad", "nombre_municipalidad"]),
        "where": j({**base_where, "beneficiario": "76592530-4"}),
        "limit": 500,
    })
    out["cholchol_flexing_2025_raw"] = call({
        "where": j({**base_where, "beneficiario": "76592530-4"}),
        "limit": 500,
        "order-by": j(["fecha_documento", "desc"]),
    })
    out["cholchol_flexing_all_years"] = call({
        "group-by": j(["periodo"]),
        "select": j(["nombre_beneficiario", "municipalidad", "nombre_municipalidad"]),
        "where": j({"region": region, "comuna": comuna, "beneficiario": "76592530-4"}),
        "order-by": j(["periodo"]),
        "limit": 100,
    })
    out["cross_municipality_shape"] = call({
        "group-by": j(["region", "comuna", "beneficiario"]),
        "select": j(["municipalidad", "nombre_municipalidad", "nombre_beneficiario"]),
        "where": j({"periodo": 2025}),
        "order-by": j(["sum", "desc"]),
        "limit": 25,
    })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    beneficiaries = out["cholchol_2025_beneficiaries"].get("rows") or []
    flex = [r for r in beneficiaries if "76592530-4" in str(r.get("beneficiario", "")) or "FLEXING CHILE" in str(r.get("nombre_beneficiario", "")).upper()]
    raw = out["cholchol_flexing_2025_raw"]
    print(json.dumps({
        "cholchol": out["cholchol_resolved"],
        "cholchol_rows": out["cholchol_2025_beneficiaries"].get("count"),
        "flexing_grouped": flex,
        "flexing_raw_count": raw.get("count"),
        "flexing_raw_rows": (raw.get("rows") or [])[:10],
        "flexing_by_doc": out["cholchol_flexing_2025_by_doc"].get("rows"),
        "flexing_all_years": out["cholchol_flexing_all_years"].get("rows"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
