from __future__ import annotations

"""What the analyst decided, fed back into what the radar ranks.

Every closed expediente carries a verdict and a written reason. That verdict is
the only honest supervision this system can get: nobody else can say whether a
pattern was worth the trip. Until now it was written to `localStorage` and
thrown away.

This module reads sealed expedientes, keeps only the ones whose hash verifies,
and measures — per signal type and per typology — how often a pattern led
somewhere. The result is a **bounded multiplier** on the review priority score.

Four rules keep it from doing damage:

1. **Only closed cases are labels.** An open expediente is not a negative
   result; it is an unfinished one, and counting it would teach the model that
   slow work is bad work.
2. **Evidence gate.** Below a minimum number of closures a pattern gets a
   multiplier of exactly 1.0. Three discards are an anecdote.
3. **Bounded.** A multiplier cannot move the score more than the configured
   band, so a bad week of triage cannot bury a whole family of patterns.
4. **Never silent.** Every adjustment reports its sample, its observed
   precision and why it was applied — and the whole mechanism can be switched
   off in configuration.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from .case_model import CLOSING_STATES, verify

SCHEMA = "RIGP-CALIBRATION-v1"

# Un expediente escalado o explicado con hallazgo significa que valió la pena
# mirarlo. Uno cerrado sin mérito significa que no. Esa es toda la supervisión.
USEFUL_STATES = {"ESCALADO"}
NOT_USEFUL_STATES = {"CERRADO_SIN_MERITO"}
EXPLAINED_STATES = {"CERRADO_EXPLICADO"}

GUARDRAIL = (
    "La calibración mide utilidad de revisión observada, no verdad. Un patrón con baja "
    "precisión no es inocuo: puede reflejar que el equipo aún no sabe revisarlo, que la "
    "evidencia no estaba disponible o que la muestra es pequeña. Por eso el ajuste es "
    "acotado, exige un mínimo de casos cerrados y queda siempre explicado."
)

DEFAULT_POLICY = {
    "apply": True,
    "min_closed_cases": 10,
    "multiplier_floor": 0.70,
    "multiplier_ceiling": 1.30,
    # Precisión de referencia: por encima sube, por debajo baja.
    "neutral_precision": 0.35,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _iter_envelopes(source: Path):
    """Yield every case envelope found in a file or directory."""
    if source.is_dir():
        paths = sorted(source.glob("**/*.json"))
    elif source.exists():
        paths = [source]
    else:
        paths = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            yield path, None
            continue
        if isinstance(payload, dict) and payload.get("schema") == "RIGP-CASE-BUNDLE-v1":
            for envelope in payload.get("cases") or []:
                yield path, envelope
        else:
            yield path, payload


def collect_outcomes(sources: list[str | Path]) -> dict:
    """Read sealed expedientes, discarding anything whose hash does not verify."""
    verified: list[dict] = []
    rejected: list[dict] = []
    read = 0
    for source in sources:
        for path, envelope in _iter_envelopes(Path(source)):
            read += 1
            if envelope is None:
                rejected.append({"path": str(path), "problems": ["archivo ilegible"]})
                continue
            report = verify(envelope)
            if not report["valid"]:
                rejected.append({"path": str(path), "problems": report["problems"]})
                continue
            verified.append(envelope["case"])
    return {"read": read, "verified": verified, "rejected": rejected}


def _label(case: dict) -> str | None:
    state = str(case.get("state") or "")
    if state not in CLOSING_STATES and state not in USEFUL_STATES:
        return None  # todavía en curso: no es una etiqueta
    if state in USEFUL_STATES:
        return "UTIL"
    if state in NOT_USEFUL_STATES:
        return "NO_UTIL"
    if state in EXPLAINED_STATES:
        return "EXPLICADO"
    return None


def _closing_rationale(case: dict) -> str:
    for decision in reversed(case.get("decisions") or []):
        if decision.get("to_state") in CLOSING_STATES | USEFUL_STATES:
            return str(decision.get("rationale") or "")
    return ""


def _tally(cases: list[dict], key_fn) -> dict[str, dict]:
    buckets: dict[str, dict] = {}
    for case in cases:
        label = _label(case)
        if label is None:
            continue
        for key in key_fn(case):
            bucket = buckets.setdefault(
                key,
                {"closed": 0, "useful": 0, "explained": 0, "not_useful": 0, "rationales": []},
            )
            bucket["closed"] += 1
            if label == "UTIL":
                bucket["useful"] += 1
            elif label == "EXPLICADO":
                bucket["explained"] += 1
            else:
                bucket["not_useful"] += 1
            rationale = _closing_rationale(case)
            if rationale and len(bucket["rationales"]) < 5:
                bucket["rationales"].append(rationale)
    return buckets


def _multiplier(bucket: dict, policy: dict) -> dict:
    closed = int(bucket["closed"])
    useful = int(bucket["useful"])
    precision = useful / closed if closed else 0.0
    minimum = int(policy["min_closed_cases"])
    floor = float(policy["multiplier_floor"])
    ceiling = float(policy["multiplier_ceiling"])
    neutral = float(policy["neutral_precision"])

    if closed < minimum:
        return {
            "closed_cases": closed,
            "useful": useful,
            "observed_precision": round(precision, 4),
            "multiplier": 1.0,
            "applied": False,
            "why": (
                f"{closed} caso(s) cerrado(s); se exigen {minimum} antes de mover el score. "
                "Tres descartes son una anécdota, no una medición."
            ),
        }

    if precision >= neutral:
        span = (precision - neutral) / max(1e-9, 1.0 - neutral)
        multiplier = 1.0 + span * (ceiling - 1.0)
    else:
        span = (neutral - precision) / max(1e-9, neutral)
        multiplier = 1.0 - span * (1.0 - floor)
    multiplier = max(floor, min(ceiling, multiplier))

    direction = "sube" if multiplier > 1 else "baja" if multiplier < 1 else "mantiene"
    return {
        "closed_cases": closed,
        "useful": useful,
        "observed_precision": round(precision, 4),
        "multiplier": round(multiplier, 4),
        "applied": bool(policy.get("apply", True)),
        "why": (
            f"{useful} de {closed} revisiones cerradas llegaron a escalamiento "
            f"(precisión observada {precision:.0%} frente a {neutral:.0%} de referencia); "
            f"el ajuste {direction} la prioridad en {abs(multiplier - 1):.0%}."
        ),
    }


def build_calibration(
    sources: list[str | Path] | None = None,
    output_json: str | Path = "docs/data/calibration.json",
    policy: dict | None = None,
) -> dict:
    merged_policy = {**DEFAULT_POLICY, **(policy or {})}
    sources = sources or ["data/cases"]
    collected = collect_outcomes(sources)
    cases = collected["verified"]

    by_signal = _tally(cases, lambda c: [s for s in (c.get("source_signals") or []) if s])
    by_typology = _tally(
        cases,
        lambda c: [t] if (t := str((c.get("hypothesis") or {}).get("typology") or "")) else [],
    )

    signal_adjustments = {k: _multiplier(v, merged_policy) for k, v in by_signal.items()}
    typology_adjustments = {k: _multiplier(v, merged_policy) for k, v in by_typology.items()}
    for key, bucket in by_signal.items():
        signal_adjustments[key]["sample_rationales"] = bucket["rationales"]
    for key, bucket in by_typology.items():
        typology_adjustments[key]["sample_rationales"] = bucket["rationales"]

    labelled = sum(1 for c in cases if _label(c) is not None)
    payload = {
        "schema": SCHEMA,
        "generated_at": _now(),
        "guardrail": GUARDRAIL,
        "policy": merged_policy,
        "label_definition": {
            "UTIL": "Expediente escalado: la revisión llegó a algo.",
            "NO_UTIL": "Cerrado sin mérito: la revisión no llegó a nada.",
            "EXPLICADO": "Cerrado con explicación documentada; cuenta como cerrado pero no como útil.",
            "EN_CURSO": "No es una etiqueta. Un expediente abierto no es un resultado negativo.",
        },
        "evidence": {
            "envelopes_read": collected["read"],
            "verified": len(cases),
            "rejected": len(collected["rejected"]),
            "rejected_detail": collected["rejected"][:20],
            "labelled_cases": labelled,
            "open_cases": len(cases) - labelled,
        },
        "by_signal_type": signal_adjustments,
        "by_typology": typology_adjustments,
        "note": (
            "Sólo los expedientes cuyo hash de integridad verifica alimentan la calibración. "
            "Un expediente editado después de sellarse se rechaza y se informa."
        ),
    }

    out = Path(output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    return payload


def load_multipliers(path: str | Path = "docs/data/calibration.json") -> dict[str, float]:
    """Signal-type multipliers ready to apply, or an empty dict if there is no evidence."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if payload.get("schema") != SCHEMA:
        return {}
    if not (payload.get("policy") or {}).get("apply", True):
        return {}
    return {
        signal: float(entry["multiplier"])
        for signal, entry in (payload.get("by_signal_type") or {}).items()
        if entry.get("applied") and float(entry.get("multiplier", 1.0)) != 1.0
    }


def summarize(payload: dict) -> str:
    applied = sum(
        1 for entry in (payload.get("by_signal_type") or {}).values() if entry.get("applied")
    )
    evidence = payload.get("evidence") or {}
    return (
        f"{evidence.get('verified', 0)} expediente(s) verificados · "
        f"{evidence.get('labelled_cases', 0)} con veredicto · "
        f"{applied} patrón(es) con ajuste aplicado"
    )
