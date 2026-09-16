"""Qué distingue un fraccionamiento de una cuota.

`POTENTIAL_FRAGMENTATION` es la señal más frecuente del radar —171.968 casos,
el 31% del total— y su propia hipótesis nombra la explicación inocente: «puede
corresponder a facturación periódica o pagos parciales». Mientras no se separe
una cosa de la otra, el 31% es una masa que el analista no puede triar, y el
volumen mismo vuelve inútil la señal.

La orden de compra es lo que las separa, y ya está en los datos. Cinco
documentos de monto parejo a un mismo proveedor en una semana bajo **una sola
orden** son las cuotas de una compra: exactamente lo que la hipótesis inocente
describe. Los mismos cinco documentos con **cinco órdenes distintas** son cinco
compras separadas, que es la forma que deja una compra partida. No prueba que
se haya partido para evitar un umbral —eso exige la modalidad, que vive en
Mercado Público— pero ordena la cola por dónde vale la pena preguntarlo.

El campo `orden_compra` cubre el 36,7% de las filas del bulk. Donde no alcanza,
la forma se declara `NO_DETERMINADO` y se publica la cobertura sobre la que
descansa la clasificación: una clasificación apoyada en dos de siete documentos
no es una clasificación, y decirlo es lo que impide leerla como un hallazgo.
"""
from __future__ import annotations

SEPARATE_ORDERS = "ORDENES_SEPARADAS"
UNDER_ONE_ORDER = "PAGOS_BAJO_UNA_ORDEN"
NO_ORDER_RECORDED = "SIN_ORDEN_REGISTRADA"
MIXED = "MIXTO"
UNDETERMINED = "NO_DETERMINADO"

# Fracción mínima de documentos del grupo que debe traer orden de compra para
# que la forma se declare. Bajo este piso la clasificación descansaría sobre una
# minoría de los documentos y diría más del registro que del gasto.
ORDER_COVERAGE_FLOOR = 0.6

# Órdenes distintas por documento observado a partir de la cual el grupo se lee
# como compras separadas. No es 1.0 porque un documento rezagado bajo una orden
# anterior no convierte el grupo en cuotas.
SEPARATE_ORDERS_RATIO = 0.8

SHAPE_MEANING = {
    SEPARATE_ORDERS: (
        "Documentos de monto parejo en una misma semana, cada uno con su propia orden "
        "de compra: compras separadas, no cuotas de una compra. Es la forma que deja un "
        "fraccionamiento, y también la de un organismo que compra lo mismo seguido."
    ),
    UNDER_ONE_ORDER: (
        "Los documentos comparten una sola orden de compra: son pagos de una misma "
        "compra. Es la explicación inocente que la señal de fragmentación ya nombraba."
    ),
    NO_ORDER_RECORDED: (
        "Ningún documento del grupo trae orden de compra. No dice que no exista: dice "
        "que Presupuesto Abierto no la registró, y que la pregunta se responde en "
        "Mercado Público."
    ),
    MIXED: (
        "Varias órdenes, pero menos que documentos: parte del grupo son cuotas y parte "
        "compras distintas. Hay que mirar el detalle antes de leerlo en un sentido u otro."
    ),
    UNDETERMINED: (
        "La cobertura de orden de compra en el grupo no alcanza para distinguir cuotas "
        "de compras separadas."
    ),
}

# Formas que merecen la cola de revisión antes que las demás. `MIXTO` entra
# porque contiene compras separadas; `PAGOS_BAJO_UNA_ORDEN` sale porque la
# explicación inocente ya está a la vista en los propios datos.
SHAPES_WORTH_TRIAGE = (SEPARATE_ORDERS, MIXED)

GUARDRAIL = (
    "La forma del grupo describe cómo se registraron las compras, no si fueron "
    "irregulares. Órdenes separadas no acreditan fraccionamiento: la modalidad que lo "
    "haría exigible se verifica en Mercado Público y en el expediente del procedimiento."
)


