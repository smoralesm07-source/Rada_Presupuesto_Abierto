from __future__ import annotations

import json

import pytest

from radar_presupuesto.case_model import (
    CASE_STATES,
    GUARDRAIL,
    SCHEMA,
    VERIFICATION_CHAIN,
    add_evidence,
    add_note,
    apply_decision,
    content_hash,
    new_case,
    seal,
    set_hypothesis,
    verify,
)


def _case():
    return new_case(
        "ORG-PA-13-06-001",
        "PRV-RUT-76071943-9",
        2026,
        organization_name="COMISION NACIONAL DE RIEGO",
        provider_name="GLOBAL CATALOG LTDA",
        owner="analista@rigp",
        typology="PROVEEDOR_FACHADA",
        review_priority_score=78.0,
        laft_compatibility_score=61.0,
    )


def test_a_new_case_has_identity_and_the_honest_verification_chain():
    case = _case()
    assert case["case_id"].startswith("CASO-RIGP-")
    assert case["state"] == "ABIERTO"
    assert case["owner"] == "analista@rigp"
    stages = {s["name"]: s["status"] for s in case["verification_chain"]}
    assert stages["Propiedad, control y administración"] == "POR_INTEGRAR"
    assert stages["Beneficio final"] == "NO_DETERMINADO"
    assert len(case["verification_chain"]) == len(VERIFICATION_CHAIN)


def test_case_id_is_stable_for_the_same_focus():
    assert new_case("ORG-1", "PRV-1", 2026)["case_id"] == new_case("ORG-1", "PRV-1", 2026)["case_id"]
    assert new_case("ORG-1", "PRV-1", 2026)["case_id"] != new_case("ORG-1", "PRV-2", 2026)["case_id"]


def test_closing_a_case_without_a_reason_is_refused():
    """El motivo del descarte es el único insumo honesto para recalibrar el score."""
    case = apply_decision(_case(), to_state="EN_REVISION", rationale="tomo el caso", actor="a")
    with pytest.raises(ValueError, match="motivo"):
        apply_decision(case, to_state="CERRADO_SIN_MERITO", rationale="   ", actor="a")


def test_escalating_requires_a_formulated_hypothesis():
    case = apply_decision(_case(), to_state="EN_REVISION", rationale="tomo", actor="a")
    with pytest.raises(ValueError, match="hipótesis"):
        apply_decision(case, to_state="ESCALADO", rationale="parece grave", actor="a")
    set_hypothesis(
        case,
        typology="PROVEEDOR_FACHADA",
        statement="Sociedad sin capacidad operativa concentrada en un comprador.",
        author="a",
    )
    apply_decision(case, to_state="ESCALADO", rationale="convergen tres patrones", actor="a")
    assert case["state"] == "ESCALADO"


def test_illegal_transitions_are_refused():
    case = _case()
    with pytest.raises(ValueError, match="transición no permitida"):
        apply_decision(case, to_state="ESCALADO", rationale="x", actor="a")


def test_decision_log_is_append_only_and_records_who_and_why():
    case = _case()
    apply_decision(case, to_state="EN_REVISION", rationale="asignado en bandeja", actor="ana")
    apply_decision(case, to_state="CERRADO_EXPLICADO", rationale="contrato marco vigente", actor="ana")
    assert [d["to_state"] for d in case["decisions"]] == ["EN_REVISION", "CERRADO_EXPLICADO"]
    assert all(d["actor"] == "ana" and d["at"] and d["rationale"] for d in case["decisions"])


def test_evidence_requires_a_title_and_a_known_kind():
    case = _case()
    with pytest.raises(ValueError, match="título"):
        add_evidence(case, kind="DOCUMENTO_OFICIAL", title="  ")
    with pytest.raises(ValueError, match="tipo de evidencia"):
        add_evidence(case, kind="RUMOR", title="algo")
    add_evidence(
        case, kind="REGISTRO_PUBLICO", title="Constitución societaria",
        source_url="https://registro/1", sha256="abc", added_by="ana",
    )
    assert case["evidence"][0]["captured_at"]
    assert case["evidence"][0]["evidence_id"].startswith("EV-")


def test_sealed_export_verifies_and_detects_tampering():
    case = _case()
    apply_decision(case, to_state="EN_REVISION", rationale="tomo", actor="ana")
    add_note(case, "Revisar orden de compra 1234-56-SE26", author="ana")
    envelope = seal(case, exported_by="ana")

    assert envelope["schema"] == SCHEMA
    assert envelope["guardrail"] == GUARDRAIL
    report = verify(envelope)
    assert report["valid"], report["problems"]
    assert report["decisions"] == 1

    # Viaja como JSON y sigue verificando.
    roundtrip = json.loads(json.dumps(envelope, ensure_ascii=False))
    assert verify(roundtrip)["valid"]

    # Alguien edita el contenido sin rehacer el sobre.
    roundtrip["case"]["state"] = "CERRADO_EXPLICADO"
    broken = verify(roundtrip)
    assert not broken["valid"]
    assert any("hash de integridad" in p for p in broken["problems"])


def test_verify_rejects_a_forged_decision_trail():
    case = _case()
    apply_decision(case, to_state="EN_REVISION", rationale="tomo", actor="ana")
    # Se inyecta un cierre que nunca pasó por el modelo.
    case["decisions"].append(
        {
            "decision_id": "DEC-FALSO", "at": "2026-01-01T00:00:00+00:00", "actor": "x",
            "from_state": "ABIERTO", "to_state": "CERRADO_EXPLICADO", "rationale": "",
        }
    )
    case["state"] = "CERRADO_EXPLICADO"
    report = verify(seal(case))
    assert not report["valid"]
    assert any("traza de decisiones se rompe" in p for p in report["problems"])


def test_verify_rejects_a_foreign_envelope():
    assert not verify({"schema": "OTRO", "case": {}})["valid"]
    assert not verify({"schema": SCHEMA})["valid"]


def test_content_hash_is_order_independent():
    case = _case()
    reordered = dict(reversed(list(case.items())))
    assert content_hash(case) == content_hash(reordered)


def test_every_state_is_documented():
    for state in CASE_STATES:
        assert CASE_STATES[state].strip()
