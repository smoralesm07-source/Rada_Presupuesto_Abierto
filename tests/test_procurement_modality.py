"""Una orden sin licitación sólo dice algo si su tipo suele traer una.

Medido sobre las 524 órdenes que el puente resolvió el 16 de septiembre:

    SE   193 con licitación · 113 sin      (63% la declara)
    CM     0 con licitación · 213 sin      (ninguna la declara)

En Convenio Marco la licitación ocurrió una vez, centralizada. Marcar esas 213
inundaría la bandeja con la categoría más sana que existe. La regla es la misma
del resto del motor: rareza relativa a pares, nunca un umbral absoluto sobre
poblaciones distintas.
"""
import pytest

from radar_presupuesto.procurement_modality import (
    BELOW_FLOOR,
    INTRA_STATE,
    LINKED,
    UNDETERMINED,
    UNLINKED_EXPECTED,
    UNLINKED_INFORMATIVE,
    classify_linkage,
    linkage_baseline,
    review_orders,
)


def _order(kind, tender=None, total=50_000_000, currency="CLP"):
    return {"purchase_type": kind, "linked_tender_code": tender,
            "total": total, "currency": currency,
            "supplier": {"rut": "76415528-9", "supplier_name": "PROVEEDOR X"}}


def _orders(se_con=193, se_sin=113, cm=213):
    o = {}
    for i in range(se_con):
        o[f"1-{i}-SE24"] = _order("SE", tender=f"1-{i}-LP24")
    for i in range(se_sin):
        o[f"2-{i}-SE24"] = _order("SE")
    for i in range(cm):
        o[f"3-{i}-CM24"] = _order("CM")
    return o


# --- la línea base se aprende, no se fija a mano ---------------------------


def test_la_linea_base_reproduce_lo_medido_en_los_datos_reales():
    b = linkage_baseline(_orders())
    assert b["SE"]["orders"] == 306
    assert 0.63 == pytest.approx(b["SE"]["linkage_share"], abs=0.005)
    assert b["SE"]["informative"] is True
    assert b["CM"]["linkage_share"] == 0.0
    assert b["CM"]["informative"] is False, "en CM la ausencia no distingue nada"


def test_un_tipo_con_pocas_ordenes_no_establece_nada():
    """Con cuatro casos, «ninguna declara licitación» es ruido, no una norma."""
    b = linkage_baseline({f"4-{i}-AG24": _order("AG") for i in range(4)})
    assert b["AG"]["established"] is False
    assert classify_linkage(_order("AG"), b)["linkage_state"] == UNDETERMINED


# --- la clasificación -------------------------------------------------------


def test_una_orden_que_declara_su_licitacion_no_pregunta_nada():
    b = linkage_baseline(_orders())
    v = classify_linkage(_order("SE", tender="1-5-LP24"), b)
    assert v["linkage_state"] == LINKED and v["worth_asking"] is False


def test_una_se_sin_licitacion_es_la_pregunta_que_vale_la_pena():
    b = linkage_baseline(_orders())
    v = classify_linkage(_order("SE"), b)
    assert v["linkage_state"] == UNLINKED_INFORMATIVE
    assert v["worth_asking"] is True
    assert v["peer_linkage_share"] > 0.5
    # El significado formula una pregunta; no afirma que falte la licitación.
    assert "no una respuesta" in v["meaning"]


def test_convenio_marco_nunca_entra_a_la_bandeja():
    """Las 213 órdenes CM sin licitación son la forma normal del instrumento."""
    b = linkage_baseline(_orders())
    v = classify_linkage(_order("CM"), b)
    assert v["linkage_state"] == UNLINKED_EXPECTED
    assert v["worth_asking"] is False
    assert "por diseño" in v["meaning"]


def test_una_compra_chica_no_ocupa_la_revision():
    b = linkage_baseline(_orders())
    v = classify_linkage(_order("SE", total=200_000), b)
    assert v["linkage_state"] == BELOW_FLOOR and v["worth_asking"] is False


def test_un_monto_en_otra_moneda_no_se_compara_contra_un_piso_en_pesos():
    b = linkage_baseline(_orders())
    v = classify_linkage(_order("SE", total=4_220, currency="USD"), b)
    assert v["linkage_state"] == UNLINKED_INFORMATIVE
    assert "otra moneda" in v["note"]


# --- el convenio entre organismos públicos se aparta por un hecho ----------


def test_el_gasto_intraestado_sale_de_la_bandeja_por_la_marca_del_bulk():
    """No por el nombre del proveedor ni por el tramo de su RUT.

    Medido: la UFRO es 87.912.900-1 y la U. Adolfo Ibáñez, privada, es
    71.543.200-5. Un rango de RUT afirmaría una regla que los datos desmienten.
    """
    b = linkage_baseline(_orders())
    v = classify_linkage(_order("SE", total=12_333_333_333), b, intra_state_share=0.9)
    assert v["linkage_state"] == INTRA_STATE
    assert v["worth_asking"] is False
    assert "no se dedujo del nombre" in v["meaning"].lower()


def test_sin_la_marca_se_marca_de_mas_antes_que_inventar_el_dato():
    b = linkage_baseline(_orders())
    v = classify_linkage(_order("SE", total=12_333_333_333), b, intra_state_share=None)
    assert v["linkage_state"] == UNLINKED_INFORMATIVE


def test_una_relacion_mayormente_privada_no_se_aparta_por_un_pago_intraestado():
    b = linkage_baseline(_orders())
    v = classify_linkage(_order("SE"), b, intra_state_share=0.1)
    assert v["linkage_state"] == UNLINKED_INFORMATIVE


# --- el bloque publicado ----------------------------------------------------


def test_el_bloque_declara_si_la_marca_intraestado_llego_o_no():
    sin = review_orders(_orders())
    assert sin["intra_state_state"] == "NO_MEDIDO"
    assert "62%" in sin["intra_state_note"], "la limitación se declara con su medida"

    con = review_orders(_orders(), intra_state_by_order={"2-0-SE24": 0.9})
    assert con["intra_state_state"] == "MEDIDO"


def test_las_ordenes_se_publican_por_monto_y_acotadas():
    o = _orders(se_con=0, se_sin=0, cm=0)
    for i, monto in enumerate([10_000_000, 900_000_000, 50_000_000]):
        o[f"9-{i}-SE24"] = _order("SE", total=monto)
    o.update({f"1-{i}-SE24": _order("SE", tender=f"1-{i}-LP24") for i in range(30)})
    r = review_orders(o, max_rows=2)
    assert [x["purchase_order_code"] for x in r["orders"]] == ["9-1-SE24", "9-2-SE24"]
    assert r["orders_worth_asking"] == 3 and r["orders_published"] == 2


def test_el_guardrail_no_afirma_incumplimiento():
    r = review_orders(_orders())
    assert "no prueba que no la hubiera" in r["guardrail"]
    assert "no acredita irregularidad" in r["guardrail"]
