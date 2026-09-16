"""Qué publica ChileCompra, medido en vez de supuesto.

El radar sabe hoy quién recibió un pago del Estado, pero no bajo qué modalidad
se contrató ni a qué precio unitario. Sin eso, una señal de fragmentación es
una curiosidad estadística —«cinco documentos de monto similar en una semana»—
y no una irregularidad administrativa con una regla detrás.

Este módulo no descarga compras: **averigua qué se puede descargar**. La
diferencia importa porque de una sola respuesta depende la factibilidad de todo
lo demás. El endpoint documentado en `mercado_publico_bridge` resuelve una orden
por consulta, contra un límite informado de 10.000 consultas diarias por ticket.
Si existe un listado por fecha, cubrir 2024 en adelante cuesta unos cientos de
llamadas y cabe de sobra en ese límite; si no existe, el grueso de las compras
públicas es inalcanzable por esa vía y hay que buscar descargas masivas.

Cada candidato se declara como hipótesis y se prueba. Lo que no se pudo
determinar queda dicho como tal, no omitido: una fuente no probada porque falta
el ticket no es una fuente inexistente, y confundirlas llevaría a descartar un
camino que sí estaba abierto.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

SCHEMA = "RIGP-PROCUREMENT-SOURCES-v1"
OUTPUT_JSON = "docs/data/procurement_sources.json"
USER_AGENT = "RadarPresupuestoAbierto/0.1 (+public OSINT research)"

# Límite informado por ChileCompra para la API pública, ya documentado en
# `mercado_publico_bridge`. Se repite aquí porque es el número contra el que se
# decide si una vía sirve para volumen o sólo para resolución dirigida.
DAILY_REQUEST_LIMIT = 10_000

NEEDS_TICKET = "REQUIERE_TICKET"
REACHABLE = "ALCANZABLE"
UNREACHABLE = "NO_ALCANZABLE"
BLOCKED = "BLOQUEADO_POR_RED"

GUARDRAIL = (
    "Este inventario describe disponibilidad de fuentes, no conducta. Que una "
    "compra sea observable no la vuelve irregular, y que una fuente no esté "
    "disponible no vuelve limpio lo que contiene."
)


def candidate_sources(sample_date: str, sample_order: str, sample_rut: str) -> list[dict]:
    """Los candidatos a probar, cada uno con qué desbloquearía si existe.

    Son hipótesis declaradas, no endpoints confirmados. El probe existe
    justamente para no escribir un ingestor contra un esquema supuesto.
    """
    api = "https://api.mercadopublico.cl/servicios/v1/publico"
    return [
        {
            "id": "OC_POR_CODIGO",
            "kind": "API",
            "url": f"{api}/OrdenCompra.json?codigo={sample_order}&ticket=",
            "needs_ticket": True,
            "unlocks": (
                "Resolución dirigida de una orden ya identificada: ítems, cantidades y "
                "precio unitario. Es la vía que el puente ya implementa."
            ),
            "volume": "UNA_ORDEN_POR_CONSULTA",
        },
        {
            "id": "OC_POR_FECHA",
            "kind": "API",
            "url": f"{api}/ordenesdecompra.json?fecha={sample_date}&ticket=",
            "needs_ticket": True,
            "unlocks": (
                "Listado de órdenes emitidas en una fecha. Es la pregunta que decide la "
                "factibilidad: con un listado diario, cubrir un año cuesta unas 365 "
                "consultas y cabe holgadamente en el límite diario."
            ),
            "volume": "UN_DIA_POR_CONSULTA",
        },
        {
            "id": "LICITACIONES_POR_FECHA",
            "kind": "API",
            "url": f"{api}/licitaciones.json?fecha={sample_date}&ticket=",
            "needs_ticket": True,
            "unlocks": (
                "Licitaciones del día con su modalidad y estado. La modalidad es lo que "
                "convierte una secuencia de pagos en una pregunta sobre el umbral que "
                "habría obligado a licitar."
            ),
            "volume": "UN_DIA_POR_CONSULTA",
        },
        {
            "id": "PROVEEDOR_POR_RUT",
            "kind": "API",
            "url": f"{api}/Empresas/BuscarProveedor?rutempresaproveedor={sample_rut}&ticket=",
            "needs_ticket": True,
            "unlocks": "Ficha del proveedor en el registro de ChileCompra, por RUT.",
            "volume": "UN_PROVEEDOR_POR_CONSULTA",
        },
        {
            "id": "CATALOGO_DATOS_ABIERTOS",
            "kind": "CKAN",
            "url": "https://datos.gob.cl/api/3/action/package_search?q=compras+publicas&rows=20",
            "needs_ticket": False,
            "unlocks": (
                "Catálogo nacional de datos abiertos. Si publica descargas masivas de "
                "órdenes de compra, es la vía de volumen y no consume el límite diario."
            ),
            "volume": "CATALOGO",
        },
    ]


def probe(url: str, timeout: int = 25) -> dict:
    """Prueba un candidato sin descargarlo entero y sin confundir causas de fallo.

    Un 403 del proxy de red y un 404 del servidor significan cosas distintas: el
    primero dice que desde aquí no se ve, el segundo que no existe. Tratarlos
    igual haría descartar fuentes disponibles.
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    try:
        with requests.get(url, timeout=timeout, headers=headers, stream=True) as r:
            body = r.raw.read(4096, decode_content=True) or b""
            shape = _describe_shape(body)
            return {
                "state": REACHABLE if r.status_code < 400 else UNREACHABLE,
                "http_status": r.status_code,
                "content_type": r.headers.get("content-type"),
                "sample_shape": shape,
            }
    except requests.exceptions.ProxyError as exc:
        return {"state": BLOCKED, "error": type(exc).__name__,
                "note": "La red de esta ejecución no permite salir a ese host; no dice nada sobre la fuente."}
    except requests.RequestException as exc:
        return {"state": UNREACHABLE, "error": type(exc).__name__}


