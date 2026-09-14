"""El cruce CGR: el RUT acredita identidad, el nombre es una hipótesis.

Antes ambos podían alcanzar la misma confianza, y el score no distinguía entre
«es la misma empresa» y «se llama parecido». La consulta ya traía
`rut_beneficiario` desde el principio y lo descartaba.
"""
import json
from pathlib import Path

import pandas as pd
import pytest

from radar_presupuesto.cgr_correlation import (
    MATCH_GRADE_NAME_EXACT,
    MATCH_GRADE_NAME_FUZZY,
    MATCH_GRADE_RUT,
    NAME_CONFIDENCE_CEILING,
    build_rut_index,
    correlate_with_cgr,
    external_rut,
)


def _dv(body: int) -> str:
    total, factor = 0, 2
    for digit in reversed(str(body)):
        total += int(digit) * factor
        factor = 2 if factor == 7 else factor + 1
    rest = 11 - (total % 11)
    return {11: "0", 10: "K"}.get(rest, str(rest))


def rut(body: int) -> str:
    return f"{body}-{_dv(body)}"


def _silver(tmp_path: Path, providers: list[dict], orgs: list[dict] | None = None, findings: list[dict] | None = None) -> Path:
    d = tmp_path / "silver"
    d.mkdir(parents=True, exist_ok=True)
    for name, rows in (("providers", providers), ("organizations", orgs or []), ("findings", findings or [])):
        (d / f"{name}.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8"
        )
    return d


