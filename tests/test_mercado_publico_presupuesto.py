"""Lo que se recorta para que quepa es contexto, nunca el hallazgo.

La corrida #22 resolvió 524 órdenes y escribió 1,7 MB contra una guarda de
1,5 MB. De esos, 300 KB eran sangría: el archivo entero se perdía por cómo se
escribía, no por lo que contenía.
"""
import json

import pytest

from radar_presupuesto.mercado_publico_bridge import (
    COMPACT_JSON,
    TRIM_LAYERS,
    fit_to_budget,
)


def _order(code, review=False, bulk=400):
    return {
        "purchase_order_code": code,
        "total": 1_000_000,
        "identity_check": {"status": "REVIEW" if review else "MATCH",
                           "expected_rut": "76415528-9",
                           "observed_rut": "77777777-7" if review else "76415528-9"},
        "description": "D" * bulk,
        "categories": ["C" * 40] * 5,
        "products": ["P" * 40] * 5,
        "name": "N" * 60,
    }


def _payload(n_match=60, n_review=3):
    orders = {f"100-{i}-SE26": _order(f"100-{i}-SE26") for i in range(n_match)}
    orders.update({f"200-{i}-SE26": _order(f"200-{i}-SE26", review=True)
                   for i in range(n_review)})
    return {"schema": "RIGP-MERCADO-PUBLICO-CONTEXT-v1", "orders": orders}


def _size(payload):
    return len(json.dumps(payload, **COMPACT_JSON))


def test_si_ya_cabe_no_se_recorta_nada():
    """Medir mal el presupuesto hace sacrificar lo que no hacía falta."""
    p = _payload()
    fit_to_budget(p, budget=_size(p) + 10_000)
    assert p["trimming"]["applied"] == []
    assert p["trimming"]["orders_trimmed"] == 0
    assert "No fue necesario" in p["trimming"]["note"]


def test_el_presupuesto_mide_el_archivo_que_se_escribe():
    """Con los separadores por defecto el tamaño se sobreestima >20%.

    Esa diferencia fue real: hizo recortar 511 órdenes para entrar a un
    presupuesto en el que el payload ya cabía.
    """
    p = _payload()
    compacto = len(json.dumps(p, **COMPACT_JSON))
    con_espacios = len(json.dumps(p, ensure_ascii=False, default=str))
    assert compacto < con_espacios
    fit_to_budget(p, budget=compacto + 1_000)
    assert p["trimming"]["applied"] == [], "no debe recortar si cabe compacto"


def test_una_discrepancia_de_identidad_nunca_se_recorta():
    """Es el hallazgo. Recortarlo para que quepa el relleno sería al revés."""
    p = _payload()
    fit_to_budget(p, budget=1_000)  # imposible de cumplir: se sacrifica todo lo sacrificable
    revisiones = [o for o in p["orders"].values()
                  if o["identity_check"]["status"] == "REVIEW"]
    assert len(revisiones) == 3
    for o in revisiones:
        assert {"description", "categories", "products", "name"} <= set(o)


def test_se_sacrifica_en_el_orden_declarado():
    p = _payload()
    fit_to_budget(p, budget=1_000)
    esperado = [label for _, label in TRIM_LAYERS]
    assert p["trimming"]["applied"] == esperado
    # La descripción es lo último: es lo único que dice en palabras qué se compró.
    assert p["trimming"]["applied"][-1] == "descripción de la orden"


def test_el_recorte_se_declara_para_que_no_parezca_un_dato_ausente():
    p = _payload()
    fit_to_budget(p, budget=1_000)
    nota = p["trimming"]["note"]
    assert "recortado, no inexistente" in nota
    assert p["trimming"]["orders_trimmed"] == 60
    assert p["trimming"]["budget_bytes"] == 1_000


def test_un_payload_sin_ordenes_no_rompe_el_presupuesto():
    p = {"schema": "x", "orders": {}}
    fit_to_budget(p, budget=10)
    assert p["trimming"]["orders_trimmed"] == 0
