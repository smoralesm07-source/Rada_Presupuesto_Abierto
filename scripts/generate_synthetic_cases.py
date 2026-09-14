#!/usr/bin/env python3
"""Genera expedientes sintéticos para ejercitar la calibración sin analistas.

Existe porque el mecanismo de calibración no se puede probar de verdad hasta que
alguien cierre expedientes reales, y hasta entonces uno no sabe si responde como
debería. Esto permite verlo funcionar.

**Estos casos no son datos.** No corresponden a ninguna revisión ni a ninguna
decisión de un analista, y no pueden mover el ranking real: declaran otro
esquema, exigen un `--allow-synthetic` explícito para ser leídos, y el payload
que producen queda marcado de modo que `load_multipliers` lo rechaza.

Uso:

    python3 scripts/generate_synthetic_cases.py            # escribe el respaldo
    python3 scripts/generate_synthetic_cases.py --simular  # además, lo calibra

El escenario cubre a propósito los cuatro comportamientos que importan: un
patrón útil, uno inútil, uno con muestra insuficiente, y cierres explicados que
cuentan en el denominador pero no en el numerador.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from radar_presupuesto.calibration import (  # noqa: E402
    SYNTHETIC_BACKUP_SCHEMA,
    SYNTHETIC_WARNING,
    build_calibration,
)

DEFAULT_OUT = ROOT / "data" / "calibration" / "synthetic"

# Cada escenario: (tipo de señal, cerrados, escalados, explicados, qué ilustra)
SCENARIOS = [
    ("PROVIDER_CONCENTRATION", 24, 14, 4,
     "patrón útil: la mayoría de las revisiones escala, debería subir"),
    ("YEAR_END_SPIKE", 22, 1, 3,
     "patrón poco rendidor: casi nada escala, debería bajar sin desaparecer"),
    ("AMOUNT_OUTLIER", 6, 4, 1,
     "muestra insuficiente: buena precisión pero bajo el mínimo, no debe ajustar"),
    ("EXACT_DUPLICATE_CANDIDATE", 15, 5, 9,
     "muchos cierres explicados: cuentan en el denominador, no en el numerador"),
]


def build_cases(seed: int = 20260914) -> tuple[list[dict], list[dict]]:
    rng = random.Random(seed)
    base = datetime(2026, 1, 15, tzinfo=timezone.utc)
    cases: list[dict] = []
    findings: list[dict] = []
    n = 0

    for signal, closed, escalated, explained, note in SCENARIOS:
        finding_id = f"SINT-HAL-{signal}"
        findings.append({
            "finding_id": finding_id,
            "signal_types": [signal],
            "_synthetic_note": note,
        })
        states = (
            ["ESCALADO"] * escalated
            + ["EXPLICADO"] * explained
            + ["CERRADO"] * (closed - escalated - explained)
        )
        rng.shuffle(states)
        for state in states:
            n += 1
            at = (base + timedelta(days=rng.randint(0, 200))).isoformat(timespec="seconds")
            cases.append({
                "case_id": f"SINT-{n:04d}",
                "case_ref": f"SINTETICO-{n:04d}",
                "state": state,
                "finding_ids": [finding_id],
                "created_at": at,
                "updated_at": at,
                "synthetic": True,
                "synthetic_warning": SYNTHETIC_WARNING,
                "case_notes": [],
                "events": [{"event_type": "ESTADO_SINTETICO_ASIGNADO", "created_at": at}],
            })

    # Expedientes abiertos: el mecanismo debe ignorarlos por completo.
    for i in range(12):
        at = (base + timedelta(days=rng.randint(0, 200))).isoformat(timespec="seconds")
        cases.append({
            "case_id": f"SINT-ABIERTO-{i:03d}",
            "case_ref": f"SINTETICO-ABIERTO-{i:03d}",
            "state": rng.choice(["TRIAGE", "EN_REVISION", "PROFUNDIZAR"]),
            "finding_ids": [f"SINT-HAL-{SCENARIOS[i % len(SCENARIOS)][0]}"],
            "created_at": at,
            "updated_at": at,
            "synthetic": True,
            "synthetic_warning": SYNTHETIC_WARNING,
            "case_notes": [],
            "events": [],
        })
    return cases, findings


def write(out_dir: Path, seed: int) -> tuple[Path, Path, int]:
    cases, findings = build_cases(seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    backup = out_dir / "casos-sinteticos.json"
    backup.write_text(json.dumps({
        "schema": SYNTHETIC_BACKUP_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seed": seed,
        "synthetic": True,
        "synthetic_warning": SYNTHETIC_WARNING,
        "scenarios": [
            {"signal_type": s, "closed": c, "escalated": e, "explained": x, "illustrates": note}
            for s, c, e, x, note in SCENARIOS
        ],
        "cases": cases,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # Hallazgos sintéticos, para que los casos tengan a qué señal atribuirse.
    hallazgos = out_dir / "hallazgos-sinteticos.json"
    hallazgos.write_text(json.dumps({
        "schema": "RIGP-FINDINGS-SYNTHETIC-v1",
        "synthetic": True,
        "synthetic_warning": SYNTHETIC_WARNING,
        "relation_findings": findings,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return backup, hallazgos, len(cases)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="directorio destino")
    ap.add_argument("--seed", type=int, default=20260914, help="semilla; el escenario es reproducible")
    ap.add_argument("--simular", action="store_true", help="además, corre la calibración sobre estos casos")
    args = ap.parse_args()

    out_dir = Path(args.out)
    backup, hallazgos, total = write(out_dir, args.seed)
    print(f"[sintético] {total} expedientes en {backup}")
    print(f"[sintético] hallazgos de apoyo en {hallazgos}")
    print(f"[sintético] esquema {SYNTHETIC_BACKUP_SCHEMA}: el cargador de producción los ignora")

    if not args.simular:
        print("[sintético] usa --simular para ver cómo respondería el mecanismo")
        return

    payload = build_calibration(
        cases_source=str(out_dir),
        findings_json=str(hallazgos),
        output_json=str(out_dir / "calibration-simulada.json"),
        allow_synthetic=True,
    )
    print(f"\n[simulación] estado: {payload['status']}")
    print(f"[simulación] {payload['status_note']}\n")
    ancho = max(len(s) for s, *_ in SCENARIOS)
    for signal, adj in sorted(payload["signal_calibration"].items()):
        marca = "ajusta" if adj["applied"] else "sin ajuste"
        print(f"  {signal:<{ancho}}  x{adj['multiplier']:<6}  {marca:<11}  {adj['why']}")
    print(f"\n[simulación] guardada en {out_dir / 'calibration-simulada.json'}")
    print("[simulación] marcada como sintética: load_multipliers la rechaza")


if __name__ == "__main__":
    main()
