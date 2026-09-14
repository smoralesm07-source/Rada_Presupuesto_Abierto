from __future__ import annotations

import json
from pathlib import Path


SCHEMA = "RIGP-BROWSER-PUBLICATION-v1"


def _compact_pattern(value: object, *, include_question: bool = True) -> dict | None:
    if not isinstance(value, dict):
        return None
    score = int(value.get("compatibility_score") or 0)
    code = value.get("pattern_code")
    label = value.get("pattern_label")
    if not code and not label and score <= 0:
        return None
    out = {
        "pattern_code": code,
        "pattern_label": label,
        "compatibility_score": score,
        "matched_signals": list(value.get("matched_signals") or []),
    }
    if include_question and value.get("review_question"):
        out["review_question"] = value.get("review_question")
    return out


def _compact_relation(row: dict) -> dict:
    out = dict(row)

    # These strings are identical across many rows and already live at payload level.
    out.pop("review_steps", None)
    out.pop("guardrail", None)

    review_priority = out.get("review_priority")
    if isinstance(review_priority, dict):
        out["review_priority"] = {
            "score": float(review_priority.get("score") or out.get("max_priority_score") or 0),
            "attention_level": review_priority.get("attention_level") or out.get("attention_level"),
        }

    primary = _compact_pattern(out.get("primary_pattern"), include_question=True)
    if primary:
        out["primary_pattern"] = primary
    else:
        out["primary_pattern"] = None

    raw_candidates = out.get("pattern_compatibility")
    candidates: list[dict] = []
    if isinstance(raw_candidates, list):
        for item in raw_candidates[:2]:
            compact = _compact_pattern(item, include_question=False)
            if compact:
                candidates.append(compact)
    elif isinstance(raw_candidates, dict):
        compact = _compact_pattern(raw_candidates, include_question=False)
        if compact:
            candidates.append(compact)
    out["pattern_compatibility"] = candidates

    peer = out.get("peer_context")
    if isinstance(peer, dict):
        compact_peer = dict(peer)
        compact_peer.pop("guardrail", None)
        out["peer_context"] = compact_peer

    return out


def _compact_hotspot(row: dict) -> dict:
    out = dict(row)
    out.pop("guardrail", None)
    out.pop("review_steps", None)
    return out


def compact_browser_publication(
    input_path: str = "docs/data/investigative_findings.json",
    *,
    max_hotspots: int = 80,
) -> dict:
    """Compact the browser-facing findings payload without changing analytical ranking.

    The analytical parquet remains complete. This function only removes repeated prose,
    bounds hotspot/network summaries that the case-first UI does not render exhaustively,
    and minifies JSON. It does not change scores, attention levels, selected relations,
    signal composition, peer values or review hypotheses.
    """
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(input_path)

    before = path.stat().st_size
    payload = json.loads(path.read_text(encoding="utf-8"))

    relations = [
        _compact_relation(dict(row))
        for row in (payload.get("relation_findings") or [])
        if isinstance(row, dict)
    ]
    payload["relation_findings"] = relations

    bounded_counts: dict[str, dict[str, int]] = {}
    for key in ("service_hotspots", "provider_hotspots", "network_candidates"):
        rows = [dict(row) for row in (payload.get(key) or []) if isinstance(row, dict)]
        bounded = [_compact_hotspot(row) for row in rows[: max(0, int(max_hotspots))]]
        payload[key] = bounded
        bounded_counts[key] = {"before": len(rows), "after": len(bounded)}

    # Root-level contracts preserve the prose removed from repeated row objects.
    payload["browser_publication"] = {
        "schema": SCHEMA,
        "relation_count": len(relations),
        "max_hotspots_per_collection": int(max_hotspots),
        "bounded_collections": bounded_counts,
        "compaction": [
            "remove_repeated_row_guardrails",
            "remove_repeated_review_steps",
            "compact_pattern_candidates",
            "remove_repeated_peer_guardrail",
            "bound_hotspot_and_network_collections",
            "minify_json",
        ],
        "analytical_effect": "NONE",
        "note": (
            "Compresión exclusiva para publicación web. No modifica prioridad, scores, "
            "señales, selección de relaciones ni contexto cuantitativo."
        ),
    }

    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    path.write_text(encoded, encoding="utf-8")
    after = path.stat().st_size

    payload["browser_publication"]["bytes_before"] = int(before)
    payload["browser_publication"]["bytes_after"] = int(after)
    payload["browser_publication"]["reduction_ratio"] = round(1 - (after / before), 4) if before else 0.0

    # Re-write once so size metadata is included in the published product.
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    path.write_text(encoded, encoding="utf-8")
    final_size = path.stat().st_size
    payload["browser_publication"]["bytes_after"] = int(final_size)
    payload["browser_publication"]["reduction_ratio"] = round(1 - (final_size / before), 4) if before else 0.0
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str),
        encoding="utf-8",
    )

    return payload["browser_publication"]


def main() -> None:
    result = compact_browser_publication()
    print(
        "[RIGP browser publication]",
        f"relations={result['relation_count']}",
        f"bytes={result['bytes_before']}->{result['bytes_after']}",
        f"reduction={result['reduction_ratio']:.1%}",
    )


if __name__ == "__main__":
    main()
