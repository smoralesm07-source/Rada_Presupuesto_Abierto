#!/usr/bin/env python3
"""Build a compact analyst-facing findings payload for GitHub Pages.

This is a publication fallback only. The operational pipeline remains the
canonical producer of investigative_findings.json. Pages must never force the
browser to aggregate the full investigation_queue.json (tens of thousands of
signals), because doing so duplicates CPU/memory work and can freeze the UI.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "docs" / "data" / "investigation_queue.json"
OUT = ROOT / "docs" / "data" / "investigative_findings.json"
MAX_RELATIONS = 2500
MAX_HOTSPOTS = 500
MAX_NETWORKS = 250

GUARDRAIL = (
    "Un hallazgo RIGP prioriza revisión documental y OSINT. No acredita "
    "irregularidad, delito funcionario, fraude, corrupción, lavado de activos "
    "ni responsabilidad de una entidad o persona."
)

SIGNAL_FAMILY = {
    "POTENTIAL_FRAGMENTATION": "DOCUMENTOS_Y_PAGOS",
    "EXACT_DUPLICATE_CANDIDATE": "DOCUMENTOS_Y_PAGOS",
    "PROVIDER_CONCENTRATION": "COMPETENCIA_Y_CONCENTRACION",
    "NEW_TO_SERIES_HIGH_SPEND": "ENTRADA_Y_CAMBIO_DE_ESCALA",
    "AMOUNT_OUTLIER": "MAGNITUD_ATIPICA",
    "PAYMENT_DELAY_OUTLIER": "EJECUCION_CONTRACTUAL",
    "YEAR_END_SPIKE": "EJECUCION_PRESUPUESTARIA",
    "NEWBORN_SUPPLIER": "CONTRAPARTE_Y_CAPACIDAD",
    "CAPACITY_MISMATCH": "CONTRAPARTE_Y_CAPACIDAD",
    "ACTIVITY_MISMATCH": "CONTRAPARTE_Y_CAPACIDAD",
    "TERMINATION_AFTER_PAYMENT": "CONTRAPARTE_Y_CAPACIDAD",
    "DORMANT_REACTIVATION": "CONTRAPARTE_Y_CAPACIDAD",
}

TITLES = {
    "CONVERGENCIA_MULTIFACTOR": "Varios patrones coinciden en la misma relación",
    "INTEGRIDAD_DOCUMENTAL_PAGOS": "Reiteración documental o de pagos que conviene validar",
    "COMPETENCIA_ADJUDICACION": "Concentración o irrupción relevante en la contratación",
    "CONCENTRACION_DEPENDENCIA": "Relación con concentración significativa",
    "IRRUPCION_CAMBIO_ESCALA": "Proveedor con irrupción o cambio de escala material",
    "EJECUCION_CONTRACTUAL": "Comportamiento contractual fuera de patrón",
    "EJECUCION_PRESUPUESTARIA": "Patrón temporal de ejecución que requiere contexto",
    "CONTRAPARTE_Y_CAPACIDAD": "Características registrales del proveedor que conviene contrastar",
    "PATRON_ATIPICO": "Patrón atípico que requiere contexto",
}


def finding_family(signal_types: list[str], signal_families: list[str]) -> str:
    st, sf = set(signal_types), set(signal_families)
    if len(sf) >= 3:
        return "CONVERGENCIA_MULTIFACTOR"
    if {"POTENTIAL_FRAGMENTATION", "EXACT_DUPLICATE_CANDIDATE"} <= st:
        return "INTEGRIDAD_DOCUMENTAL_PAGOS"
    if "PROVIDER_CONCENTRATION" in st and (
        "NEW_TO_SERIES_HIGH_SPEND" in st or "AMOUNT_OUTLIER" in st
    ):
        return "COMPETENCIA_ADJUDICACION"
    if "PROVIDER_CONCENTRATION" in st:
        return "CONCENTRACION_DEPENDENCIA"
    if "NEW_TO_SERIES_HIGH_SPEND" in st or "AMOUNT_OUTLIER" in st:
        return "IRRUPCION_CAMBIO_ESCALA"
    if "PAYMENT_DELAY_OUTLIER" in st:
        return "EJECUCION_CONTRACTUAL"
    if "YEAR_END_SPIKE" in st:
        return "EJECUCION_PRESUPUESTARIA"
    if st & {
        "CAPACITY_MISMATCH", "NEWBORN_SUPPLIER", "TERMINATION_AFTER_PAYMENT",
        "ACTIVITY_MISMATCH", "DORMANT_REACTIVATION",
    }:
        return "CONTRAPARTE_Y_CAPACIDAD"
    return "PATRON_ATIPICO"


def attention_level(g: dict) -> str:
    families = g["signal_family_count"]
    types = g["signal_type_count"]
    score = g["max_priority_score"]
    cgr = g["cgr_match_count"]
    if (families >= 2 and score >= 70) or (families >= 2 and cgr > 0) or types >= 3:
        return "ATENCION_INMEDIATA"
    if score >= 70 or (families >= 2 and score >= 50) or (cgr > 0 and score >= 50):
        return "REVISION_PRIORITARIA"
    return "SEGUIMIENTO"


def why(level: str) -> str:
    if level == "ATENCION_INMEDIATA":
        return "Convergen patrones independientes o evidencia candidata suficiente para reconstruir primero esta relación."
    if level == "REVISION_PRIORITARIA":
        return "La relación reúne prioridad suficiente para una revisión documental dirigida."
    return "Mantener visible y reevaluar si aparecen nuevas señales o evidencia."


def level_rank(level: str) -> int:
    return {"ATENCION_INMEDIATA": 0, "REVISION_PRIORITARIA": 1, "SEGUIMIENTO": 2}.get(level, 3)


def compact_findings(queue_payload: dict) -> dict:
    rows = queue_payload.get("queue") or []
    groups: dict[tuple[str, str, int], dict] = {}
    eligible_signal_count = 0

    for r in rows:
        score = float(r.get("investigation_priority_score") or 0)
        tier = str(r.get("priority_tier") or "")
        cgr = int(r.get("cgr_match_count") or 0)
        # Publication payload is analyst-facing: keep P1/P2 and externally-supported signals.
        if score < 50 and tier not in {"P1", "P2"} and cgr <= 0:
            continue
        eligible_signal_count += 1
        oid = str(r.get("organization_id") or "")
        pid = str(r.get("provider_id") or r.get("recipient_id") or "")
        year = int(r.get("periodo") or r.get("year") or 0)
        if not oid or not pid or not year:
            continue
        key = (oid, pid, year)
        if key not in groups:
            groups[key] = {
                "finding_id": f"{oid}|{pid}|{year}",
                "organization_id": oid,
                "provider_id": pid,
                "periodo": year,
                "organization_name": r.get("organization_name") or oid,
                "provider_name": r.get("provider_or_recipient_name") or r.get("provider_name") or pid,
                "signal_types": [],
                "signal_families": [],
                "max_priority_score": 0.0,
                "p1_signals": 0,
                "p2_signals": 0,
                "cgr_match_count": 0,
                "cgr_max_confidence": 0.0,
                "max_transaction_amount": 0.0,
            }
        g = groups[key]
        signal = str(r.get("signal_type") or "")
        if signal and signal not in g["signal_types"]:
            g["signal_types"].append(signal)
        family = SIGNAL_FAMILY.get(signal, "OTRA_SENAL")
        if family not in g["signal_families"]:
            g["signal_families"].append(family)
        g["max_priority_score"] = max(g["max_priority_score"], score)
        g["p1_signals"] += int(tier == "P1")
        g["p2_signals"] += int(tier == "P2")
        g["cgr_match_count"] = max(g["cgr_match_count"], cgr)
        g["cgr_max_confidence"] = max(g["cgr_max_confidence"], float(r.get("cgr_max_confidence") or 0))
        g["max_transaction_amount"] = max(g["max_transaction_amount"], float(r.get("transaction_amount") or 0))

    relations = []
    for g in groups.values():
        g["signal_type_count"] = len(g["signal_types"])
        g["signal_family_count"] = len(g["signal_families"])
        g["finding_family"] = finding_family(g["signal_types"], g["signal_families"])
        g["attention_level"] = attention_level(g)
        g["finding_title"] = TITLES[g["finding_family"]]
        g["why_review"] = why(g["attention_level"])
        g["guardrail"] = GUARDRAIL
        relations.append(g)

    relations.sort(
        key=lambda x: (
            level_rank(x["attention_level"]),
            -float(x["max_priority_score"]),
            -int(x["signal_family_count"]),
            -int(x["signal_type_count"]),
            -float(x["max_transaction_amount"]),
        )
    )
    published = relations[:MAX_RELATIONS]

    services: dict[str, dict] = {}
    providers: dict[str, dict] = {}
    provider_orgs: dict[str, set[str]] = defaultdict(set)
    provider_families: dict[str, set[str]] = defaultdict(set)

    for r in published:
        oid, pid = r["organization_id"], r["provider_id"]
        s = services.setdefault(oid, {
            "organization_id": oid,
            "organization_name": r["organization_name"],
            "finding_count": 0,
            "immediate_count": 0,
            "provider_count": 0,
            "max_priority_score": 0,
            "_providers": set(),
        })
        s["finding_count"] += 1
        s["immediate_count"] += int(r["attention_level"] == "ATENCION_INMEDIATA")
        s["max_priority_score"] = max(s["max_priority_score"], r["max_priority_score"])
        s["_providers"].add(pid)

        p = providers.setdefault(pid, {
            "provider_id": pid,
            "provider_name": r["provider_name"],
            "finding_count": 0,
            "immediate_count": 0,
            "service_count": 0,
            "max_priority_score": 0,
            "_services": set(),
        })
        p["finding_count"] += 1
        p["immediate_count"] += int(r["attention_level"] == "ATENCION_INMEDIATA")
        p["max_priority_score"] = max(p["max_priority_score"], r["max_priority_score"])
        p["_services"].add(oid)
        provider_orgs[pid].add(oid)
        provider_families[pid].add(r["finding_family"])

    service_rows = []
    for s in services.values():
        s["provider_count"] = len(s.pop("_providers"))
        service_rows.append(s)
    service_rows.sort(key=lambda x: (-x["immediate_count"], -x["finding_count"], -x["max_priority_score"]))

    provider_rows = []
    for p in providers.values():
        p["service_count"] = len(p.pop("_services"))
        provider_rows.append(p)
    provider_rows.sort(key=lambda x: (-x["immediate_count"], -x["service_count"], -x["finding_count"], -x["max_priority_score"]))

    networks = []
    by_provider_name = {p["provider_id"]: p["provider_name"] for p in provider_rows}
    by_provider_score = {p["provider_id"]: p["max_priority_score"] for p in provider_rows}
    for pid, orgs in provider_orgs.items():
        fams = provider_families[pid]
        score = by_provider_score.get(pid, 0)
        if len(orgs) >= 3 and len(fams) >= 2 and score >= 50:
            networks.append({
                "provider_id": pid,
                "provider_name": by_provider_name.get(pid, pid),
                "service_count": len(orgs),
                "finding_family_count": len(fams),
                "max_priority_score": score,
                "interpretation": "El proveedor aparece en varios servicios y familias de hallazgo. Esta red tipo estrella no implica coordinación impropia entre actores.",
            })
    networks.sort(key=lambda x: (-x["service_count"], -x["finding_family_count"], -x["max_priority_score"]))

    return {
        "methodology_version": "RIGP-FINDINGS-PAGES-v1",
        "guardrail": GUARDRAIL,
        "publication_note": "Payload compacto para navegación web; no reemplaza el dataset analítico completo.",
        "source_signal_count": int(queue_payload.get("total_signals") or len(rows)),
        "eligible_signal_count": eligible_signal_count,
        "relation_count_before_cap": len(relations),
        "relation_count": len(published),
        "relation_cap": MAX_RELATIONS,
        "relation_findings": published,
        "service_hotspots": service_rows[:MAX_HOTSPOTS],
        "provider_hotspots": provider_rows[:MAX_HOTSPOTS],
        "network_candidates": networks[:MAX_NETWORKS],
    }


def main() -> None:
    if not QUEUE.exists():
        print(f"[RIGP Pages] queue absent: {QUEUE}")
        return
    payload = json.loads(QUEUE.read_text(encoding="utf-8"))
    compact = compact_findings(payload)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(compact, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    size_mb = OUT.stat().st_size / 1024 / 1024
    print(
        "[RIGP Pages] compact findings:",
        compact["relation_count"],
        "relations from",
        compact["source_signal_count"],
        f"signals · {size_mb:.2f} MiB",
    )


if __name__ == "__main__":
    main()
