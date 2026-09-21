"""Una marca que aparece en casi todo dejó de ser una marca.

La regla anterior decidía el nivel con `familias>=2 AND score>=70`. Medido sobre
las 390 relaciones publicadas, esa sola condición disparaba en el **95,1%**: la
selección ya había elegido las de score alto —de 53 a 92, mediana 87— así que
volver a cortarlas en 70 no separaba a nadie. 372 de 390 decían «atención
inmediata», y el analista se quedaba sin el único orden que el sistema le daba.
"""
import pytest

from radar_presupuesto.attention_level import (
    FOLLOW,
    IMMEDIATE,
    MIN_ROWS_FOR_RARITY,
    PRIORITY,
    RARITY_CEILING,
    assign,
    calibrate,
    level_for,
)


def _rel(families=2, types=2, cgr=0, score=87, amount=100_000_000):
    return {"signal_family_count": families, "signal_type_count": types,
            "cgr_match_count": cgr, "max_priority_score": score,
            "max_transaction_amount": amount}


def _tray(n=100, **kw):
    """Una bandeja del tamaño de la real, toda igual salvo lo que se indique."""
    return [_rel(**kw) for _ in range(n)]


# --- el defecto que esto corrige -------------------------------------------


def test_una_marca_presente_en_casi_todos_deja_de_contar():
    """Es la lección entera: 95,1% no es una prioridad, es una etiqueta."""
    tray = _tray(100, types=3)          # todos con tres tipos de señal
    cal = calibrate(tray)
    assert cal["marks"]["TIPOS_MULTIPLES"]["share"] == 1.0
    assert cal["marks"]["TIPOS_MULTIPLES"]["counts"] is False
    assert "deja de distinguir" in cal["marks"]["TIPOS_MULTIPLES"]["why"]


def test_la_misma_marca_cuenta_cuando_es_rara():
    tray = _tray(95) + [_rel(types=3) for _ in range(5)]
    cal = calibrate(tray)
    assert cal["marks"]["TIPOS_MULTIPLES"]["share"] == 0.05
    assert cal["marks"]["TIPOS_MULTIPLES"]["counts"] is True


def test_el_techo_de_rareza_es_el_que_decide():
    justo_bajo = _tray(100 - 33) + [_rel(cgr=1) for _ in range(33)]
    assert calibrate(justo_bajo)["marks"]["EVIDENCIA_EXTERNA"]["share"] == pytest.approx(0.33)
    assert calibrate(justo_bajo)["marks"]["EVIDENCIA_EXTERNA"]["counts"] is True
    justo_sobre = _tray(100 - 34) + [_rel(cgr=1) for _ in range(34)]
    assert calibrate(justo_sobre)["marks"]["EVIDENCIA_EXTERNA"]["counts"] is False


# --- los niveles ------------------------------------------------------------


def test_dos_marcas_raras_convergen_en_atencion_inmediata():
    tray = _tray(96) + [_rel(families=3, types=3, cgr=1) for _ in range(4)]
    cal = calibrate(tray)
    v = level_for(_rel(families=3, types=3, cgr=1), cal)
    assert v["attention_level"] == IMMEDIATE
    assert len(v["attention_marks"]) >= 2
    assert v["attention_why"]


def test_una_sola_marca_rara_es_revision_prioritaria():
    tray = _tray(96) + [_rel(cgr=1) for _ in range(4)]
    v = level_for(_rel(cgr=1), calibrate(tray))
    assert v["attention_level"] == PRIORITY
    assert v["attention_marks"] == ["EVIDENCIA_EXTERNA"]


def test_sin_marcas_es_seguimiento_y_no_descarte():
    v = level_for(_rel(), calibrate(_tray(100)))
    assert v["attention_level"] == FOLLOW
    assert "Ninguna marca" in v["attention_why"]
    assert "vuelve a mirarse" in v["attention_meaning"], "seguimiento no es descarte"


# --- bandeja demasiado chica para medir rareza -----------------------------


def test_en_una_bandeja_minuscula_la_rareza_no_se_puede_medir():
    """Con una sola relación toda marca aparece en el 100%.

    Aplicar ahí el techo de rareza mandaría a seguimiento un caso con tres tipos
    de señal y cruce CGR. Bajo el mínimo, las marcas estructurales cuentan por sí
    mismas: son propiedades de la relación, no de la población.
    """
    tray = [_rel(families=3, types=3, cgr=1)]
    cal = calibrate(tray)
    assert cal["rarity_state"] == "NO_MEDIBLE_POR_TAMANO"
    assert level_for(tray[0], cal)["attention_level"] == IMMEDIATE


def test_bajo_el_minimo_las_marcas_de_cola_no_se_aplican():
    """Estar en el decil superior de una bandeja de tres no significa nada."""
    cal = calibrate([_rel(amount=10**12), _rel(), _rel()])
    assert "MONTO_EN_LA_COLA" not in cal["counting_marks"]
    assert "PRIORIDAD_EN_LA_COLA" not in cal["counting_marks"]


def test_el_minimo_declarado_es_el_que_se_usa():
    assert calibrate(_tray(MIN_ROWS_FOR_RARITY))["rarity_state"] == "MEDIDA"
    assert calibrate(_tray(MIN_ROWS_FOR_RARITY - 1))["rarity_state"] == "NO_MEDIBLE_POR_TAMANO"


def test_una_bandeja_vacia_no_rompe_la_calibracion():
    cal = calibrate([])
    assert cal["published_rows"] == 0 and cal["counting_marks"] == []


# --- el bloque publicado ----------------------------------------------------


def test_assign_reparte_la_bandeja_en_vez_de_etiquetarla_entera():
    tray = (_tray(60) + [_rel(cgr=1) for _ in range(20)]
            + [_rel(families=3, types=3, cgr=1) for _ in range(10)]
            + [_rel(types=3) for _ in range(10)])
    cal = assign(tray)
    niveles = cal["levels"]
    assert sum(niveles.values()) == 100
    # Lo que se corrige: que el nivel superior no se coma la bandeja.
    assert niveles[IMMEDIATE] <= 25, niveles
    assert niveles[FOLLOW] >= 40, niveles
    assert all(r.get("attention_level") for r in tray)


def test_el_guardrail_dice_que_seguimiento_no_es_descarte():
    cal = assign(_tray(100))
    assert "no está descartada" in cal["guardrail"]
    assert "ni acredita irregularidad" in cal["guardrail"]


def test_el_metodo_declara_que_se_recalibra_en_cada_corrida():
    assert "cada corrida" in assign(_tray(100))["method"]
