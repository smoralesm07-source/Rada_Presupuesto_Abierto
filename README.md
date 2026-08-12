# Radar Presupuesto Abierto

Radar autónomo para explotar datos públicos de **Presupuesto Abierto (DIPRES)** con enfoque de inteligencia financiera, integridad del gasto y detección de patrones anómalos.

## Objetivo v0.1

Responder, con evidencia trazable:

1. **Qué está pasando** en el gasto público.
2. **Por qué el patrón es inusual** frente a su historia o pares.
3. **Qué transacciones soportan la señal**.
4. **Qué investigación OSINT conviene ejecutar después**.

El radar **no califica delitos ni declara sospecha AML por sí solo**. Genera señales priorizables y reproducibles.

## Principio de diseño

`SOURCE_FACT -> NORMALIZED_FACT -> DERIVED_FEATURE -> RISK_SIGNAL -> INVESTIGATION_CANDIDATE -> EVIDENCE`

Cada etapa mantiene trazabilidad hacia el dato original. Las relaciones no observadas directamente en Presupuesto Abierto se reservan para futuras fuentes externas y se identifican explícitamente como inferencias o evidencia externa.

## Fuente primaria

- https://presupuestoabierto.gob.cl/
- https://api.presupuestoabierto.gob.cl/

La documentación oficial describe información de ejecución mensualizada a nivel transaccional, beneficiario/proveedor/receptor, clasificador presupuestario, documentos, fechas, montos, pago/devengo, Orden de Compra cuando está disponible, código BIP y ubicación geográfica en los datasets de mayor detalle.

El sondeo automatizado del repositorio verifica los archivos bulk anuales oficiales antes de procesarlos. Los años no confirmados se registran como **brecha de cobertura**, nunca como cero gasto.

## Arquitectura

```text
Presupuesto Abierto
      |
      v
Source Discovery + Coverage Audit
      |
      v
Raw snapshots (.gz/.csv)
      |
      v
Canonical Normalization
      |
      +--> Parquet facts
      +--> SQLite FTS search index
      |
      v
Data Quality Audit
      |
      v
Feature Engineering
      |
      v
Risk Signal Engine
      |
      v
Investigation Candidates
      |
      v
Dashboard + Evidence/Lineage
```

## Componentes v0.1 implementados

- Descubrimiento automático de fuentes oficiales y prueba de URLs anuales.
- Descarga streaming y checksum SHA-256.
- Normalización tolerante a drift del esquema SIGFE/Presupuesto Abierto.
- IDs determinísticos para organizaciones, proveedores y transacciones.
- Índice SQLite FTS5 para búsqueda textual por beneficiario/receptor, RUT, organismo, área, clasificador, documento, OC y BIP.
- Motor DuckDB sobre Parquet para búsqueda estructurada por texto, RUT, organismo, proveedor, año, mes, rango de devengo, OC, BIP, ubicación y clasificador presupuestario.
- Workflow manual **Search Presupuesto Abierto** que genera `result.csv`, `result.json` y `query_metadata.json` auditables.
- Perfiles agregados de proveedor y organismo, incluido HHI de concentración de proveedores.
- Señales v0.1: `AMOUNT_OUTLIER`, `POTENTIAL_FRAGMENTATION`, `YEAR_END_SPIKE` y `EXACT_DUPLICATE_CANDIDATE`.
- Auditoría de calidad y cobertura de campos antes de interpretar señales.
- Separación estricta entre hechos fuente, variables derivadas e inferencias.
- Esquemas SQL preparados para evolución relacional y futura capa de evidencia.
- GitHub Actions para CI, cobertura de fuentes, búsqueda, análisis y publicación.

## Esquema real observado

El bulk de producción actual agrega campos que enriquecen el análisis, entre ellos indicadores de honorario/proveedor/persona, sector, región, intraestado, deuda flotante y días de pago. El normalizador conserva estos atributos y traduce variantes como `beneficiario`, `moneda`, `monto` y `devengo` al contrato canónico.

Ver `docs/SCHEMA_DESIGN.md`, `docs/SEARCH_ENGINE.md` y `docs/ANOMALY_CATALOG.md`.

## Uso local

```bash
python -m pip install -r requirements.txt
python -m pip install -e .
python -m radar_presupuesto.pipeline --years 2024 2025 2026
python -m radar_presupuesto.search --query "constructora" --limit 50
```

Para una prueba pequeña sin descargar años completos:

```bash
python -m radar_presupuesto.pipeline --sample tests/fixtures/sample_transactions.csv
```

## Búsqueda desde GitHub Actions

En **Actions -> Search Presupuesto Abierto -> Run workflow** se puede ejecutar una búsqueda auditada por año usando texto libre y filtros estructurados. El resultado se entrega como artifact temporal; el dataset bulk no se incorpora al historial Git.

## Salidas

```text
data/raw/                  snapshots fuente (no versionados)
data/processed/            Parquet normalizado y perfiles (no versionados)
data/index/                SQLite FTS (no versionado)
data/signals/              señales/anomalías (no versionado)
docs/data/dashboard.json   resumen publicable
docs/data/quality.json     auditoría de calidad/cobertura
docs/data/source_catalog.json catálogo de fuentes auditadas
docs/index.html            visor ejecutivo
```

Los archivos masivos no se versionan en Git para evitar crecimiento innecesario del repositorio. Las corridas pueden conservar índices y salidas analíticas como artifacts de GitHub Actions.

## GitHub Pages

El workflow `Deploy Pages` está preparado para publicar `docs/`. En un repositorio nuevo debe configurarse una vez **Settings -> Pages -> Build and deployment -> Source: GitHub Actions** antes del primer despliegue.

## Integración futura

Radar Presupuesto Abierto se mantiene independiente en esta etapa. La futura integración con Radar CGR se realizará mediante IDs canónicos, RUT, temporalidad, OC/BIP y una capa explícita de `evidence_links`, sin acoplar los pipelines de ambos radares.
