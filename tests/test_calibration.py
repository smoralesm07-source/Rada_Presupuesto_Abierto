from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from radar_presupuesto.calibration import (
    DEFAULT_POLICY,
    build_calibration,
    collect_outcomes,
    load_multipliers,
)
from radar_presupuesto.case_model import (
    apply_decision, new_case, seal, set_hypothesis,
)
from radar_presupuesto.prioritization import prioritize_signals


def _case(index: int, signals: list[str], outcome: str, typology: str = "") -> dict:
    case = new_case(
        f"ORG-{index % 3}", f"PRV-RUT-{index}", 2026,
        review_priority_score=80.0, source_signals=signals,
    )
    case["source_signals"] = list(signals)
    apply_decision(case, to_state="EN_REVISION", rationale="tomo el caso", actor="ana")
    if outcome == "ESCALADO":
        set_hypothesis(case, typology=typology or "PROVEEDOR_FACHADA",
                       statement="Hipótesis sostenida.", author="ana")
        apply_decision(case, to_state="ESCALADO", rationale="convergen patrones", actor="ana")
    elif outcome:
        if typology:
            set_hypothesis(case, typology=typology, statement="Hipótesis evaluada.", author="ana")
        apply_decision(case, to_state=outcome, rationale="explicación documentada", actor="ana")
    return case


def _write(tmp_path: Path, cases: list[dict]) -> Path:
    folder = tmp_path / "cases"
    folder.mkdir(parents=True, exist_ok=True)
    for i, case in enumerate(cases):
        (folder / f"case-{i}.json").write_text(
            json.dumps(seal(case, exported_by="ana"), ensure_ascii=False), encoding="utf-8"
        )
    return folder


def test_open_cases_are_not_treated_as_negative_results(tmp_path):
    """Un expediente abierto es trabajo inconcluso, no un falso positivo."""
    cases = [_case(i, ["AMOUNT_OUTLIER"], "") for i in range(12)]
    payload = build_calibration(
        [_write(tmp_path, cases)], output_json=tmp_path / "cal.json"
    )
    assert payload["evidence"]["labelled_cases"] == 0
    assert payload["evidence"]["open_cases"] == 12
    assert payload["by_signal_type"] == {}


def test_a_small_sample_never_moves_the_score(tmp_path):
    cases = [_case(i, ["AMOUNT_OUTLIER"], "CERRADO_SIN_MERITO") for i in range(3)]
    payload = build_calibration([_write(tmp_path, cases)], output_json=tmp_path / "cal.json")
    entry = payload["by_signal_type"]["AMOUNT_OUTLIER"]

    assert entry["closed_cases"] == 3
    assert entry["multiplier"] == 1.0
    assert entry["applied"] is False
    assert "anécdota" in entry["why"]
    assert load_multipliers(tmp_path / "cal.json") == {}


def test_a_pattern_the_analyst_keeps_discarding_is_deprioritised(tmp_path):
    cases = [_case(i, ["AMOUNT_OUTLIER"], "CERRADO_SIN_MERITO") for i in range(14)]
    payload = build_calibration([_write(tmp_path, cases)], output_json=tmp_path / "cal.json")
    entry = payload["by_signal_type"]["AMOUNT_OUTLIER"]

    assert entry["closed_cases"] == 14
    assert entry["observed_precision"] == 0.0
    assert entry["multiplier"] == DEFAULT_POLICY["multiplier_floor"]
    assert entry["applied"] is True
    assert "precisión observada 0%" in entry["why"]
    assert load_multipliers(tmp_path / "cal.json")["AMOUNT_OUTLIER"] < 1.0


def test_a_pattern_that_keeps_leading_somewhere_is_promoted(tmp_path):
    cases = [_case(i, ["POTENTIAL_FRAGMENTATION"], "ESCALADO") for i in range(12)]
    payload = build_calibration([_write(tmp_path, cases)], output_json=tmp_path / "cal.json")
    entry = payload["by_signal_type"]["POTENTIAL_FRAGMENTATION"]

    assert entry["observed_precision"] == 1.0
    assert entry["multiplier"] == DEFAULT_POLICY["multiplier_ceiling"]
    assert entry["multiplier"] <= 1.30, "el ajuste tiene que quedar acotado"


def test_adjustment_stays_inside_the_configured_band(tmp_path):
    for outcome in ("CERRADO_SIN_MERITO", "ESCALADO"):
        cases = [_case(i, ["EXACT_DUPLICATE_CANDIDATE"], outcome) for i in range(40)]
        payload = build_calibration(
            [_write(tmp_path / outcome, cases)], output_json=tmp_path / f"cal-{outcome}.json"
        )
        multiplier = payload["by_signal_type"]["EXACT_DUPLICATE_CANDIDATE"]["multiplier"]
        assert DEFAULT_POLICY["multiplier_floor"] <= multiplier <= DEFAULT_POLICY["multiplier_ceiling"]


