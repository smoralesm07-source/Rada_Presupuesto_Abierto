"""La marca de monto se había vuelto un detector de transferencias.

Medido sobre las 353 relaciones que publicó la corrida #42, el decil superior de
monto de la bandeja tenía 25 transferencias y 5 adquisiciones. No porque las
transferencias fueran más anómalas, sino porque son más grandes: un subsidio al
transporte son decenas de miles de millones y una compra de insumos clínicos son
cientos de millones. Ordenadas juntas, las compras no aparecen nunca.

Con el corte calculado dentro de cada naturaleza, esa misma cola pasa a 24
adquisiciones y 11 transferencias.
"""
import pytest

from radar_presupuesto.attention_level import calibrate, level_for
from radar_presupuesto.spend_nature import (
    ADQUISICION,
    NO_DECLARADA,
    TRANSFERENCIA,
    classify,
    nature_of,
)


def _rel(subtitulo, amount, **kw):
    row = {"signal_family_count": 1, "signal_type_count": 1, "cgr_match_count": 0,
           "max_priority_score": 60, "max_transaction_amount": amount}
    row.update(kw)
    if subtitulo is not None:
        row["peer_context"] = {"subtitulo": subtitulo}
    return row


# --- el clasificador --------------------------------------------------------


@pytest.mark.parametrize("subtitulo", ["22", "29", "31"])
def test_solo_las_adquisiciones_esperan_un_procedimiento_de_contratacion(subtitulo):
    out = classify(subtitulo)
    assert out["nature"] == ADQUISICION
    assert out["procurement_expected"] is True
    assert "orden de compra" in out["note"]


@pytest.mark.parametrize("subtitulo", ["24", "33"])
def test_las_transferencias_no_esperan_orden_de_compra(subtitulo):
    out = classify(subtitulo)
    assert out["nature"] == TRANSFERENCIA
    assert out["procurement_expected"] is False
    assert "ley de presupuestos" in out["note"]


def test_un_subtitulo_desconocido_se_declara_en_vez_de_forzarse_a_un_grupo():
    """Meterlo en «otro gasto corriente» lo escondería; decirlo lo deja a la vista."""
    out = classify("99")
    assert out["nature"] == NO_DECLARADA
    assert out["procurement_expected"] is False
    assert "no está en el clasificador" in out["note"]


def test_sin_subtitulo_la_naturaleza_no_se_inventa():
    for vacio in ("", None, "   "):
        assert classify(vacio)["nature"] == NO_DECLARADA
    assert nature_of({})["nature"] == NO_DECLARADA


def test_el_subtitulo_se_lee_del_contexto_de_pares():
    assert nature_of(_rel("24", 1))["nature"] == TRANSFERENCIA
    # Tolera el ruido de la fuente: espacios y un solo dígito.
    assert classify(" 22 ")["nature"] == ADQUISICION
    assert classify("22-03")["subtitulo"] == "22"


# --- el defecto que esto corrige -------------------------------------------


def _bandeja_mixta():
    """Transferencias grandes y adquisiciones chicas, como la bandeja real.

    Las 30 transferencias van de 10.000 a 300.000 millones; las 30 adquisiciones,
    de 10 a 300 millones. Un corte único sobre las 60 deja la cola entera del
    lado de las transferencias.
    """
    transferencias = [_rel("24", 10_000_000_000 * (i + 1)) for i in range(30)]
    adquisiciones = [_rel("22", 10_000_000 * (i + 1)) for i in range(30)]
    return transferencias + adquisiciones


def test_el_corte_unico_convertia_la_marca_de_monto_en_un_detector_de_transferencias():
    bandeja = _bandeja_mixta()
    plano = {"max_transaction_amount": sorted(
        r["max_transaction_amount"] for r in bandeja)[int(60 * 0.90)]}
    en_la_cola = [r for r in bandeja
                  if r["max_transaction_amount"] >= plano["max_transaction_amount"]]
    assert all(nature_of(r)["nature"] == TRANSFERENCIA for r in en_la_cola), (
        "con un corte único ninguna adquisición alcanza la cola")


def test_con_el_corte_por_naturaleza_las_adquisiciones_vuelven_a_la_cola():
    bandeja = _bandeja_mixta()
    cal = calibrate(bandeja)
    marcadas = [r for r in bandeja
                if "MONTO_EN_LA_COLA" in level_for(r, cal)["attention_marks"]]
    naturalezas = {nature_of(r)["nature"] for r in marcadas}
    assert ADQUISICION in naturalezas and TRANSFERENCIA in naturalezas, naturalezas
    # Cada naturaleza aporta su propia cola, no la bandeja entera.
    assert sum(1 for r in marcadas if nature_of(r)["nature"] == ADQUISICION) == 3
    assert sum(1 for r in marcadas if nature_of(r)["nature"] == TRANSFERENCIA) == 3


def test_cada_naturaleza_declara_su_corte_y_cuantas_filas_lo_sostienen():
    cal = calibrate(_bandeja_mixta())
    tails = cal["amount_tail_by_nature"]
    assert tails[ADQUISICION]["rows"] == 30 and tails[TRANSFERENCIA]["rows"] == 30
    assert tails[ADQUISICION]["cut"] < tails[TRANSFERENCIA]["cut"]
    assert all(t["state"] == "MEDIDA" for t in tails.values())


# --- lo que no se puede medir se declara -----------------------------------


def test_una_naturaleza_con_pocas_filas_no_recibe_la_marca_de_monto():
    """Con cuatro observaciones no hay decil superior que valga."""
    bandeja = ([_rel("22", 10_000_000 * (i + 1)) for i in range(40)]
               + [_rel("23", 500_000_000_000) for _ in range(4)])
    cal = calibrate(bandeja)
    prestacion = cal["amount_tail_by_nature"]["PRESTACION_SOCIAL"]
    assert prestacion["state"] == "NO_MEDIBLE_POR_TAMANO"
    assert prestacion["cut"] is None
    assert "no tiene cola propia" in prestacion["why"]
    enorme = bandeja[-1]
    assert "MONTO_EN_LA_COLA" not in level_for(enorme, cal)["attention_marks"], (
        "el monto más alto de la bandeja no marca si su naturaleza no se puede medir")


def test_la_naturaleza_viaja_con_la_fila_para_que_el_analista_la_vea():
    cal = calibrate(_bandeja_mixta())
    veredicto = level_for(_rel("24", 300_000_000_000), cal)
    assert veredicto["spend_nature"]["nature"] == TRANSFERENCIA
    assert veredicto["spend_nature"]["procurement_expected"] is False
    assert veredicto["spend_nature"]["note"]


def test_la_etiqueta_de_la_marca_dice_contra_que_se_compara():
    from radar_presupuesto.attention_level import assign
    cal = assign(_bandeja_mixta())
    assert "naturaleza de gasto" in cal["marks"]["MONTO_EN_LA_COLA"]["label"]
    assert "naturaleza de gasto" in cal["method"]


def test_una_bandeja_calibrada_con_el_corte_plano_anterior_sigue_funcionando():
    """Compatibilidad hacia atrás: `cuts` plano no rompe `marks_for`."""
    from radar_presupuesto.attention_level import marks_for
    assert "MONTO_EN_LA_COLA" in marks_for(
        _rel("22", 1_000), {"max_transaction_amount": 500})
    assert "MONTO_EN_LA_COLA" not in marks_for(
        _rel("22", 100), {"max_transaction_amount": 500})