def classify_split_shape(
    documents: int,
    distinct_orders: int,
    rows_with_order: int,
    *,
    coverage_floor: float = ORDER_COVERAGE_FLOOR,
    separate_ratio: float = SEPARATE_ORDERS_RATIO,
) -> dict:
    """Clasifica un grupo semanal por cómo se repartieron sus órdenes de compra.

    La razón se calcula contra los documentos **que traen orden**, no contra
    todos: clasificar sobre lo observado y declarar aparte cuánto se observó es
    distinto de diluir la señal con lo que falta.
    """
    documents = int(documents or 0)
    distinct_orders = int(distinct_orders or 0)
    rows_with_order = int(rows_with_order or 0)

    if documents <= 0:
        return _shape(UNDETERMINED, 0.0, 0.0, "el grupo no tiene documentos")

    coverage = rows_with_order / documents

    if rows_with_order == 0:
        return _shape(NO_ORDER_RECORDED, 0.0, 0.0,
                      "ningún documento del grupo trae orden de compra")
    if coverage < coverage_floor:
        return _shape(
            UNDETERMINED, coverage, 0.0,
            f"sólo {rows_with_order} de {documents} documentos traen orden de compra, "
            f"bajo el piso de {coverage_floor:.0%} necesario para declarar la forma",
        )

    ratio = distinct_orders / rows_with_order if rows_with_order else 0.0

    if distinct_orders <= 1:
        return _shape(UNDER_ONE_ORDER, coverage, ratio,
                      "los documentos con orden comparten una sola")
    if ratio >= separate_ratio:
        return _shape(SEPARATE_ORDERS, coverage, ratio,
                      f"{distinct_orders} órdenes distintas para {rows_with_order} documentos con orden")
    return _shape(MIXED, coverage, ratio,
                  f"{distinct_orders} órdenes para {rows_with_order} documentos con orden")


def _shape(shape: str, coverage: float, ratio: float, why: str) -> dict:
    return {
        "split_shape": shape,
        "split_shape_meaning": SHAPE_MEANING[shape],
        "split_shape_why": why,
        "order_coverage": round(coverage, 6),
        "orders_per_document": round(ratio, 6),
        "worth_triage": shape in SHAPES_WORTH_TRIAGE,
    }


def cluster_sql(
    min_count: int = 3,
    max_cv: float = 0.15,
    max_clusters: int = 3,
    item_expr: str = "coalesce(f.item,'')",
) -> str:
    """Los grupos semanales de cada hallazgo, con su reparto de órdenes.

    Usa la misma regla que `POTENTIAL_FRAGMENTATION` en `analytics.py` —mismo
    mínimo de documentos, mismo coeficiente de variación— a propósito: si el
    corte fuera otro, esta capa describiría una población distinta de la que
    pretende explicar.

    `item_expr` existe porque una vista de hechos sin la columna `item` no debe
    matar la capa entera: quien llama decide si agrupa por ítem o si lo declara
    vacío, y el resto del cálculo sigue en pie.
    """
    return f"""
        WITH weekly AS (
          SELECT
            t.finding_id,
            {item_expr} AS item,
            date_trunc('week', try_cast(f.fecha_documento AS DATE)) AS wk,
            count(*) AS documents,
            sum(cast(f.monto_devengado AS DOUBLE)) AS cluster_total,
            max(cast(f.monto_devengado AS DOUBLE)) AS max_document_amount,
            avg(cast(f.monto_devengado AS DOUBLE)) AS avg_amount,
            stddev_pop(cast(f.monto_devengado AS DOUBLE)) AS sd_amount,
            sum(CASE WHEN coalesce(trim(f.orden_compra),'')<>'' THEN 1 ELSE 0 END) AS rows_with_order,
            count(DISTINCT nullif(trim(f.orden_compra),'')) AS distinct_orders,
            list_slice(
              list_sort(list_distinct(list(nullif(trim(f.orden_compra),'')))), 1, 6
            ) AS order_examples
          FROM targets t
          JOIN facts f
            ON f.organization_id=t.organization_id
           AND f.provider_id=t.provider_id
           AND f.periodo=t.periodo
          WHERE coalesce(f.is_aggregated,FALSE)=FALSE
            AND try_cast(f.fecha_documento AS DATE) IS NOT NULL
            AND try_cast(f.monto_devengado AS DOUBLE)>0
          GROUP BY 1,2,3
        ), qualifying AS (
          SELECT *, CASE WHEN avg_amount=0 THEN NULL ELSE sd_amount/avg_amount END AS cv
          FROM weekly
          WHERE documents >= {int(min_count)}
            AND avg_amount > 0
            AND sd_amount/avg_amount <= {float(max_cv)}
        ), ranked AS (
          SELECT *, row_number() OVER (
                      PARTITION BY finding_id ORDER BY cluster_total DESC, documents DESC
                    ) AS rn,
                 count(*) OVER (PARTITION BY finding_id) AS cluster_count
          FROM qualifying
        )
        SELECT finding_id, item, cast(wk AS VARCHAR) AS week_start, documents,
               cluster_total, max_document_amount, cv,
               rows_with_order, distinct_orders, order_examples,
               cluster_count, rn
        FROM ranked
        WHERE rn <= {int(max_clusters)}
        ORDER BY finding_id, rn
    """