def _facts(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "facts.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def _fact(body: int, nombre: str, region: str = "RM"):
    return {
        "transaction_id": f"TX-{body}",
        "organization_id": "ORG-1",
        "provider_id": f"PRV-RUT-{rut(body)}",
        "rut_beneficiario": rut(body),
        "nombre_beneficiario": nombre,
        "region": region,
        "periodo": 2026,
        "monto_devengado": 1_000_000.0,
        "is_provider": True,
        "is_aggregated": False,
        "nombre_area": "Area",
        "nombre_capitulo": "Capitulo",
        "nombre_partida": "Partida",
    }


def _run(tmp_path: Path, facts: Path, silver: Path) -> dict:
    return correlate_with_cgr(
        str(facts),
        cgr_silver_dir=str(silver),
        output_parquet=str(tmp_path / "links.parquet"),
        output_json=str(tmp_path / "cgr.json"),
    )


# ---------------------------------------------------------------------------
# Lo que el RUT resuelve
# ---------------------------------------------------------------------------

def test_rut_beats_a_better_looking_name_match(tmp_path: Path):
    """Dos empresas homónimas; sólo el RUT dice cuál es."""
    facts = _facts(tmp_path, [_fact(77111222, "CONSTRUCTORA ANDES LIMITADA")])
    silver = _silver(tmp_path, [
        # Nombre idéntico, pero es otra empresa.
        {"provider_id": "ENT-homonima", "name": "Constructora Andes Limitada",
         "normalized_name": "CONSTRUCTORA ANDES LIMITADA", "rut": "", "region": "RM",
         "confidence": 0.95, "source_document_id": "DOC-1"},
        # Nombre distinto, pero el RUT coincide: es ésta.
        {"provider_id": "ENT-correcta", "name": "CONSTRUCTORA ANDES SpA (ex Limitada)",
         "normalized_name": "CONSTRUCTORA ANDES SPA EX LIMITADA", "rut": rut(77111222),
         "region": "V", "confidence": 0.80, "source_document_id": "DOC-2"},
    ])
    _run(tmp_path, facts, silver)
    links = pd.read_parquet(tmp_path / "links.parquet")
    provider = links[links.local_entity_type == "PROVIDER"].iloc[0]

    assert provider.external_entity_id == "ENT-correcta"
    assert provider.match_grade == MATCH_GRADE_RUT
    assert provider.confidence > NAME_CONFIDENCE_CEILING


def test_a_name_match_can_never_reach_the_confidence_a_rut_earns(tmp_path: Path):
    facts = _facts(tmp_path, [_fact(77111222, "SERVICIOS AUSTRAL LIMITADA")])
    silver = _silver(tmp_path, [
        {"provider_id": "ENT-1", "name": "Servicios Austral Limitada",
         "normalized_name": "SERVICIOS AUSTRAL LIMITADA", "rut": "", "region": "RM",
         "confidence": 1.0, "source_document_id": "DOC-1"},
    ])
    _run(tmp_path, facts, silver)
    row = pd.read_parquet(tmp_path / "links.parquet").iloc[0]

    assert row.match_grade == MATCH_GRADE_NAME_EXACT
    assert row.confidence <= NAME_CONFIDENCE_CEILING
    basis = json.loads(row.match_basis)
    assert basis["grade"] == MATCH_GRADE_NAME_EXACT
    assert "no acredita identidad" in basis["note"]


def test_a_rut_that_does_not_match_falls_back_to_name_not_to_a_wrong_link(tmp_path: Path):
    facts = _facts(tmp_path, [_fact(77111222, "TRANSPORTES SUR LIMITADA")])
    silver = _silver(tmp_path, [
        {"provider_id": "ENT-otra", "name": "Otra Empresa SpA",
         "normalized_name": "OTRA EMPRESA SPA", "rut": rut(60000000),
         "region": "RM", "confidence": 0.9, "source_document_id": "DOC-1"},
    ])
    _run(tmp_path, facts, silver)
    out = tmp_path / "links.parquet"
    # El RUT no coincide y el nombre tampoco se parece: no debe inventarse un enlace.
    assert not out.exists() or pd.read_parquet(out).empty


# ---------------------------------------------------------------------------
# Lo que el sistema declara cuando no puede acreditar identidad
# ---------------------------------------------------------------------------

def test_zero_external_ruts_is_declared_not_hidden(tmp_path: Path):
    """Es el estado real de la fuente CGR hoy: publica el campo y lo deja vacío."""
    facts = _facts(tmp_path, [_fact(77111222, "EMPRESA UNO LIMITADA")])
    silver = _silver(tmp_path, [
        {"provider_id": "ENT-1", "name": "Empresa Uno Limitada",
         "normalized_name": "EMPRESA UNO LIMITADA", "rut": "", "region": "RM",
         "confidence": 0.9, "source_document_id": "DOC-1"},
    ])
    summary = _run(tmp_path, facts, silver)
    coverage = summary["identity_coverage"]

    assert coverage["external_provider_ruts_available"] == 0
    assert coverage["rut_links"] == 0
    assert coverage["name_exact_links"] == 1
    # El lado local sí tiene RUT: la brecha es de la fuente externa, y se dice.
    assert coverage["local_entities_with_rut"] == 1
    assert "no publica RUT" in summary["identity_note"]


def test_external_rut_is_read_whatever_the_field_is_called():
    assert external_rut({"rut": rut(77111222)}) == rut(77111222)
    assert external_rut({"tax_id": rut(77111222)}) == rut(77111222)
    assert external_rut({"rut_proveedor": rut(77111222)}) == rut(77111222)
    assert external_rut({"entity_id": f"ENT-RUT-{rut(77111222)}"}) == rut(77111222)
    # Un RUT con dígito verificador inválido no es un RUT.
    assert external_rut({"rut": "77111222-9"}) == ""
    assert external_rut({"rut": "", "name": "Empresa"}) == ""


def test_the_rut_index_skips_records_without_a_usable_identifier():
    index = build_rut_index([
        {"provider_id": "A", "rut": rut(77111222)},
        {"provider_id": "B", "rut": ""},
        {"rut": rut(60000000)},          # sin provider_id: no indexable
        {"provider_id": "D", "rut": "1-1"},  # DV inválido
    ], "provider_id")
    assert set(index) == {rut(77111222)}


# ---------------------------------------------------------------------------
# Lo que el score hace con esa distinción
# ---------------------------------------------------------------------------

from radar_presupuesto.prioritization import prioritize_signals

LINK_BASE = {
    "local_entity_type": "PROVIDER", "external_system": "RADAR_CGR",
    "external_name": "Externa", "external_document_id": "DOC-1",
    "name_similarity": 1.0, "region_agreement": None, "status": "CANDIDATE",
    "cgr_finding_count": 3, "cgr_max_aml_score": 90.0, "cgr_max_severity": "HIGH",
    "cgr_risk_families": "[]", "cgr_source_urls": "[]", "match_basis": "{}",
}


def _scoring_workspace(tmp_path: Path, grades: dict[str, str]):
    """Dos proveedores idénticos salvo por el grado de identidad de su enlace CGR."""
    facts, signals, links = [], [], []
    for i, (pid, grade) in enumerate(grades.items()):
        facts.append({
            "transaction_id": f"TX-{i}", "organization_id": "ORG-1", "provider_id": pid,
            "recipient_id": pid, "periodo": 2026, "mes": 6,
            "nombre_area": "Area", "nombre_capitulo": "Cap", "nombre_partida": "Part",
            "nombre_beneficiario": pid, "monto_devengado": 50_000_000.0,
            "orden_compra": "", "codigo_bip": "", "region": "RM",
            "is_provider": True, "is_aggregated": False, "subtitulo": "22", "item": "08",
        })
        signals.append({
            "signal_id": f"SIG-{i}", "signal_type": "AMOUNT_OUTLIER", "transaction_id": f"TX-{i}",
            "organization_id": "ORG-1", "recipient_id": pid, "provider_id": pid,
            "periodo": 2026, "mes": 6, "observed_value": 1.0, "expected_value": 1.0,
            "deviation": 1.0, "severity": "MEDIUM", "confidence": "MEDIUM",
            "record_class": "DERIVED_SIGNAL", "why_flagged": "fixture",
            "investigation_hypothesis": "fixture", "recommended_checks": "[]",
            "detected_at": "2026-01-01T00:00:00+00:00",
        })
        links.append({
            **LINK_BASE,
            "evidence_link_id": f"EVL-{i}", "local_entity_id": pid, "local_name": pid,
            "external_entity_id": f"ENT-{i}",
            "match_method": "RUT_VALIDATED" if grade == MATCH_GRADE_RUT else "EXACT_NORMALIZED_NAME",
            "confidence": 0.97 if grade == MATCH_GRADE_RUT else 0.79,
            "match_grade": grade,
        })

    facts_path = tmp_path / "facts.parquet"
    sig_path = tmp_path / "signals.parquet"
    links_path = tmp_path / "links.parquet"
    pd.DataFrame(facts).to_parquet(facts_path, index=False)
    pd.DataFrame(signals).to_parquet(sig_path, index=False)
    pd.DataFrame(links).to_parquet(links_path, index=False)

    prioritize_signals(
        str(facts_path), signals_path=str(sig_path), cgr_links_path=str(links_path),
        peer_context_path=str(tmp_path / "absent_peers.parquet"),
        output_parquet=str(tmp_path / "priority.parquet"),
        output_json=str(tmp_path / "queue.json"),
    )
    return pd.read_parquet(tmp_path / "priority.parquet").set_index("provider_id")


def test_a_rut_verified_link_outweighs_a_name_only_one(tmp_path: Path):
    df = _scoring_workspace(tmp_path, {
        "PRV-CON-RUT": MATCH_GRADE_RUT,
        "PRV-POR-NOMBRE": MATCH_GRADE_NAME_EXACT,
    })
    con_rut = df.loc["PRV-CON-RUT"]
    por_nombre = df.loc["PRV-POR-NOMBRE"]

    # Mismo monto, misma señal, misma severidad: la única diferencia es la identidad.
    assert con_rut.external_evidence_component > por_nombre.external_evidence_component
    assert con_rut.external_evidence_component == 7  # 5 de identidad + 2 de AML
    assert por_nombre.external_evidence_component == 2
    assert con_rut.investigation_priority_score > por_nombre.investigation_priority_score


def test_the_cgr_aml_score_does_not_weigh_on_an_unverified_identity(tmp_path: Path):
    """Ponderar un hallazgo ajeno por parecido de nombre es atribuirlo sin prueba."""
    df = _scoring_workspace(tmp_path, {
        "PRV-NOMBRE-EXACTO": MATCH_GRADE_NAME_EXACT,
        "PRV-NOMBRE-APROX": MATCH_GRADE_NAME_FUZZY,
    })
    # Ambos enlaces traen cgr_max_aml_score=90 y ninguno recibe el bono de 2.
    assert df.loc["PRV-NOMBRE-EXACTO"].external_evidence_component == 2
    assert df.loc["PRV-NOMBRE-APROX"].external_evidence_component == 1


def test_no_cgr_link_earns_nothing(tmp_path: Path):
    facts_path = tmp_path / "facts.parquet"
    sig_path = tmp_path / "signals.parquet"
    df = _scoring_workspace(tmp_path, {"PRV-UNO": MATCH_GRADE_RUT})
    assert df.loc["PRV-UNO"].external_evidence_component == 7

    # La misma corrida sin archivo de enlaces no debe regalar puntos.
    prioritize_signals(
        str(facts_path), signals_path=str(sig_path),
        cgr_links_path=str(tmp_path / "no_existe.parquet"),
        peer_context_path=str(tmp_path / "absent_peers.parquet"),
        output_parquet=str(tmp_path / "priority2.parquet"),
        output_json=str(tmp_path / "queue2.json"),
    )
    sin_cgr = pd.read_parquet(tmp_path / "priority2.parquet").set_index("provider_id")
    assert sin_cgr.loc["PRV-UNO"].external_evidence_component == 0