def _describe_shape(body: bytes) -> dict:
    """Describe la forma del primer trozo de respuesta, sin afirmar de más."""
    if not body:
        return {"determined": False, "why": "respuesta vacía en el primer trozo"}
    try:
        text = body.decode("utf-8", errors="replace")
    except Exception:
        return {"determined": False, "why": "cuerpo no decodificable como texto"}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"determined": False, "why": "el primer trozo no es JSON completo",
                "head": text[:200]}
    if isinstance(parsed, dict):
        return {"determined": True, "type": "object", "keys": sorted(parsed.keys())[:15]}
    if isinstance(parsed, list):
        first = parsed[0] if parsed else None
        return {"determined": True, "type": "array", "length": len(parsed),
                "first_keys": sorted(first.keys())[:15] if isinstance(first, dict) else None}
    return {"determined": True, "type": type(parsed).__name__}


def assess_feasibility(results: list[dict]) -> dict:
    """Traduce lo probado en una respuesta sobre cobertura, o dice que no se sabe."""
    by_id = {r["id"]: r for r in results}
    daily = by_id.get("OC_POR_FECHA", {})
    catalog = by_id.get("CATALOGO_DATOS_ABIERTOS", {})
    days_per_year = 366

    if daily.get("state") == REACHABLE:
        return {
            "verdict": "VIABLE_POR_LISTADO_DIARIO",
            "why": (
                f"Existe listado por fecha. Cubrir un año cuesta ~{days_per_year} consultas "
                f"contra un límite informado de {DAILY_REQUEST_LIMIT:,} diarias, de modo que "
                "2024 en adelante se recorre en una fracción de un día de cuota."
            ).replace(",", "."),
            "estimated_requests_per_year": days_per_year,
        }
    if catalog.get("state") == REACHABLE:
        return {
            "verdict": "REVISAR_DESCARGAS_MASIVAS",
            "why": (
                "No se confirmó listado por fecha, pero el catálogo de datos abiertos "
                "respondió. Hay que revisar qué descargas publica antes de descartar el "
                "volumen."
            ),
        }
    blocked = [r["id"] for r in results if r.get("state") == BLOCKED]
    if blocked:
        return {
            "verdict": "NO_DETERMINADO",
            "why": (
                "La red de esta ejecución bloqueó la salida hacia "
                f"{len(blocked)} de {len(results)} candidatos, así que no se puede "
                "concluir nada sobre su disponibilidad. Debe ejecutarse donde haya "
                "salida a internet, como el runner de CI que ya descarga los bulks de DIPRES."
            ),
            "blocked": blocked,
        }
    return {
        "verdict": "SIN_VIA_DE_VOLUMEN_CONFIRMADA",
        "why": (
            "Ningún candidato de volumen respondió. Con sólo resolución por código, "
            f"el límite de {DAILY_REQUEST_LIMIT:,} consultas diarias no alcanza para el "
            "grueso de las compras y hay que buscar otra vía."
        ).replace(",", "."),
    }


def discover(
    ticket: str | None = None,
    sample_date: str | None = None,
    sample_order: str = "1509-11-SE24",
    sample_rut: str = "76045081-2",
    timeout: int = 25,
) -> dict:
    ticket = (ticket or "").strip()
    if not sample_date:
        # Una fecha reciente y ya cerrada, para no probar contra un día en curso.
        sample_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%d%m%Y")

    results: list[dict] = []
    for cand in candidate_sources(sample_date, sample_order, sample_rut):
        row = dict(cand)
        if cand["needs_ticket"] and not ticket:
            row.update({
                "state": NEEDS_TICKET,
                "note": (
                    "No se probó porque no hay ticket configurado. Una fuente no probada "
                    "no es una fuente inexistente: configurar MERCADO_PUBLICO_TICKET "
                    "permite resolver esto."
                ),
            })
        else:
            url = cand["url"] + ticket if cand["needs_ticket"] else cand["url"]
            row.update(probe(url, timeout=timeout))
            row["url"] = cand["url"] + ("<ticket>" if cand["needs_ticket"] else "")
        results.append(row)

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "guardrail": GUARDRAIL,
        "daily_request_limit": DAILY_REQUEST_LIMIT,
        "ticket_present": bool(ticket),
        "sample_date_probed": sample_date,
        "sources": results,
        "coverage_feasibility": assess_feasibility(results),
    }


def write_sources(path: str | Path = OUTPUT_JSON, **kwargs) -> dict:
    payload = discover(**kwargs)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return payload


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=OUTPUT_JSON)
    ap.add_argument("--ticket", default=None)
    ap.add_argument("--timeout", type=int, default=25)
    args = ap.parse_args()
    import os
    payload = write_sources(args.out, ticket=args.ticket or os.environ.get("MERCADO_PUBLICO_TICKET"),
                            timeout=args.timeout)
    f = payload["coverage_feasibility"]
    print("[RIGP compras] veredicto:", f["verdict"])
    print("  ", f["why"])
    for s in payload["sources"]:
        print(f"   {s['id']:26} {s.get('state')}")


if __name__ == "__main__":
    main()
