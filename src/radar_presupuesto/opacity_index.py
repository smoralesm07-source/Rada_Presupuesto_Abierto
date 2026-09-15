from __future__ import annotations

"""Cuánto del gasto de cada servicio simplemente no se puede verificar.

Alrededor de un quinto de las contrapartes llega pseudonimizada: la fuente
publica un hash en vez del RUT. `quality.json` ya lo informa a nivel país; lo
que faltaba es saber **dónde** se concentra, porque un 22% repartido parejo y un
22% concentrado en tres servicios son problemas distintos.

Lo que esta capa NO dice
------------------------
Opacidad no es riesgo. Un receptor pseudonimizado no es más sospechoso: es menos
verificable, y eso cambia qué puede afirmarse a partir del dato, no cuán grave
es. La mayor parte de la pseudonimización es protección de datos personales
funcionando como corresponde —pagos a personas naturales— y leerla como señal de
irregularidad sería exactamente el error contrario al que el radar quiere evitar.

Para qué sirve entonces
-----------------------
Para saber dónde el radar tiene menos capacidad de ver. Un servicio con la mayor
parte de su gasto en contrapartes opacas no es un servicio limpio: es uno donde
las señales de contraparte no pueden calcularse, y decirlo es más honesto que
publicar su ausencia como tranquilidad.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

SCHEMA = "RIGP-OPACITY-INDEX-v1"

GUARDRAIL = (
    "La opacidad describe un límite de la fuente, no una conducta. Un receptor "
    "pseudonimizado no es más sospechoso: es menos verificable, y eso cambia qué "
    "puede afirmarse a partir del dato. La mayor parte corresponde a pagos a "
    "personas naturales, donde la pseudonimización protege datos personales."
)

OPACITY_LABEL = {
    "TRAZABLE": "Contraparte identificada con RUT validado.",
    "PARCIAL": "Parte del gasto va a contrapartes pseudonimizadas por la fuente.",
    "OPACA": (
        "La mayor parte del gasto va a contrapartes pseudonimizadas: las señales de "
        "contraparte no pueden calcularse para este servicio."
    ),
}

OPAQUE_THRESHOLD = 0.50
PARTIAL_THRESHOLD = 0.0


def classify_opacity(share: float | None) -> str:
    value = float(share or 0)
    if value >= OPAQUE_THRESHOLD:
        return "OPACA"
    if value > PARTIAL_THRESHOLD:
        return "PARCIAL"
    return "TRAZABLE"


def build_opacity_index(
    parquet_glob: str,
    output_json: str = "docs/data/opacity_index.json",
    top_n: int = 500,
) -> dict:
    """Publica qué parte del gasto de cada servicio no es verificable."""
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"""
            SELECT
              'SRV-PA-' || lpad(cast(partida AS VARCHAR),2,'0') || '-'
                        || lpad(cast(capitulo AS VARCHAR),2,'0') AS service_id,
              any_value(nombre_capitulo) AS service_name,
              any_value(nombre_partida) AS ministry_name,
              sum(coalesce(try_cast(monto_devengado AS DOUBLE),0)) AS amount_clp,
              sum(CASE WHEN beneficiario_id_type='HASH_SHA1'
                       THEN coalesce(try_cast(monto_devengado AS DOUBLE),0) ELSE 0 END) AS opaque_amount_clp,
              -- El gasto a personas naturales es donde la pseudonimización es
              -- esperable: separarlo evita leer protección de datos como opacidad
              -- inexplicada.
              sum(CASE WHEN beneficiario_id_type='HASH_SHA1' AND is_person=TRUE
                       THEN coalesce(try_cast(monto_devengado AS DOUBLE),0) ELSE 0 END) AS opaque_person_amount_clp,
              count(*) AS rows_total,
              count(*) FILTER (WHERE beneficiario_id_type='HASH_SHA1') AS opaque_rows
            FROM read_parquet('{parquet_glob}', union_by_name=true)
            WHERE coalesce(nombre_capitulo,'')<>''
            GROUP BY 1
            HAVING sum(coalesce(try_cast(monto_devengado AS DOUBLE),0)) > 0
            """
        ).df()
    finally:
        con.close()

    services = []
    for row in rows.itertuples():
        amount = float(row.amount_clp or 0)
        opaque = float(row.opaque_amount_clp or 0)
        share = opaque / amount if amount else 0.0
        person = float(row.opaque_person_amount_clp or 0)
        services.append({
            "service_id": str(row.service_id),
            "service_name": str(row.service_name or row.service_id),
            "ministry_name": str(row.ministry_name or ""),
            "amount_clp": amount,
            "opaque_amount_clp": opaque,
            "opaque_share": round(share, 6),
            "opacity_level": classify_opacity(share),
            # Qué parte de la opacidad se explica por pagos a personas naturales.
            "opaque_person_share_of_opaque": round(person / opaque, 6) if opaque else 0.0,
            "rows_total": int(row.rows_total or 0),
            "opaque_rows": int(row.opaque_rows or 0),
        })
    services.sort(key=lambda s: (-s["opaque_amount_clp"], s["service_name"]))

    total = sum(s["amount_clp"] for s in services)
    opaque_total = sum(s["opaque_amount_clp"] for s in services)
    levels = {"TRAZABLE": 0, "PARCIAL": 0, "OPACA": 0}
    for s in services:
        levels[s["opacity_level"]] += 1

    payload = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "guardrail": GUARDRAIL,
        "labels": OPACITY_LABEL,
        "overall": {
            "services": len(services),
            "amount_clp": total,
            "opaque_amount_clp": opaque_total,
            "opaque_share": round(opaque_total / total, 6) if total else 0.0,
            "services_by_level": levels,
        },
        "interpretation": (
            "Un servicio OPACA no es un servicio con más riesgo: es uno donde el radar "
            "ve menos. Las señales de contraparte —proveedor recién creado, capacidad "
            "incompatible, término de giro— no pueden calcularse sobre una identidad "
            "pseudonimizada, así que su ausencia ahí no es tranquilidad."
        ),
        "services": services[: int(top_n)],
        "services_truncated": max(0, len(services) - int(top_n)),
    }
    out = Path(output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return payload
