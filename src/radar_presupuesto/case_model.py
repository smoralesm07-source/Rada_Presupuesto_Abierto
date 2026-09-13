from __future__ import annotations

"""The expediente as an object with identity, lifecycle and chain of custody.

Before this, the analyst's entire work product lived in nine `localStorage` keys:
no identifier, no owner, no history of who concluded what, no way to hand it to a
reviewer, and nothing left after clearing a browser. For a file meant to support a
ROS or a referral, that is disqualifying.

This module defines the contract — states, legal transitions, evidence with
capture metadata, an append-only decision log, and a sealed export whose hash
covers the content. The browser implements the same envelope, so an expediente
can leave one machine and be verified on another, and `schemas/011_case_management.sql`
holds the same shape for when a real database is put behind it.

The rule that matters most: **a case cannot be closed without a reason.** Every
discard carries its rationale, because that rationale is the only honest input a
scoring model can learn from.
"""

import hashlib
import json
import re
from datetime import datetime, timezone

SCHEMA = "RIGP-CASE-EXPORT-v1"

GUARDRAIL = (
    "Un expediente RIGP organiza revisión documental y OSINT sobre gasto público. "
    "No acredita irregularidad, delito funcionario, fraude, corrupción ni lavado de activos, "
    "y no atribuye responsabilidad a ninguna persona o entidad. Las conclusiones que contenga "
    "son del analista que las firma, no del radar."
)

# Estados del expediente. Cerrar exige motivo; escalar exige hipótesis.
CASE_STATES: dict[str, str] = {
    "ABIERTO": "Creado desde un hallazgo priorizado; todavía sin trabajo de análisis.",
    "EN_REVISION": "Un analista lo está trabajando.",
    "EN_ESPERA_DOCUMENTO": "Detenido a la espera de un documento solicitado.",
    "ESCALADO": "Derivado a una instancia superior con hipótesis formulada.",
    "CERRADO_EXPLICADO": "El patrón tiene explicación documentada y no amerita seguir.",
    "CERRADO_SIN_MERITO": "Revisado y descartado por falta de mérito investigativo.",
}

TRANSITIONS: dict[str, set[str]] = {
    "ABIERTO": {"EN_REVISION", "CERRADO_SIN_MERITO"},
    "EN_REVISION": {"EN_ESPERA_DOCUMENTO", "ESCALADO", "CERRADO_EXPLICADO", "CERRADO_SIN_MERITO"},
    "EN_ESPERA_DOCUMENTO": {"EN_REVISION", "ESCALADO", "CERRADO_EXPLICADO", "CERRADO_SIN_MERITO"},
    "ESCALADO": {"EN_REVISION", "CERRADO_EXPLICADO"},
    "CERRADO_EXPLICADO": {"EN_REVISION"},
    "CERRADO_SIN_MERITO": {"EN_REVISION"},
}

CLOSING_STATES = {"CERRADO_EXPLICADO", "CERRADO_SIN_MERITO"}

# Las cuatro etapas se conservan tal como estaban declaradas: decir qué no se sabe
# es lo que hace defendible el expediente.
VERIFICATION_CHAIN = [
    {"stage": 1, "name": "Receptor económico directo", "status": "DISPONIBLE",
     "meaning": "Persona o sociedad que aparece como proveedor o receptor de recursos públicos."},
    {"stage": 2, "name": "Propiedad, control y administración", "status": "POR_INTEGRAR",
     "meaning": "Socios, accionistas, controladores, representantes legales o directores del periodo."},
    {"stage": 3, "name": "Personas y sociedades vinculadas", "status": "POR_VERIFICAR",
     "meaning": "Vínculos documentados que extiendan la trazabilidad más allá del receptor directo."},
    {"stage": 4, "name": "Beneficio final", "status": "NO_DETERMINADO",
     "meaning": "Sólo puede atribuirse con evidencia de propiedad, control o disposición del valor."},
]

