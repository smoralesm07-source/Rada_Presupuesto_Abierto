"""Una orden sin licitación sólo dice algo si su tipo suele traer una.

`POTENTIAL_FRAGMENTATION` nunca pudo preguntar lo que importa —si ese gasto
debió licitarse— porque la modalidad de contratación no estaba en los datos.
Ahora sí: el puente de Mercado Público resuelve órdenes reales y cada una
declara su tipo y, cuando existe, la licitación de la que proviene.

La tentación sería marcar toda orden sin licitación vinculada. Medido sobre las
524 órdenes resueltas, eso sería un error grosero:

    SE    193 con licitación   113 sin
    CM      0 con licitación   213 sin

En Convenio Marco la licitación ocurrió una vez, de forma centralizada, y
ninguna orden la referencia. Su ausencia ahí no es información: es la forma
normal del instrumento, y marcarla inundaría la bandeja con 213 falsos
positivos. En cambio dos de cada tres órdenes SE sí declaran licitación, así que
una SE que no la trae es rara **dentro de su propio tipo**.

Es la misma regla que el resto del motor: rareza relativa a pares, nunca un
umbral absoluto aplicado a poblaciones distintas.

Y una advertencia que viaja en el payload: que la API no devuelva código de
licitación no prueba que no la hubiera. Puede ser trato directo con resolución
fundada, compra bajo el umbral, o una emergencia. Lo que la capa afirma es más
modesto y más defendible: esta orden no declara la licitación que sus pares sí
declaran.
"""
from __future__ import annotations

SCHEMA_BLOCK = "modality_review"

# Bajo este número de órdenes, la proporción de un tipo no establece una línea
# base: con seis casos, «dos de cada tres» es ruido.
MIN_PEERS_FOR_BASELINE = 20

# Si menos de la mitad de las órdenes de un tipo declara licitación, su ausencia
# no distingue nada. Convenio Marco está en cero y por eso nunca se marca.
INFORMATIVE_LINKAGE_FLOOR = 0.5

# Una orden de $200.000 sin licitación no es un hallazgo, es una compra chica.
# El piso existe para no gastar la atención del analista, no para negar el caso.
MIN_AMOUNT_CLP = 10_000_000

# Medido sobre las 40 órdenes que la capa marcó en la corrida del 16 de
# septiembre: 8 tenían por contraparte una universidad, y esas 8 concentraban el
# 62% del monto marcado. Un convenio entre organismos públicos queda fuera de
# licitación por su naturaleza, así que encabezar la bandeja con ellos sería
# gastar la revisión en la categoría más sana que hay.
#
# No se resuelve por nombre ni por tramo de RUT —la UFRO es 87.912.900-1 y la
# U. Adolfo Ibáñez, privada, es 71.543.200-5—, sino con la marca `intraestado`
# que el bulk de DIPRES ya trae y que `procurement_context` ahora transporta.
# Mientras esa marca no llegue, la capa lo dice en vez de suponer.
INTRA_STATE_SHARE_FLOOR = 0.5

LINKED = "DECLARA_LICITACION"
UNLINKED_INFORMATIVE = "NO_DECLARA_LICITACION_Y_SUS_PARES_SI"
UNLINKED_EXPECTED = "SU_TIPO_NO_DECLARA_LICITACION"
INTRA_STATE = "CONVENIO_ENTRE_ORGANISMOS_PUBLICOS"
BELOW_FLOOR = "BAJO_EL_PISO_DE_MONTO"
UNDETERMINED = "NO_DETERMINADO"

MEANING = {
    LINKED: "La orden declara la licitación de la que proviene.",
    UNLINKED_INFORMATIVE: (
        "La orden no declara licitación, y la mayoría de las órdenes de su mismo tipo sí "
        "lo hace. Es la pregunta que vale la pena formular, no una respuesta."
    ),
    UNLINKED_EXPECTED: (
        "Su tipo de compra no declara licitación por diseño —Convenio Marco la resolvió "
        "una vez, de forma centralizada—, así que la ausencia no distingue nada."
    ),
    INTRA_STATE: (
        "El gasto de esta relación está marcado como intraestado en el bulk de DIPRES: "
        "es un convenio entre organismos públicos, que queda fuera de licitación por su "
        "naturaleza. No se dedujo del nombre ni del RUT del proveedor."
    ),
    BELOW_FLOOR: "No declara licitación, pero el monto no justifica ocupar la revisión.",
    UNDETERMINED: (
        "El tipo de compra tiene muy pocas órdenes resueltas para establecer qué es "
        "normal en él."
    ),
}

GUARDRAIL = (
    "Que una orden no declare licitación no prueba que no la hubiera: puede corresponder "
    "a trato directo con resolución fundada, a compra bajo el umbral o a una emergencia. "
    "Esta capa no acredita irregularidad ni incumplimiento; ordena por dónde preguntar."
)


