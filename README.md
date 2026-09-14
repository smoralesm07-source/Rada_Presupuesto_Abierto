# Radar Presupuesto Abierto

Radar autónomo para explotar datos públicos de **Presupuesto Abierto (DIPRES)** con enfoque de inteligencia financiera, integridad del gasto y detección de patrones anómalos.

**Estado actual: v2 operacional.** El sistema procesa bulk oficiales, controla identidad y calidad, detecta señales en cinco capas, las puntúa en **dos ejes independientes**, las traduce a tipologías LA/FT y las entrega como expedientes con ciclo de vida y cadena de custodia.

Método vigente: [`docs/RIGP_METHOD_v2.md`](docs/RIGP_METHOD_v2.md).

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

## Capas de análisis

| Capa | Señales | Estado |
|---|---|---|
| 1 · Transacción | `AMOUNT_OUTLIER`, `POTENTIAL_FRAGMENTATION`, `EXACT_DUPLICATE_CANDIDATE`, `PROVIDER_CONCENTRATION`, `NEW_TO_SERIES_HIGH_SPEND`, `PAYMENT_DELAY_OUTLIER`, `YEAR_END_SPIKE` | Operativa |
| 2 · Proceso de compra | `SINGLE_BIDDER`, `DIRECT_AWARD_DEPENDENCE`, `DIRECT_AWARD_RECURRENCE`, `AWARD_TO_PAYMENT_INFLATION`, `THRESHOLD_HUGGING`, `SPLIT_PROCUREMENT`, `BID_ROTATION`, `SPEED_ANOMALY` | Adaptador listo, fuente pendiente |
| 3 · Entidad | `NEWBORN_SUPPLIER`, `CAPACITY_MISMATCH`, `ACTIVITY_MISMATCH`, `TERMINATION_AFTER_PAYMENT`, `DORMANT_REACTIVATION` | Operativa |
| 4 · Tipologías LA/FT | 7 tipologías con criterios de sostén, de descarte y documentos a requerir | Operativa |
| 5 · Cuantificación | Dos ejes independientes, calibrados con los cierres del analista | Operativa |

Ninguna señal constituye un hallazgo de ilegalidad.

## Los dos horizontes

La información histórica ya no permite actuar —los contratos cerraron, las autoridades cambiaron, el respaldo puede no ser recuperable— pero sí es lo único que dice cómo se veía lo normal. Por eso el radar mantiene dos ventanas separadas, configurables en `config/analysis_windows.yaml`:

| Ventana | Desde | Qué hace |
|---|---|---|
| **Acción** | `action_from_year` (por defecto 2023) | Lo único que puede convertirse en expediente. Es la bandeja. |
| **Aprendizaje** | `learning_from_year` (por defecto 2016) | Alimenta prevalencias, medianas de pares, primera aparición de proveedor y calibración. Nunca llega a la bandeja. |

Mover `action_from_year` cambia qué se publica, no qué se analiza. Cada relación publicada informa además su **accionabilidad**: si la última actividad se acerca al horizonte de evidencia configurado, la interfaz lo advierte antes de que alguien comprometa trabajo en algo cuyo respaldo quizá ya no se pueda pedir. Ese horizonte es un supuesto operativo, no un plazo de prescripción.

Esto es lo que corrige `NEW_TO_SERIES_HIGH_SPEND`: antes "nuevo" significaba "no visto en la serie procesada", así que un proveedor activo desde 2015 parecía una irrupción apenas la serie empezaba en 2024. Ahora la primera aparición se busca en toda la ventana de aprendizaje, y la señal declara cuántos años de línea base respaldan la afirmación.

## Los dos ejes

Mezclar «cuánto conviene mirar esto» con «qué tan compatible es con una tipología de lavado» producía una cola encabezada por una factura de combustible. Ahora se calculan por separado:

- **`review_priority_score`** (0–100) — rareza empírica del patrón en su **grupo de pares**, convergencia de familias, materialidad **relativa** a los pares, evidencia externa ponderada por calidad del match y contexto registral de la contraparte. Tramos `P1` ≥70, `P2` ≥50, `P3` <50.
- **`laft_compatibility_score`** (0–100) — cuántos patrones de una tipología están presentes. Nunca es probabilidad de delito, y no puede superar el **techo de evidencia** de las capas todavía no integradas.

