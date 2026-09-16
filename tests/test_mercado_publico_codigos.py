"""Una referencia que nunca fue un código no es una orden que falte.

Medido sobre los 4.366 códigos distintos que publica `procurement_context.json`,
el 22,9% del campo `orden_compra` no son códigos de orden: `0`, `00000`, `C/T`,
`COMISION`, `CONTRATO DE ARRASTRE`. Consultarlos gasta cuota, pero el daño real
es que quedarían publicados como órdenes que Mercado Público no encontró, y eso
se lee como ausencia de la orden en vez de ausencia del dato.
"""
import pytest

from radar_presupuesto.mercado_publico_bridge import (
    CANONICAL,
    NOT_AN_ORDER_CODE,
    REPAIRED_DASH,
    REPAIRED_SEPARATOR,
    build_targets_with_discards,
    classify_order_code,
)


@pytest.mark.parametrize("code", ["1509-11-SE24", "01-10-CP18", "01057508-1173-CM19"])
def test_un_codigo_canonico_pasa_tal_cual(code):
    v = classify_order_code(code)
    assert v["shape"] == CANONICAL and v["code"] == code and v["consultable"]


def test_las_minusculas_no_hacen_invalido_un_codigo():
    assert classify_order_code("894778-124-cm17")["code"] == "894778-124-CM17"


# --- las dos reparaciones, ambas mecánicas y declaradas -------------------


@pytest.mark.parametrize("raw,fixed", [
    ("-3398-5-CM16", "3398-5-CM16"),
    ("3398-3-CM16-", "3398-3-CM16"),
])
def test_un_guion_sobrante_se_quita_y_se_declara(raw, fixed):
    v = classify_order_code(raw)
    assert v["code"] == fixed and v["shape"] == REPAIRED_DASH
    # Lo original se conserva: la reparación no borra lo que decía la fuente.
    assert v["raw"] == raw


def test_el_separador_faltante_se_repone_sin_inventar_digitos():
    v = classify_order_code("1079639-10CM20")
    assert v["code"] == "1079639-10-CM20" and v["shape"] == REPAIRED_SEPARATOR
    assert v["code"].replace("-", "") == "1079639" + "10" + "CM20"


# --- lo que no es un código se declara, no se consulta --------------------


@pytest.mark.parametrize("junk", [
    "0", "00000", "C/T", "COMISION", "CONTRATO DE ARRASTRE", "XXX", "TRASPASO",
    "-SE-", "-CM857-147", "", None,
])
def test_lo_que_no_es_un_codigo_no_se_consulta(junk):
    v = classify_order_code(junk)
    assert v["shape"] == NOT_AN_ORDER_CODE
    assert v["consultable"] is False
    assert v["code"] is None


def test_una_forma_desconocida_se_descarta_en_vez_de_adivinarse():
    """`1553-12358-SE` no trae año. Completarlo sería inventar el dato."""
    assert classify_order_code("1553-12358-SE")["consultable"] is False


# --- lo descartado se cuenta, no desaparece ------------------------------


def _procurement(*codes):
    return {"findings": [{"finding_id": "HAL-1", "organization_id": "ORG",
                          "provider_id": "PRV", "periodo": 2026,
                          "purchase_order_examples": list(codes)}]}


def test_las_referencias_descartadas_se_devuelven_para_poder_declararlas():
    targets, discarded = build_targets_with_discards(
        _procurement("1509-11-SE24", "COMISION"), {}, max_orders_per_finding=2
    )
    assert [t["purchase_order_code"] for t in targets] == ["1509-11-SE24"]
    assert len(discarded) == 1
    assert discarded[0]["reference"] == "COMISION"
    assert "nunca fue un código" in discarded[0]["note"]


def test_el_objetivo_conserva_de_qué_referencia_salió():
    targets, _ = build_targets_with_discards(
        _procurement("-3398-5-CM16"), {}, max_orders_per_finding=2
    )
    assert targets[0]["purchase_order_code"] == "3398-5-CM16"
    assert targets[0]["source_reference"] == "-3398-5-CM16"
    assert targets[0]["code_shape"] == REPAIRED_DASH


def test_un_hallazgo_sin_ningun_codigo_valido_no_aporta_objetivos():
    targets, discarded = build_targets_with_discards(
        _procurement("0", "TRASPASO"), {}, max_orders_per_finding=2
    )
    assert targets == []
    assert len(discarded) == 2
