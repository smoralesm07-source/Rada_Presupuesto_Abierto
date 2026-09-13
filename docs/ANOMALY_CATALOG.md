# Catálogo de señales v0.3 operacional

## Principios

- Una señal **prioriza revisión**; no presume delito, fraude, corrupción ni lavado de activos.
- `recipient_id` y `provider_id` son dimensiones distintas.
- `transaction_id` identifica una fila física única; `transaction_fingerprint` identifica una huella documental/económica potencialmente repetible.
- El RUT solo se usa cuando supera validación de dígito verificador; identidades SHA1 permanecen pseudonimizadas.
- La significancia estadística se combina con **materialidad económica** cuando corresponde.
- La ausencia de Orden de Compra no constituye por sí sola una señal.
- Los enlaces con Radar CGR son evidencia candidata de identidad y nunca atribuyen automáticamente un hallazgo a una transacción.

## AMOUNT_OUTLIER

Detecta la cola alta material del monto devengado de proveedores dentro de un grupo comparable `organismo + subtítulo + ítem`, usando mediana/MAD, percentil superior y múltiplo mínimo de la mediana.

## POTENTIAL_FRAGMENTATION

Busca tres o más documentos del mismo `organismo + proveedor + ítem` dentro de una ventana semanal con baja variación relativa de montos. Deben descartarse facturación periódica, estados de pago, hitos contractuales y contratos distintos.

## YEAR_END_SPIKE

Compara noviembre-diciembre con enero-octubre por organismo. No se interpreta si el año no contiene noviembre y diciembre.

## EXACT_DUPLICATE_CANDIDATE

Agrupa filas por claves documentales/económicas. En v0.3 las filas mantienen `transaction_id` distintos aunque compartan `transaction_fingerprint`.

## PROVIDER_CONCENTRATION

Calcula participación del proveedor dominante y HHI por `organismo + año`. Configuración inicial: al menos 8 proveedores, participación >=45%, HHI >=0,25 y gasto dominante >=$10 millones. Deben descartarse monopolios técnicos, contratos marco, concesiones y proyectos de gran escala.

## PAYMENT_DELAY_OUTLIER

Utiliza `dias_de_pago` cuando es numérico y exige un grupo institucional suficiente, plazo >=60 días y ubicación en la cola extrema. Deben revisarse recepción conforme, notas de crédito y controversias contractuales.

## NEW_TO_SERIES_HIGH_SPEND

Opera solo con al menos dos años procesados. Identifica proveedores cuya primera aparición se produce en el último año de la **serie observada** y cuyo gasto acumulado está en la cola superior. “Nuevo en la serie” no significa “empresa nueva”.

## Coocurrencia y prioridad

La coocurrencia se usa para ordenar revisión, no como prueba. El score 0–100 incorpora severidad, tipo de patrón, coocurrencia, evidencia candidata Radar CGR, accionabilidad documental y materialidad.

La salida es:

`SIGNAL -> supporting facts -> contexto del actor -> comparación histórica/pares -> evidencia externa -> investigación propuesta`

---

# Catálogo v2 · capas 2, 3 y 4

El método vigente está en [`RIGP_METHOD_v2.md`](RIGP_METHOD_v2.md). Las señales
de arriba siguen siendo la capa 1; lo que sigue son las capas incorporadas en v2.

## Capa 2 · Proceso de compra

Requieren el snapshot de Mercado Público, unido a los pagos por `orden_compra`.
Los umbrales de modalidad se configuran en UTM en
`config/procurement_thresholds.yaml` y deben fijarse contra el texto vigente de
la Ley 19.886 y su reglamento.

| Señal | Qué observa |
|---|---|
| `SINGLE_BIDDER` | Licitación adjudicada con un único oferente admisible |
| `DIRECT_AWARD_DEPENDENCE` | Proporción del monto resuelto sin competencia abierta, frente a pares |
| `DIRECT_AWARD_RECURRENCE` | Trato directo reiterado con el mismo proveedor |
| `AWARD_TO_PAYMENT_INFLATION` | Pagado muy por encima de lo adjudicado |
| `THRESHOLD_HUGGING` | Densidad anómala de adjudicaciones justo bajo un umbral de modalidad |
| `SPLIT_PROCUREMENT` | Órdenes sucesivas cuya suma cruza un umbral que ninguna alcanza sola |
| `BID_ROTATION` | Rotación del adjudicatario entre un grupo estable de oferentes |
| `SPEED_ANOMALY` | Plazo entre publicación y adjudicación inverosímilmente breve |

