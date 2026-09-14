"""Los casos sintéticos no pueden mover el ranking real.

Tres barreras independientes lo impiden. Cada una se prueba sola, y después se
prueba que hacen falta las tres: romper una no basta.
"""
import json
from pathlib import Path

import pytest

from radar_presupuesto.calibration import (
    BACKUP_SCHEMA,
    SYNTHETIC_BACKUP_SCHEMA,
    SYNTHETIC_WARNING,
    build_calibration,
    load_closed_cases,
    load_multipliers,
)

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from generate_synthetic_cases import SCENARIOS, build_cases, write  # noqa: E402


@pytest.fixture
def generated(tmp_path: Path):
    backup, findings, total = write(tmp_path / "synthetic", seed=20260914)
    return backup, findings, total


# ---------------------------------------------------------------------------
# Barrera 1: otro esquema
# ---------------------------------------------------------------------------

def test_the_production_loader_ignores_synthetic_backups(generated):
    backup, _, _ = generated
    closed, stats = load_closed_cases(str(backup.parent))

    assert closed == [], "un caso sintético no debe entrar por la puerta de producción"
    assert stats["cases_closed"] == 0
    assert stats["synthetic_rejected"] >= 1, "y el rechazo debe quedar contado, no ser silencioso"


def test_the_synthetic_backup_does_not_claim_the_real_schema(generated):
    backup, _, _ = generated
    payload = json.loads(backup.read_text(encoding="utf-8"))
    assert payload["schema"] == SYNTHETIC_BACKUP_SCHEMA
    assert payload["schema"] != BACKUP_SCHEMA
    assert payload["synthetic"] is True
    assert "no corresponde a ninguna revisión real" in payload["synthetic_warning"].lower()
    assert all(c["synthetic"] is True for c in payload["cases"])


# ---------------------------------------------------------------------------
# Barrera 2: opt-in explícito
# ---------------------------------------------------------------------------

def test_reading_synthetic_cases_requires_asking_for_them(generated):
    backup, _, _ = generated
    closed, stats = load_closed_cases(str(backup.parent), allow_synthetic=True)

    assert closed, "con el opt-in explícito sí se leen"
    assert stats["synthetic_files"] == 1
    assert stats["cases_open"] == 12, "los expedientes abiertos siguen sin contar como etiquetas"


# ---------------------------------------------------------------------------
# Barrera 3: el resultado queda marcado
# ---------------------------------------------------------------------------

def test_a_simulated_payload_can_never_feed_the_score(generated):
    backup, findings, _ = generated
    out = backup.parent / "calibration-simulada.json"
    payload = build_calibration(
        cases_source=str(backup.parent), findings_json=str(findings),
        output_json=str(out), allow_synthetic=True,
    )

    assert payload["synthetic"] is True
    assert payload["status"] == "SIMULACION"
    assert payload["synthetic_warning"] == SYNTHETIC_WARNING
    # Hay multiplicadores calculados...
    assert any(a["applied"] for a in payload["signal_calibration"].values())
    # ...y aun así ninguno llega al scoring.
    assert load_multipliers(str(out)) == {}


def test_even_copied_over_the_real_payload_it_is_refused(generated, tmp_path: Path):
    """La marca viaja con el resultado, no con su ubicación."""
    backup, findings, _ = generated
    simulada = backup.parent / "sim.json"
    build_calibration(cases_source=str(backup.parent), findings_json=str(findings),
                      output_json=str(simulada), allow_synthetic=True)

    suplantado = tmp_path / "calibration.json"
    suplantado.write_text(simulada.read_text(encoding="utf-8"), encoding="utf-8")
    assert load_multipliers(str(suplantado)) == {}


# ---------------------------------------------------------------------------
# El escenario sirve para algo: ejercita las cuatro reglas del mecanismo
# ---------------------------------------------------------------------------

