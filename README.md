# Radar Presupuesto Abierto

Radar autónomo para explotar datos públicos de **Presupuesto Abierto (DIPRES)** con enfoque de inteligencia financiera, integridad del gasto y detección de patrones anómalos.

**Estado actual: v0.4.** El sistema procesa bulk oficiales, controla identidad y calidad, detecta señales, las prioriza para investigación, contrasta entidades con evidencia del repositorio Radar CGR y publica el **módulo de ejecución y pagos del Estado** (`docs/ejecucion.html`).

## Objetivo

Responder con evidencia trazable:

1. **Qué está pasando** en el gasto público.
2. **Por qué el patrón es inusual** frente a su historia o pares.
3. **Qué transacciones soportan la señal**.
4. **Qué evidencia externa puede reforzar o contextualizar la hipótesis**.
5. **Qué investigación OSINT conviene ejecutar después**.

El radar no califica delitos ni declara sospecha AML por sí solo. Genera señales priorizables y reproducibles.

## Principio de diseño

`SOURCE_SNAPSHOT -> SOURCE_FACT -> NORMALIZED_FACT -> DERIVED_FEATURE -> RISK_SIGNAL -> INVESTIGATION_PRIORITY -> EVIDENCE`

## Identidad

La v0.3 distingue `transaction_id` (fila física única), `transaction_fingerprint` (huella documental/económica potencialmente repetible), `recipient_id` y `provider_id`. El RUT se usa solo tras validar su dígito verificador y un SHA1 nunca se transforma en RUT.

Esto permite que una repetición documental sea analizada por `EXACT_DUPLICATE_CANDIDATE` sin generar una colisión en la clave primaria del radar.

## Señales operativas

- `AMOUNT_OUTLIER`
- `POTENTIAL_FRAGMENTATION`
- `YEAR_END_SPIKE`
- `EXACT_DUPLICATE_CANDIDATE`
- `PROVIDER_CONCENTRATION`
- `PAYMENT_DELAY_OUTLIER`
- `NEW_TO_SERIES_HIGH_SPEND`

Las señales no constituyen hallazgos de ilegalidad.

## Prioridad investigativa

`data/signals/prioritized_signals.parquet` y `docs/data/investigation_queue.json` ordenan las señales mediante un score 0–100 explicable que combina severidad, tipo de patrón, coocurrencia, evidencia candidata CGR, accionabilidad documental y materialidad.

- `P1`: 70–100
- `P2`: 50–69
- `P3`: < 50

El score es **prioridad de revisión**, no probabilidad de delito ni de LA/FT.

## Módulo de ejecución y pagos del Estado (v0.4)

Vista analítica del gasto a terceros, publicada en `docs/ejecucion.html` a partir de `docs/data/spend_view_v1.json`:

- **Ritmo de ejecución**: serie mensual, curva acumulada, peso de diciembre y Q4, razón pagado/devengado.
- **Concentración territorial**: franja nacional norte→sur, Gini, HHI, curva de Lorenz y métricas normalizadas por 100k pagos.
- **Dependencia comprador/proveedor**: HHI de proveedores por organismo y participación del proveedor dominante.
- **Proveedores atípicos**: score 0–100 por suma de contribuciones nombradas, cada una con su métrica y su lectura alternativa.
- **Entrantes nuevos**: proveedores cuya primera aparición ocurre en el último año de la serie con monto sobre el corte de su propio cohorte.
- **Patrones transversales**: fraccionamiento, duplicados candidatos, cierre de año, montos redondos, velocidad de pago y brecha de orden de compra.
- **Herramientas gráficas**: mapa coroplético nacional con métrica seleccionable, heatmaps de estacionalidad (organismo×mes y región×mes), dispersión interactiva de proveedores y organismos, curvas de Lorenz y Pareto, histograma de días de pago, matriz de concurrencia de patrones y un simulador de umbrales que recalcula el score en el navegador.

La fuente de pagos no publica presupuesto vigente por organismo: aquí *ejecución* significa flujo devengado y pagado observado, no avance sobre la Ley de Presupuestos. Detalle metodológico en `docs/SPEND_VIEW.md`; umbrales en `config/spend_view.yaml`.

```bash
radar-pa spend-view                                     # tras una corrida del pipeline
PYTHONPATH=src python scripts/build_demo_spend_view.py  # demo sintética para revisar el módulo
PYTHONPATH=src python scripts/build_standalone_page.py  # módulo en un solo HTML autocontenido
```

## Integración con Radar CGR

Las corridas operativas descargan `smoralesm07-source/Radar-CGR` y contrastan organizaciones y proveedores con sus capas silver. Todos los enlaces quedan con estado `CANDIDATE`: una coincidencia de entidad no atribuye automáticamente un hallazgo CGR a una transacción de Presupuesto Abierto.

Salidas:

- `data/evidence/cgr_evidence_links.parquet`
- `docs/data/cgr_correlation.json`

## Arquitectura

```text
Presupuesto Abierto
       |
       v
Source Discovery + Snapshot SHA-256
       |
       v
Canonical Normalization / Identity Resolution
       |
       +---- Parquet + DuckDB structured search
       +---- SQLite FTS5 text index
       |
       v
Data Quality Audit
       |
       v
Risk Signal Engine
       |
       +---- Radar CGR candidate evidence
       |
       v
Explainable Investigation Priority
       |
       +---- Spend View (ejecución, territorio, proveedores)
       |
       v
Dashboard + Evidence/Lineage
```

## Búsqueda histórica

El motor puede consultar **un año, varios años o 2016-2026** secuencialmente, sin requerir un servidor externo. Workflow: **Actions -> Search Presupuesto Abierto -> Run workflow**.

## Operación

```bash
python -m pip install -e .            # instala el paquete y sus dependencias
python -m pip install -e '.[test]'    # con dependencias de test
radar-pa probe                        # audita fuentes oficiales
radar-pa-pipeline --years 2026        # corrida completa (normaliza, señaliza, prioriza, publica)
radar-pa spend-view                   # reconstruye sólo la vista de ejecución
python -m radar_presupuesto.pipeline --years 2026
python -m radar_presupuesto.query_job --years 2016-2026 --text "constructora" --filters-json '{"provider_only":true}' --limit 1000
```

Los `.gz`, Parquet e índices SQLite no se versionan en Git. Los productos pesados se conservan como artifacts temporales; Pages publica las salidas compactas.

El paquete se instala con `pip install .` y expone los comandos `radar-pa`, `radar-pa-pipeline` y `radar-pa-spend-view`.

Documentación: `docs/SCHEMA_DESIGN.md`, `docs/ANOMALY_CATALOG.md`, `docs/SEARCH_ENGINE.md`, `docs/OPERATIONAL_V03.md` y `docs/SPEND_VIEW.md`.
