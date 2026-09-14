#!/usr/bin/env python3
"""Publish the payloads that do not require a facts snapshot.

Two of the app's payloads are declarative — the typology catalog and the state
of the procurement adapter — and can be published on every deploy. Two others
(entity signals, opacity index) are computed by the pipeline over the parquet
facts, which Pages does not have.

Rather than let the browser 404 on the missing ones, this writes an explicit
"not generated yet" payload. A missing file and an empty result are different
things, and the interface has to be able to tell them apart.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from radar_presupuesto.calibration import GUARDRAIL as CALIBRATION_GUARDRAIL  # noqa: E402
from radar_presupuesto.procurement import write_status  # noqa: E402
from radar_presupuesto.relation_context import GUARDRAIL as OPACITY_GUARDRAIL  # noqa: E402
from radar_presupuesto.typologies import (  # noqa: E402
    GUARDRAIL as TYPOLOGY_GUARDRAIL,
    OBSERVABLE_LAYERS,
    PATTERN_LABEL,
    PATTERN_LAYER,
    TYPOLOGIES,
)

DATA = ROOT / "docs" / "data"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_typology_catalog() -> None:
    payload = {
        "schema": "RIGP-TYPOLOGY-CONTEXT-v1",
        "generated_at": now(),
        "guardrail": TYPOLOGY_GUARDRAIL,
        "observable_layers": sorted(OBSERVABLE_LAYERS),
        "pending_layers": sorted(set(PATTERN_LAYER.values()) - OBSERVABLE_LAYERS),
        "coverage_note": (
            "Las tipologías que dependen del proceso de compra o de propiedad y control no "
            "pueden alcanzar su puntaje máximo mientras esas fuentes no estén integradas."
        ),
        "catalog": [
            {
                "code": t.code,
                "name": t.name,
                "question": t.question,
                "anchors": [list(group) for group in t.anchors],
                "reinforcing": list(t.reinforcing),
                "sustains": list(t.sustains),
                "discards": list(t.discards),
                "documents": list(t.documents),
                "evidence_ceiling": t.evidence_ceiling,
                "reachable_today": t.anchorable_now,
                "missing_layers": list(t.missing_layers),
            }
            for t in TYPOLOGIES
        ],
        "pattern_layers": PATTERN_LAYER,
        "pattern_labels": PATTERN_LABEL,
    }
    (DATA / "typology_context.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )


def write_windows_context() -> None:
    """Publish the two horizons, so the interface can explain what it is not showing."""
    import yaml

    from radar_presupuesto.windows import from_config

    config_path = ROOT / "config" / "analysis_windows.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    payload = {
        "schema": "RIGP-ANALYSIS-WINDOWS-v1",
        "generated_at": now(),
        **from_config(config).describe(),
    }
    (DATA / "analysis_windows.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )


def write_placeholder(name: str, schema: str, guardrail: str, body: dict) -> bool:
    path = DATA / name
    if path.exists():
        return False
    payload = {
        "schema": schema,
        "generated_at": now(),
        "state": "NOT_GENERATED_YET",
        "note": (
            "Esta capa la calcula el pipeline sobre los hechos normalizados, que no están "
            "disponibles al publicar el sitio. Ausencia de datos no es ausencia de riesgo."
        ),
        "guardrail": guardrail,
        **body,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    return True


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    write_typology_catalog()
    write_windows_context()
    status = write_status(output_json=DATA / "procurement_status.json")
    placeholders = [
        name
        for name, schema, guardrail, body in (
            ("entity_signals.json", "RIGP-ENTITY-SIGNALS-v1", TYPOLOGY_GUARDRAIL,
             {"coverage": {}, "by_type": {}, "providers": {}}),
            ("opacity_index.json", "RIGP-OPACITY-INDEX-v1", OPACITY_GUARDRAIL,
             {"overall": {}, "services": []}),
            # La calibración nace vacía a propósito: sin expedientes cerrados no
            # hay nada que el modelo pueda aprender, y decirlo es más útil que
            # un 404 silencioso.
            ("calibration.json", "RIGP-CALIBRATION-v1", CALIBRATION_GUARDRAIL,
             {"evidence": {"labelled_cases": 0, "verified": 0}, "by_signal_type": {},
              "by_typology": {}, "policy": {"apply": True}}),
        )
        if write_placeholder(name, schema, guardrail, body)
    ]
    from radar_presupuesto.windows import from_config as _wf
    import yaml as _yaml

    _cfg_path = ROOT / "config" / "analysis_windows.yaml"
    _windows = _wf(_yaml.safe_load(_cfg_path.read_text(encoding="utf-8")) if _cfg_path.exists() else {})
    print(
        f"[RIGP Static] catálogo de tipologías: {len(TYPOLOGIES)} · "
        f"adaptador de compras: {status['integration_state']} · "
        f"ventana de acción desde {_windows.action_from_year}"
    )
    if placeholders:
        print(f"[RIGP Static] marcadores de capa aún no calculada: {', '.join(placeholders)}")


if __name__ == "__main__":
    main()