def test_a_tampered_expediente_is_rejected_not_learned_from(tmp_path):
    """Nada que no verifique su hash puede enseñarle algo al modelo."""
    cases = [_case(i, ["AMOUNT_OUTLIER"], "CERRADO_SIN_MERITO") for i in range(12)]
    folder = _write(tmp_path, cases)
    target = folder / "case-0.json"
    envelope = json.loads(target.read_text(encoding="utf-8"))
    envelope["case"]["state"] = "ESCALADO"  # editado después de sellarse
    target.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")

    payload = build_calibration([folder], output_json=tmp_path / "cal.json")
    assert payload["evidence"]["rejected"] == 1
    assert payload["evidence"]["verified"] == 11
    assert payload["evidence"]["rejected_detail"][0]["problems"]


def test_calibration_can_be_switched_off(tmp_path):
    cases = [_case(i, ["AMOUNT_OUTLIER"], "CERRADO_SIN_MERITO") for i in range(14)]
    build_calibration(
        [_write(tmp_path, cases)], output_json=tmp_path / "cal.json", policy={"apply": False}
    )
    assert load_multipliers(tmp_path / "cal.json") == {}


def test_guardrail_refuses_to_read_precision_as_truth(tmp_path):
    payload = build_calibration([tmp_path / "vacio"], output_json=tmp_path / "cal.json")
    assert "no verdad" in payload["guardrail"]
    assert "muestra es pequeña" in payload["guardrail"]
    assert payload["label_definition"]["EN_CURSO"].startswith("No es una etiqueta")


SIGNAL_COLUMNS = [
    "signal_id", "signal_type", "transaction_id", "organization_id", "recipient_id",
    "provider_id", "periodo", "mes", "observed_value", "expected_value", "deviation",
    "severity", "confidence", "record_class", "why_flagged", "investigation_hypothesis",
    "recommended_checks",
]


def test_calibration_actually_reorders_the_published_queue(tmp_path):
    """El aprendizaje tiene que llegar a la cola, no quedarse en un informe."""
    facts, signals = [], []
    for i in range(20):
        for kind, prefix in (("AMOUNT_OUTLIER", "A"), ("POTENTIAL_FRAGMENTATION", "F")):
            provider = f"PRV-RUT-{prefix}{i:02d}"
            tx = f"TRX-{prefix}-{i:02d}"
            facts.append({
                "transaction_id": tx, "organization_id": "ORG-1", "provider_id": provider,
                "recipient_id": provider.replace("PRV", "RCV"), "periodo": 2026, "mes": 6,
                "subtitulo": "22", "monto_devengado": 100_000_000.0,
                "nombre_beneficiario": provider, "nombre_area": "ORG-1",
                "nombre_capitulo": "ORG-1", "nombre_partida": "ORG-1",
                "orden_compra": "", "codigo_bip": "", "region": "13", "is_aggregated": False,
                "fecha_documento": pd.Timestamp("2026-06-01"),
                "fecha_pago": pd.Timestamp("2026-06-20"),
            })
            if i < 2:
                signals.append({
                    "signal_id": f"SIG-{kind}-{i}", "signal_type": kind, "transaction_id": tx,
                    "organization_id": "ORG-1", "recipient_id": provider.replace("PRV", "RCV"),
                    "provider_id": provider, "periodo": 2026, "mes": 6,
                    "observed_value": 1.0, "expected_value": 1.0, "deviation": 1.0,
                    "severity": "HIGH", "confidence": "MEDIUM", "record_class": "DERIVED_SIGNAL",
                    "why_flagged": "t", "investigation_hypothesis": "t", "recommended_checks": "[]",
                })
    facts_path = tmp_path / "f.parquet"
    pd.DataFrame(facts).to_parquet(facts_path, index=False)
    signals_path = tmp_path / "s.parquet"
    pd.DataFrame(signals, columns=SIGNAL_COLUMNS).to_parquet(signals_path, index=False)

    # El analista descarta sistemáticamente los montos atípicos.
    cases = [_case(i, ["AMOUNT_OUTLIER"], "CERRADO_SIN_MERITO") for i in range(14)]
    cal = tmp_path / "cal.json"
    build_calibration([_write(tmp_path, cases)], output_json=cal)

    def run(calibration_path):
        prioritize_signals(
            str(facts_path), signals_path=str(signals_path),
            cgr_links_path=str(tmp_path / "no.parquet"),
            entity_signals_path=str(tmp_path / "no2.parquet"),
            calibration_path=str(calibration_path),
            output_parquet=str(tmp_path / "p.parquet"),
            output_json=str(tmp_path / "q.json"),
        )
        frame = pd.read_parquet(tmp_path / "p.parquet")
        return frame.groupby("signal_type")["review_priority_score"].max().to_dict()

    before = run(tmp_path / "inexistente.json")
    after = run(cal)

    assert before["AMOUNT_OUTLIER"] == before["POTENTIAL_FRAGMENTATION"]
    assert after["AMOUNT_OUTLIER"] < before["AMOUNT_OUTLIER"]
    assert after["POTENTIAL_FRAGMENTATION"] == before["POTENTIAL_FRAGMENTATION"]

    queue = json.loads((tmp_path / "q.json").read_text(encoding="utf-8"))
    assert queue["calibration"]["multipliers_applied"] == 1
    explained = [r for r in queue["queue"] if r["signal_type"] == "AMOUNT_OUTLIER"][0]
    assert "calibración=x" in explained["priority_explanation"]
