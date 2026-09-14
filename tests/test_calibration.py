"""Lo que el analista cerró, devuelto al ranking — con frenos.

Cuatro reglas evitan que esta capa haga daño: sólo los cierres son etiquetas,
hay umbral de evidencia, el ajuste es acotado, y nunca es silencioso.
"""
import json
from pathlib import Path

import pytest

from radar_presupuesto.calibration import (
    BACKUP_SCHEMA,
    SCHEMA,
    build_calibration,
    load_closed_cases,
    load_multipliers,
    load_policy,
    measure,
    multipliers,
)

POLICY = {
    "apply": True, "min_closed_cases": 10,
    "multiplier_floor": 0.70, "multiplier_ceiling": 1.30,
    "neutral_precision": 0.35,
}


def _backup(tmp_path: Path, cases: list[dict], name: str = "respaldo.json") -> Path:
    d = tmp_path / "cases"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(
        json.dumps({"schema": BACKUP_SCHEMA, "cases": cases}, ensure_ascii=False), encoding="utf-8"
    )
    return d


def _case(i: int, state: str, finding_ids=("HAL-1",)):
    return {"case_id": f"CASO-{i}", "case_ref": f"REF-{i}", "state": state,
            "finding_ids": list(finding_ids), "events": [], "case_notes": []}


def _findings(signal_types, finding_id="HAL-1"):
    return {"relation_findings": [{"finding_id": finding_id, "signal_types": list(signal_types)}]}


# ---------------------------------------------------------------------------
# Regla 1: sólo los casos cerrados son etiquetas
# ---------------------------------------------------------------------------

def test_open_cases_are_not_negative_results(tmp_path: Path):
    d = _backup(tmp_path, [
        _case(1, "ESCALADO"), _case(2, "CERRADO"),
        _case(3, "TRIAGE"), _case(4, "EN_REVISION"), _case(5, "PROFUNDIZAR"),
    ])
    closed, stats = load_closed_cases(str(d))
    assert stats["cases_closed"] == 2
    assert stats["cases_open"] == 3
    assert {c["state"] for c in closed} == {"ESCALADO", "CERRADO"}


def test_a_backup_of_another_schema_is_rejected_whole(tmp_path: Path):
    d = tmp_path / "cases"
    d.mkdir()
    (d / "ajeno.json").write_text(json.dumps({"schema": "OTRA-COSA-v1", "cases": [_case(1, "ESCALADO")]}), encoding="utf-8")
    (d / "roto.json").write_text("{no es json", encoding="utf-8")
    closed, stats = load_closed_cases(str(d))
    assert closed == []
    assert stats["files_rejected"] == 2
    assert stats["files_read"] == 0


def test_the_same_case_exported_twice_counts_once(tmp_path: Path):
    d = _backup(tmp_path, [_case(1, "ESCALADO")], "uno.json")
    (d / "dos.json").write_text(
        json.dumps({"schema": BACKUP_SCHEMA, "cases": [_case(1, "ESCALADO")]}), encoding="utf-8"
    )
    closed, stats = load_closed_cases(str(d))
    assert len(closed) == 1
    assert stats["cases_seen"] == 1


# ---------------------------------------------------------------------------
# Regla 2: umbral de evidencia
# ---------------------------------------------------------------------------

def test_a_short_sample_never_moves_the_score():
    """Tres descartes son una anécdota, no una medición."""
    cases = [_case(i, "CERRADO") for i in range(3)]
    m = measure(cases, _findings(["AMOUNT_OUTLIER"]))
    adj = multipliers(m, POLICY)["AMOUNT_OUTLIER"]

    assert adj["closed_cases"] == 3
    assert adj["observed_precision"] == 0.0     # ninguno escaló
    assert adj["multiplier"] == 1.0             # y aun así no se castiga
    assert adj["applied"] is False
    assert "10" in adj["why"]


# ---------------------------------------------------------------------------
# Regla 3: acotado
# ---------------------------------------------------------------------------

def test_a_useless_pattern_is_demoted_but_never_buried():
    cases = [_case(i, "CERRADO") for i in range(20)]
    adj = multipliers(measure(cases, _findings(["YEAR_END_SPIKE"])), POLICY)["YEAR_END_SPIKE"]

    assert adj["observed_precision"] == 0.0
    assert adj["multiplier"] == POLICY["multiplier_floor"]
    assert adj["multiplier"] > 0, "el patrón sigue publicándose, con menos peso"
    assert adj["applied"] is True
    assert "sigue publicándose" in adj["why"]