El corte de publicación reserva una **cuota mínima por familia**: sin ella, las familias individualmente más débiles —fraccionamiento, estacionalidad— desaparecían enteras del ranking.

## El ciclo de aprendizaje

Cada expediente cerrado lleva un veredicto y un motivo escrito. Esa es la única supervisión que este sistema puede tener: nadie más puede decir si un patrón valía el viaje.

`calibration.py` lee expedientes sellados, **descarta los que no verifican su hash**, y mide por patrón cuántas revisiones cerradas llegaron a escalamiento. El resultado es un multiplicador acotado sobre la prioridad de revisión, con cuatro reglas que le impiden hacer daño:

- Sólo los casos **cerrados** son etiquetas. Un expediente abierto es trabajo inconcluso, no un falso positivo.
- Por debajo de `min_closed_cases` el multiplicador es exactamente 1.0. Tres descartes son una anécdota.
- El ajuste queda dentro de una banda configurable, así una mala semana de triage no entierra una familia entera.
- Nunca es silencioso: cada fila muestra el factor aplicado y la precisión observada, y todo el mecanismo se apaga con `calibration.apply: false`.

## El expediente

La unidad de trabajo es el expediente, no la señal. Mismo contrato en `src/radar_presupuesto/case_model.py`, `docs/app/cases.mjs` y `schemas/011_case_management.sql`; un expediente exportado en el navegador se verifica en Python con el mismo SHA-256.

- Cerrar exige motivo escrito; escalar exige hipótesis formulada.
- Todo vínculo entre actores nace `CANDIDATE` y confirmarlo exige indicar fuente.
- La bitácora sólo crece: es la cadena de custodia y viaja con el expediente.

## Integración con Radar CGR

Las corridas operativas descargan `smoralesm07-source/Radar-CGR` y contrastan organizaciones y proveedores con sus capas silver. El cruce intenta primero **RUT validado con dígito verificador**; sólo si la fuente externa no publica RUT cae a nombre normalizado, y en ese caso la confianza queda limitada por debajo del umbral que otorga peso alto en la prioridad. El grado del match (`RUT_EXACT`, `NAME_EXACT`, `NAME_FUZZY`) viaja con cada enlace.

Todos los enlaces quedan con estado `CANDIDATE`: una coincidencia de entidad no atribuye automáticamente un hallazgo CGR a una transacción de Presupuesto Abierto.

Salidas:

- `data/evidence/cgr_evidence_links.parquet`
- `docs/data/cgr_correlation.json`

## Arquitectura

```text
Presupuesto Abierto                  Mercado Público (adaptador listo)
       |                                        |
       v                                        | union por orden_compra
Source Discovery + Snapshot SHA-256             |
       |                                        v
       v                               Capa 2 · Proceso de compra
Canonical Normalization / Identity Resolution
       |
       +---- Parquet + DuckDB structured search
       +---- SQLite FTS5 text index
       |
       v
Data Quality Audit + indice de opacidad de identidad
       |
       v
Capa 1 · Senales de transaccion
       |
       +---- Capa 3 · Senales de entidad (enriquecimiento SII)
       +---- Radar CGR candidate evidence (RUT primero)
       |
       v
Capa 5 · Prioridad de revision (rareza x grupo de pares)
       |
       v
Capa 4 · Tipologias LA/FT (eje independiente)
       |
       v
Expediente: hipotesis, actores, evidencia, bitacora, informe sellado
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

## Aplicación

Cinco destinos, un punto de entrada (`docs/app/main.mjs`), un store: **Mi bandeja**, **Triage**, **Caso**, **Entidad 360** e **Informe**. La ruta guiada de cuatro pasos se conserva como columna narrativa del caso.

Documentación: `docs/RIGP_METHOD_v2.md` (método vigente), `docs/SCHEMA_DESIGN.md`, `docs/ANOMALY_CATALOG.md`, `docs/SEARCH_ENGINE.md` y `docs/OPERATIONAL_V03.md`.
