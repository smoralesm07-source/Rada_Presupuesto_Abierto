#!/usr/bin/env python3
"""Build a compact benefit-verification context for RIGP Pages.

This product does NOT identify illicit beneficiaries. It organizes direct public
payment recipients and the evidence gaps that must be closed before attributing
ownership, control or final benefit to a person or company.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FINDINGS = ROOT / "docs" / "data" / "investigative_findings.json"
EXPLORE = ROOT / "docs" / "data" / "explore_context.json"
ENRICH = ROOT / "docs" / "data" / "entity_enrichment_v1.json"
OUT = ROOT / "docs" / "data" / "benefit_context.json"


def canon_rut(value: object) -> str:
    s = "".join(ch for ch in str(value or "").upper() if ch.isdigit() or ch == "K")
    return f"{s[:-1]}-{s[-1]}" if len(s) >= 2 else ""


def provider_rut(provider_id: str, provider_ctx: dict[str, Any] | None) -> str:
    if provider_ctx and provider_ctx.get("rut"):
        return canon_rut(provider_ctx.get("rut"))
    token = str(provider_id or "")
    if "RUT-" in token:
        return canon_rut(token.split("RUT-", 1)[1])
    return ""


def entity_kind(entity: dict[str, Any] | None) -> str:
    if not entity:
        return "NO_DETERMINADO"
    text = " ".join(
        str(entity.get(k) or "")
        for k in ("taxpayer_type", "taxpayer_subtype", "taxpayer_subtype_code")
    ).upper()
    if "PERSONA NATURAL" in text or "NATURAL" in text:
        return "PERSONA"
    return "SOCIEDAD"


def sev_points(mark: dict[str, Any]) -> int:
    return {"HIGH": 5, "MEDIUM": 4, "LOW": 2}.get(str(mark.get("severity") or "").upper(), 1)


def verification_score(rows: list[dict[str, Any]], entity: dict[str, Any] | None) -> tuple[int, dict[str, int]]:
    max_priority = max((float(r.get("max_priority_score") or 0) for r in rows), default=0)
    services = len({str(r.get("organization_id") or "") for r in rows if r.get("organization_id")})
    families = len({str(r.get("finding_family") or "") for r in rows if r.get("finding_family")})
    immediate = sum(1 for r in rows if r.get("attention_level") == "ATENCION_INMEDIATA")
    marks = (entity or {}).get("marks") or []
    parts = {
        "prioridad_hallazgos": min(40, round(max_priority * 0.40)),
        "recurrencia_servicios": min(18, max(0, services - 1) * 6),
        "convergencia_familias": min(16, families * 4),
        "atencion_inmediata": min(14, immediate * 7),
        "contexto_tributario": min(12, sum(sev_points(m) for m in marks)),
    }
    return min(100, sum(parts.values())), parts


def compact_mark(mark: dict[str, Any]) -> dict[str, Any]:
    return {
        "signal_type": mark.get("signal_type"),
        "severity": mark.get("severity"),
        "year": mark.get("year"),
        "why": mark.get("why"),
    }


def main() -> None:
    if not FINDINGS.exists() or not EXPLORE.exists():
        print("[RIGP Benefit] compact findings/explore context absent; not generated")
        return

    findings = json.loads(FINDINGS.read_text(encoding="utf-8"))
    explore = json.loads(EXPLORE.read_text(encoding="utf-8"))
    enrichment = json.loads(ENRICH.read_text(encoding="utf-8")) if ENRICH.exists() else {"entities": {}}
    entities = enrichment.get("entities") or {}
    rows = findings.get("relation_findings") or []

    by_provider: dict[str, list[dict[str, Any]]] = defaultdict(list)
    service_names: dict[str, str] = {}
    provider_names: dict[str, str] = {}
    for row in rows:
        pid = str(row.get("provider_id") or "")
        oid = str(row.get("organization_id") or "")
        if pid:
            by_provider[pid].append(row)
            provider_names.setdefault(pid, str(row.get("provider_name") or pid))
        if oid:
            service_names.setdefault(oid, str(row.get("organization_name") or oid))

    candidates: dict[str, Any] = {}
    service_candidates: dict[str, list[str]] = defaultdict(list)
    kinds = defaultdict(int)
    sii_matches = 0

    for pid, prows in by_provider.items():
        pctx = (explore.get("providers") or {}).get(pid) or {}
        rut = provider_rut(pid, pctx)
        tax = entities.get(rut) if rut else None
        if tax:
            sii_matches += 1
        kind = entity_kind(tax)
        kinds[kind] += 1
        score, components = verification_score(prows, tax)
        services = sorted({str(r.get("organization_id")) for r in prows if r.get("organization_id")})
        families = sorted({str(r.get("finding_family")) for r in prows if r.get("finding_family")})
        signals = sorted({str(s) for r in prows for s in (r.get("signal_types") or []) if s})
        years = sorted({str(r.get("periodo")) for r in prows if r.get("periodo")})

        relation_amount = 0.0
        relation_pairs_with_flow = 0
        for oid in services:
            rel = (explore.get("relations") or {}).get(f"{oid}|{pid}") or {}
            if rel.get("flow_available"):
                relation_pairs_with_flow += 1
                relation_amount += sum(float(x.get("amount_clp") or 0) for x in rel.get("yearly") or [])

        total_spend = sum(float(x.get("amount_clp") or 0) for x in pctx.get("yearly") or [])
        top_services = [
            {
                "organization_id": str(x.get("organization_id") or ""),
                "organization_name": x.get("organization_name") or x.get("organization_id"),
                "amount_clp": float(x.get("amount_clp") or 0),
            }
            for x in (pctx.get("top_services") or [])[:8]
        ]

        findings_compact = []
        for r in sorted(prows, key=lambda x: float(x.get("max_priority_score") or 0), reverse=True):
            findings_compact.append(
                {
                    "finding_id": r.get("finding_id"),
                    "organization_id": str(r.get("organization_id") or ""),
                    "organization_name": r.get("organization_name") or r.get("organization_id"),
                    "periodo": r.get("periodo"),
                    "finding_title": r.get("finding_title") or r.get("finding_family"),
                    "finding_family": r.get("finding_family"),
                    "attention_level": r.get("attention_level"),
                    "priority_score": float(r.get("max_priority_score") or 0),
                }
            )

        candidates[pid] = {
            "provider_id": pid,
            "provider_name": provider_names.get(pid, pid),
            "rut": rut,
            "entity_kind": kind,
            "stage": "RECEPTOR_DIRECTO",
            "verification_priority": score,
            "score_components": components,
            "services_in_findings": len(services),
            "finding_count": len(prows),
            "immediate_count": sum(1 for r in prows if r.get("attention_level") == "ATENCION_INMEDIATA"),
            "priority_count": sum(1 for r in prows if r.get("attention_level") == "REVISION_PRIORITARIA"),
            "max_priority_score": max((float(r.get("max_priority_score") or 0) for r in prows), default=0),
            "families": families,
            "signals": signals,
            "years": years,
            "max_transaction_amount": max((float(r.get("max_transaction_amount") or 0) for r in prows), default=0),
            "relation_amount_published": relation_amount,
            "relation_pairs_with_flow": relation_pairs_with_flow,
            "total_public_spend_published": total_spend,
            "top_services": top_services,
            "tax_profile": {
                "available": bool(tax),
                "legal_name": (tax or {}).get("legal_name"),
                "tax_status": (tax or {}).get("tax_status"),
                "start_date": (tax or {}).get("start_date"),
                "termination_date": (tax or {}).get("termination_date"),
                "taxpayer_type": (tax or {}).get("taxpayer_type"),
                "taxpayer_subtype": (tax or {}).get("taxpayer_subtype"),
                "sales_band_label": (tax or {}).get("sales_band_label"),
                "workers": (tax or {}).get("workers"),
                "main_region": (tax or {}).get("main_region"),
                "main_activity": (tax or {}).get("main_activity"),
                "marks": [compact_mark(m) for m in ((tax or {}).get("marks") or [])[:10]],
            },
            "ownership_control": {
                "status": "NO_INTEGRADO",
                "confirmed_people": [],
                "confirmed_companies": [],
                "coverage_note": "Las fuentes compactas actuales no contienen socios/accionistas, controladores, representantes legales ni transferencias posteriores. Estos vínculos deben documentarse antes de atribuir beneficio final.",
            },
            "findings": findings_compact,
        }
        for oid in services:
            service_candidates[oid].append(pid)

    for oid, ids in service_candidates.items():
        ids.sort(key=lambda x: candidates.get(x, {}).get("verification_priority", 0), reverse=True)

    services = {
        oid: {
            "organization_id": oid,
            "organization_name": service_names.get(oid, oid),
            "candidate_providers": ids,
        }
        for oid, ids in service_candidates.items()
    }

    payload = {
        "schema": "RIGP-BENEFIT-CONTEXT-v1",
        "methodology": "RIGP-BENEFIT-CHAIN-v1",
        "generated_at": findings.get("generated_at") or explore.get("generated_at"),
        "candidates": candidates,
        "services": services,
        "coverage": {
            "direct_recipients": len(candidates),
            "sii_matched": sii_matches,
            "classified_people": kinds["PERSONA"],
            "classified_companies": kinds["SOCIEDAD"],
            "unclassified": kinds["NO_DETERMINADO"],
            "ownership_control_sources_integrated": 0,
            "decision_side_people_integrated": 0,
        },
        "verification_chain": [
            {"stage": 1, "name": "Receptor económico directo", "status": "DISPONIBLE", "meaning": "Persona o sociedad que aparece como proveedor/receptor de recursos públicos en relaciones priorizadas."},
            {"stage": 2, "name": "Propiedad, control y administración", "status": "POR_INTEGRAR", "meaning": "Socios/accionistas, controladores, representantes legales, directores o administradores durante el periodo relevante."},
            {"stage": 3, "name": "Personas y sociedades vinculadas", "status": "POR_VERIFICAR", "meaning": "Vínculos documentados que permitan extender la trazabilidad más allá del receptor directo."},
            {"stage": 4, "name": "Beneficio final", "status": "NO_DETERMINADO", "meaning": "Sólo puede atribuirse con evidencia de propiedad/control, disposición del valor o transferencias posteriores."},
        ],
        "guardrail": "La prioridad de verificación de beneficio organiza a quién revisar primero. No es probabilidad de delito ni acredita que una persona o sociedad haya obtenido un beneficio ilícito. Un proveedor/receptor directo no equivale a beneficiario final.",
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(
        "[RIGP Benefit] compact context:",
        f"{OUT.stat().st_size / 1024:.1f} KiB ·",
        f"{len(candidates)} direct recipients ·",
        f"{sii_matches} SII matches",
    )


if __name__ == "__main__":
    main()
