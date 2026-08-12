# Radar Presupuesto Abierto v0.3 — Operación investigativa

## Objetivo

Convertir el núcleo transaccional validado en una cola reproducible de investigación:

`HECHO FUENTE -> PATRÓN -> SEÑAL -> PRIORIDAD -> EVIDENCIA EXTERNA -> CHEQUEO HUMANO`

La prioridad no estima culpabilidad, fraude ni lavado de activos. Ordena señales según su utilidad investigativa.

## Identidad transaccional

- `transaction_id`: identidad única de la fila física del bulk oficial. Incorpora archivo fuente, número estable de fila y fingerprint.
- `transaction_fingerprint`: huella documental/económica. Dos filas pueden compartirla y constituir un candidato a repetición sin colisionar en la clave primaria.

La corrida falla si `transaction_id` no es 100% único. `quality.json` reporta por separado `source_fact_repeat_ratio`.

## Señales nuevas

- `PROVIDER_CONCENTRATION`: proveedor dominante + HHI material en organismo/año.
- `PAYMENT_DELAY_OUTLIER`: plazo de pago en cola extrema del organismo y con umbral material.
- `NEW_TO_SERIES_HIGH_SPEND`: proveedor nuevo **en la serie observada**, con gasto inicial en cola superior. No implica empresa recién creada.

Se conservan `AMOUNT_OUTLIER`, `POTENTIAL_FRAGMENTATION`, `YEAR_END_SPIKE` y `EXACT_DUPLICATE_CANDIDATE`.

## Cola priorizada

Se generan `prioritized_signals.parquet` e `investigation_queue.json`. El score 0–100 combina componentes auditables: severidad, tipo de patrón, coocurrencia, evidencia candidata CGR, accionabilidad documental y materialidad.

- `P1`: >= 70
- `P2`: 50–69
- `P3`: < 50

`priority_explanation` expone la contribución de cada componente.

## Correlación con Radar CGR

GitHub Actions descarga `Radar-CGR` durante la corrida y utiliza sus capas silver de organizaciones, proveedores y hallazgos. El matching exige nombre normalizado exacto o similitud muy alta; región refuerza o penaliza cuando existe.

Todos los enlaces son `CANDIDATE`. Significan “posible misma entidad”, no “este hallazgo CGR corresponde a esta transacción”.

Salidas:

- `data/evidence/cgr_evidence_links.parquet`
- `docs/data/cgr_correlation.json`

## Regla AML

El Radar puede afirmar que un patrón es estadísticamente inusual, material y coincidente con evidencia externa identificada. No puede afirmar por sí solo que existe corrupción, fraude, delito funcionario o LA/FT. La salida correcta es una **hipótesis verificable con ruta de investigación**.
