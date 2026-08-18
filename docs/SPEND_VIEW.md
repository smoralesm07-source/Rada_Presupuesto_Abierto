# Módulo de ejecución y pagos del Estado (v0.4)

Vista analítica del gasto del Estado a terceros: ritmo de ejecución, concentración
territorial, dependencia comprador/proveedor, proveedores atípicos, entrantes nuevos
con adjudicación material y patrones de calendario y documentación.

- **Constructor:** `src/radar_presupuesto/spend_view.py`
- **Artefacto:** `docs/data/spend_view_v1.json` (esquema `PRESUPUESTO_SPEND_VIEW_V1`)
- **Página:** `docs/ejecucion.html`
- **Umbrales:** `config/spend_view.yaml`
- **Demostración:** `scripts/build_demo_spend_view.py` → `docs/data/spend_view_demo_v1.json`

```bash
# tras una corrida del pipeline (o directamente sobre los parquet ya normalizados)
radar-pa spend-view                       # paquete instalado
PYTHONPATH=src python -m radar_presupuesto.spend_view   # desde el repositorio
```

El pipeline (`radar_presupuesto.pipeline`) ya construye esta vista al final de cada
corrida, de modo que la página se actualiza junto con el resto del radar.

## Qué responde el módulo

| Pregunta operativa | Bloque del artefacto | Lectura |
|---|---|---|
| ¿Cómo se ejecuta el gasto durante el año? | `execution.monthly`, `execution.by_year` | Ritmo mensual, curva acumulada, peso de diciembre y Q4, razón pagado/devengado |
| ¿Dónde se concentra territorialmente? | `territory.regions`, `territory.concentration`, `territory.macrozones` | Franja norte→sur, Gini, HHI, Lorenz, participación del líder |
| ¿Qué comprador depende de un proveedor? | `organizations` | HHI de proveedores, participación del dominante, brecha de OC |
| ¿Qué proveedores muestran patrones concurrentes? | `providers.anomalous` | Score 0–100 con contribuciones nombradas y lectura alternativa |
| ¿Quién entra nuevo y se lleva montos importantes? | `new_providers` | Cohorte del último año, corte por percentil, comprador principal |
| ¿Qué patrones transversales existen? | `patterns` | Fraccionamiento, duplicados candidatos, cierre de año, montos redondos, velocidad de pago |
| ¿Qué mirar primero? | `headline_indicators`, `alerts` | Indicadores con tono y alertas redactadas con su matiz |
| ¿Cómo se comporta un proveedor mes a mes? | `explorer.providers` | Métricas crudas + estacionalidad mensual y trayectoria anual por proveedor |
| ¿Dónde se acumula el gasto en el calendario? | `heatmaps` | Matrices organismo×mes y región×mes |
| ¿Dónde está mi caso dentro de la población? | `distributions`, `pareto` | Histograma de días de pago, tramos de monto y curva de Pareto |
| ¿Qué patrones aparecen juntos? | `reason_cooccurrence` | Matriz de concurrencia entre contribuciones del score |

## Semántica de "ejecución"

La fuente de pagos de Presupuesto Abierto **no publica el presupuesto vigente por
organismo**. Por eso el módulo no calcula porcentaje de avance sobre la Ley de
Presupuestos: reporta el flujo efectivamente devengado y pagado, su ritmo intra-anual
y su composición. Cualquier lectura de "ejecución presupuestaria" debe entenderse en
ese sentido acotado, declarado en `methodology.budget_appropriation_note`.

## Score de atipicidad de proveedor

Suma acotada a 100 de contribuciones explicables. Cada una aporta su peso máximo,
su métrica de respaldo y la lectura alternativa que permite descartarla.

| Código | Peso | Se activa cuando |
|---|---:|---|
| `CONCENTRA_GASTO_DEL_COMPRADOR` | 16 | Supera `concentration.buyer_share_watch` del gasto a proveedores de un organismo |
| `NUEVO_CON_MONTO_MATERIAL` | 16 | Primera aparición en el último año y monto sobre el corte del cohorte de entrantes |
| `DEPENDENCIA_DE_UN_COMPRADOR` | 12 | Su principal comprador concentra ≥ `concentration.client_dependency_share` de sus pagos |
| `CONCENTRACION_EN_DICIEMBRE` | 10 | Diciembre pesa ≥ `calendar.december_share_watch` de su gasto, con al menos 3 pagos |
| `SIN_ORDEN_DE_COMPRA` | 10 | ≥ `documentation.missing_purchase_order_share` de sus pagos sin OC registrada |
| `SENAL_FRACCIONAMIENTO_O_DUPLICADO` | 10 | La cola priorizada registra fraccionamiento o duplicado candidato |
| `MONTOS_REDONDOS` | 8 | ≥50% de sus pagos son múltiplo exacto del monto de referencia, con ≥5 pagos |
| `PAGO_ACELERADO` | 8 | Mediana ≤ `payment_speed.fast_payment_days` mientras el país está sobre el piso configurado |
| `MONTO_ATIPICO` | 6 | Tiene señales `AMOUNT_OUTLIER` en la cola |
| `ENLACE_CGR` | 4 | Existe coincidencia candidata de entidad con hallazgos CGR |

