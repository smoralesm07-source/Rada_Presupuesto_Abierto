#!/usr/bin/env python3
"""Build a compact, on-demand contextual exploration payload for RIGP Pages.

The browser must never parse spend_years_v1.json (~14 MiB). This builder reduces
that historical dataset to only the services and providers the published queue
actually references.

It reads the investigation queue directly rather than a derived findings file:
the triage payload needs the amounts this produces, so depending on triage here
would make the two builders circular.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "docs" / "data" / "investigation_queue.json"
YEARS = ROOT / "docs" / "data" / "spend_years_v1.json"
OUT = ROOT / "docs" / "data" / "explore_context.json"
TOP_COUNTERPARTS = 8


def flow_total(row: dict[str, Any]) -> float:
    return sum(float(x.get("amount_clp") or 0) for x in row.get("yearly") or [])


def main() -> None:
    if not QUEUE.exists() or not YEARS.exists():
        print("[RIGP Explore] source absent; compact context not generated")
        return

    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    hist = json.loads(YEARS.read_text(encoding="utf-8"))
    rows = [
        {
            "organization_id": row.get("organization_id"),
            "organization_name": row.get("organization_name"),
            "provider_id": row.get("provider_id") or row.get("recipient_id"),
            "provider_name": row.get("provider_or_recipient_name") or row.get("provider_name"),
        }
        for row in (queue.get("queue") or [])
        if row.get("organization_id") and (row.get("provider_id") or row.get("recipient_id"))
    ]

    service_profiles = {str(x.get("organization_id")): x for x in hist.get("services") or []}
    provider_profiles = {str(x.get("provider_id")): x for x in hist.get("providers") or []}
    flows = hist.get("flows") or []

    flows_by_service: dict[str, list[dict[str, Any]]] = {}
    flows_by_provider: dict[str, list[dict[str, Any]]] = {}
    flow_map: dict[tuple[str, str], dict[str, Any]] = {}
    for flow in flows:
        oid = str(flow.get("organization_id") or "")
        pid = str(flow.get("provider_id") or "")
        if not oid or not pid:
            continue
        flows_by_service.setdefault(oid, []).append(flow)
        flows_by_provider.setdefault(pid, []).append(flow)
        flow_map[(oid, pid)] = flow

    def parent_org(oid: str) -> str:
        if oid in service_profiles:
            return oid
        parent = oid.rsplit("-", 1)[0] if "-" in oid else oid
        return parent if parent in service_profiles else oid

    child_names: dict[str, str] = {}
    provider_names: dict[str, str] = {}
    for row in rows:
        oid = str(row.get("organization_id") or "")
        pid = str(row.get("provider_id") or "")
        child_names.setdefault(oid, str(row.get("organization_name") or oid))
        provider_names.setdefault(pid, str(row.get("provider_name") or pid))

    services: dict[str, Any] = {}
    for oid, display_name in child_names.items():
        parent = parent_org(oid)
        profile = service_profiles.get(parent)
        if not profile:
            continue
        area_code = oid.rsplit("-", 1)[-1] if oid != parent else None
        area = None
        if area_code:
            area = next(
                (x for x in profile.get("areas") or [] if str(x.get("area")) == str(area_code)),
                None,
            )
        top_flows = sorted(flows_by_service.get(parent, []), key=flow_total, reverse=True)[:TOP_COUNTERPARTS]
        services[oid] = {
            "organization_id": oid,
            "organization_name": display_name,
            "parent_organization_id": parent,
            "parent_organization_name": profile.get("organization_name") or parent,
            "main_region": profile.get("main_region"),
            "area": area,
            "yearly": profile.get("yearly") or [],
            "top_providers": [
                {
                    "provider_id": str(x.get("provider_id") or ""),
                    "provider_name": x.get("provider_name") or x.get("provider_id"),
                    "amount_clp": flow_total(x),
                }
                for x in top_flows
            ],
        }

    providers: dict[str, Any] = {}
    for pid, display_name in provider_names.items():
        profile = provider_profiles.get(pid)
        top_flows = sorted(flows_by_provider.get(pid, []), key=flow_total, reverse=True)[:TOP_COUNTERPARTS]
        providers[pid] = {
            "provider_id": pid,
            "provider_name": display_name,
            "profile_available": bool(profile),
            "rut": profile.get("rut") if profile else "",
            "first_year": profile.get("first_year") if profile else None,
            "yearly": profile.get("yearly") or [] if profile else [],
            "monthly": profile.get("monthly") or [] if profile else [],
            "top_services": [
                {
                    "organization_id": str(x.get("organization_id") or ""),
                    "organization_name": x.get("organization_name") or x.get("organization_id"),
                    "amount_clp": flow_total(x),
                }
                for x in top_flows
            ],
        }

    relations: dict[str, Any] = {}
    for row in rows:
        oid = str(row.get("organization_id") or "")
        pid = str(row.get("provider_id") or "")
        key = f"{oid}|{pid}"
        if key in relations:
            continue
        parent = parent_org(oid)
        flow = flow_map.get((parent, pid))
        service = service_profiles.get(parent)
        provider = provider_profiles.get(pid)
        yearly = []
        if flow:
            service_year = {int(x.get("year")): x for x in (service or {}).get("yearly") or []}
            provider_year = {int(x.get("year")): x for x in (provider or {}).get("yearly") or []}
            for item in flow.get("yearly") or []:
                year = int(item.get("year") or 0)
                amount = float(item.get("amount_clp") or 0)
                service_private = float((service_year.get(year) or {}).get("provider_amount_clp") or 0)
                provider_total = float((provider_year.get(year) or {}).get("amount_clp") or 0)
                yearly.append(
                    {
                        "year": year,
                        "amount_clp": amount,
                        "transactions": int(item.get("transactions") or 0),
                        "share_of_service_private": amount / service_private if service_private else None,
                        "share_of_provider": amount / provider_total if provider_total else None,
                    }
                )
        relations[key] = {
            "organization_id": oid,
            "provider_id": pid,
            "parent_organization_id": parent,
            "flow_available": bool(flow),
            "yearly": yearly,
        }

    payload = {
        "schema": "RIGP-EXPLORE-CONTEXT-v1",
        "generated_at": hist.get("generated_at"),
        "years": hist.get("years") or [],
        "services": services,
        "providers": providers,
        "relations": relations,
        "coverage": {
            "finding_relations": len(rows),
            "unique_pairs": len(relations),
            "relations_with_historical_flow": sum(1 for x in relations.values() if x["flow_available"]),
            "service_contexts": len(services),
            "provider_contexts": len(providers),
            "provider_profiles_available": sum(1 for x in providers.values() if x["profile_available"]),
        },
        "notes": {
            "service_mapping": "Las unidades compradoras/áreas de los hallazgos se normalizan al capítulo presupuestario padre para métricas históricas; el área específica se conserva cuando puede identificarse.",
            "relation_coverage": "El contexto de relación sólo se muestra cuando la relación está publicada en spend_years_v1. Su ausencia no significa inexistencia de transacciones.",
            "guardrail": "El contexto histórico ayuda a interpretar un hallazgo; no acredita irregularidad ni responsabilidad.",
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(
        "[RIGP Explore] compact context:",
        f"{OUT.stat().st_size / 1024:.1f} KiB ·",
        f"{payload['coverage']['relations_with_historical_flow']}/{payload['coverage']['unique_pairs']} relation pairs with historical flow",
    )


if __name__ == "__main__":
    main()
