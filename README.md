# Radar Presupuesto Abierto

Radar autónomo para explotar datos públicos de **Presupuesto Abierto (DIPRES)** con enfoque de inteligencia financiera, integridad del gasto y detección de patrones anómalos.

**Estado actual: v0.3 operacional.** El sistema procesa bulk oficiales, controla identidad y calidad, detecta señales, las prioriza para investigación y contrasta entidades con evidencia del repositorio Radar CGR.

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
       v
Dashboard + Evidence/Lineage
```

## Búsqueda histórica

El motor puede consultar **un año, varios años o 2016-2026** secuencialmente, sin requerir un servidor externo. Workflow: **Actions -> Search Presupuesto Abierto -> Run workflow**.

## Operación

```bash
python -m pip install -r requirements.txt
python -m pip install -e .
python -m radar_presupuesto.pipeline --years 2026
python -m radar_presupuesto.query_job --years 2016-2026 --text "constructora" --filters-json '{"provider_only":true}' --limit 1000
```

Los `.gz`, Parquet e índices SQLite no se versionan en Git. Los productos pesados se conservan como artifacts temporales; Pages publica las salidas compactas.

Documentación: `docs/SCHEMA_DESIGN.md`, `docs/ANOMALY_CATALOG.md`, `docs/SEARCH_ENGINE.md` y `docs/OPERATIONAL_V03.md`.