def linkage_baseline(orders: dict, min_peers: int = MIN_PEERS_FOR_BASELINE) -> dict:
    """Qué proporción de cada tipo de compra declara su licitación.

    Se aprende de las órdenes observadas en vez de fijarse a mano: si ChileCompra
    cambia el comportamiento de un instrumento, la línea base lo sigue sin que
    nadie edite un número.
    """
    counts: dict[str, list[int]] = {}
    for order in (orders or {}).values():
        kind = str((order or {}).get("purchase_type") or "").strip() or "SIN_TIPO"
        slot = counts.setdefault(kind, [0, 0])
        slot[0] += 1
        if (order or {}).get("linked_tender_code"):
            slot[1] += 1

    baseline = {}
    for kind, (total, linked) in counts.items():
        share = (linked / total) if total else 0.0
        baseline[kind] = {
            "orders": total,
            "with_tender": linked,
            "linkage_share": round(share, 6),
            "established": total >= int(min_peers),
            "informative": total >= int(min_peers) and share >= INFORMATIVE_LINKAGE_FLOOR,
        }
    return baseline


def classify_linkage(
    order: dict,
    baseline: dict,
    min_amount: float = MIN_AMOUNT_CLP,
    intra_state_share: float | None = None,
) -> dict:
    """Clasifica una orden contra lo que es normal en su propio tipo.

    `intra_state_share` viene de `procurement_context` y es opcional a propósito:
    hasta que una corrida lo regenere no existe, y la capa prefiere marcar de más
    a inventar el dato. Cuando llega, los convenios entre organismos públicos
    salen de la bandeja por un hecho declarado, no por una heurística de nombre.
    """
    kind = str((order or {}).get("purchase_type") or "").strip() or "SIN_TIPO"
    peers = (baseline or {}).get(kind) or {}
    tender = (order or {}).get("linked_tender_code")

    if tender:
        return _verdict(LINKED, kind, peers, tender=str(tender))
    if not peers.get("established"):
        return _verdict(UNDETERMINED, kind, peers)
    if not peers.get("informative"):
        return _verdict(UNLINKED_EXPECTED, kind, peers)
    if intra_state_share is not None and float(intra_state_share) >= INTRA_STATE_SHARE_FLOOR:
        return _verdict(INTRA_STATE, kind, peers, amount=_amount(order),
                        intra_state_share=round(float(intra_state_share), 6))

    # El monto sólo se compara cuando viene en pesos: mezclar CLP, USD y CLF en
    # un mismo piso compararía cosas distintas.
    currency = str((order or {}).get("currency") or "CLP").strip().upper() or "CLP"
    amount = _amount(order)
    if currency != "CLP":
        return _verdict(UNLINKED_INFORMATIVE, kind, peers, amount=amount, currency=currency,
                        note="El monto viene en otra moneda y no se compara contra el piso en pesos.")
    if amount < float(min_amount):
        return _verdict(BELOW_FLOOR, kind, peers, amount=amount, currency=currency)
    return _verdict(UNLINKED_INFORMATIVE, kind, peers, amount=amount, currency=currency)


def _amount(order: dict) -> float:
    try:
        return float((order or {}).get("total") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _verdict(state: str, kind: str, peers: dict, **extra) -> dict:
    out = {
        "linkage_state": state,
        "meaning": MEANING[state],
        "purchase_type": kind,
        "peer_orders": peers.get("orders", 0),
        "peer_linkage_share": peers.get("linkage_share", 0.0),
        "worth_asking": state == UNLINKED_INFORMATIVE,
    }
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def review_orders(orders: dict, min_amount: float = MIN_AMOUNT_CLP,
                  max_rows: int = 60,
                  intra_state_by_order: dict | None = None) -> dict:
    """El bloque que se publica: línea base por tipo y las órdenes que preguntar.

    Las filas van ordenadas por monto porque la materialidad es lo que decide a
    quién mira primero un analista, y se acotan porque el payload es un activo
    web y no un volcado.
    """
    baseline = linkage_baseline(orders)
    rows = []
    tally: dict[str, int] = {}
    shares = intra_state_by_order or {}
    for code, order in (orders or {}).items():
        verdict = classify_linkage(order, baseline, min_amount=min_amount,
                                   intra_state_share=shares.get(code))
        tally[verdict["linkage_state"]] = tally.get(verdict["linkage_state"], 0) + 1
        if verdict["worth_asking"]:
            rows.append({
                "purchase_order_code": code,
                "supplier_rut": ((order or {}).get("supplier") or {}).get("rut"),
                "supplier_name": ((order or {}).get("supplier") or {}).get("supplier_name"),
                **verdict,
            })
    rows.sort(key=lambda r: -float(r.get("amount") or 0.0))
    return {
        "guardrail": GUARDRAIL,
        "intra_state_state": "MEDIDO" if shares else "NO_MEDIDO",
        "intra_state_note": (
            "Los convenios entre organismos públicos se apartan con la marca `intraestado` "
            "del bulk."
            if shares else
            "La marca `intraestado` no llegó a esta corrida, así que ningún convenio entre "
            "organismos públicos se apartó. En la medición del 16-09 eso dejó 8 órdenes con "
            "contraparte universitaria concentrando el 62% del monto marcado: son el caso "
            "sano más frecuente de esta lista."
        ),
        "min_amount_clp": float(min_amount),
        "baseline_by_purchase_type": baseline,
        "states": tally,
        "orders_worth_asking": len(rows),
        "orders_published": min(len(rows), int(max_rows)),
        "orders": rows[: int(max_rows)],
    }
