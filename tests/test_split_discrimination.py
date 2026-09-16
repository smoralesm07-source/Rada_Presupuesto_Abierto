"""Lo que separa un fraccionamiento de una cuota es la orden de compra.

`POTENTIAL_FRAGMENTATION` nombra en su propia hipótesis la explicación inocente
—pagos parciales de una misma compra— y hasta ahora no la descartaba. Estas
pruebas cuidan que la distinción se haga sobre lo observado y que declare su
cobertura: una clasificación apoyada en dos de siete documentos diría más del
registro que del gasto.
"""
import json

import pandas as pd
import pytest

from radar_presupuesto.procurement_context import build_procurement_context
from radar_presupuesto.split_discrimination import (
    MIXED,
    NO_ORDER_RECORDED,
    SEPARATE_ORDERS,
    UNDER_ONE_ORDER,
    UNDETERMINED,
    classify_split_shape,
)


# --- la distinción que hace triable el 31% de las señales -----------------


def test_una_orden_para_varios_documentos_son_cuotas():
    shape = classify_split_shape(documents=5, distinct_orders=1, rows_with_order=5)
    assert shape["split_shape"] == UNDER_ONE_ORDER
    # La explicación inocente no entra a la cola: ya está a la vista en los datos.
    assert shape["worth_triage"] is False


def test_una_orden_por_documento_son_compras_separadas():
    shape = classify_split_shape(documents=5, distinct_orders=5, rows_with_order=5)
    assert shape["split_shape"] == SEPARATE_ORDERS
    assert shape["worth_triage"] is True
    assert shape["orders_per_document"] == 1.0


def test_ordenes_repartidas_a_medias_quedan_mixtas():
    shape = classify_split_shape(documents=6, distinct_orders=3, rows_with_order=6)
    assert shape["split_shape"] == MIXED
    # Contiene compras separadas, así que se tria igual.
    assert shape["worth_triage"] is True


def test_un_documento_rezagado_no_convierte_compras_separadas_en_cuotas():
    """4 órdenes para 5 documentos sigue siendo la forma de compras separadas."""
    assert classify_split_shape(5, 4, 5)["split_shape"] == SEPARATE_ORDERS


# --- no clasificar sobre lo que no se observó ------------------------------


def test_sin_ninguna_orden_no_se_afirma_que_no_exista():
    shape = classify_split_shape(documents=4, distinct_orders=0, rows_with_order=0)
    assert shape["split_shape"] == NO_ORDER_RECORDED
    assert "no la registró" in shape["split_shape_meaning"]
    assert shape["worth_triage"] is False


def test_cobertura_insuficiente_se_declara_en_vez_de_adivinarse():
    """Dos de siete documentos con orden no alcanzan para declarar la forma."""
    shape = classify_split_shape(documents=7, distinct_orders=2, rows_with_order=2)
    assert shape["split_shape"] == UNDETERMINED
    assert "2 de 7" in shape["split_shape_why"]
    assert shape["worth_triage"] is False


def test_la_razon_se_calcula_sobre_los_documentos_que_traen_orden():
    """Con 8 de 10 documentos con orden y 8 órdenes distintas, son separadas.

    Dividir por los 10 daría 0,8 igual, pero el punto es que los 2 sin registrar
    no diluyen lo observado: la cobertura se publica aparte para que se vea.
    """
    shape = classify_split_shape(documents=10, distinct_orders=8, rows_with_order=8)
    assert shape["split_shape"] == SEPARATE_ORDERS
    assert shape["orders_per_document"] == 1.0
    assert shape["order_coverage"] == 0.8


def test_grupo_vacio_no_produce_una_forma():
    assert classify_split_shape(0, 0, 0)["split_shape"] == UNDETERMINED


# --- de punta a punta sobre el payload publicado ---------------------------


def _fact(org, prv, oc, amount, date, item="ITEM-1"):
    return {"organization_id": org, "provider_id": prv, "periodo": 2026,
            "item": item, "orden_compra": oc, "monto_devengado": amount,
            "fecha_documento": date, "is_aggregated": False}


def _findings(tmp_path, ids):
    f = tmp_path / "findings.json"
    f.write_text(json.dumps({"relation_findings": [
        {"finding_id": fid, "organization_id": org, "provider_id": prv, "periodo": 2026}
        for fid, org, prv in ids
    ]}), encoding="utf-8")
    return f


def _build(tmp_path, facts, ids):
    parquet = tmp_path / "facts.parquet"
    pd.DataFrame(facts).to_parquet(parquet, index=False)
    out = tmp_path / "procurement.json"
    coverage = build_procurement_context(
        parquet_glob=str(parquet),
        findings_json=str(_findings(tmp_path, ids)),
        output_json=str(out),
    )
    return coverage, json.loads(out.read_text(encoding="utf-8"))


