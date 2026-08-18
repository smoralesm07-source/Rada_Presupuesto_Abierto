"""Genera una vista de ejecución de demostración con datos sintéticos.

Sirve para revisar el diseño del módulo ``docs/ejecucion.html`` y para validar
extremo a extremo el constructor ``spend_view`` sin descargar los bulk
nacionales (>500 MB) ni esperar la corrida mensual.

Los datos son sintéticos y deterministas (semilla fija). El artefacto se marca
``mode=DEMO_SYNTHETIC`` y la página muestra un banner permanente: nunca debe
leerse como pagos reales del Estado.

Uso:
    PYTHONPATH=src python scripts/build_demo_spend_view.py
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

import pandas as pd

from radar_presupuesto.advanced_signals import extend_signals
from radar_presupuesto.analytics import build_signals
from radar_presupuesto.normalize import normalize_frame
from radar_presupuesto.prioritization import prioritize_signals
from radar_presupuesto.regions import REGION_CATALOG
from radar_presupuesto.spend_view import build_spend_view

SEED = 20260817
YEARS = (2024, 2025, 2026)

MINISTRIES = [
    ("05", "MINISTERIO DEL INTERIOR"),
    ("09", "MINISTERIO DE EDUCACION"),
    ("11", "MINISTERIO DE OBRAS PUBLICAS"),
    ("16", "MINISTERIO DE SALUD"),
    ("18", "MINISTERIO DE VIVIENDA Y URBANISMO"),
    ("21", "MINISTERIO DE DESARROLLO SOCIAL"),
    ("29", "MINISTERIO DEL DEPORTE"),
]
SUBTITLES = [
    ("22", "BIENES Y SERVICIOS DE CONSUMO", 0.34),
    ("24", "TRANSFERENCIAS CORRIENTES", 0.28),
    ("31", "INICIATIVAS DE INVERSION", 0.19),
    ("29", "ADQUISICION DE ACTIVOS NO FINANCIEROS", 0.12),
    ("21", "GASTOS EN PERSONAL", 0.07),
]
# Peso relativo del gasto por región: reproduce el centralismo observado.
REGION_WEIGHTS = {
    "15": 1.4, "01": 1.8, "02": 3.4, "03": 1.7, "04": 2.6, "05": 7.4,
    "13": 46.0, "06": 3.1, "07": 3.4, "16": 1.8, "08": 7.1, "09": 4.2,
    "14": 1.9, "10": 3.6, "11": 1.0, "12": 1.2,
}


def _check_digit(body: int) -> str:
    """Dígito verificador módulo 11: la demo debe ejercitar la ruta de RUT válido."""
    total, factor = 0, 2
    for digit in reversed(str(body)):
        total += int(digit) * factor
        factor = 2 if factor == 7 else factor + 1
    rest = 11 - (total % 11)
    return {11: "0", 10: "K"}.get(rest, str(rest))


def _rut(rng: random.Random) -> str:
    body = rng.randint(60_000_000, 99_999_999)
    return f"{body}-{_check_digit(body)}"


def _purchase_order(year: int, doc: int) -> str:
    return f"{1000 + (year + doc) % 9000}-{doc}-L{str(year)[2:]}"


def _row(
    year: int,
    month: int,
    ministry: tuple[str, str],
    area: str,
    subtitle: tuple[str, str, float],
    region: str,
    rut: str,
    name: str,
    amount: int,
    *,
    provider: bool = True,
    with_purchase_order: bool = True,
    days_to_pay: int = 30,
    person: bool = False,
    doc: int = 0,
) -> dict[str, object]:
    return {
        "PERIODO": year,
        "MES": f"{month:02d}",
        "PARTIDA": ministry[0],
        "NOMBRE_PARTIDA": ministry[1],
        "CAPITULO": "01",
        "NOMBRE_CAPITULO": f"SUBSECRETARIA {ministry[1].split()[-1]}",
        "AREA": area[:3],
        "NOMBRE_AREA": area,
        "SUBTITULO": subtitle[0],
        "NOMBRE_SUBTITULO": subtitle[1],
        "ITEM": "01",
        "NOMBRE_ITEM": "GASTO OPERACIONAL",
        "RUT_BENEFICIARIO": rut,
        "NOMBRE_BENEFICIARIO": name,
        "NUMERO_DOCUMENTO": 100000 + doc,
        "FECHA_DOCUMENTO": f"{year}-{month:02d}-05",
        "TIPO_DOCUMENTO": "FACTURA",
        "ORDEN_DE_COMPRA": _purchase_order(year, doc) if with_purchase_order else "",
        "MONEDA_PRESUPUESTARIA": "PESOS",
        "MONTO_DEVENGADO": amount,
        "FECHA_PAGO": f"{year}-{month:02d}-25",
        "MONTO": amount,
        "FOLIO": doc,
        "CODIGO_UBICACION_GEOGRAFICA": region,
        "NOMBRE_UBICACION_GEOGRAFICA": "",
        "REGION": region,
        "SECTOR": subtitle[1][:12],
        "PROVEEDOR": 1 if provider else 0,
        "PERSONA": 1 if person else 0,
        "HONORARIO": 1 if person else 0,
        "INTRAESTADO": 0,
        "DEUDA_FLOTANTE": 0,
        "AGREGADO": 0,
        "DIAS_DE_PAGO": days_to_pay,
    }


def build_frame() -> pd.DataFrame:
    rng = random.Random(SEED)
    codes = [code for code, *_ in REGION_CATALOG]
    weights = [REGION_WEIGHTS[c] for c in codes]
    # Dos poblaciones: proveedores históricos presentes en toda la serie y un
    # cohorte que aparece sólo en el último año, para ejercitar la vista de
    # entrantes nuevos con dispersión realista de montos.
    historic = [(f"PROVEEDOR NACIONAL {i:03d} SPA", _rut(rng)) for i in range(1, 620)]
    entrants = [(f"NUEVA SOCIEDAD {i:03d} SPA", _rut(rng)) for i in range(1, 61)]
    rows: list[dict[str, object]] = []
    doc = 0

    def payment(year: int, pool: list[tuple[str, str]], scale: float = 1.0) -> None:
        nonlocal doc
        doc += 1
        month = rng.choices(range(1, 13), weights=[7, 7, 8, 8, 8, 9, 8, 8, 8, 9, 9, 11])[0]
        ministry = rng.choice(MINISTRIES)
        subtitle = rng.choices(SUBTITLES, weights=[s[2] for s in SUBTITLES])[0]
        region = rng.choices(codes, weights=weights)[0]
        name, rut = rng.choice(pool)
        base = rng.choice([1, 1, 1, 2, 4, 9, 22, 60]) * 1_000_000
        amount = int(base * rng.uniform(0.35, 1.9) * scale)
        rows.append(
            _row(year, month, ministry, f"SERVICIO REGIONAL {region}", subtitle, region, rut, name,
                 amount, days_to_pay=rng.choice([12, 20, 28, 33, 45, 62]), doc=doc)
        )

    for year in YEARS:
        for _ in range(2600):
            payment(year, historic)
    for _ in range(420):
        payment(YEARS[-1], entrants, scale=rng.uniform(0.8, 3.2))

    # Patrón 1: proveedor dominante de un servicio (concentración del comprador).
    dominant, dominant_rut = "CONSTRUCTORA DOMINANTE AUSTRAL LTDA", "76900111-5"
    for year in YEARS:
        for month in (3, 6, 9, 11, 12):
            doc += 1
            rows.append(
                _row(year, month, MINISTRIES[2], "DIRECCION REGIONAL AUSTRAL", SUBTITLES[2], "11",
                     dominant_rut, dominant, 890_000_000 + doc * 1_000, days_to_pay=21, doc=doc)
            )

    # Patrón 2: entrante nuevo del último año con monto material y comprador único.
    newcomer, newcomer_rut = "SERVICIOS INTEGRALES NUEVA ERA SPA", "77555222-0"
    for month in (8, 9, 10, 11, 12):
        doc += 1
        rows.append(
            _row(YEARS[-1], month, MINISTRIES[3], "SERVICIO DE SALUD METROPOLITANO", SUBTITLES[0], "13",
                 newcomer_rut, newcomer, 640_000_000, with_purchase_order=False, days_to_pay=2, doc=doc)
        )

    # Patrón 3: fraccionamiento (pagos casi idénticos, mismo mes y organismo).
    frag, frag_rut = "SUMINISTROS FRACCIONADOS LTDA", "76432100-6"
    for i in range(9):
        doc += 1
        rows.append(
            _row(YEARS[-1], 12, MINISTRIES[1], "DIRECCION DE EDUCACION PUBLICA", SUBTITLES[0], "08",
                 frag_rut, frag, 9_950_000 + i * 20_000, days_to_pay=8, doc=doc)
        )

    # Patrón 4: montos exactamente redondos y sin orden de compra.
    round_provider, round_rut = "ASESORIAS MONTO REDONDO SPA", "76111999-0"
    for year in (YEARS[-2], YEARS[-1]):
        for month in (4, 7, 10, 12):
            doc += 1
            rows.append(
                _row(year, month, MINISTRIES[5], "SUBSECRETARIA DE EVALUACION SOCIAL", SUBTITLES[1], "05",
                     round_rut, round_provider, 120_000_000, with_purchase_order=False, days_to_pay=1, doc=doc)
            )

    # Patrón 5: cierre de año extremo en un servicio regional.
    year_end, year_end_rut = "OBRAS DE CIERRE ANUAL LTDA", "76777333-1"
    for year in YEARS:
        doc += 1
        rows.append(
            _row(year, 12, MINISTRIES[4], "SERVICIO DE VIVIENDA REGIONAL", SUBTITLES[2], "09",
                 year_end_rut, year_end, 430_000_000, days_to_pay=18, doc=doc)
        )

    # Patrón 6: pago duplicado candidato (mismo documento, monto y organismo).
    dup, dup_rut = "EQUIPAMIENTO REPETIDO SPA", "76222444-5"
    for _ in range(2):
        doc += 1
        row = _row(YEARS[-1], 7, MINISTRIES[3], "SERVICIO DE SALUD METROPOLITANO", SUBTITLES[3], "13",
                   dup_rut, dup, 78_400_000, days_to_pay=30, doc=doc)
        row["NUMERO_DOCUMENTO"] = 990001
        row["FOLIO"] = 990001
        row["ORDEN_DE_COMPRA"] = "5500-77-L26"
        rows.append(row)

    # Patrón 7: personas naturales a honorarios (no proveedor) para contraste.
    for i in range(120):
        doc += 1
        rows.append(
            _row(YEARS[-1], (i % 12) + 1, MINISTRIES[0], "NIVEL CENTRAL", SUBTITLES[4],
                 codes[i % len(codes)], f"1{i:07d}-{i % 10}", f"PERSONA NATURAL {i:03d}",
                 1_200_000 + i * 5_000, provider=False, with_purchase_order=False, person=True,
                 days_to_pay=15, doc=doc)
        )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Construye la vista de ejecución de demostración")
    parser.add_argument("--work-dir", default="data/demo")
    parser.add_argument("--output", default="docs/data/spend_view_demo_v1.json")
    args = parser.parse_args()

    work = Path(args.work_dir)
    (work / "processed").mkdir(parents=True, exist_ok=True)
    (work / "signals").mkdir(parents=True, exist_ok=True)

    frame = normalize_frame(build_frame().astype(str), source_file="demo_synthetic.csv")
    parquet = work / "processed" / "transactions_demo.parquet"
    frame.to_parquet(parquet, index=False)

    signals_path = work / "signals" / "risk_signals.parquet"
    build_signals(str(parquet), output_path=str(signals_path))
    extend_signals(str(parquet), signals_path=str(signals_path))
    prioritize_signals(
        str(parquet),
        signals_path=str(signals_path),
        cgr_links_path=str(work / "signals" / "no_cgr.parquet"),
        output_parquet=str(work / "signals" / "prioritized_signals.parquet"),
        output_json=str(work / "investigation_queue.json"),
    )
    payload = build_spend_view(
        str(parquet),
        str(work / "signals" / "prioritized_signals.parquet"),
        args.output,
        mode="DEMO_SYNTHETIC",
    )
    print(
        f"[OK] demo sintética: {payload['coverage']['transactions']:,} transacciones | "
        f"regiones={len(payload['territory']['regions'])} | "
        f"proveedores atípicos={len(payload['providers']['anomalous'])} | "
        f"nuevos materiales={len(payload['new_providers'].get('material', []))} | "
        f"alertas={len(payload['alerts'])}"
    )


if __name__ == "__main__":
    main()
