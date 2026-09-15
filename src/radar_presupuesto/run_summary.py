from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

GUARDRAIL = (
    "Este resumen describe cobertura y comportamiento operativo del radar. "
    "No acredita irregularidad, fraude, corrupción, delito funcionario, lavado de activos "
    "ni responsabilidad de una entidad o persona."
)


def _load(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _ratio(num: int | float, den: int | float) -> float:
    return round(float(num or 0) / float(den or 1), 6) if den else 0.0


def _first_int(source: dict, keys: tuple[str, ...], default: int | None = 0) -> int | None:
    """Primer valor presente entre `keys`, respetando el cero como valor legítimo.

    Una cadena de `or` descarta el 0 igual que descarta la clave ausente, y ahí
    se pierde la diferencia entre medir cero y no haber medido.
    """
    for key in keys:
        if key in source and source[key] is not None:
            try:
                return int(source[key])
            except (TypeError, ValueError):
                continue
    return default


def build_run_summary(
    findings_json: str = "docs/data/investigative_findings.json",
    bundle_json: str = "docs/data/operational_bundle.json",
    health_json: str = "docs/data/signal_health.json",
    procurement_json: str = "docs/data/procurement_context.json",
    entity_context_json: str = "docs/data/case_entity_context.json",
    snapshot_json: str = "docs/data/snapshot_manifest.json",
    output_json: str = "docs/data/radar_run_summary.json",
) -> dict:
    findings = _load(findings_json)
    bundle = _load(bundle_json)
    health = _load(health_json)
    procurement = _load(procurement_json)
    entities = _load(entity_context_json)
    snapshots = _load(snapshot_json)

    rows = findings.get("relation_findings") or []
    pattern_counts: Counter[str] = Counter()
    attention_counts: Counter[str] = Counter()
    peer_count = 0
    for row in rows:
        attention_counts[str(row.get("attention_level") or "SEGUIMIENTO")] += 1
        primary = row.get("primary_pattern") or {}
        pattern = primary.get("pattern_id") or primary.get("pattern") or primary.get("name")
        if pattern:
            pattern_counts[str(pattern)] += 1
        if row.get("peer_context"):
            peer_count += 1

    signal_rows = health.get("signals") or []
    signal_counts = {
        str(x.get("signal_type")): int(x.get("signal_count") or 0)
        for x in signal_rows
    }
    signal_shares = {
        str(x.get("signal_type")): float(x.get("share_of_signal_universe") or 0)
        for x in signal_rows
    }
    signal_statuses = {
        str(x.get("signal_type")): str(x.get("status") or "UNKNOWN")
        for x in signal_rows
    }

    snap_rows = snapshots.get("snapshots") or []
    years = sorted({int(x.get("year")) for x in snap_rows if x.get("year") is not None})
    total_rows = sum(int(x.get("normalized_rows") or 0) for x in snap_rows)

    publication = bundle.get("publication") or findings.get("publication_selection") or {}
    available = int(
        publication.get("relations_available")
        or findings.get("relation_count_before_cap")
        or len(rows)
    )
    published = int(
        publication.get("relations_published")
        or findings.get("counts", {}).get("relations_returned")
        or len(rows)
    )

    proc_requested = int(
        procurement.get("findings_requested")
        or procurement.get("coverage", {}).get("findings_requested")
        or 0
    )
    proc_with_oc = int(
        procurement.get("findings_with_purchase_order")
        or procurement.get("coverage", {}).get("findings_with_purchase_order")
        or 0
    )

    entity_cov = entities.get("coverage") or {}
    # El productor de la capa de entidad escribe `providers_published` y
    # `providers_matched_in_sii`; este resumen buscaba tres alias que nadie
    # escribe nunca, así que caía al 0 por defecto e informaba una capa muerta
    # cuando estaba viva. Se listan primero los nombres reales.
    entity_requested = _first_int(
        entity_cov,
        ("providers_published", "published_providers", "providers_requested", "requested"),
        default=len(rows),
    )
    entity_matched = _first_int(
        entity_cov,
        ("providers_matched_in_sii", "providers_with_sii_context", "matched_entities", "matched"),
        default=None,
    )
    # Distinto es «ningún proveedor cruzó» y «nadie midió el cruce». Lo primero
    # es un resultado; lo segundo, una capa que no puede calcularse y que el
    # invariante obliga a declarar en vez de publicar un cero.
    entity_measured = entity_matched is not None
    if not entity_measured:
        entity_matched = 0

    context_cov = findings.get("context_coverage") or bundle.get("finding_context_coverage") or {}
    primary_pattern_count = int(context_cov.get("relations_with_primary_pattern") or sum(pattern_counts.values()))
    peer_count = int(context_cov.get("relations_with_peer_context") or peer_count)

    warnings: list[dict] = []
    for row in signal_rows:
        status = str(row.get("status") or "")
        if status != "ACTIVE":
            warnings.append(
                {
                    "type": "SIGNAL_HEALTH",
                    "signal_type": row.get("signal_type"),
                    "status": status,
                    "note": row.get("note"),
                }
            )
    if years and len(years) < 5:
        warnings.append(
            {
                "type": "HISTORICAL_COVERAGE",
                "status": "INSUFFICIENT",
                "note": "La corrida efectiva cubre menos de cinco años; no debe tratarse como ventana histórica estable.",
            }
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "schema": "RIGP-RUN-SUMMARY-v1",
        "guardrail": GUARDRAIL,
        "analysis_window": {
            **(bundle.get("analysis_window") or findings.get("analysis_window") or {}),
            "effective_years": years,
            "effective_year_count": len(years),
            "normalized_rows": total_rows,
        },
        "signals": {
            "total": int(health.get("total_signals") or sum(signal_counts.values())),
            "counts": signal_counts,
            "shares": signal_shares,
            "statuses": signal_statuses,
            "active_types": int(health.get("active_signal_types") or 0),
            "types_needing_review": int(health.get("needs_review_signal_types") or 0),
            "dominant_signal": max(signal_counts, key=signal_counts.get) if signal_counts else None,
            "dominant_share": max(signal_shares.values()) if signal_shares else 0.0,
        },
        "findings": {
            "relations_available": available,
            "relations_published": published,
            "publication_ratio": _ratio(published, available),
            "attention_levels": dict(attention_counts),
            "published_by_signal": publication.get("published_by_signal") or {},
            "selection_method": (
                findings.get("publication_selection", {}).get("method")
                or publication.get("method")
                or "unknown"
            ),
        },
        "context": {
            "peer_context_relations": peer_count,
            "peer_context_coverage": _ratio(peer_count, published),
            "primary_pattern_relations": primary_pattern_count,
            "primary_pattern_coverage": _ratio(primary_pattern_count, published),
            "primary_pattern_distribution": dict(pattern_counts),
        },
        "procurement": {
            "findings_requested": proc_requested,
            "findings_with_purchase_order": proc_with_oc,
            "purchase_order_coverage": _ratio(proc_with_oc, proc_requested),
            "schema": procurement.get("schema"),
        },
        "sii": {
            "providers_requested": entity_requested,
            "providers_with_context": entity_matched,
            "context_coverage": _ratio(entity_matched, entity_requested),
            "coverage_state": "MEDIDO" if entity_measured else "NO_MEDIDO",
            "coverage_note": (
                None if entity_measured else
                "La capa de entidad no reportó cuántos proveedores cruzaron. El cero de "
                "arriba es ausencia de medición, no ausencia de cruce: no debe leerse como "
                "que ningún proveedor tiene perfil registral."
            ),
            "reported_coverage": entity_cov,
            "schema": entities.get("schema"),
        },
        "warnings": warnings,
        "interpretation": (
            "El resumen sirve para evaluar cobertura, diversidad, salud de detectores y disponibilidad de contexto. "
            "No recalibra automáticamente pesos ni umbrales y no transforma patrones en conclusiones jurídicas."
        ),
    }

    out = Path(output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return payload


def main() -> None:
    payload = build_run_summary()
    print("[RIGP summary] years:", payload["analysis_window"]["effective_years"])
    print("[RIGP summary] signals:", payload["signals"]["total"], payload["signals"]["statuses"])
    print("[RIGP summary] findings:", payload["findings"]["relations_published"])
    print("[RIGP summary] peer coverage:", payload["context"]["peer_context_coverage"])
    print("[RIGP summary] OC coverage:", payload["procurement"]["purchase_order_coverage"])
    print("[RIGP summary] SII coverage:", payload["sii"]["context_coverage"])


if __name__ == "__main__":
    main()