`THRESHOLD_HUGGING` es el equivalente al *structuring*: se mide como
discontinuidad de densidad a ambos lados del umbral. Si el umbral está mal
configurado, no encuentra nada; nunca inventa un hallazgo.

## Capa 3 · Entidad

Derivadas del enriquecimiento SII publicado. Cada registro declara su supuesto
en el campo `assumption`.

| Señal | Qué observa |
|---|---|
| `NEWBORN_SUPPLIER` | Primer pago público a poco del inicio de actividades declarado |
| `CAPACITY_MISMATCH` | Monto desproporcionado frente al tramo de ventas declarado |
| `ACTIVITY_MISMATCH` | Giro registrado ajeno a las actividades que concentran el gasto del subtítulo |
| `TERMINATION_AFTER_PAYMENT` | Término de giro poco después del último pago relevante |
| `DORMANT_REACTIVATION` | Reaparición con monto alto tras un periodo sin pagos |

El tramo superior de ventas no tiene techo declarado y por eso nunca genera
`CAPACITY_MISMATCH`. Los RUT comodín que la fuente usa para agregar receptores
sin RUT propio se excluyen: son cubos contables, no entidades.

## Contexto de relación

No son señales de riesgo sino condiciones de lectura, y alimentan las tipologías:
`OPAQUE_COUNTERPARTY`, `HONORARIUM_CONCENTRATION`, `PERSON_RECIPIENT`,
`NO_PURCHASE_ORDER_TRAIL`.

La opacidad describe un límite de la fuente, no una conducta. Un receptor
pseudonimizado no es más sospechoso: es **menos verificable**.

## Capa 4 · Tipologías LA/FT

| Tipología | Anclas |
|---|---|
| `PROVEEDOR_FACHADA` | (`NEWBORN_SUPPLIER` \| `DORMANT_REACTIVATION`) + (`CAPACITY_MISMATCH` \| `ACTIVITY_MISMATCH`) |
| `FRACCIONAMIENTO_CONTROL` | `POTENTIAL_FRAGMENTATION` \| `SPLIT_PROCUREMENT` \| `THRESHOLD_HUGGING` |
| `EXTRACCION_Y_DISOLUCION` | `TERMINATION_AFTER_PAYMENT` |
| `INTERPOSICION_DE_PERSONAS` | `HONORARIUM_CONCENTRATION` \| `PERSON_RECIPIENT` |
| `SOBREPRECIO_Y_DESVIO` | `AWARD_TO_PAYMENT_INFLATION` \| `AMOUNT_OUTLIER` |
| `CAPTURA_DEL_COMPRADOR` | `DIRECT_AWARD_DEPENDENCE` \| `PROVIDER_CONCENTRATION` |
| `COLUSION_DE_OFERENTES` | `BID_ROTATION` \| `COVER_BIDDING` \| `PHANTOM_COMPETITION` |

Cada tipología trae **qué la sostendría, qué la descartaría y qué documento
pedir**. Un patrón aislado nunca configura una tipología: se exigen al menos dos
patrones concurrentes. Y cada una declara su **techo de evidencia**, de modo que
una tipología limitada por una capa no integrada lo dice en vez de puntuar bajo y
parecer un resultado negativo.

## Diagnóstico de detectores silenciosos

`extend_signals` reporta `silent_detectors`: los detectores que produjeron cero
señales en la corrida. `PAYMENT_DELAY_OUTLIER` producía cero porque dependía de
un campo opcional del bulk; ahora reconstruye el plazo desde
`fecha_recepcion_conforme` o `fecha_documento` hacia `fecha_pago`, e informa la
base usada en cada señal. Un detector que no puede disparar debe decirlo, no
desaparecer en silencio.
