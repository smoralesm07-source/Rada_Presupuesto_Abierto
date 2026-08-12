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
