from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from radar_presupuesto.cgr_correlation import (
    MATCH_GRADE_NAME_EXACT,
    MATCH_GRADE_NAME_FUZZY,
    MATCH_GRADE_RUT,
    NAME_CONFIDENCE_CEILING,
    build_rut_index,
    correlate_with_cgr,
    external_rut,
)


def _silver(tmp_path: Path, providers: list[dict], orgs: list[dict] | None = None) -> Path:
    silver = tmp_path / "silver"
    silver.mkdir(parents=True, exist_ok=True)
    (silver / "providers.jsonl").write_text(
        "\n".join(json.dumps(p, ensure_ascii=False) for p in providers), encoding="utf-8"
    )
    (silver / "organizations.jsonl").write_text(
        "\n".join(json.dumps(o, ensure_ascii=False) for o in (orgs or [])), encoding="utf-8"
    )
    (silver / "findings.jsonl").write_text(
        json.dumps(
            {
                "document_id": "DOC-1",
                "aml_score": 88,
                "severity": "HIGH",
                "risk_family": "PROBIDAD",
                "source_url": "https://contraloria.cl/doc-1",
            }
        ),
        encoding="utf-8",
    )
    return silver


def _facts(tmp_path: Path, rows: list[dict]) -> str:
    path = tmp_path / "transactions.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    return str(path)


def _fact(rut: str, name: str) -> dict:
    return {
        "provider_id": f"PRV-RUT-{rut}",
        "organization_id": "ORG-PA-13-06-001",
        "nombre_beneficiario": name,
        "rut_beneficiario": rut,
        "region": "METROPOLITANA",
        "is_provider": True,
        "is_aggregated": False,
        "nombre_area": "AREA X",
        "nombre_capitulo": "CAPITULO X",
        "nombre_partida": "PARTIDA X",
        "monto_devengado": 1_000_000.0,
        "periodo": 2026,
    }


def test_external_rut_is_read_from_any_reasonable_field():
    assert external_rut({"rut": "76071943-9"}) == "76071943-9"
    assert external_rut({"rut_proveedor": "76.071.943-9"}) == "76071943-9"
    assert external_rut({"entity_id": "ENT-RUT-76071943-9"}) == "76071943-9"
    assert external_rut({"rut": "76071943-1"}) == "", "un DV inválido no es un RUT"
    assert external_rut({"name": "ACME"}) == ""


def test_rut_index_ignores_records_without_validated_rut():
    index = build_rut_index(
        [
            {"provider_id": "P1", "rut": "76071943-9"},
            {"provider_id": "P2", "rut": "no-es-un-rut"},
            {"rut": "77111222-6"},  # sin provider_id
        ],
        "provider_id",
    )
    assert set(index) == {"76071943-9"}


def test_rut_match_beats_name_and_is_graded(tmp_path):
    silver = _silver(
        tmp_path,
        [
            {
                "provider_id": "CGR-1",
                "rut": "76071943-9",
                "name": "NOMBRE COMPLETAMENTE DISTINTO SPA",
                "normalized_name": "NOMBRE COMPLETAMENTE DISTINTO SPA",
                "source_document_id": "DOC-1",
                "confidence": 0.9,
            }
        ],
    )
    facts = _facts(tmp_path, [_fact("76071943-9", "GLOBAL CATALOG LTDA")])
    summary = correlate_with_cgr(
        facts,
        cgr_silver_dir=str(silver),
        output_parquet=str(tmp_path / "links.parquet"),
        output_json=str(tmp_path / "cgr.json"),
    )
    links = pd.read_parquet(tmp_path / "links.parquet")
    provider = links[links["local_entity_type"] == "PROVIDER"].iloc[0]

    assert provider["match_grade"] == MATCH_GRADE_RUT
    assert provider["confidence"] >= 0.88
    assert provider["status"] == "CANDIDATE"
    assert summary["providers_matched_by_rut"] == 1
    assert summary["by_match_grade"][MATCH_GRADE_RUT] == 1


def test_name_only_match_cannot_reach_high_confidence(tmp_path):
    """Una coincidencia de nombre no puede comprar el peso alto en la prioridad."""
    silver = _silver(
        tmp_path,
        [
            {
                "provider_id": "CGR-2",
                "name": "GLOBAL CATALOG LTDA",
                "normalized_name": "GLOBAL CATALOG LTDA",
                "source_document_id": "DOC-1",
                "confidence": 1.0,
            }
        ],
    )
    facts = _facts(tmp_path, [_fact("76071943-9", "GLOBAL CATALOG LTDA")])
    correlate_with_cgr(
        facts,
        cgr_silver_dir=str(silver),
        output_parquet=str(tmp_path / "links.parquet"),
        output_json=str(tmp_path / "cgr.json"),
    )
    links = pd.read_parquet(tmp_path / "links.parquet")
    provider = links[links["local_entity_type"] == "PROVIDER"].iloc[0]

    assert provider["match_grade"] == MATCH_GRADE_NAME_EXACT
    assert provider["confidence"] <= NAME_CONFIDENCE_CEILING
    assert provider["confidence"] < 0.88, (
        "un match por nombre no debe alcanzar el umbral de confianza alta"
    )
    basis = json.loads(provider["match_basis"])
    assert basis["grade"] == MATCH_GRADE_NAME_EXACT
    assert "no acredita identidad" in basis["note"]


def test_methodology_states_the_rut_first_policy(tmp_path):
    silver = _silver(tmp_path, [])
    facts = _facts(tmp_path, [_fact("76071943-9", "ACME")])
    summary = correlate_with_cgr(
        facts,
        cgr_silver_dir=str(silver),
        output_parquet=str(tmp_path / "links.parquet"),
        output_json=str(tmp_path / "cgr.json"),
    )
    assert "RUT validado" in summary["methodology"]
    assert "dígito verificador" in summary["methodology"]
    assert summary["links"] == 0