def test_the_scenario_exercises_every_rule_of_the_mechanism(generated):
    backup, findings, _ = generated
    payload = build_calibration(
        cases_source=str(backup.parent), findings_json=str(findings),
        output_json=str(backup.parent / "sim2.json"), allow_synthetic=True,
    )
    cal = payload["signal_calibration"]

    # Patrón útil: sube.
    assert cal["PROVIDER_CONCENTRATION"]["multiplier"] > 1.0
    # Patrón poco rendidor: baja, pero sigue publicándose.
    assert 0 < cal["YEAR_END_SPIKE"]["multiplier"] < 1.0
    # Muestra insuficiente: no ajusta pese a buena precisión.
    assert cal["AMOUNT_OUTLIER"]["multiplier"] == 1.0
    assert cal["AMOUNT_OUTLIER"]["applied"] is False
    # Cierres explicados: cuentan en el denominador, no en el numerador.
    dup = cal["EXACT_DUPLICATE_CANDIDATE"]
    assert dup["explained"] == 9 and dup["escalated"] == 5
    assert dup["closed_cases"] == 15


def test_the_generator_is_reproducible_from_its_seed(tmp_path: Path):
    a, _ = build_cases(seed=7)
    b, _ = build_cases(seed=7)
    c, _ = build_cases(seed=8)
    assert a == b, "la misma semilla debe dar el mismo escenario"
    assert a != c


def test_every_scenario_declares_what_it_illustrates():
    for signal, closed, escalated, explained, note in SCENARIOS:
        assert escalated + explained <= closed, f"{signal}: los estados no pueden exceder los cierres"
        assert note.strip(), f"{signal}: el escenario no dice qué ilustra"


# ---------------------------------------------------------------------------
# La barrera que importa: la que no depende del archivo
# ---------------------------------------------------------------------------

def test_renaming_the_schema_is_not_enough_to_pass_synthetic_cases_as_real(generated, tmp_path: Path):
    """Las dos primeras barreras caen juntas al reescribir el esquema.

    Esta prueba existe porque la primera versión de este mecanismo sí se dejaba
    engañar así: las tres barreras colgaban del esquema del archivo. La marca
    por caso es la que lo impide.
    """
    backup, findings, _ = generated
    disfrazado = tmp_path / "disfrazado"
    disfrazado.mkdir()
    payload = json.loads(backup.read_text(encoding="utf-8"))
    payload["schema"] = BACKUP_SCHEMA      # se hace pasar por respaldo real
    payload.pop("synthetic", None)          # y se le quita la marca al archivo
    (disfrazado / "casos.json").write_text(json.dumps(payload), encoding="utf-8")

    out = tmp_path / "calibration.json"
    result = build_calibration(
        cases_source=str(disfrazado), findings_json=str(findings), output_json=str(out)
    )

    assert result["synthetic"] is True, "cada caso sigue declarándose sintético"
    assert result["status"] == "SIMULACION"
    assert load_multipliers(str(out)) == {}


def test_one_synthetic_case_contaminates_the_whole_run(tmp_path: Path):
    """Mezclar sintéticos con reales no da una calibración a medias: da una inaplicable."""
    d = tmp_path / "mezcla"
    d.mkdir()
    reales = [{"case_id": f"R{i}", "state": "ESCALADO", "finding_ids": ["HAL-1"]} for i in range(15)]
    reales.append({"case_id": "COLADO", "state": "CERRADO", "finding_ids": ["HAL-1"], "synthetic": True})
    (d / "mezcla.json").write_text(
        json.dumps({"schema": BACKUP_SCHEMA, "cases": reales}), encoding="utf-8"
    )
    findings = tmp_path / "f.json"
    findings.write_text(json.dumps({"relation_findings": [
        {"finding_id": "HAL-1", "signal_types": ["AMOUNT_OUTLIER"]}]}), encoding="utf-8")

    out = tmp_path / "cal.json"
    result = build_calibration(cases_source=str(d), findings_json=str(findings), output_json=str(out))
    assert result["synthetic"] is True
    assert load_multipliers(str(out)) == {}
