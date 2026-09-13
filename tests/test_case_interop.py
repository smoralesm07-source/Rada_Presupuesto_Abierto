from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from radar_presupuesto.case_model import (
    add_evidence,
    apply_decision,
    canonical_json,
    content_hash,
    new_case,
    seal,
    verify,
)

NODE = shutil.which("node")
APP = Path("docs/app")


def _worked_case() -> dict:
    case = new_case(
        "ORG-PA-13-06-001",
        "PRV-RUT-76071943-9",
        2026,
        organization_name="COMISIÓN NACIONAL DE RIEGO",
        provider_name="GLOBAL CATALOG LTDA",
        owner="ana",
        review_priority_score=78.0,   # float entero: el caso que rompe el hash si no se normaliza
        laft_compatibility_score=61.5,
        typology="PROVEEDOR_FACHADA",
    )
    apply_decision(case, to_state="EN_REVISION", rationale="tomo el caso", actor="ana")
    add_evidence(
        case,
        kind="REGISTRO_PUBLICO",
        title="Constitución societaria",
        source_url="https://registro.example/1",
        added_by="ana",
    )
    return case


def test_integral_floats_serialise_like_javascript():
    """78.0 en Python y 78 en JavaScript deben producir los mismos bytes."""
    assert '"a":78' in canonical_json({"a": 78.0})
    assert '"b":61.5' in canonical_json({"b": 61.5})
    assert canonical_json({"z": 1, "a": 2}) == '{"a":2,"z":1}'


@pytest.mark.skipif(NODE is None, reason="node no disponible")
def test_browser_and_python_agree_on_the_sealed_hash(tmp_path):
    """Un expediente sellado en el navegador tiene que verificar en Python.

    Si ambos lados no serializan igual, la verificación de integridad falla en
    cada traspaso y la cadena de custodia no sirve para nada.
    """
    case = _worked_case()
    envelope = seal(case, exported_by="ana")
    payload = tmp_path / "case.json"
    payload.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")

    script = tmp_path / "check.mjs"
    script.write_text(
        textwrap.dedent(
            f"""
            import {{ readFileSync }} from 'node:fs';
            import {{ webcrypto }} from 'node:crypto';
            if (!globalThis.crypto) globalThis.crypto = webcrypto;
            const {{ verify, contentHash }} = await import('{APP.resolve().as_posix()}/cases.mjs');
            const envelope = JSON.parse(readFileSync('{payload.as_posix()}', 'utf-8'));
            const report = await verify(envelope);
            process.stdout.write(JSON.stringify({{
              valid: report.valid,
              problems: report.problems,
              hash: await contentHash(envelope.case),
            }}));
            """
        ).strip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [NODE, str(script)], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)

    assert report["hash"] == content_hash(case), (
        "el navegador y Python deben calcular el mismo hash del expediente"
    )
    assert report["valid"], report["problems"]


@pytest.mark.skipif(NODE is None, reason="node no disponible")
def test_browser_detects_tampering_the_same_way(tmp_path):
    case = _worked_case()
    envelope = seal(case)
    envelope["case"]["state"] = "CERRADO_EXPLICADO"  # editado sin rehacer el sobre
    payload = tmp_path / "case.json"
    payload.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")

    script = tmp_path / "check.mjs"
    script.write_text(
        textwrap.dedent(
            f"""
            import {{ readFileSync }} from 'node:fs';
            import {{ webcrypto }} from 'node:crypto';
            if (!globalThis.crypto) globalThis.crypto = webcrypto;
            const {{ verify }} = await import('{APP.resolve().as_posix()}/cases.mjs');
            const report = await verify(JSON.parse(readFileSync('{payload.as_posix()}', 'utf-8')));
            process.stdout.write(JSON.stringify(report));
            """
        ).strip(),
        encoding="utf-8",
    )
    result = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)

    assert not report["valid"]
    assert not verify(envelope)["valid"]


@pytest.mark.skipif(NODE is None, reason="node no disponible")
def test_state_machines_are_identical_on_both_sides(tmp_path):
    from radar_presupuesto.case_model import CASE_STATES, CLOSING_STATES, TRANSITIONS

    script = tmp_path / "states.mjs"
    script.write_text(
        textwrap.dedent(
            f"""
            const m = await import('{APP.resolve().as_posix()}/cases.mjs');
            process.stdout.write(JSON.stringify({{
              states: Object.keys(m.CASE_STATES).sort(),
              transitions: Object.fromEntries(
                Object.entries(m.TRANSITIONS).map(([k, v]) => [k, [...v].sort()])
              ),
              closing: [...m.CLOSING_STATES].sort(),
              chain: m.VERIFICATION_CHAIN.map((s) => [s.stage, s.status]),
            }}));
            """
        ).strip(),
        encoding="utf-8",
    )
    result = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    js = json.loads(result.stdout)

    assert js["states"] == sorted(CASE_STATES)
    assert js["closing"] == sorted(CLOSING_STATES)
    assert js["transitions"] == {k: sorted(v) for k, v in TRANSITIONS.items()}
    # Las etapas 2 a 4 siguen declarando honestamente que no están integradas.
    assert js["chain"] == [[1, "DISPONIBLE"], [2, "POR_INTEGRAR"], [3, "POR_VERIFICAR"], [4, "NO_DETERMINADO"]]