def test_cuotas_y_compras_separadas_se_publican_distinto(tmp_path):
    """Dos hallazgos idénticos en monto y conteo, separados sólo por la orden."""
    facts = (
        # Cinco documentos de monto parejo bajo UNA orden: cuotas.
        [_fact("ORG-A", "PRV-CUOTAS", "1234-10-SE26", 10_000_000, f"2026-03-0{d}")
         for d in range(2, 7)]
        # Cinco documentos de monto parejo con CINCO órdenes: compras separadas.
        + [_fact("ORG-A", "PRV-SEPARADAS", f"1234-2{d}-SE26", 10_000_000, f"2026-03-0{d}")
           for d in range(2, 7)]
    )
    coverage, payload = _build(
        tmp_path, facts,
        [("HAL-CUOTAS", "ORG-A", "PRV-CUOTAS"), ("HAL-SEP", "ORG-A", "PRV-SEPARADAS")],
    )
    by_id = {r["finding_id"]: r for r in payload["findings"]}

    assert by_id["HAL-CUOTAS"]["split_shape"] == UNDER_ONE_ORDER
    assert by_id["HAL-CUOTAS"]["split_worth_triage"] is False
    assert by_id["HAL-SEP"]["split_shape"] == SEPARATE_ORDERS
    assert by_id["HAL-SEP"]["split_worth_triage"] is True
    # El mismo gasto, el mismo conteo: sólo uno entra a la cola.
    assert coverage["findings_with_weekly_clusters"] == 2
    assert coverage["findings_worth_triage"] == 1


def test_el_grupo_publica_su_monto_total_que_es_lo_que_lo_hace_material(tmp_path):
    facts = [_fact("ORG-B", "PRV-Y", f"999-{d}-SE26", 80_000_000, f"2026-05-1{d}")
             for d in range(1, 5)]
    _, payload = _build(tmp_path, facts, [("HAL-2", "ORG-B", "PRV-Y")])
    cluster = payload["findings"][0]["weekly_clusters"][0]

    assert cluster["documents"] == 4
    assert cluster["cluster_total"] == 320_000_000
    assert cluster["max_document_amount"] == 80_000_000
    assert len(cluster["order_examples"]) == 4


def test_gasto_disperso_no_forma_grupo_semanal(tmp_path):
    """Un pago al mes no es un fraccionamiento: no hay grupo que clasificar."""
    facts = [_fact("ORG-C", "PRV-Z", f"777-{m}-SE26", 5_000_000, f"2026-0{m}-15")
             for m in range(1, 6)]
    coverage, payload = _build(tmp_path, facts, [("HAL-3", "ORG-C", "PRV-Z")])
    row = payload["findings"][0]

    assert row["weekly_cluster_count"] == 0
    assert row["weekly_clusters"] == []
    assert row["split_shape"] == UNDETERMINED
    assert coverage["findings_with_weekly_clusters"] == 0


def test_un_grupo_menor_con_ordenes_separadas_no_queda_escondido(tmp_path):
    """El resumen toma la forma del grupo mayor, pero la cola mira todos.

    Si el grupo grande son cuotas y uno menor son compras separadas, esconder el
    segundo detrás del primero sería perder justamente lo que se busca.
    """
    facts = (
        [_fact("ORG-D", "PRV-W", "555-1-SE26", 100_000_000, f"2026-02-0{d}", "ITEM-GRANDE")
         for d in range(2, 6)]
        + [_fact("ORG-D", "PRV-W", f"555-9{d}-SE26", 1_000_000, f"2026-02-0{d}", "ITEM-CHICO")
           for d in range(2, 6)]
    )
    _, payload = _build(tmp_path, facts, [("HAL-4", "ORG-D", "PRV-W")])
    row = payload["findings"][0]

    assert row["weekly_cluster_count"] == 2
    assert row["split_shape"] == UNDER_ONE_ORDER, "el grupo mayor son cuotas"
    assert row["split_worth_triage"] is True, "el grupo menor son compras separadas"
    assert [c["split_shape"] for c in row["weekly_clusters"]] == [UNDER_ONE_ORDER, SEPARATE_ORDERS]


def test_el_payload_sube_de_esquema_y_declara_su_guardrail(tmp_path):
    findings = tmp_path / "findings.json"
    findings.write_text(json.dumps({"relation_findings": []}), encoding="utf-8")
    out = tmp_path / "p.json"
    build_procurement_context(parquet_glob=str(tmp_path / "no-*.parquet"),
                              findings_json=str(findings), output_json=str(out))
    payload = json.loads(out.read_text(encoding="utf-8"))

    assert payload["schema"] == "RIGP-PROCUREMENT-CONTEXT-v2"
    assert "no acredita" in payload["guardrail"].lower()
    assert "no acreditan fraccionamiento" in payload["split_guardrail"]