EVIDENCE_KINDS = {
    "DOCUMENTO_OFICIAL", "REGISTRO_PUBLICO", "PUBLICACION_PRENSA",
    "CAPTURA_SISTEMA", "ANALISIS_PROPIO", "RESPUESTA_TRANSPARENCIA",
}

_ID_SAFE = re.compile(r"[^A-Z0-9]+")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _digest(*parts: object, length: int = 20) -> str:
    payload = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length].upper()


def case_id(organization_id: str, provider_id: str, periodo: object) -> str:
    return "CASO-RIGP-" + _digest(organization_id, provider_id, periodo)


def _canonical(value: object) -> object:
    """Normalise so Python and the browser serialise identical bytes.

    Python renders 78.0 as "78.0" and JavaScript as "78"; left alone, the same
    expediente would hash differently depending on where it was sealed, and the
    integrity check would fail on every handoff.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def canonical_json(payload: object) -> str:
    """Stable serialisation, so the same content always hashes the same."""
    return json.dumps(
        _canonical(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def content_hash(case: dict) -> str:
    return hashlib.sha256(canonical_json(case).encode("utf-8")).hexdigest()


def new_case(
    organization_id: str,
    provider_id: str,
    periodo: object,
    *,
    organization_name: str = "",
    provider_name: str = "",
    owner: str = "",
    finding_id: str = "",
    typology: str = "",
    review_priority_score: float = 0.0,
    laft_compatibility_score: float = 0.0,
    opacity_level: str = "TRAZABLE",
    source_signals: list[str] | None = None,
) -> dict:
    now = _now()
    return {
        "case_id": case_id(organization_id, provider_id, periodo),
        "state": "ABIERTO",
        "opened_at": now,
        "updated_at": now,
        "owner": owner,
        "focus": {
            "organization_id": organization_id,
            "organization_name": organization_name,
            "provider_id": provider_id,
            "provider_name": provider_name,
            "periodo": periodo,
            "finding_id": finding_id,
        },
        "scores": {
            "review_priority_score": float(review_priority_score),
            "laft_compatibility_score": float(laft_compatibility_score),
        },
        "opacity_level": opacity_level,
        "hypothesis": {"typology": typology, "statement": "", "formulated_at": "", "formulated_by": ""},
        "source_signals": list(source_signals or []),
        "entities": [],
        "evidence": [],
        "notes": [],
        "decisions": [],
        "verification_chain": [dict(stage) for stage in VERIFICATION_CHAIN],
    }


def add_entity(case: dict, *, entity_id: str, role: str, name: str = "", rut: str = "",
               identity_status: str = "UNRESOLVED", source: str = "") -> dict:
    case["entities"].append(
        {
            "entity_id": entity_id,
            "name": name,
            "rut": rut,
            "role": role,
            "identity_status": identity_status,
            "link_status": "CANDIDATE",
            "source": source,
            "added_at": _now(),
        }
    )
    case["updated_at"] = _now()
    return case


def add_evidence(case: dict, *, kind: str, title: str, source_url: str = "",
                 captured_at: str = "", sha256: str = "", note: str = "",
                 added_by: str = "") -> dict:
    if kind not in EVIDENCE_KINDS:
        raise ValueError(f"tipo de evidencia desconocido: {kind}")
    if not title.strip():
        raise ValueError("la evidencia requiere un título que la identifique")
    case["evidence"].append(
        {
            "evidence_id": "EV-" + _digest(case["case_id"], kind, title, source_url, len(case["evidence"])),
            "kind": kind,
            "title": title,
            "source_url": source_url,
            "captured_at": captured_at or _now(),
            "sha256": sha256,
            "note": note,
            "added_by": added_by,
            "added_at": _now(),
        }
    )
    case["updated_at"] = _now()
    return case


def add_note(case: dict, text: str, author: str = "") -> dict:
    if not text.strip():
        raise ValueError("una nota vacía no aporta al expediente")
    case["notes"].append(
        {"note_id": "NT-" + _digest(case["case_id"], text, len(case["notes"])),
         "text": text, "author": author, "at": _now()}
    )
    case["updated_at"] = _now()
    return case


def apply_decision(case: dict, *, to_state: str, rationale: str, actor: str = "") -> dict:
    """Move the case, recording who moved it and why. Append-only."""
    current = case["state"]
    if to_state not in CASE_STATES:
        raise ValueError(f"estado desconocido: {to_state}")
    if to_state not in TRANSITIONS.get(current, set()):
        raise ValueError(f"transición no permitida: {current} -> {to_state}")
    if to_state in CLOSING_STATES and not rationale.strip():
        raise ValueError("cerrar un expediente exige un motivo explícito")
    if to_state == "ESCALADO" and not (case.get("hypothesis") or {}).get("statement", "").strip():
        raise ValueError("escalar exige una hipótesis formulada")
    case["decisions"].append(
        {
            "decision_id": "DEC-" + _digest(case["case_id"], current, to_state, len(case["decisions"])),
            "at": _now(),
            "actor": actor,
            "from_state": current,
            "to_state": to_state,
            "rationale": rationale,
        }
    )
    case["state"] = to_state
    case["updated_at"] = _now()
    return case


def set_hypothesis(case: dict, *, typology: str, statement: str, author: str = "") -> dict:
    if not statement.strip():
        raise ValueError("la hipótesis requiere un enunciado")
    case["hypothesis"] = {
        "typology": typology,
        "statement": statement,
        "formulated_at": _now(),
        "formulated_by": author,
    }
    case["updated_at"] = _now()
    return case


def seal(case: dict, *, exported_by: str = "") -> dict:
    """Produce a portable envelope whose hash covers the case content."""
    return {
        "schema": SCHEMA,
        "exported_at": _now(),
        "exported_by": exported_by,
        "generator": "RIGP",
        "guardrail": GUARDRAIL,
        "integrity": {"algorithm": "SHA-256", "content_sha256": content_hash(case)},
        "case": case,
    }


def verify(envelope: dict) -> dict:
    """Check a received expediente before trusting anything in it."""
    problems: list[str] = []
    if envelope.get("schema") != SCHEMA:
        problems.append(f"esquema inesperado: {envelope.get('schema')!r}")
    case = envelope.get("case")
    if not isinstance(case, dict):
        problems.append("el sobre no contiene un expediente")
        return {"valid": False, "problems": problems}
    declared = ((envelope.get("integrity") or {}).get("content_sha256") or "")
    actual = content_hash(case)
    if declared != actual:
        problems.append("el hash de integridad no corresponde al contenido")
    if case.get("state") not in CASE_STATES:
        problems.append(f"estado desconocido: {case.get('state')!r}")
    state = "ABIERTO"
    for decision in case.get("decisions") or []:
        if decision.get("from_state") != state:
            problems.append(
                f"la traza de decisiones se rompe en {decision.get('decision_id')}: "
                f"sale de {decision.get('from_state')!r} y el estado previo era {state!r}"
            )
            break
        if decision.get("to_state") not in TRANSITIONS.get(state, set()):
            problems.append(f"transición no permitida registrada: {state} -> {decision.get('to_state')}")
            break
        if decision.get("to_state") in CLOSING_STATES and not str(decision.get("rationale") or "").strip():
            problems.append("hay un cierre sin motivo registrado")
        state = decision.get("to_state")
    else:
        if case.get("decisions") and state != case.get("state"):
            problems.append(
                f"el estado declarado ({case.get('state')}) no coincide con la traza ({state})"
            )
    return {
        "valid": not problems,
        "problems": problems,
        "case_id": case.get("case_id"),
        "state": case.get("state"),
        "decisions": len(case.get("decisions") or []),
        "evidence": len(case.get("evidence") or []),
        "content_sha256": actual,
    }
