from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .sii_targets import canon_rut, rut_from_provider_id


SCHEMA = "RIGP-MERCADO-PUBLICO-CONTEXT-v1"
API_ROOT = "https://api.mercadopublico.cl/servicios/v1/publico"

# La corrida #20 falló las 20 consultas con HTTP 404 —no 401— así que el ticket
# es aceptado y lo que no existe es la ruta. Antes se consultaba `OrdenCompra.json`
# a secas; ChileCompra ha cambiado los envoltorios de su API más de una vez y el
# nombre vigente no es una cosa que convenga suponer.
#
# En vez de cambiar un nombre por otro a ciegas, el puente prueba los candidatos
# en la primera orden y adopta el que resuelva, dejando dicho en el payload cuál
# usó. Cuesta a lo más un par de consultas extra sobre un límite de 10.000.
ORDER_ENDPOINT_CANDIDATES = (
    "ordenesdecompra.json",
    "OrdenCompra.json",
)
API_BASE = f"{API_ROOT}/{ORDER_ENDPOINT_CANDIDATES[0]}"
GUARDRAIL = (
    "La información de Mercado Público complementa el expediente con antecedentes del proceso de compra. "
    "Diferencias de identidad, monto, estado o fechas son candidatos de revisión y no acreditan por sí solas "
    "irregularidad, fraude, corrupción, delito funcionario ni responsabilidad de una entidad o persona."
)


