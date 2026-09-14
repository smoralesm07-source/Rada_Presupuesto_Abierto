"""Dónde la Contraloría observó desórdenes, sin atribuírselos a quien no fue.

El riesgo de esta capa no es dejar de cruzar: es cruzar mal. Atribuirle a un
servicio la auditoría de otro de su misma familia sería peor que no decir nada,
y los nombres institucionales chilenos se parecen muchísimo entre sí.
"""
import json
from pathlib import Path

import pytest

from radar_presupuesto.public_service_audits import (
    ACRONYMS,
    MATCH_ACRONYM,
    MATCH_EXACT,
    MATCH_NONE,
    MATCH_PARENT,
    OUT_OF_SCOPE_TYPES,
    SCHEMA,
    UNMATCHED_REASON,
    build_public_service_audits,
    discriminators,
    expand_acronyms,
    match_audited_body,
    same_entity,
)

CATALOG = [
    {"service_id": "SRV-PA-13-06", "service_name": "COMISIÓN NACIONAL DE RIEGO"},
    {"service_id": "SRV-PA-13-03", "service_name": "INSTITUTO DE DESARROLLO AGROPECUARIO"},
    {"service_id": "SRV-PA-09-30", "service_name": "SERVICIO LOCAL DE EDUCACIÓN AYSÉN"},
    {"service_id": "SRV-PA-09-31", "service_name": "SERVICIO LOCAL DE EDUCACIÓN HUASCO"},
    {"service_id": "SRV-PA-16-02", "service_name": "SERVICIO DE SALUD ANTOFAGASTA"},
    {"service_id": "SRV-PA-16-03", "service_name": "SERVICIO DE SALUD MAULE"},
    {"service_id": "SRV-PA-05-31", "service_name": "HOSPITAL DE CARABINEROS"},
]


def _body(name, kind="PUBLIC_ORGANIZATION", document="DOC-1"):
    return {"name": name, "normalized_name": name.upper(), "organization_type": kind,
            "source_document_id": document, "region": "", "commune": ""}


# ---------------------------------------------------------------------------
# La regla de seguridad: parecerse no es ser
# ---------------------------------------------------------------------------

def test_two_services_of_the_same_family_are_never_confused():
    """El caso que motivó la regla: dos SLEP se parecen un 85% y son distintos."""
    ok, why = same_entity("SERVICIO LOCAL DE EDUCACIÓN PÚBLICA DE AYSÉN",
                          "SERVICIO LOCAL DE EDUCACIÓN HUASCO")
    assert ok is False
    assert "distintivos incompatibles" in why
    assert "AYSEN" in why and "HUASCO" in why


def test_sharing_one_mark_is_not_enough():
    """Dos oficinas regionales del mismo servicio comparten el nombre del servicio."""
    ok, _ = same_entity("INSTITUTO NACIONAL DE LA JUVENTUD DE VALPARAÍSO",
                        "INSTITUTO NACIONAL DE LA JUVENTUD DE ANTOFAGASTA")
    assert ok is False, "compartir 'JUVENTUD' no las hace la misma entidad"


def test_a_regional_office_belongs_to_its_service():
    ok, why = same_entity("INSTITUTO NACIONAL DE LA JUVENTUD DE VALPARAÍSO",
                          "INSTITUTO NACIONAL DE LA JUVENTUD")
    assert ok is True
    assert "VALPARAISO" in why


@pytest.mark.parametrize("audited,expected_id", [
    ("SERVICIO LOCAL DE EDUCACIÓN PÚBLICA DE AYSÉN", "SRV-PA-09-30"),
    ("SERVICIO LOCAL DE EDUCACIÓN PÚBLICA DE HUASCO", "SRV-PA-09-31"),
    ("Servicio de Salud de Antofagasta", "SRV-PA-16-02"),
])
def test_the_right_sibling_is_chosen_among_lookalikes(audited, expected_id):
    result = match_audited_body(_body(audited), CATALOG)
    assert result["service"] is not None, f"{audited} debería cruzar"
    assert result["service"]["service_id"] == expected_id


def test_a_hospital_is_not_matched_to_an_unrelated_hospital():
    result = match_audited_body(_body("HOSPITAL DE VICTORIA", "HOSPITAL"), CATALOG)
    assert result["method"] == MATCH_NONE
    assert result["service"] is None
    assert "dentro del" in result["why"], "la razón debe explicar la estructura, no sólo fallar"


# ---------------------------------------------------------------------------
# Siglas: conocimiento de dominio, explícito y verificable
# ---------------------------------------------------------------------------

def test_an_acronym_the_budget_does_not_use_still_finds_its_service():
    """«Dirección Regional Metropolitana del INDAP» se parece un 60% a su servicio."""
    result = match_audited_body(_body("Dirección Regional Metropolitana del INDAP"), CATALOG)
    assert result["service"]["service_id"] == "SRV-PA-13-03"
    assert result["method"] == MATCH_ACRONYM


