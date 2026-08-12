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

## Componentes v0.1

- Descubrimiento automático de fuentes oficiales y prueba de URLs anuales.
- Descarga streaming y checksum SHA-256.
- Normalización del esquema SIGFE/Presupuesto Abierto.
- IDs determinísticos para organizaciones, proveedores y transacciones.
- Índice SQLite FTS5 para búsqueda textual y por RUT/OC/documento.
- Motor DuckDB para consultas analíticas sobre Parquet.
- Señales robustas: monto atípico, repetición/fragmentación potencial, concentración, picos de fin de año, expansión rápida de proveedor, diversidad presupuestaria inusual y duplicados.
- Separación estricta entre hechos fuente, variables derivadas e inferencias.
- `data_lineage` y `evidence` desde el inicio.
- GitHub Actions para CI, extracción/análisis y publicación.

## Uso local

```bash
python -m pip install -r requirements.txt
python -m radar_presupuesto.pipeline --years 2024 2025 2026
python -m radar_presupuesto.search --query "constructora" --limit 50
```

Para una primera prueba pequeña sin descargar años completos:

```bash
python -m radar_presupuesto.pipeline --sample tests/fixtures/sample_transactions.csv
```

## Salidas

```text
data/raw/                 snapshots fuente (no versionados)
data/processed/           parquet normalizado (no versionado)
data/index/               SQLite FTS (no versionado)
data/signals/             señales/anomalías (no versionado)
docs/data/dashboard.json  resumen publicable
docs/index.html            visor ejecutivo
```

## Integración futura

Radar Presupuesto Abierto se mantiene independiente en esta etapa. La futura integración con Radar CGR se realizará mediante IDs canónicos y una capa de `evidence_links`, sin acoplar los pipelines de ambos radares.