def _read(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _as_list(value: object) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _clean_code(value: object) -> str:
    return str(value or "").strip().upper()


# Forma canónica de ChileCompra: comprador-correlativo-tipo+año, p.ej. 1509-11-SE24.
CANONICAL_ORDER_CODE = re.compile(r"^\d+-\d+-[A-Z]{1,3}\d{2}$")
MISSING_SEPARATOR = re.compile(r"^(\d+)-(\d+)([A-Z]{1,3}\d{2})$")

CANONICAL = "CANONICO"
REPAIRED_DASH = "REPARADO_GUION_SOBRANTE"
REPAIRED_SEPARATOR = "REPARADO_SEPARADOR_FALTANTE"
NOT_AN_ORDER_CODE = "NO_ES_CODIGO_DE_ORDEN"

NOT_A_CODE_NOTE = (
    "El campo `orden_compra` de Presupuesto Abierto no trae aquí un código de orden. "
    "No es una orden que Mercado Público no tenga: es una referencia que nunca fue un "
    "código, y consultarla produciría un «no encontrado» que se leería como ausencia "
    "de la orden."
)


def classify_order_code(raw: object) -> dict:
    """Separa un código de orden de un campo usado como nota libre.

    Medido sobre los 4.366 códigos distintos publicados, el 22,9% no son códigos:
    `0`, `00000`, `C/T`, `COMISION`, `CONTRATO DE ARRASTRE`. Consultarlos gasta
    cuota, pero el daño real es otro: quedarían publicados como órdenes que
    Mercado Público no encontró, cuando la verdad es que nunca hubo un código que
    buscar. Es la misma regla de siempre: una capa que no puede calcularse lo
    declara, en vez de publicar un cero que parece un resultado negativo.

    Las dos reparaciones son mecánicas y se declaran: quitar guiones sobrantes en
    los extremos y reponer el separador que falta antes del tipo. Recuperan 23 de
    los 4.366 —poco— y ninguna inventa un dígito. Cualquier otra forma se descarta
    en vez de adivinarse.
    """
    code = _clean_code(raw)
    if not code:
        return {"code": None, "shape": NOT_AN_ORDER_CODE, "consultable": False, "raw": code}
    if CANONICAL_ORDER_CODE.match(code):
        return {"code": code, "shape": CANONICAL, "consultable": True, "raw": code}

    trimmed = code.strip("-").strip()
    if CANONICAL_ORDER_CODE.match(trimmed):
        return {"code": trimmed, "shape": REPAIRED_DASH, "consultable": True, "raw": code}
    match = MISSING_SEPARATOR.match(trimmed)
    if match:
        repaired = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
        return {"code": repaired, "shape": REPAIRED_SEPARATOR, "consultable": True, "raw": code}
    return {"code": None, "shape": NOT_AN_ORDER_CODE, "consultable": False, "raw": code}


def _number(value: object) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _nested(obj: dict, key: str) -> dict:
    value = obj.get(key)
    return value if isinstance(value, dict) else {}


def _items(obj: dict) -> list[dict]:
    block = _nested(obj, "Items")
    values = block.get("Listado")
    if isinstance(values, dict) and "Item" in values:
        values = values.get("Item")
    return [x for x in _as_list(values) if isinstance(x, dict)]


def _order_rows(payload: dict) -> list[dict]:
    listed = payload.get("Listado")
    if isinstance(listed, dict):
        for key in ("OrdenCompra", "Listado", "Ordenes"):
            if key in listed:
                listed = listed[key]
                break
    return [x for x in _as_list(listed) if isinstance(x, dict)]


def parse_order_payload(payload: dict, requested_code: str | None = None) -> dict | None:
    """Normalize one Mercado Público purchase-order API response.

    The adapter accepts the current public API shape and a few historical nesting
    variants because ChileCompra has changed wrappers over time. It does not infer
    missing fields.
    """
    rows = _order_rows(payload)
    if requested_code:
        requested = _clean_code(requested_code)
        exact = [x for x in rows if _clean_code(x.get("Codigo")) == requested]
        if exact:
            rows = exact
    if not rows:
        return None

    row = rows[0]
    buyer = _nested(row, "Comprador")
    supplier = _nested(row, "Proveedor")
    dates = _nested(row, "Fechas")
    items = _items(row)
    categories: list[str] = []
    products: list[str] = []
    for item in items:
        category = str(item.get("Categoria") or "").strip()
        product = str(item.get("Producto") or item.get("NombreProducto") or item.get("CodigoProducto") or "").strip()
        if category and category not in categories:
            categories.append(category)
        if product and product not in products:
            products.append(product)

    return {
        "purchase_order_code": _clean_code(row.get("Codigo") or requested_code),
        "name": row.get("Nombre"),
        "description": row.get("Descripcion"),
        "state_code": row.get("CodigoEstado"),
        "supplier_state_code": row.get("CodigoEstadoProveedor"),
        "supplier_state": row.get("EstadoProveedor"),
        "purchase_type_code": row.get("CodigoTipo"),
        "purchase_type": row.get("Tipo"),
        "linked_tender_code": _clean_code(row.get("CodigoLicitacion")) or None,
        "currency": row.get("TipoMoneda"),
        "net_total": _number(row.get("TotalNeto")),
        "taxes": _number(row.get("Impuestos")),
        "charges": _number(row.get("Cargos")),
        "discounts": _number(row.get("Descuentos")),
        "total": _number(row.get("Total")),
        "financing": row.get("Financiamiento"),
        "payment_form": row.get("FormaPago"),
        "created_at": dates.get("FechaCreacion"),
        "sent_at": dates.get("FechaEnvio"),
        "accepted_at": dates.get("FechaAceptacion"),
        "cancelled_at": dates.get("FechaCancelacion"),
        "last_modified_at": dates.get("FechaUltimaModificacion"),
        "buyer": {
            "organization_code": buyer.get("CodigoOrganismo"),
            "organization_name": buyer.get("NombreOrganismo"),
            "unit_rut": canon_rut(buyer.get("RutUnidad")),
            "unit_code": buyer.get("CodigoUnidad"),
            "unit_name": buyer.get("NombreUnidad"),
            "commune": buyer.get("ComunaUnidad"),
            "region": buyer.get("RegionUnidad"),
        },
        "supplier": {
            "supplier_code": supplier.get("Codigo"),
            "supplier_name": supplier.get("Nombre"),
            "activity": supplier.get("Actividad"),
            "branch_code": supplier.get("CodigoSucursal"),
            "branch_name": supplier.get("NombreSucursal"),
            "rut": canon_rut(supplier.get("RutSucursal")),
            "commune": supplier.get("Comuna"),
            "region": supplier.get("Region"),
        },
        "item_count": int(_nested(row, "Items").get("Cantidad") or len(items) or 0),
        "categories": categories[:8],
        "products": products[:8],
        "source": "API_MERCADO_PUBLICO_ORDEN_COMPRA",
    }


def _priority_by_finding(findings: dict) -> dict[str, tuple[int, float]]:
    out: dict[str, tuple[int, float]] = {}
    rank = {"ATENCION_INMEDIATA": 0, "REVISION_PRIORITARIA": 1, "SEGUIMIENTO": 2}
    for row in findings.get("relation_findings") or []:
        fid = str(row.get("finding_id") or "")
        out[fid] = (
            rank.get(str(row.get("attention_level") or "SEGUIMIENTO"), 3),
            -float(row.get("max_priority_score") or 0),
        )
    return out


def build_targets(
    procurement: dict,
    findings: dict,
    max_orders_per_finding: int = 2,
    max_total_orders: int = 800,
) -> list[dict]:
    return build_targets_with_discards(
        procurement, findings,
        max_orders_per_finding=max_orders_per_finding,
        max_total_orders=max_total_orders,
    )[0]


def build_targets_with_discards(
    procurement: dict,
    findings: dict,
    max_orders_per_finding: int = 2,
    max_total_orders: int = 800,
) -> tuple[list[dict], list[dict]]:
    """Los objetivos a consultar y las referencias que no son códigos de orden.

    Lo descartado se devuelve en vez de desaparecer: el payload tiene que poder
    decir cuántas referencias nunca fueron un código, para que su ausencia no se
    lea como una orden que Mercado Público no tiene.
    """
    priority = _priority_by_finding(findings)
    rows = list(procurement.get("findings") or [])
    rows.sort(key=lambda x: priority.get(str(x.get("finding_id") or ""), (9, 0)))
    selected: list[dict] = []
    discarded: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        fid = str(row.get("finding_id") or "")
        provider_id = str(row.get("provider_id") or "")
        expected_rut = rut_from_provider_id(provider_id)
        for raw in (row.get("purchase_order_examples") or [])[: max(0, int(max_orders_per_finding))]:
            verdict = classify_order_code(raw)
            if not verdict["consultable"]:
                if verdict["raw"]:
                    discarded.append({"finding_id": fid, "reference": verdict["raw"],
                                      "shape": verdict["shape"], "note": NOT_A_CODE_NOTE})
                continue
            code = verdict["code"]
            if code in seen:
                continue
            seen.add(code)
            selected.append(
                {
                    "purchase_order_code": code,
                    "source_reference": verdict["raw"],
                    "code_shape": verdict["shape"],
                    "finding_id": fid,
                    "organization_id": str(row.get("organization_id") or ""),
                    "provider_id": provider_id,
                    "expected_provider_rut": expected_rut or None,
                    "periodo": row.get("periodo"),
                }
            )
            if len(selected) >= max_total_orders:
                return selected, discarded
    return selected, discarded


def _api_url(code: str, ticket: str, endpoint: str = ORDER_ENDPOINT_CANDIDATES[0]) -> str:
    query = urllib.parse.urlencode({"codigo": code, "ticket": ticket})
    return f"{API_ROOT}/{endpoint}?{query}"


def fetch_order(
    code: str,
    ticket: str,
    timeout: int = 25,
    endpoint: str = ORDER_ENDPOINT_CANDIDATES[0],
) -> dict | None:
    req = urllib.request.Request(
        _api_url(code, ticket, endpoint),
        headers={"User-Agent": "RIGP/1.0 MercadoPublico targeted evidence bridge"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8-sig"))
    return parse_order_payload(payload, requested_code=code)


def resolve_order_endpoint(
    code: str,
    ticket: str,
    timeout: int = 25,
    candidates: tuple[str, ...] = ORDER_ENDPOINT_CANDIDATES,
    fetch=None,
) -> dict:
    """Averigua qué ruta resuelve una orden, en vez de darla por sabida.

    Una ruta que responde 404 no existe; una que responde cualquier otra cosa
    —incluso «no encontré esa orden»— existe y es la buena. La distinción es la
    misma del inventario de fuentes: no confundir «no se pudo probar» con «no
    está».
    """
    fetch = fetch or fetch_order
    attempts: list[dict] = []
    for endpoint in candidates:
        try:
            fetch(code, ticket, timeout, endpoint)
        except Exception as exc:
            status = getattr(exc, "code", None)
            attempts.append({"endpoint": endpoint, "http_status": status,
                             "error": str(exc)[:200]})
            if status == 404:
                continue
            # Cualquier otro fallo —credencial, red, límite— no dice que la ruta
            # no exista, y probar las demás sólo gastaría cuota para repetirlo.
            return {"endpoint": endpoint, "resolved": False, "attempts": attempts,
                    "why": "El primer candidato falló por una causa ajena a la ruta."}
        else:
            attempts.append({"endpoint": endpoint, "http_status": 200})
            return {"endpoint": endpoint, "resolved": True, "attempts": attempts,
                    "why": f"`{endpoint}` respondió; se usa para el resto de la corrida."}
    return {
        "endpoint": candidates[0],
        "resolved": False,
        "attempts": attempts,
        "why": (
            "Ninguna de las rutas candidatas existe: todas respondieron 404. El adaptador "
            "necesita la ruta vigente de la API de órdenes de compra."
        ),
    }


def _identity_check(target: dict, order: dict | None) -> dict:
    expected = canon_rut(target.get("expected_provider_rut"))
    observed = canon_rut((order or {}).get("supplier", {}).get("rut"))
    if not expected:
        status = "NOT_COMPARABLE"
        note = "El proveedor RIGP no tiene RUT explícitamente resuelto; no se compara por nombre."
    elif not observed:
        status = "API_RUT_NOT_AVAILABLE"
        note = "La orden fue resuelta, pero la respuesta API no entregó un RUT de proveedor comparable."
    elif expected == observed:
        status = "MATCH"
        note = "El RUT explícito del proveedor RIGP coincide con el RUT publicado para la orden de compra."
    else:
        status = "REVIEW"
        note = (
            "El RUT explícito del proveedor RIGP no coincide con el RUT publicado para esta orden. "
            "Debe verificarse la relación documental antes de interpretar la diferencia."
        )
    return {"status": status, "expected_rut": expected or None, "observed_rut": observed or None, "note": note}


TICKET_REJECTED = "TICKET_RECHAZADO"
ENDPOINT_CHANGED = "ENDPOINT_NO_DISPONIBLE"
RATE_LIMITED = "LIMITE_DE_CONSULTAS"
NETWORK = "RED_NO_DISPONIBLE"
UNCLASSIFIED = "NO_CLASIFICADO"

FAILURE_MEANING = {
    TICKET_REJECTED: (
        "La API rechazó la credencial. El ticket existe pero no autoriza esta consulta: "
        "hay que renovarlo o verificar que corresponde al endpoint de órdenes de compra. "
        "Es acción del operador, no defecto del puente."
    ),
    ENDPOINT_CHANGED: (
        "La API respondió que el recurso no existe para todas las órdenes consultadas. "
        "O el endpoint cambió de forma, o los códigos de orden que publica Presupuesto "
        "Abierto no son los que Mercado Público resuelve por este camino."
    ),
    RATE_LIMITED: (
        "La API limitó las consultas. El puente ya se detiene solo; conviene espaciar la "
        "corrida antes de reintentar."
    ),
    NETWORK: "No hubo salida de red hacia la API. No dice nada sobre la credencial ni sobre las órdenes.",
    UNCLASSIFIED: "El error no cae en ninguna causa conocida; se conserva el texto tal cual para leerlo.",
}


def diagnose_api_failure(exc: Exception) -> dict:
    """Traduce un fallo de API a una causa accionable, sin adivinar cuál es.

    La diferencia importa: un ticket rechazado lo arregla el operador en un minuto,
    un endpoint cambiado lo arregla el adaptador. Informar sólo «20 errores» obliga
    a repetir la corrida para averiguar cuál de las dos cosas pasó.
    """
    text = str(exc)
    code = getattr(exc, "code", None)
    if code in (401, 403) or "401" in text or "403" in text:
        cause = TICKET_REJECTED
    elif code == 404 or "404" in text:
        cause = ENDPOINT_CHANGED
    elif code == 429 or "429" in text:
        cause = RATE_LIMITED
    elif isinstance(exc, (OSError,)) and code is None and "HTTP" not in text:
        cause = NETWORK
    else:
        cause = UNCLASSIFIED
    return {
        "cause": cause,
        "meaning": FAILURE_MEANING[cause],
        "http_status": code,
        "error": text[:300],
    }


RATE_LIMIT_STATUS = 429

# ChileCompra no publica su ventana de ritmo, así que el puente no la supone: parte
# con una pausa corta y la alarga sola cada vez que recibe un 429. La corrida #21
# perdió 413 de 800 consultas contra un ritmo fijo de 0,05s; ceder terreno ante la
# primera negativa cuesta segundos y recupera consultas que ya estaban pagadas con
# el tiempo del runner.
RATE_LIMIT_BACKOFF_SECONDS = 2.0
RATE_LIMIT_MAX_RETRIES = 3
PAUSE_GROWTH_ON_LIMIT = 2.0
MAX_PAUSE_SECONDS = 2.0


def _is_rate_limited(exc: Exception) -> bool:
    return getattr(exc, "code", None) == RATE_LIMIT_STATUS or "429" in str(exc)


def fetch_order_with_backoff(
    code: str,
    ticket: str,
    endpoint: str,
    timeout: int = 25,
    max_retries: int = RATE_LIMIT_MAX_RETRIES,
    backoff_seconds: float = RATE_LIMIT_BACKOFF_SECONDS,
    fetch=None,
    sleep=None,
) -> tuple[dict | None, int]:
    """Consulta una orden cediendo terreno ante un 429, en vez de darla por perdida.

    Devuelve la orden y cuántos reintentos costó. Un 429 dice «espera», no «no
    existe»: tratarlo como fallo definitivo fue lo que botó la mitad de la corrida
    #21. Cualquier otro error se propaga sin reintentar, porque repetirlo no lo
    va a cambiar.
    """
    fetch = fetch or fetch_order
    sleep = sleep or time.sleep
    retries = 0
    while True:
        try:
            return fetch(code, ticket, timeout, endpoint), retries
        except Exception as exc:
            if not _is_rate_limited(exc) or retries >= max_retries:
                raise
            retries += 1
            sleep(backoff_seconds * retries)


def build_mercado_publico_context(
    procurement_path: str = "docs/data/procurement_context.json",
    findings_path: str = "docs/data/investigative_findings.json",
    output_path: str = "docs/data/mercado_publico_context.json",
    ticket: str | None = None,
    max_orders_per_finding: int = 2,
    max_total_orders: int = 800,
    request_pause_seconds: float = 0.05,
) -> dict:
    procurement = _read(procurement_path)
    findings = _read(findings_path)
    targets, discarded = build_targets_with_discards(
        procurement,
        findings,
        max_orders_per_finding=max_orders_per_finding,
        max_total_orders=max_total_orders,
    )
    ticket = (ticket if ticket is not None else os.environ.get("MERCADO_PUBLICO_TICKET", "")).strip()

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "schema": SCHEMA,
        "source": {
            "name": "API Mercado Público - Órdenes de Compra",
            "endpoint": API_BASE,
            "mode": "TARGETED_BY_PURCHASE_ORDER_CODE",
            "credential_required": True,
            "ticket_present": bool(ticket),
            "daily_request_limit_note": "ChileCompra informa un límite de 10.000 solicitudes diarias por ticket.",
        },
        "guardrail": GUARDRAIL,
        "selection": {
            "max_orders_per_finding": int(max_orders_per_finding),
            "max_total_orders": int(max_total_orders),
            "target_orders": len(targets),
            "note": (
                "Se consultan sólo códigos de OC ya observados en hallazgos publicados. "
                "La selección es una muestra de evidencia, no una reconstrucción exhaustiva del proceso de compra."
            ),
        },
        "status": "AWAITING_TICKET" if not ticket else "RUNNING",
        "coverage": {
            "target_orders": len(targets),
            "api_requests_attempted": 0,
            "orders_resolved": 0,
            "orders_not_resolved": 0,
            "api_errors": 0,
            "identity_matches": 0,
            "identity_reviews": 0,
            "linked_tenders": 0,
            "endpoint_probe_requests": 0,
            "non_code_references": len(discarded),
            "repaired_codes": sum(1 for t in targets if t["code_shape"] != CANONICAL),
            "rate_limit_retries": 0,
            "rate_limit_abandoned": 0,
        },
        "orders": {},
        "findings": [],
    }

    if not ticket:
        result["status_note"] = (
            "El puente está listo, pero no se efectuaron consultas porque el repositorio no expone un ticket de API. "
            "Configurar el secreto MERCADO_PUBLICO_TICKET habilita la resolución dirigida de órdenes."
        )
        Path(output_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    orders: dict[str, dict] = {}
    failures: dict[str, dict] = {}
    consecutive_errors = 0

    # Resolver la ruta antes de gastar la cuota: la corrida #20 quemó 20 consultas
    # contra un endpoint que no existía y no pudo decir cuál sí.
    endpoint_probe = resolve_order_endpoint(targets[0]["purchase_order_code"], ticket)
    # El sondeo no es una consulta de orden: sumarlo a `api_requests_attempted`
    # empujó el contador a 801 y rompió el tope declarado de 800. Va en su propio
    # contador, y el total se declara aparte en vez de mezclar dos cosas distintas.
    result["coverage"]["endpoint_probe_requests"] = len(endpoint_probe["attempts"])
    endpoint = endpoint_probe["endpoint"]
    result["source"]["endpoint"] = f"{API_ROOT}/{endpoint}"
    result["source"]["endpoint_resolution"] = endpoint_probe
    if not endpoint_probe["resolved"]:
        result["status"] = "PARTIAL_API_FAILURE"
        result["status_note"] = endpoint_probe["why"]
        result["failure_diagnosis"] = {
            "cause": ENDPOINT_CHANGED,
            "meaning": FAILURE_MEANING[ENDPOINT_CHANGED],
            "http_status": None,
            "error": json.dumps(endpoint_probe["attempts"], ensure_ascii=False)[:300],
        }
        result["failures"] = {}
        Path(output_path).write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return result

    for target in targets:
        code = target["purchase_order_code"]
        result["coverage"]["api_requests_attempted"] += 1
        try:
            order, retries = fetch_order_with_backoff(code, ticket, endpoint)
            result["coverage"]["rate_limit_retries"] += retries
            if not order:
                failures[code] = {"status": "NOT_FOUND", "message": "La API no devolvió una orden para el código solicitado."}
                result["coverage"]["orders_not_resolved"] += 1
                consecutive_errors = 0
            else:
                check = _identity_check(target, order)
                order["identity_check"] = check
                orders[code] = order
                result["coverage"]["orders_resolved"] += 1
                result["coverage"]["linked_tenders"] += int(bool(order.get("linked_tender_code")))
                result["coverage"]["identity_matches"] += int(check["status"] == "MATCH")
                result["coverage"]["identity_reviews"] += int(check["status"] == "REVIEW")
                consecutive_errors = 0
        except Exception as exc:  # network/API failures are coverage events, not analytical findings
            failures[code] = {"status": "API_ERROR", "message": str(exc)[:300]}
            result["coverage"]["api_errors"] += 1
            consecutive_errors += 1
            if _is_rate_limited(exc):
                result["coverage"]["rate_limit_abandoned"] += 1
                request_pause_seconds = min(
                    MAX_PAUSE_SECONDS,
                    max(request_pause_seconds, 0.05) * PAUSE_GROWTH_ON_LIMIT,
                )
                result["coverage"]["request_pause_seconds"] = round(request_pause_seconds, 4)
            if consecutive_errors >= 20:
                result["status"] = "PARTIAL_API_FAILURE"
                # El motivo viaja en la nota, no sólo en el conteo: una corrida que
                # se detiene sin decir por qué obliga a repetirla para averiguarlo.
                result["status_note"] = (
                    "Se detuvo la corrida tras 20 errores API consecutivos para evitar solicitudes "
                    f"inútiles. Último error, en la orden {code}: {str(exc)[:200]}"
                )
                result["failure_diagnosis"] = diagnose_api_failure(exc)
                break
        if request_pause_seconds > 0:
            time.sleep(request_pause_seconds)

    result["orders"] = orders
    by_finding: dict[str, list[dict]] = {}
    target_by_code = {x["purchase_order_code"]: x for x in targets}
    for code, target in target_by_code.items():
        fid = target["finding_id"]
        item = {"purchase_order_code": code}
        if code in orders:
            order = orders[code]
            item.update(
                {
                    "status": "RESOLVED",
                    "supplier_rut": order.get("supplier", {}).get("rut"),
                    "supplier_name": order.get("supplier", {}).get("supplier_name"),
                    "identity_check": order.get("identity_check"),
                    "purchase_type": order.get("purchase_type"),
                    "supplier_state": order.get("supplier_state"),
                    "linked_tender_code": order.get("linked_tender_code"),
                    "currency": order.get("currency"),
                    "total": order.get("total"),
                    "sent_at": order.get("sent_at"),
                    "accepted_at": order.get("accepted_at"),
                    "categories": order.get("categories") or [],
                }
            )
        else:
            item.update(failures.get(code, {"status": "NOT_ATTEMPTED"}))
        by_finding.setdefault(fid, []).append(item)

    result["findings"] = [
        {"finding_id": fid, "orders": values}
        for fid, values in by_finding.items()
    ]
    if result["status"] == "RUNNING":
        result["status"] = "READY" if not failures else "READY_WITH_GAPS"
    result["failures"] = failures
    result["non_code_references"] = discarded[:50]
    result["method_note"] = (
        "Este producto valida y contextualiza una muestra dirigida de órdenes asociadas a hallazgos RIGP. "
        "No incorpora sus diferencias al score de prioridad de forma automática."
    )
    Path(output_path).write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return result


def main() -> None:
    result = build_mercado_publico_context()
    print("[RIGP Mercado Público]", result["status"])
    print("[RIGP Mercado Público coverage]", result["coverage"])
    probe = (result.get("source") or {}).get("endpoint_resolution")
    if probe:
        print("[RIGP Mercado Público ruta]", result["source"]["endpoint"], "-", probe["why"])
    if result.get("status_note"):
        print("[RIGP Mercado Público nota]", result["status_note"])
    diagnosis = result.get("failure_diagnosis")
    if diagnosis:
        print("[RIGP Mercado Público causa]", diagnosis["cause"], "-", diagnosis["meaning"])
    # Las primeras fallas van al log porque el payload puede no llegar a publicarse:
    # una corrida que muere al empujar no puede llevarse consigo el diagnóstico.
    for code, failure in list((result.get("failures") or {}).items())[:3]:
        print(f"[RIGP Mercado Público falla] {code}: {failure.get('status')} {failure.get('message','')[:200]}")


if __name__ == "__main__":
    main()
