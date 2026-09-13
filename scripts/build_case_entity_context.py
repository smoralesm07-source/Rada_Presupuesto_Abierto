from __future__ import annotations

import json
from pathlib import Path

FINDINGS = Path("docs/data/investigative_findings.json")
ENRICHMENT = Path("docs/data/entity_enrichment_v1.json")
OUT = Path("docs/data/case_entity_context.json")

GUARDRAIL = (
    "El contexto SII sirve para caracterizar capacidad y trayectoria observable. No acredita irregularidad, "
    "simulación, conflicto de interés ni delito. Debe interpretarse junto con contratación, ejecución y evidencia documental."
)


def _rut_from_provider_id(provider_id: object) -> str:
    value = str(provider_id or "")
    prefix = "PRV-RUT-"
    return value[len(prefix):] if value.startswith(prefix) else ""


def _compact(entity: dict) -> dict:
    activities = entity.get("acteco") or []
    marks = entity.get("marks") or []
    return {
        "rut": entity.get("rut"),
        "legal_name": entity.get("legal_name"),
        "tax_status": entity.get("tax_status"),
        "start_date": entity.get("start_date"),
        "termination_date": entity.get("termination_date"),
        "main_activity": entity.get("main_activity"),
        "main_region": entity.get("main_region"),
        "sales_band_code": entity.get("sales_band_code"),
        "sales_band": entity.get("sales_band") or entity.get("sales_band_label"),
        "workers": entity.get("workers"),
        "taxpayer_type": entity.get("taxpayer_type"),
        "taxpayer_subtype": entity.get("taxpayer_subtype"),
        "history_available_years": entity.get("history_available_years") or [],
        "activities": [
            {
                "codigo": a.get("codigo"),
                "glosa": a.get("glosa"),
                "estado": a.get("estado"),
                "categoria_tributaria": a.get("categoria_tributaria"),
            }
            for a in activities[:8]
        ],
        "marks": [
            {
                "signal_type": m.get("signal_type"),
                "severity": m.get("severity"),
                "year": m.get("year"),
                "why": m.get("why"),
            }
            for m in marks[:12]
        ],
    }


def build() -> dict:
    if not FINDINGS.exists():
        raise FileNotFoundError(FINDINGS)
    findings = json.loads(FINDINGS.read_text(encoding="utf-8"))
    relation_findings = findings.get("relation_findings") or []

    enrichment = {"entities": {}}
    if ENRICHMENT.exists():
        try:
            enrichment = json.loads(ENRICHMENT.read_text(encoding="utf-8"))
        except Exception:
            enrichment = {"entities": {}}
    sii_entities = enrichment.get("entities") or {}

    provider_ids = []
    seen = set()
    for row in relation_findings:
        pid = str(row.get("provider_id") or "")
        if pid and pid not in seen:
            seen.add(pid)
            provider_ids.append(pid)

    out_entities = {}
    rut_resolved = 0
    sii_matched = 0
    unresolved = 0
    for pid in provider_ids:
        rut = _rut_from_provider_id(pid)
        if not rut:
            unresolved += 1
            out_entities[pid] = {
                "provider_id": pid,
                "identity_status": "NO_RUT_RESOLVED",
                "identity_note": "La identidad publicada no contiene un RUT validado; no se intenta inferirlo desde hashes o nombres.",
                "sii": None,
            }
            continue
        rut_resolved += 1
        entity = sii_entities.get(rut) or sii_entities.get(f"ENT-RUT-{rut}")
        if entity:
            sii_matched += 1
        out_entities[pid] = {
            "provider_id": pid,
            "identity_status": "RUT_RESOLVED",
            "rut": rut,
            "sii": _compact(entity) if entity else None,
        }

    payload = {
        "schema": "RIGP-CASE-ENTITY-CONTEXT-v1",
        "guardrail": GUARDRAIL,
        "coverage": {
            "providers_published": len(provider_ids),
            "providers_with_valid_rut": rut_resolved,
            "providers_matched_in_sii": sii_matched,
            "providers_without_valid_rut": unresolved,
        },
        "entities": out_entities,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")
    print("[RIGP] case entity context", payload["coverage"], "bytes", OUT.stat().st_size)
    return payload


if __name__ == "__main__":
    build()
