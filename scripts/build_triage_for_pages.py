#!/usr/bin/env python3
"""Build the triage payload the app actually opens on.

This replaces the old publication path, which grouped a queue that had already
been cut to 250 signals and produced 105 relations out of 79.871 — one signal
type each, so nothing ever converged.

Three things changed here. It reads the v2 queue (and still understands v1, so a
deploy before the next pipeline run does not break). It carries **both axes** —
review priority and LA/FT compatibility — instead of collapsing them. And it
states its own coverage: how many signals existed, how many were published, and
which analytical layers are still pending, so the interface can say what it does
not know instead of looking complete.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from radar_presupuesto.typologies import (  # noqa: E402
    GUARDRAIL as TYPOLOGY_GUARDRAIL,
    OBSERVABLE_LAYERS,
    PATTERN_LABEL,
    PATTERN_LAYER,
    TYPOLOGIES,
    alignment_level,
    match_all,
)

QUEUE = ROOT / "docs" / "data" / "investigation_queue.json"
ENTITY_SIGNALS = ROOT / "docs" / "data" / "entity_signals.json"
EXPLORE = ROOT / "docs" / "data" / "explore_context.json"
OPACITY = ROOT / "docs" / "data" / "opacity_index.json"
PROCUREMENT = ROOT / "docs" / "data" / "procurement_status.json"
OUT = ROOT / "docs" / "data" / "triage.json"

MAX_RELATIONS = 4000

GUARDRAIL = (
    "RIGP prioriza revisión documental y OSINT sobre gasto público. No acredita "
    "irregularidad, delito funcionario, fraude, corrupción ni lavado de activos, "
    "y no atribuye responsabilidad a ninguna persona o entidad."
)

SIGNAL_LABEL = dict(PATTERN_LABEL)


def load(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def queue_rows(payload: dict) -> tuple[list[dict], str]:
    """Read either queue schema; the publication must survive a stale input."""
    rows = payload.get("queue") or []
    schema = str(payload.get("schema") or "RIGP-INVESTIGATION-QUEUE-v1")
    return rows, schema


def score_of(row: dict) -> float:
    for key in ("review_priority_score", "investigation_priority_score"):
        value = row.get(key)
        if value is not None:
            return float(value)
    return 0.0


def build() -> dict:
    queue_payload = load(QUEUE, {})
    rows, queue_schema = queue_rows(queue_payload)
    entity_payload = load(ENTITY_SIGNALS, {})
    entity_by_provider = entity_payload.get("providers") or {}
    explore = load(EXPLORE, {})
    opacity = load(OPACITY, {})
    procurement = load(PROCUREMENT, {})

    opacity_by_service = {
        str(s.get("organization_id")): s for s in (opacity.get("services") or [])
    }

    grouped: dict[tuple[str, str, int], dict] = {}
    for row in rows:
        org = str(row.get("organization_id") or "")
        provider = str(row.get("provider_id") or row.get("recipient_id") or "")
        try:
            year = int(row.get("periodo") or row.get("year") or 0)
        except (TypeError, ValueError):
            year = 0
        if not org or not provider or not year:
            continue
        key = (org, provider, year)
        entry = grouped.setdefault(
            key,
            {
                "finding_id": f"{org}|{provider}|{year}",
                "organization_id": org,
                "organization_name": row.get("organization_name") or org,
                "provider_id": provider,
                "provider_name": row.get("provider_or_recipient_name")
                or row.get("provider_name")
                or provider,
                "periodo": year,
                "signals": [],
                "review_priority_score": 0.0,
                "peer_group": row.get("peer_group") or "",
                "min_prevalence": 1.0,
                "max_transaction_amount": 0.0,
                "cgr_match_grade": row.get("cgr_match_grade") or "NONE",
                "cgr_match_count": 0,
                "priority_explanation": row.get("priority_explanation") or "",
                "region": row.get("region") or "",
            },
        )
        signal = str(row.get("signal_type") or "")
        if signal and signal not in entry["signals"]:
            entry["signals"].append(signal)
        entry["review_priority_score"] = max(entry["review_priority_score"], score_of(row))
        prevalence = row.get("pattern_prevalence")
        if prevalence is not None:
            entry["min_prevalence"] = min(entry["min_prevalence"], float(prevalence))
        entry["max_transaction_amount"] = max(
            entry["max_transaction_amount"], float(row.get("transaction_amount") or 0)
        )
        entry["cgr_match_count"] = max(
            entry["cgr_match_count"], int(row.get("cgr_match_count") or 0)
        )
        if row.get("priority_explanation") and not entry["priority_explanation"]:
            entry["priority_explanation"] = row["priority_explanation"]

    relations: list[dict] = []
    for (org, provider, year), entry in grouped.items():
        patterns = set(entry["signals"])
        entity_entry = entity_by_provider.get(provider) or {}
        entity_signals = [
            s for s in (entity_entry.get("signals") or [])
            if not s.get("periodo") or int(s.get("periodo") or 0) <= year
        ]
        patterns |= {str(s.get("signal_type")) for s in entity_signals}

        service_opacity = opacity_by_service.get(org) or {}
        opacity_level = str(service_opacity.get("opacity_level") or "TRAZABLE")
        if opacity_level == "OPACA":
            patterns.add("OPAQUE_COUNTERPARTY")

        provider_ctx = (explore.get("providers") or {}).get(provider) or {}
        relation_ctx = (explore.get("relations") or {}).get(f"{org}|{provider}") or {}
        relation_amount = sum(
            float(x.get("amount_clp") or 0) for x in (relation_ctx.get("yearly") or [])
        )

        matches = match_all(patterns)
        best = matches[0] if matches else None
        laft = float(best["score"]) if best else 0.0

        families = sorted({PATTERN_LAYER.get(p, "TRANSACCION") for p in patterns})
        entry.update(
            {
                "signal_labels": [SIGNAL_LABEL.get(s, s) for s in entry["signals"]],
                "entity_signals": entity_signals,
                "observed_patterns": sorted(patterns),
                "layers_present": families,
                "laft_compatibility_score": laft,
                "laft_alignment": alignment_level(laft),
                "top_typology": best["typology"] if best else "",
                "top_typology_name": best["typology_name"] if best else "",
                "typology_question": best["question"] if best else "",
                "typologies": matches,
                "opacity_level": opacity_level,
                "opaque_share": float(service_opacity.get("opaque_share") or 0),
                "relation_amount": relation_amount,
                "provider_total_spend": sum(
                    float(x.get("amount_clp") or 0) for x in (provider_ctx.get("yearly") or [])
                ),
                "provider_rut": provider_ctx.get("rut")
                or (provider.split("RUT-", 1)[1] if "RUT-" in provider else ""),
                "guardrail": GUARDRAIL,
            }
        )
        relations.append(entry)

    # Ordena por prioridad de revisión; el eje LA/FT es un filtro, no el ranking.
    relations.sort(
        key=lambda r: (
            -r["review_priority_score"],
            -r["laft_compatibility_score"],
            -len(r["signals"]),
            -r["max_transaction_amount"],
        )
    )
    published = relations[:MAX_RELATIONS]

    facets = {
        "typologies": defaultdict(int),
        "alignments": defaultdict(int),
        "opacity": defaultdict(int),
        "years": defaultdict(int),
        "layers": defaultdict(int),
    }
    for relation in published:
        facets["typologies"][relation["top_typology"] or "SIN_TIPOLOGIA"] += 1
        facets["alignments"][relation["laft_alignment"]] += 1
        facets["opacity"][relation["opacity_level"]] += 1
        facets["years"][str(relation["periodo"])] += 1
        for layer in relation["layers_present"]:
            facets["layers"][layer] += 1

    pending_layers = sorted(set(PATTERN_LAYER.values()) - OBSERVABLE_LAYERS)
    return {
        "schema": "RIGP-TRIAGE-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "guardrail": GUARDRAIL,
        "typology_guardrail": TYPOLOGY_GUARDRAIL,
        "axes": {
            "review_priority_score": "Cuánto conviene mirar esto primero (0-100).",
            "laft_compatibility_score": (
                "Cuántos patrones de una tipología LA/FT están presentes (0-100). "
                "No es probabilidad de delito."
            ),
        },
        "source": {
            "queue_schema": queue_schema,
            "queue_generated_at": queue_payload.get("generated_at"),
            "signals_total": int(queue_payload.get("total_signals") or 0),
            "signals_published": len(rows),
            "priority_tiers": queue_payload.get("priority_tiers") or {},
            "publication_policy": queue_payload.get("publication_policy") or {},
            "peer_group_definition": queue_payload.get("peer_group_definition") or "",
        },
        "coverage": {
            "relations": len(relations),
            "relations_published": len(published),
            "services": len({r["organization_id"] for r in published}),
            "providers": len({r["provider_id"] for r in published}),
            "relations_with_typology": sum(1 for r in published if r["top_typology"]),
            "entity_layer_providers": len(entity_by_provider),
            "pending_layers": pending_layers,
            "procurement_state": procurement.get("integration_state", "ADAPTER_READY_SOURCE_PENDING"),
            "opacity_overall": (opacity.get("overall") or {}).get("opaque_share"),
        },
        "facets": {k: dict(v) for k, v in facets.items()},
        "typology_catalog": [
            {
                "code": t.code,
                "name": t.name,
                "question": t.question,
                "sustains": list(t.sustains),
                "discards": list(t.discards),
                "documents": list(t.documents),
                "evidence_ceiling": t.evidence_ceiling,
                "reachable_today": t.anchorable_now,
                "missing_layers": list(t.missing_layers),
            }
            for t in TYPOLOGIES
        ],
        "pattern_labels": SIGNAL_LABEL,
        "relations": published,
    }


def main() -> None:
    payload = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    coverage = payload["coverage"]
    source = payload["source"]
    print(
        f"[RIGP Triage] {coverage['relations_published']} relaciones "
        f"({coverage['services']} servicios, {coverage['providers']} proveedores) "
        f"desde {source['signals_published']} señales publicadas de {source['signals_total']} totales "
        f"· esquema {source['queue_schema']} · {OUT.stat().st_size / 1024:.1f} KiB"
    )
    if coverage["pending_layers"]:
        print(f"[RIGP Triage] capas pendientes de integración: {', '.join(coverage['pending_layers'])}")


if __name__ == "__main__":
    main()
