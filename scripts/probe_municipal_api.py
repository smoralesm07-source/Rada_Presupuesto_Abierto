from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode

import requests

BASE = "https://api.presupuestoabierto.gob.cl/api/v1/data/municipios"
OUT = Path("docs/data/municipal_api_probe.json")
UA = "ATLAS-UAF municipal-api-probe/1.0"


def call(params: dict) -> dict:
    r = requests.get(BASE, params=params, headers={"User-Agent": UA}, timeout=60)
    body = r.text
    item = {
        "url": r.url,
        "status": r.status_code,
        "content_type": r.headers.get("content-type"),
        "bytes": len(r.content),
        "sample_text": body[:12000],
    }
    try:
        data = r.json()
        item["json_type"] = type(data).__name__
        item["count"] = len(data) if isinstance(data, list) else None
        if isinstance(data, list):
            item["sample"] = data[:25]
        else:
            item["sample"] = data
    except Exception:
        pass
    return item


def j(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def main() -> None:
    queries = {
        "periods": {"distinct": j(["periodo"]), "order-by": j(["periodo"])},
        "municipalities_2025": {
            "group-by": j(["region", "comuna"]),
            "select": j(["municipalidad", "nombre_region", "nombre_comuna", "nombre_municipalidad"]),
            "where": j({"periodo": 2025}),
            "limit": 500,
        },
        "cholchol_2025_beneficiaries": {
            "group-by": j(["beneficiario"]),
            "select": j(["nombre_beneficiario"]),
            "where": j({"region": "9", "comuna": "9121", "periodo": 2025}),
            "order-by": j(["sum", "desc"]),
            "limit": 5000,
        },
        "cholchol_flexing_2025_by_doc": {
            "group-by": j(["tipo_documento"]),
            "select": j(["nombre_beneficiario", "municipalidad", "nombre_municipalidad"]),
            "where": j({"region": "9", "comuna": "9121", "periodo": 2025, "beneficiario": "76592530-4"}),
            "limit": 500,
        },
        "cholchol_flexing_2025_raw": {
            "where": j({"region": "9", "comuna": "9121", "periodo": 2025, "beneficiario": "76592530-4"}),
            "limit": 500,
        },
        "cross_municipality_shape": {
            "group-by": j(["periodo", "region", "comuna", "beneficiario"]),
            "select": j(["municipalidad", "nombre_municipalidad", "nombre_beneficiario"]),
            "where": j({"periodo": 2025}),
            "order-by": j(["sum", "desc"]),
            "limit": 25,
        },
    }
    out = {name: call(params) for name, params in queries.items()}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    flex_rows = (out.get("cholchol_2025_beneficiaries", {}).get("sample") or [])
    # Full JSON may exceed the persisted sample list, therefore also scan raw response text.
    text = out["cholchol_2025_beneficiaries"].get("sample_text", "")
    found = "76592530-4" in text or "FLEXING CHILE" in text.upper()
    print(json.dumps({
        "cholchol_status": out["cholchol_2025_beneficiaries"]["status"],
        "cholchol_rows": out["cholchol_2025_beneficiaries"].get("count"),
        "flexing_found_in_first_12k": found,
        "flexing_doc_status": out["cholchol_flexing_2025_raw"]["status"],
        "flexing_doc_count": out["cholchol_flexing_2025_raw"].get("count"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