def test_acronym_expansion_leaves_unknown_words_alone():
    assert expand_acronyms("INDAP") == ACRONYMS["INDAP"]
    assert "PALABRA" in expand_acronyms("PALABRA RARA")


def test_exact_names_match_exactly():
    result = match_audited_body(_body("Comisión Nacional de Riego"), CATALOG)
    assert result["method"] == MATCH_EXACT
    assert result["service"]["service_id"] == "SRV-PA-13-06"


# ---------------------------------------------------------------------------
# Lo que no se puede cruzar se declara, con su razón
# ---------------------------------------------------------------------------

def test_municipalities_are_out_of_scope_not_a_failed_match():
    result = match_audited_body(_body("MUNICIPALIDAD DE QUILLOTA", "MUNICIPALITY"), CATALOG)
    assert result["out_of_scope"] is True
    assert result["service"] is None
    assert "no integran el presupuesto de la Nación" in result["why"]


def test_state_universities_get_their_own_explanation():
    result = match_audited_body(_body("UNIVERSIDAD DEL BIOBÍO", "STATE_UNIVERSITY"), CATALOG)
    assert result["service"] is None
    assert result["out_of_scope"] is False
    assert result["why"] == UNMATCHED_REASON["STATE_UNIVERSITY"]
    assert "transferencias" in result["why"]


def test_every_declared_out_of_scope_type_explains_itself():
    for kind, reason in OUT_OF_SCOPE_TYPES.items():
        assert len(reason) > 40, f"{kind}: la razón debe explicar, no etiquetar"


# ---------------------------------------------------------------------------
# El payload: nada desaparece en silencio
# ---------------------------------------------------------------------------

@pytest.fixture
def silver(tmp_path: Path):
    d = tmp_path / "silver"
    d.mkdir()
    bodies = [
        _body("Comisión Nacional de Riego", "PUBLIC_COMMISSION", "DOC-A"),
        _body("MUNICIPALIDAD DE TENO", "MUNICIPALITY", "DOC-B"),
        _body("UNIVERSIDAD DEL BIOBÍO", "STATE_UNIVERSITY", "DOC-C"),
    ]
    for i, b in enumerate(bodies):
        b["organization_id"] = f"ENT-{i}"
    (d / "organizations.jsonl").write_text(
        "\n".join(json.dumps(b, ensure_ascii=False) for b in bodies), encoding="utf-8")
    (d / "findings.jsonl").write_text(
        "\n".join(json.dumps({"document_id": "DOC-A", "severity": s}) for s in ("HIGH", "MEDIUM")),
        encoding="utf-8")
    return d


def test_the_payload_accounts_for_every_audited_body(silver, tmp_path: Path, monkeypatch):
    import radar_presupuesto.public_service_audits as mod
    monkeypatch.setattr(mod, "service_catalog", lambda _glob: CATALOG)

    out = tmp_path / "public_service_audits.json"
    payload = build_public_service_audits("irrelevante.parquet", str(silver), str(out))
    coverage = payload["coverage"]

    assert payload["schema"] == SCHEMA
    # Los tres organismos están explicados: uno cruza, uno fuera de alcance, uno sin cruce.
    assert coverage["audited_bodies"] == 3
    assert coverage["matched_bodies"] + coverage["out_of_scope_bodies"] + coverage["unmatched_bodies"] == 3
    assert coverage["services_with_observations"] == 1

    servicio = payload["services"][0]
    assert servicio["service_name"] == "COMISIÓN NACIONAL DE RIEGO"
    assert servicio["observation_count"] == 2, "las observaciones del documento llegan al servicio"

    assert payload["out_of_scope"][0]["organization_type"] == "MUNICIPALITY"
    assert payload["unmatched"][0]["organization_type"] == "STATE_UNIVERSITY"
    assert json.loads(out.read_text(encoding="utf-8"))["schema"] == SCHEMA


def test_the_guardrail_refuses_to_call_an_observation_a_crime(silver, tmp_path: Path, monkeypatch):
    import radar_presupuesto.public_service_audits as mod
    monkeypatch.setattr(mod, "service_catalog", lambda _glob: CATALOG)
    payload = build_public_service_audits("x.parquet", str(silver), str(tmp_path / "o.json"))
    guardrail = payload["guardrail"].lower()
    assert "no acredita delito" in guardrail
    assert "desorden administrativo" in guardrail
    assert "nunca deriva" in guardrail or "mayoría" in guardrail


def test_no_cgr_data_produces_an_empty_but_honest_payload(tmp_path: Path):
    payload = build_public_service_audits("x.parquet", str(tmp_path / "vacio"), str(tmp_path / "o.json"))
    assert payload["coverage"]["audited_bodies"] == 0
    assert payload["services"] == []


def test_discriminators_drop_words_that_do_not_distinguish():
    assert discriminators("SERVICIO DE SALUD MAULE") == {"MAULE"}
    assert discriminators("MUNICIPALIDAD DE LA SERENA") == {"SERENA"}
    assert "SERVICIO" not in discriminators("SERVICIO LOCAL DE EDUCACIÓN AYSÉN")
