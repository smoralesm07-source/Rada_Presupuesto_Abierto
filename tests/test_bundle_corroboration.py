"""Lo que la regla de corroboración cambia en el payload publicado."""
import json
from pathlib import Path

from radar_presupuesto.operational_bundle import annotate_published_findings


def _findings(tmp_path: Path, relations: list[dict]) -> Path:
    path = tmp_path / "findings.json"
    path.write_text(
        json.dumps({"relation_findings": relations}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _relation(i: int, signal_types: list[str]) -> dict:
    return {
        "finding_id": f"HAL-{i}",
        "organization_id": "ORG-1",
        "provider_id": f"PRV-{i}",
        "periodo": 2026,
        "signal_types": signal_types,
        "max_priority_score": 70,
        "attention_level": "REVISION_PRIORITARIA",
    }


def test_single_signal_relation_keeps_the_similarity_but_loses_the_hypothesis(tmp_path: Path):
    path = _findings(tmp_path, [_relation(1, ["PROVIDER_CONCENTRATION"])])
    coverage = annotate_published_findings(
        findings_json=str(path),
        peer_parquet=str(tmp_path / "missing_peers.parquet"),
        years=[2026],
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    row = payload["relation_findings"][0]

    assert row["primary_pattern"] is None, "una sola señal no debe proponer hipótesis"
    # Pero el parecido no se borra: el analista ve a qué se parece y qué le falta.
    assert row["pattern_compatibility"], "el parecido descriptivo no debe desaparecer"
    top = row["pattern_compatibility"][0]
    assert top["pattern_code"] == "CONCENTRACION_COMPETENCIA"
    assert top["evidence_status"] == "SIN_CORROBORAR"
    assert top["discards"], "el descarte viaja con la fila"

    assert coverage["relations_with_primary_pattern"] == 0
    assert coverage["relations_with_uncorroborated_similarity"] == 1


def test_two_concurrent_signals_still_produce_a_primary_pattern(tmp_path: Path):
    path = _findings(
        tmp_path,
        [_relation(2, ["POTENTIAL_FRAGMENTATION", "EXACT_DUPLICATE_CANDIDATE"])],
    )
    coverage = annotate_published_findings(
        findings_json=str(path),
        peer_parquet=str(tmp_path / "missing_peers.parquet"),
        years=[2026],
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    row = payload["relation_findings"][0]

    assert row["primary_pattern"] is not None
    assert row["primary_pattern"]["pattern_code"] == "INTEGRIDAD_DOCUMENTAL"
    assert row["primary_pattern"]["corroborated"] is True
    assert coverage["relations_with_primary_pattern"] == 1
    assert coverage["relations_with_uncorroborated_similarity"] == 0


def test_profile_catalogue_and_rule_travel_once_at_payload_level(tmp_path: Path):
    """Los descartes son texto fijo: pesan una vez, no una vez por relación."""
    path = _findings(tmp_path, [_relation(i, ["YEAR_END_SPIKE"]) for i in range(5)])
    annotate_published_findings(
        findings_json=str(path),
        peer_parquet=str(tmp_path / "missing_peers.parquet"),
        years=[2026],
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    profiles = payload["pattern_profiles"]
    assert len(profiles) == 4
    assert all(p["discards"] and p["next_document"] for p in profiles)
    assert "2 patrones concurrentes" in payload["corroboration_rule"]