def test_a_useful_pattern_is_promoted_within_the_band():
    cases = [_case(i, "ESCALADO") for i in range(20)]
    adj = multipliers(measure(cases, _findings(["PROVIDER_CONCENTRATION"])), POLICY)["PROVIDER_CONCENTRATION"]

    assert adj["observed_precision"] == 1.0
    assert adj["multiplier"] == POLICY["multiplier_ceiling"]
    assert adj["applied"] is True


def test_an_explained_closure_counts_as_review_but_not_as_a_hit():
    """Encontrar una explicación legítima no es un fracaso del patrón."""
    cases = [_case(i, "EXPLICADO") for i in range(10)]
    m = measure(cases, _findings(["POTENTIAL_FRAGMENTATION"]))["POTENTIAL_FRAGMENTATION"]
    assert m["closed"] == 10
    assert m["explained"] == 10
    assert m["escalated"] == 0
    assert m["dismissed"] == 0


# ---------------------------------------------------------------------------
# Regla 4: nunca silencioso
# ---------------------------------------------------------------------------

def test_every_adjustment_reports_its_sample_and_its_reason():
    cases = [_case(i, "ESCALADO" if i < 8 else "CERRADO") for i in range(20)]
    adj = multipliers(measure(cases, _findings(["AMOUNT_OUTLIER"])), POLICY)["AMOUNT_OUTLIER"]
    assert adj["closed_cases"] == 20
    assert adj["escalated"] == 8
    assert "8 de 20" in adj["why"]
    assert "%" in adj["why"]


def test_calibration_can_be_switched_off_entirely():
    cases = [_case(i, "CERRADO") for i in range(50)]
    off = dict(POLICY, apply=False)
    adj = multipliers(measure(cases, _findings(["AMOUNT_OUTLIER"])), off)["AMOUNT_OUTLIER"]
    assert adj["multiplier"] == 1.0
    assert "desactivada" in adj["why"]


def test_no_closures_is_declared_not_passed_off_as_calibrated(tmp_path: Path):
    payload = build_calibration(
        cases_source=str(tmp_path / "vacio"),
        findings_json=str(tmp_path / "sin_hallazgos.json"),
        output_json=str(tmp_path / "calibration.json"),
        policy_path=str(tmp_path / "sin_policy.yaml"),
    )
    assert payload["status"] == "SIN_CIERRES"
    assert "no se ha ejecutado" in payload["status_note"]
    assert payload["signal_calibration"] == {}
    assert "no verdad" in payload["guardrail"]


# ---------------------------------------------------------------------------
# El contrato con el scoring
# ---------------------------------------------------------------------------

def test_only_applied_multipliers_reach_the_scoring_table(tmp_path: Path):
    out = tmp_path / "calibration.json"
    d = _backup(tmp_path, [_case(i, "CERRADO") for i in range(20)] + [_case(99, "ESCALADO", ["HAL-2"])])
    findings = tmp_path / "findings.json"
    findings.write_text(json.dumps({"relation_findings": [
        {"finding_id": "HAL-1", "signal_types": ["YEAR_END_SPIKE"]},
        {"finding_id": "HAL-2", "signal_types": ["AMOUNT_OUTLIER"]},
    ]}), encoding="utf-8")

    build_calibration(cases_source=str(d), findings_json=str(findings),
                      output_json=str(out), policy_path=str(tmp_path / "np.yaml"))
    table = load_multipliers(str(out))

    # YEAR_END_SPIKE tiene 20 cierres sin escaladas: ajusta.
    assert "YEAR_END_SPIKE" in table and table["YEAR_END_SPIKE"] < 1.0
    # AMOUNT_OUTLIER tiene un solo caso: no alcanza el umbral y no viaja.
    assert "AMOUNT_OUTLIER" not in table


def test_a_payload_of_another_schema_is_not_trusted_as_a_multiplier_table(tmp_path: Path):
    other = tmp_path / "otro.json"
    other.write_text(json.dumps({"schema": "OTRA-v9", "signal_calibration": {
        "AMOUNT_OUTLIER": {"multiplier": 0.1, "applied": True}}}), encoding="utf-8")
    assert load_multipliers(str(other)) == {}
    assert load_multipliers(str(tmp_path / "no_existe.json")) == {}


def test_the_repository_policy_is_loadable_and_keeps_one_inside_the_band():
    pol = load_policy()
    assert pol["multiplier_floor"] <= 1.0 <= pol["multiplier_ceiling"]
    assert pol["min_closed_cases"] >= 1


def test_a_band_that_excludes_one_is_refused(tmp_path: Path):
    bad = tmp_path / "mala.yaml"
    bad.write_text("calibration:\n  multiplier_floor: 1.10\n  multiplier_ceiling: 1.30\n", encoding="utf-8")
    with pytest.raises(ValueError, match="1.0"):
        load_policy(str(bad))
