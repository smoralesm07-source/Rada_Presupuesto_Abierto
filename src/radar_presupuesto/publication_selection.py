from __future__ import annotations

import json
from collections import Counter

from .attention_level import assign as assign_attention
from pathlib import Path

import duckdb

from .investigative_findings import GUARDRAIL, LEGAL_REVIEW
from .pattern_compatibility import best_pattern

SIGNAL_ORDER = [
    "POTENTIAL_FRAGMENTATION",
    "EXACT_DUPLICATE_CANDIDATE",
    "YEAR_END_SPIKE",
    "NEW_TO_SERIES_HIGH_SPEND",
    "PROVIDER_CONCENTRATION",
    "PAYMENT_DELAY_OUTLIER",
    "AMOUNT_OUTLIER",
]


def _split_pipe(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value if str(x)]
    return [x for x in str(value).split("|") if x]


def _decorate(row: dict) -> dict:
    out = dict(row)
    out["signal_types"] = _split_pipe(out.get("signal_types"))
    out["signal_families"] = _split_pipe(out.get("signal_families"))
    family = str(out.get("finding_family") or "PATRON_ATIPICO")
    out["review_steps"] = LEGAL_REVIEW.get(family, LEGAL_REVIEW["PATRON_ATIPICO"])
    out["guardrail"] = GUARDRAIL
    pattern = best_pattern(out["signal_types"])
    out["pattern_compatibility"] = pattern
    return out


def _rank_key(row: dict) -> tuple:
    level = str(row.get("attention_level") or "SEGUIMIENTO")
    level_rank = {"ATENCION_INMEDIATA": 0, "REVISION_PRIORITARIA": 1, "SEGUIMIENTO": 2}.get(level, 3)
    return (
        level_rank,
        -float(row.get("max_priority_score") or 0),
        -int(row.get("signal_family_count") or 0),
        -float(row.get("max_transaction_amount") or 0),
        str(row.get("finding_id") or ""),
    )


def rebalance_findings_publication(
    findings_parquet: str = "data/signals/investigative_findings.parquet",
    payload_json: str = "docs/data/investigative_findings.json",
    max_rows: int = 600,
    reserve_per_signal: int = 20,
) -> dict:
    """Publish a bounded but diverse set of relation findings.

    The analytical parquet remains complete. This function only decides which
    relations reach the browser. It reserves representation for each signal type
    before filling the remaining capacity by investigation priority, preventing a
    dominant family (for example amount outliers) from making rarer phenomena
    disappear from the analyst's triage view.

    ``pattern_compatibility`` is descriptive and independent from review priority.
    It never changes the publication ranking and must not be interpreted as a
    probability of wrongdoing or criminal conduct.
    """
    parquet = Path(findings_parquet)
    payload_path = Path(payload_json)
    if not parquet.exists():
        raise FileNotFoundError(findings_parquet)
    if not payload_path.exists():
        raise FileNotFoundError(payload_json)

    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    con = duckdb.connect()
    df = con.execute(
        f"""
        SELECT *
        FROM read_parquet('{parquet.as_posix()}')
        ORDER BY
          CASE attention_level WHEN 'ATENCION_INMEDIATA' THEN 1 WHEN 'REVISION_PRIORITARIA' THEN 2 ELSE 3 END,
          max_priority_score DESC,
          signal_family_count DESC,
          max_transaction_amount DESC,
          finding_id
        """
    ).df()
    con.close()

    rows = [_decorate(x) for x in df.where(df.notna(), None).to_dict("records")]
    available = Counter()
    for row in rows:
        for signal in set(row.get("signal_types") or []):
            available[signal] += 1

    selected: list[dict] = []
    selected_ids: set[str] = set()
    reserved_counts: Counter = Counter()

    for signal in SIGNAL_ORDER:
        if reserve_per_signal <= 0:
            break
        for row in rows:
            if len(selected) >= max_rows or reserved_counts[signal] >= reserve_per_signal:
                break
            fid = str(row.get("finding_id") or "")
            if fid in selected_ids or signal not in (row.get("signal_types") or []):
                continue
            selected.append(row)
            selected_ids.add(fid)
            reserved_counts[signal] += 1

    for row in rows:
        if len(selected) >= max_rows:
            break
        fid = str(row.get("finding_id") or "")
        if fid in selected_ids:
            continue
        selected.append(row)
        selected_ids.add(fid)

    # El nivel se calibra contra la bandeja que este módulo acaba de decidir, no
    # contra la lista anterior. `investigative_findings` también lo calcula, pero
    # su resultado lo pisa esta selección al reemplazar `relation_findings` con
    # filas releídas del parquet: la corrida #41 publicó 582 de 600 en atención
    # inmediata mientras el bloque de calibración, calculado sobre otra lista,
    # decía 85/183/332. Calibrar aquí es además lo correcto: el nivel ordena la
    # bandeja publicada, y quien la define es este paso.
    attention_calibration = assign_attention(selected)
    selected.sort(key=_rank_key)

    published = Counter()
    attention = Counter()
    families = Counter()
    patterns = Counter()
    for row in selected:
        attention[str(row.get("attention_level") or "SEGUIMIENTO")] += 1
        families[str(row.get("finding_family") or "PATRON_ATIPICO")] += 1
        pattern = row.get("pattern_compatibility") or {}
        if pattern.get("pattern_code"):
            patterns[str(pattern["pattern_code"])] += 1
        for signal in set(row.get("signal_types") or []):
            published[signal] += 1

    payload["relation_findings"] = selected
    counts = dict(payload.get("counts") or {})
    counts["relations_returned"] = len(selected)
    counts["attention_levels"] = {
        "ATENCION_INMEDIATA": attention.get("ATENCION_INMEDIATA", 0),
        "REVISION_PRIORITARIA": attention.get("REVISION_PRIORITARIA", 0),
        "SEGUIMIENTO": attention.get("SEGUIMIENTO", 0),
    }
    counts["finding_families"] = dict(families)
    payload["attention_calibration"] = attention_calibration
    counts["pattern_compatibility"] = dict(patterns)
    payload["counts"] = counts
    payload["publication_selection"] = {
        "method": "priority_with_signal_diversity_reserve",
        "max_rows": int(max_rows),
        "reserve_per_signal": int(reserve_per_signal),
        "available_by_signal": {s: int(available.get(s, 0)) for s in SIGNAL_ORDER},
        "published_by_signal": {s: int(published.get(s, 0)) for s in SIGNAL_ORDER},
        "note": (
            "La reserva evita que un tipo de señal dominante excluya por completo fenómenos menos frecuentes. "
            "No eleva artificialmente su score ni cambia la evidencia; sólo protege diversidad en el lote publicado."
        ),
    }
    payload["score_separation"] = {
        "review_priority": "max_priority_score ordena qué revisar primero.",
        "pattern_compatibility": "pattern_compatibility describe semejanza con una hipótesis analítica de revisión y no altera la prioridad.",
        "guardrail": "Ninguno de ambos scores estima culpabilidad, corrupción, fraude o probabilidad de delito.",
    }
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    return {
        "relations_available": len(rows),
        "relations_published": len(selected),
        "available_by_signal": dict(available),
        "published_by_signal": dict(published),
        "published_by_pattern": dict(patterns),
    }
