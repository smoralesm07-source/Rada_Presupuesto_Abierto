#!/usr/bin/env python3
"""Build a bounded ownership/control resolution queue for RIGP Pages.

The queue prioritizes direct recipients whose ownership/control identity still
requires documentary resolution. It does not infer shareholders/controllers and
never converts name similarity into identity.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BENEFIT = ROOT / "docs" / "data" / "benefit_context.json"
OUT = ROOT / "docs" / "data" / "ownership_resolution_queue.json"
MAX_ROWS = 300

SOURCES = [
    {
        "id": "RES_ACTUACIONES",
        "name": "RES · Actuaciones",
        "url": "https://www.registrodeempresasysociedades.cl/BuscarActuaciones2.aspx",
        "purpose": "Constitución, modificaciones, administración, designaciones y cambios societarios que consten públicamente.",
    },
    {
        "id": "RES_PODERES",
        "name": "RES · Registro de Poderes",
        "url": "https://www.registrodeempresasysociedades.cl/BuscarActuaciones2.aspx",
        "purpose": "Poderes, representantes, administradores, gerentes y delegaciones que consten en el RES.",
    },
    {
        "id": "DIARIO_OFICIAL",
        "name": "Diario Oficial · Sociedades",
        "url": "https://www.diariooficial.interior.gob.cl/sociedades-web",
        "purpose": "Extractos públicos de constitución, modificación, administración, capital y disolución.",
    },
    {
        "id": "MERCADO_PUBLICO",
        "name": "Mercado Público",
        "url": "https://www.mercadopublico.cl/",
        "purpose": "Documentos de procesos y contratos que puedan identificar representantes, firmantes o antecedentes del proveedor.",
    },
    {
        "id": "CMF",
        "name": "CMF · Entidades fiscalizadas",
        "url": "https://www.cmfchile.cl/portal/principal/613/w3-channel.html",
        "purpose": "Directores, administradores, hechos esenciales u otra información pública cuando la entidad esté bajo supervisión CMF.",
    },
]


def unresolved_reasons(c: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if not c.get("rut"):
        reasons.append("RUT_RECEPTOR_FALTANTE")
    ownership = c.get("ownership_control") or {}
    if ownership.get("status") != "INTEGRADO":
        reasons.append("CONTROL_NO_RESUELTO")
    if not ownership.get("confirmed_people"):
        reasons.append("PERSONA_NATURAL_NO_RESUELTA")
    reasons.append("VIGENCIA_CONTROL_PENDIENTE")
    return reasons


def source_ids(c: dict[str, Any]) -> list[str]:
    # Sources are suggestions, not evidence. Order favors legal/official records.
    ids = ["RES_ACTUACIONES", "RES_PODERES", "DIARIO_OFICIAL", "MERCADO_PUBLICO"]
    if str(c.get("entity_kind") or "") == "SOCIEDAD":
        ids.append("CMF")
    return ids


def main() -> None:
    if not BENEFIT.exists():
        print("[RIGP Ownership] benefit context absent; not generated")
        return

    benefit = json.loads(BENEFIT.read_text(encoding="utf-8"))
    candidates = list((benefit.get("candidates") or {}).values())
    rows: list[dict[str, Any]] = []

    for c in candidates:
        priority = int(round(float(c.get("verification_priority") or 0)))
        max_finding = int(round(float(c.get("max_priority_score") or 0)))
        rows.append(
            {
                "provider_id": str(c.get("provider_id") or ""),
                "provider_name": c.get("provider_name"),
                "provider_rut": c.get("rut") or "",
                "entity_kind": c.get("entity_kind") or "NO_DETERMINADO",
                "verification_priority": priority,
                "max_finding_priority": max_finding,
                "finding_count": int(c.get("finding_count") or 0),
                "immediate_count": int(c.get("immediate_count") or 0),
                "services_in_findings": int(c.get("services_in_findings") or 0),
                "years": c.get("years") or c.get("periods") or [],
                "top_services": (c.get("top_services") or [])[:5],
                "unresolved_reasons": unresolved_reasons(c),
                "suggested_sources": source_ids(c),
                "resolution_status": "PENDIENTE",
                "identity_rule": "RUT confirmado permite resolver identidad transversal. Coincidencia de nombre sin RUT nunca confirma que dos registros sean la misma persona o sociedad.",
            }
        )

    rows.sort(
        key=lambda x: (
            -int(x["immediate_count"] > 0),
            -x["verification_priority"],
            -x["max_finding_priority"],
            -x["finding_count"],
        )
    )
    source_lookup = {s["id"]: s for s in SOURCES}
    payload = {
        "schema": "RIGP-OWNERSHIP-RESOLUTION-v1",
        "methodology": "RIGP-OWNERSHIP-IDENTITY-v1",
        "generated_at": benefit.get("generated_at"),
        "total_candidates": len(rows),
        "published_candidates": min(len(rows), MAX_ROWS),
        "capped": len(rows) > MAX_ROWS,
        "queue": rows[:MAX_ROWS],
        "sources": source_lookup,
        "identity_states": [
            "RUT_CONFIRMADO",
            "IDENTIDAD_DOCUMENTADA_SIN_RUT",
            "CANDIDATO_POR_NOMBRE",
            "DESCARTADO",
        ],
        "guardrail": "Esta cola prioriza resolución de propiedad, control, administración y representación. No identifica beneficiarios ilícitos. Un nombre coincidente no confirma identidad; la convergencia transversal requiere un identificador o evidencia documental suficiente.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(
        "[RIGP Ownership] queue:",
        f"{OUT.stat().st_size / 1024:.1f} KiB ·",
        f"{payload['published_candidates']}/{payload['total_candidates']} recipients",
    )


if __name__ == "__main__":
    main()
