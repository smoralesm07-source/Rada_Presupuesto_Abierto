from __future__ import annotations

"""Lo que el analista decidió, devuelto a lo que el radar prioriza.

Cada expediente cerrado lleva un veredicto. Ese veredicto es la única
supervisión honesta que este sistema puede tener: nadie más puede decir si un
patrón valió el viaje. Hasta ahora quedaba en el navegador y se perdía.

Este módulo lee los respaldos `RIGP-CASE-BACKUP-v1` que la propia app exporta
—no inventa un almacenamiento nuevo ni toca la capa de expedientes— y mide, por
tipo de señal, con qué frecuencia revisar ese patrón terminó en una escalada. El
resultado es un **multiplicador acotado** sobre la prioridad de revisión.

Cuatro reglas evitan que haga daño:

1. **Sólo los casos cerrados son etiquetas.** Un expediente abierto no es un
   resultado negativo: es uno inconcluso, y contarlo enseñaría que el trabajo
   lento es trabajo malo.
2. **Umbral de evidencia.** Bajo un mínimo de cierres el multiplicador es
   exactamente 1.0. Tres descartes son una anécdota, no una medición.
3. **Acotado.** Un multiplicador no puede mover el score más allá de la banda
   configurada, para que una mala semana de triage no entierre una familia
   entera de patrones.
4. **Nunca silencioso.** Cada ajuste informa su muestra, su precisión observada
   y por qué se aplicó; y todo el mecanismo se puede apagar en configuración.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

SCHEMA = "RIGP-CALIBRATION-v1"
BACKUP_SCHEMA = "RIGP-CASE-BACKUP-v1"

# Los estados de cierre del expediente, según schemas/011_cases.sql y la app
# case-first. Un expediente escalado significa que valió la pena mirarlo.
STATE_ESCALATED = "ESCALADO"
STATE_EXPLAINED = "EXPLICADO"
STATE_CLOSED = "CERRADO"
CLOSING_STATES = {STATE_ESCALATED, STATE_EXPLAINED, STATE_CLOSED}
OPEN_STATES = {"TRIAGE", "EN_REVISION", "PROFUNDIZAR"}

GUARDRAIL = (
    "La calibración mide utilidad de revisión observada, no verdad. Un patrón con baja "
    "precisión no es inocuo: puede reflejar que el equipo aún no sabe revisarlo, que la "
    "evidencia no estaba disponible o que la muestra es pequeña. Por eso el ajuste es "
    "acotado, exige un mínimo de casos cerrados y queda siempre explicado."
)

PRECISION_NOTE = (
    "Precisión observada = expedientes escalados / expedientes cerrados. Un cierre "
    "explicado no es un fracaso del patrón: es una revisión que encontró una explicación "
    "legítima, y por eso cuenta en el denominador pero no en el numerador."
)

DEFAULT_POLICY = {
    "apply": True,
    "min_closed_cases": 10,
    "multiplier_floor": 0.70,
    "multiplier_ceiling": 1.30,
    # Precisión de referencia: por encima el patrón sube, por debajo baja.
    "neutral_precision": 0.35,
}


def load_policy(path: str = "config/calibration.yaml") -> dict:
    p = Path(path)
    policy = dict(DEFAULT_POLICY)
    if p.exists():
        cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        policy.update(cfg.get("calibration", cfg) or {})
    if policy["multiplier_floor"] > 1.0 or policy["multiplier_ceiling"] < 1.0:
        raise ValueError("la banda del multiplicador debe contener 1.0, o el ajuste deja de ser neutral por defecto")
    return policy


def load_closed_cases(source: str = "data/calibration/cases") -> tuple[list[dict], dict]:
    """Lee respaldos exportados y separa los cerrados de los que siguen abiertos.

    Acepta un archivo o un directorio. Un respaldo que no declara el esquema
    esperado se descarta entero: mezclar formatos es cómo se cuelan etiquetas
    que nadie validó.
    """
    path = Path(source)
    files: list[Path] = []
    if path.is_dir():
        files = sorted(path.glob("*.json"))
    elif path.is_file():
        files = [path]

    closed: list[dict] = []
    stats = {"files_read": 0, "files_rejected": 0, "cases_seen": 0, "cases_open": 0, "cases_closed": 0}
    seen: set[str] = set()
    for f in files:
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            stats["files_rejected"] += 1
            continue
        if payload.get("schema") != BACKUP_SCHEMA or not isinstance(payload.get("cases"), list):
            stats["files_rejected"] += 1
            continue
        stats["files_read"] += 1
        for case in payload["cases"]:
            if not isinstance(case, dict):
                continue
            key = str(case.get("case_id") or case.get("case_ref") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            stats["cases_seen"] += 1
            state = str(case.get("state") or "").upper()
            if state in CLOSING_STATES:
                stats["cases_closed"] += 1
                closed.append(case)
            else:
                stats["cases_open"] += 1
    return closed, stats


def _signal_types_by_finding(findings: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in findings.get("relation_findings") or []:
        fid = str(row.get("finding_id") or "")
        if fid:
            out[fid] = [str(s) for s in (row.get("signal_types") or []) if s]
    return out


def measure(closed_cases: list[dict], findings: dict) -> dict[str, dict]:
    """Cierres y escaladas por tipo de señal.

    Un expediente puede cubrir varios hallazgos y varias señales; se atribuye a
    todas ellas, porque el analista revisó el conjunto.
    """
    by_finding = _signal_types_by_finding(findings)
    tally: dict[str, dict] = {}
    for case in closed_cases:
        state = str(case.get("state") or "").upper()
        signals: set[str] = set()
        for fid in case.get("finding_ids") or []:
            signals.update(by_finding.get(str(fid), []))
        for signal in signals:
            entry = tally.setdefault(signal, {"closed": 0, "escalated": 0, "explained": 0, "dismissed": 0})
            entry["closed"] += 1
            if state == STATE_ESCALATED:
                entry["escalated"] += 1
            elif state == STATE_EXPLAINED:
                entry["explained"] += 1
            else:
                entry["dismissed"] += 1
    for entry in tally.values():
        entry["observed_precision"] = round(entry["escalated"] / entry["closed"], 4) if entry["closed"] else 0.0
    return tally


def multipliers(measurements: dict[str, dict], policy: dict | None = None) -> dict[str, dict]:
    """Traduce precisión observada en un ajuste acotado, siempre explicado."""
    pol = policy or load_policy()
    floor, ceiling = float(pol["multiplier_floor"]), float(pol["multiplier_ceiling"])
    neutral = float(pol["neutral_precision"])
    minimum = int(pol["min_closed_cases"])
    apply_policy = bool(pol.get("apply", True))

    out: dict[str, dict] = {}
    for signal, m in sorted(measurements.items()):
        closed, precision = int(m["closed"]), float(m["observed_precision"])
        if not apply_policy:
            multiplier, why = 1.0, "La calibración está desactivada en configuración."
        elif closed < minimum:
            multiplier, why = 1.0, (
                f"Sólo {closed} expediente(s) cerrado(s); se requieren {minimum} para ajustar. "
                "Una muestra corta no es una medición."
            )
        elif precision >= neutral:
            span = ceiling - 1.0
            reach = min(1.0, (precision - neutral) / max(1e-9, 1.0 - neutral))
            multiplier = round(1.0 + span * reach, 4)
            why = (
                f"{m['escalated']} de {closed} revisiones escalaron ({precision:.0%}), "
                f"sobre la referencia de {neutral:.0%}."
            )
        else:
            span = 1.0 - floor
            reach = min(1.0, (neutral - precision) / max(1e-9, neutral))
            multiplier = round(1.0 - span * reach, 4)
            why = (
                f"{m['escalated']} de {closed} revisiones escalaron ({precision:.0%}), "
                f"bajo la referencia de {neutral:.0%}. El patrón sigue publicándose, con menos peso."
            )
        out[signal] = {
            "signal_type": signal,
            "multiplier": max(floor, min(ceiling, multiplier)),
            "closed_cases": closed,
            "escalated": int(m["escalated"]),
            "explained": int(m["explained"]),
            "dismissed": int(m["dismissed"]),
            "observed_precision": precision,
            "why": why,
            "applied": multiplier != 1.0,
        }
    return out


def build_calibration(
    cases_source: str = "data/calibration/cases",
    findings_json: str = "docs/data/investigative_findings.json",
    output_json: str = "docs/data/calibration.json",
    policy_path: str = "config/calibration.yaml",
) -> dict:
    policy = load_policy(policy_path)
    closed, stats = load_closed_cases(cases_source)
    findings = {}
    fp = Path(findings_json)
    if fp.exists():
        findings = json.loads(fp.read_text(encoding="utf-8"))

    measurements = measure(closed, findings)
    adjustments = multipliers(measurements, policy)
    applied = [a for a in adjustments.values() if a["applied"]]

    payload = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "guardrail": GUARDRAIL,
        "precision_note": PRECISION_NOTE,
        "policy": policy,
        "source": {
            "cases_source": str(cases_source),
            "backup_schema": BACKUP_SCHEMA,
            **stats,
        },
        # Si no hay cierres, la capa lo dice en vez de publicar multiplicadores
        # de 1.0 que parezcan una calibración que ocurrió.
        "status": "SIN_CIERRES" if not closed else ("SIN_AJUSTES" if not applied else "CALIBRADO"),
        "status_note": (
            "Ningún expediente cerrado alcanzó el motor. La calibración no se ha ejecutado: "
            f"exporta los respaldos desde la app y déjalos en {cases_source}."
            if not closed
            else (
                "Hay cierres, pero ningún tipo de señal alcanza el mínimo de casos para ajustar."
                if not applied
                else f"{len(applied)} tipo(s) de señal con ajuste activo."
            )
        ),
        "signal_calibration": adjustments,
    }
    out = Path(output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def load_multipliers(path: str = "docs/data/calibration.json") -> dict[str, float]:
    """Tabla señal → multiplicador, para que el scoring la consuma sin recalcular."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if payload.get("schema") != SCHEMA:
        return {}
    return {
        str(k): float(v.get("multiplier") or 1.0)
        for k, v in (payload.get("signal_calibration") or {}).items()
        if v.get("applied")
    }