Tiers: **A1** ≥ 55, **A2** ≥ 30, **A3** ≥ 10 (una sola contribución material). Un proveedor sin contribuciones no entra
a la lista. El tier A1 exige concurrencia de patrones: es prioridad de revisión, no
imputación ni estimación de riesgo LA/FT.

## Resolución territorial

`src/radar_presupuesto/regions.py` normaliza el campo `REGION` de la fuente aceptando
código numérico, código con cero a la izquierda, numeral romano, sigla y nombre con
variantes ortográficas. Si falta, se usa el prefijo de `CODIGO_UBICACION_GEOGRAFICA`.
Lo irresoluble queda como `UNKNOWN` ("Sin región informada") y se reporta como
categoría propia: **ausencia no es cero**, y toda lectura territorial se hace sobre el
devengado con región resuelta.

La unidad geográfica de la fuente **no** se promueve a comuna canónica; esa validación
sigue pendiente contra Context Hub (ver `territorial_export.py`).

## Guardarraíles

- `GASTO_PUBLICO_NO_ES_RIESGO_POR_SI_MISMO`
- `AUSENCIA_NO_ES_CERO`
- `SCORE_ES_PRIORIDAD_ANALITICA_NO_IMPUTACION`
- `NUEVO_EN_LA_SERIE_NO_ES_EMPRESA_NUEVA`
- `SIN_ORDEN_DE_COMPRA_NO_IMPLICA_ILEGALIDAD`
- `ENLACE_CGR_ES_COINCIDENCIA_CANDIDATA_DE_ENTIDAD`
- `EJECUCION_ES_FLUJO_OBSERVADO_NO_AVANCE_SOBRE_LEY_DE_PRESUPUESTOS`
- `REGION_DE_LA_FUENTE_NO_ES_COMUNA_CANONICA`

## Relación con el resto del radar

El módulo **no crea señales nuevas**: reutiliza `data/signals/prioritized_signals.parquet`
para que la vista de gasto y la cola de investigación no puedan divergir. Los enlaces CGR
provienen de `cgr_correlation.py` y conservan su condición de coincidencia candidata.

## Módulo web

`docs/ejecucion.html` es un workbench de una sola página con navegación por vistas:

| Vista | Herramientas |
|---|---|
| Panorama | Indicadores con tono, alertas, forma del año, ranking regional, Pareto |
| Ejecución | Barras mensuales + curva acumulada (año y métrica seleccionables), tabla por período, histograma de días de pago, heatmap organismo×mes |
| Territorio | Mapa coroplético de Chile con 9 métricas intercambiables, escala, tooltip, ranking sincronizado, ficha regional, Lorenz, macrozonas, heatmap región×mes |
| Concentración | Dispersión de organismos (proveedores vs HHI, tamaño = devengado), Pareto, clasificadores, tabla ordenable |
| Proveedores | Dispersión con ejes intercambiables, filtros por tier/contribución/región, tabla paginada con estacionalidad, ficha lateral |
| Entrantes nuevos | Cohorte del último año, ranking de montos, tabla con ficha |
| Simulador | Sliders de umbrales y pesos que recalculan el score en el navegador, efecto sobre los tiers, ranking con cambio de posición, matriz de concurrencia |
| Método | Catálogo de indicadores, umbrales de la corrida, modelo del score, cobertura, guardarraíles |

La página carga `data/spend_view_v1.json`; si no existe cae a `data/spend_view_demo_v1.json`. Con `window.__SPEND_VIEW__` incrustado funciona sin servidor:

```bash
PYTHONPATH=src python scripts/build_standalone_page.py \
    --data docs/data/spend_view_v1.json --output dist/ejecucion.html
```

El simulador reimplementa el scoring en JavaScript a partir de las métricas crudas del artefacto. Sirve para probar la robustez de una hipótesis: si un caso sólo existe con un umbral exacto, es frágil. Los scores simulados no son comparables con la corrida oficial y la página lo advierte.

## Modo demostración

`docs/ejecucion.html` carga `data/spend_view_v1.json` y, si aún no existe, cae a
`data/spend_view_demo_v1.json`, mostrando un banner permanente de datos sintéticos.
La demo es determinista (semilla fija) y sirve para revisar diseño y validar el motor
sin descargar los bulk nacionales:

```bash
PYTHONPATH=src python scripts/build_demo_spend_view.py
```
