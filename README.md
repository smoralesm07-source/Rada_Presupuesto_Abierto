# Radar Presupuesto Abierto

Radar autónomo para explotar datos públicos de **Presupuesto Abierto (DIPRES)** con enfoque de inteligencia financiera, integridad del gasto y detección de patrones anómalos.

## Objetivo

Responder con evidencia trazable:

1. **Qué está pasando** en el gasto público.
2. **Por qué el patrón es inusual** frente a su historia o pares.
3. **Qué transacciones soportan la señal**.
4. **Qué investigación OSINT conviene ejecutar después**.

El radar no califica delitos ni declara sospecha AML por sí solo. Genera señales priorizables y reproducibles.

## Principio de diseño

`SOURCE_SNAPSHOT -> SOURCE_FACT -> NORMALIZED_FACT -> DERIVED_FEATURE -> RISK_SIGNAL -> EVIDENCE`

Separa estrictamente hechos fuente, variables derivadas, inferencias y evidencia externa.

## Identidad: receptor no es lo mismo que proveedor

El bulk actual usa `beneficiario` como clave de identidad de fuente. Puede ser un RUT válido o un identificador SHA1 pseudonimizado. El radar:

- valida formalmente el dígito verificador antes de declarar un RUT;
- crea `recipient_id` para todo receptor;
- crea `provider_id` solo cuando la fuente marca `proveedor=1`;
- conserva hash de fuente como identidad pseudónima y nunca lo transforma en RUT;
- mantiene banderas persona, honorario, intraestado, deuda flotante y agregado.

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
Feature Engineering
       |
       v
Risk Signal Engine
       |
       v
Dashboard + Evidence/Lineage
```

## Motor de búsqueda

La búsqueda auditada puede consultar **un año, varios años o el rango 2016-2026** sin almacenar toda la historia simultáneamente. Cada año se descarga, normaliza, consulta y libera antes de avanzar al siguiente.

Filtros disponibles incluyen texto, RUT validado, ID fuente, organismo, receptor, proveedor, período, fecha, devengo/pago, Orden de Compra, BIP, ubicación, región, sector, clasificador, documento, proveedor/persona/honorario, intraestado, deuda flotante y días de pago.

Workflow: **Actions -> Search Presupuesto Abierto -> Run workflow**. Entrega `result.csv`, `result.json` y `query_metadata.json` como artifact.

## Señales v0.1

- `AMOUNT_OUTLIER`: cola alta del monto frente a grupo comparable robusto.
- `POTENTIAL_FRAGMENTATION`: recurrencia semanal de montos similares, solo rol proveedor.
- `YEAR_END_SPIKE`: aceleración nov-dic, interpretable solo con período completo e historia.
- `EXACT_DUPLICATE_CANDIDATE`: coincidencia documental para revisión.

Las señales no constituyen hallazgos de ilegalidad.

## Calidad y trazabilidad

El pipeline controla cobertura de RUT válidos, identidades pseudónimas, nombres, devengo/pago, fechas, OC, BIP, región y sector, además de períodos inválidos, colisiones de ID y montos negativos. Cada snapshot descargado recibe checksum SHA-256.

## Uso local

```bash
python -m pip install -r requirements.txt
python -m pip install -e .
python -m radar_presupuesto.pipeline --years 2026
python -m radar_presupuesto.query_job --years 2016-2026 --text "constructora" --filters-json '{"provider_only":true}' --limit 1000
```

## Datos masivos

Los `.gz`, Parquet e índices SQLite no se versionan en Git. El repositorio conserva código, reglas, tests, metodología y salidas compactas. Los resultados analíticos pesados se publican como artifacts temporales de GitHub Actions.

## GitHub Pages

El workflow `Deploy Pages` publica `docs/`. En un repositorio nuevo debe habilitarse una vez **Settings -> Pages -> Build and deployment -> Source: GitHub Actions**.

## Integración futura

Radar Presupuesto Abierto permanece autónomo durante esta fase. La futura integración con Radar CGR se realizará mediante IDs canónicos, RUT validado, nombre normalizado, período, montos, OC/BIP y una capa explícita de `evidence_links`, sin acoplar los pipelines.
