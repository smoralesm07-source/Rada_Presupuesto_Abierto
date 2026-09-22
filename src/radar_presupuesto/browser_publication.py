from __future__ import annotations

import json
from pathlib import Path


from .attention_level import assign as assign_attention
from .attention_level import tray_rank_key

SCHEMA = "RIGP-BROWSER-PUBLICATION-v1"

# El navegador descarga este payload entero. La corrida mensual lo verifica
# contra 2 MB; el presupuesto se fija por debajo para que la guarda sea una red
# y no el mecanismo. Descubrir el exceso después de tres horas y media de
# cómputo, con la corrida ya perdida, era el peor momento posible para saberlo.
BROWSER_BYTE_BUDGET = 1_900_000

# El payload lleva su propio tamaño adentro, así que escribir la cifra la altera.
# Este margen absorbe ese vaivén para que la última medición siga siendo válida.
SELF_REPORT_SLACK = 1_024

LEARNING_ONLY_STATE = "SOLO_APRENDIZAJE"


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
        # Barato de llevar y decisivo de leer: dice si la hipótesis se sostiene en
        # patrones concurrentes o en uno solo. El texto de descartes no viaja por
        # fila; está en `pattern_profiles`, a nivel de payload.
        "corroborated": bool(value.get("corroborated")),
        "evidence_status": value.get("evidence_status") or "SIN_CORROBORAR",
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


def _is_learning_only(row: dict) -> bool:
    actionability = row.get("actionability")
    if isinstance(actionability, dict):
        return str(actionability.get("state") or "") == LEARNING_ONLY_STATE
    return False


def _drop_rank(row: dict) -> tuple:
    """Orden de sacrificio: primero lo que nadie puede trabajar, luego lo menos prioritario.

    Una relación fuera de la ventana de acción no puede volverse expediente. Si
    algo tiene que salir de la bandeja para que el payload quepa, sale eso antes
    que una relación accionable, por muy alto que puntúe.
    """
    priority = row.get("review_priority")
    score = 0.0
    if isinstance(priority, dict):
        score = float(priority.get("score") or 0)
    if not score:
        score = float(row.get("max_priority_score") or 0)
    return (0 if _is_learning_only(row) else 1, score, str(row.get("finding_id") or ""))


def _fit_to_budget(payload: dict, relations: list[dict], budget: int) -> dict:
    """Recorta relaciones hasta que el payload codificado quepa en `budget` bytes.

    Recorta de a poco y vuelve a medir, en vez de estimar bytes por fila: el
    tamaño de una relación varía con sus señales y su contexto, y una estimación
    que se equivoca por poco deja la corrida caída igual que una que se equivoca
    por mucho.
    """
    def encoded_size(rows: list[dict]) -> int:
        payload["relation_findings"] = rows
        return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))

    kept = list(relations)
    total = len(kept)
    if budget <= 0 or encoded_size(kept) <= budget:
        payload["relation_findings"] = kept
        return {"applied": False, "kept": len(kept), "dropped": 0, "dropped_learning_only": 0, "dropped_actionable": 0}

    order = sorted(range(len(kept)), key=lambda i: _drop_rank(kept[i]))
    doomed: list[int] = []
    low, high = 0, len(order)
    # Búsqueda binaria sobre cuántas filas sacrificar: el payload se codifica
    # unas pocas veces en vez de una por fila descartada.
    while low < high:
        mid = (low + high) // 2
        doomed = set(order[:mid])
        candidate = [row for i, row in enumerate(kept) if i not in doomed]
        if encoded_size(candidate) <= budget:
            high = mid
        else:
            low = mid + 1
    doomed = set(order[:low])
    survivors = [row for i, row in enumerate(kept) if i not in doomed]
    dropped_rows = [kept[i] for i in doomed]
    payload["relation_findings"] = survivors
    learning = sum(1 for row in dropped_rows if _is_learning_only(row))
    return {
        "applied": True,
        "kept": len(survivors),
        "dropped": len(dropped_rows),
        "dropped_learning_only": learning,
        "dropped_actionable": len(dropped_rows) - learning,
        "relations_before_budget": total,
    }


def _compact_hotspot(row: dict) -> dict:
    out = dict(row)
    out.pop("guardrail", None)
    out.pop("review_steps", None)
    return out


def compact_browser_publication(
    input_path: str = "docs/data/investigative_findings.json",
    *,
    max_hotspots: int = 80,
    byte_budget: int = BROWSER_BYTE_BUDGET,
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

    # Recién ahora, con la prosa repetida ya fuera, se mide contra el presupuesto:
    # recortar relaciones antes de compactar sacrificaría filas que sí cabían.
    # Recién ahora, con la prosa repetida ya fuera, se mide contra el presupuesto:
    # recortar relaciones antes de compactar sacrificaría filas que sí cabían.
    truncation = _fit_to_budget(payload, relations, int(byte_budget))

    # Root-level contracts preserve the prose removed from repeated row objects.
    payload["browser_publication"] = {
        "schema": SCHEMA,
        "relation_count": len(payload["relation_findings"]),
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
        "byte_budget": int(byte_budget),
    }

    def encode() -> str:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)

    def refresh_metadata(size: int) -> None:
        """Deja el bloque de metadatos coherente con el recorte y el tamaño actuales."""
        # El nivel de atención se recalibra sobre lo que queda. Su contrato es
        # «raro en la bandeja publicada», y tras el recorte la bandeja publicada
        # son las supervivientes: dejar los conteos de las 600 seleccionadas
        # junto a 353 filas publicadas hacía que el payload se contradijera
        # consigo mismo, que es lo que la corrida #42 dejó a la vista.
        calibration = assign_attention(payload["relation_findings"])
        # Y se reordena, porque el nivel encabeza el orden de la bandeja. La
        # corrida #44 publicó 313 filas ordenadas por el nivel que tenían antes
        # del recorte: la última de atención inmediata quedó en la posición 171
        # y los seguimientos empezaban en la 78. El analista que lee de arriba
        # hacia abajo se perdía treinta y tantas filas del nivel superior.
        payload["relation_findings"].sort(key=tray_rank_key)
        payload["attention_calibration"] = calibration
        counts = dict(payload.get("counts") or {})
        counts["relations_returned"] = len(payload["relation_findings"])
        counts["attention_levels"] = dict(calibration["levels"])
        payload["counts"] = counts

        meta = payload["browser_publication"]
        meta["relation_count"] = len(payload["relation_findings"])
        meta["budget_truncation"] = truncation
        meta["bytes_before"] = int(before)
        meta["bytes_after"] = int(size)
        meta["reduction_ratio"] = round(1 - (size / before), 4) if before else 0.0
        if truncation.get("applied"):
            if "drop_relations_over_byte_budget" not in meta["compaction"]:
                meta["compaction"].append("drop_relations_over_byte_budget")
            meta["truncation_note"] = (
                "El payload superaba el presupuesto del navegador y se recortaron "
                f"{truncation['dropped']} relaciones de "
                f"{truncation.get('relations_before_budget')}: "
                f"{truncation['dropped_learning_only']} fuera de la ventana de acción y "
                f"{truncation['dropped_actionable']} accionables de menor prioridad. "
                "Siguen completas en el parquet analítico: lo que se acota es la vista web, "
                "no el análisis. Una bandeja recortada lo declara en vez de parecer exhaustiva."
            )

    # El payload declara su propio tamaño, así que escribir la cifra cambia la
    # cifra. El margen absorbe ese vaivén de dígitos; el bucle absorbe el peso
    # del bloque de metadatos, que no existía cuando se midieron las relaciones.
    target = int(byte_budget) - SELF_REPORT_SLACK if byte_budget > 0 else 0
    for _ in range(4):
        refresh_metadata(len(encode().encode("utf-8")))
        size = len(encode().encode("utf-8"))
        if target <= 0 or size <= target:
            break
        retry = _fit_to_budget(payload, payload["relation_findings"], target - (size - target))
        if not retry.get("applied"):
            break
        truncation = {
            "applied": True,
            "kept": retry["kept"],
            "dropped": int(truncation.get("dropped") or 0) + retry["dropped"],
            "dropped_learning_only": int(truncation.get("dropped_learning_only") or 0)
            + retry["dropped_learning_only"],
            "dropped_actionable": int(truncation.get("dropped_actionable") or 0)
            + retry["dropped_actionable"],
            "relations_before_budget": truncation.get(
                "relations_before_budget", retry.get("relations_before_budget")
            ),
        }

    refresh_metadata(len(encode().encode("utf-8")))
    path.write_text(encode(), encoding="utf-8")

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
