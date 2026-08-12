# Catálogo de señales v0.1.4

## Principios

- Una señal **prioriza revisión**; no presume delito, fraude, corrupción ni lavado de activos.
- `recipient_id` y `provider_id` se tratan como dimensiones distintas.
- El RUT solo se usa cuando supera validación de dígito verificador; identidades SHA1 permanecen pseudonimizadas.
- La comparación usa historia o pares antes que umbrales absolutos.
- La significancia estadística debe acompañarse de **materialidad económica** cuando corresponda.
- Toda señal conserva valor observado, esperado, desviación, actor(es), período y chequeos sugeridos.
- La ausencia de Orden de Compra no constituye por sí sola una señal.
- El porcentaje de datos disponibles se evalúa en `quality.json` antes de interpretar una anomalía.

## AMOUNT_OUTLIER

Detecta la **cola alta material del monto devengado de proveedores** dentro de un grupo comparable `organismo + subtítulo + ítem`. El monto se transforma con `log1p` y se calcula un z robusto basado en mediana/MAD.

La configuración v0.1.4 exige simultáneamente:

- registro marcado por la fuente como `proveedor=1`;
- registro no agregado;
- al menos 20 operaciones en el grupo comparable;
- z robusto >= 4,5;
- monto en o sobre el percentil 99 del grupo;
- monto al menos 3 veces superior a la mediana del grupo.

Estas condiciones surgieron de una calibración sobre el bulk real 2026: un MAD muy pequeño podía producir z-scores extremos para pagos de baja cuantía y receptores personales, generando ruido analítico. La regla actual combina excepcionalidad estadística y materialidad relativa.

**Qué significa:** el pago a un proveedor es excepcional y material respecto del comportamiento de su grupo comparable.

**Qué no significa:** que el pago sea improcedente.

**Chequeos propuestos:** documento, OC cuando exista, objeto/ítem, historial del proveedor, hitos contractuales y operaciones comparables.

## POTENTIAL_FRAGMENTATION

Opera **solo sobre registros marcados por la fuente como proveedor** y excluye registros agregados. Busca tres o más documentos del mismo `organismo + proveedor + ítem` dentro de una ventana semanal con baja variación relativa de montos.

**Hipótesis:** posible desagregación de un mismo objeto o patrón de pagos que requiere explicación.

**Descartes necesarios:** facturación periódica legítima, estados de pago, hitos contractuales, pagos parciales y contratos diferentes.

## YEAR_END_SPIKE

Compara el promedio mensual de noviembre-diciembre con enero-octubre por organismo.

**Uso:** identificar aceleraciones de cierre presupuestario que merecen análisis de composición por proveedor, subtítulo y nuevas OC/modificaciones.

**Restricción:** no debe interpretarse cuando el año aún no contiene noviembre y diciembre. El año 2026 está actualmente incompleto para esta señal.

## EXACT_DUPLICATE_CANDIDATE

Busca coincidencias en claves documentales principales usando `recipient_id`, documento, fecha, monto, folio y período. Los registros agregados se excluyen de esta detección.

**Hipótesis:** posible duplicación de origen o evento documental repetido.

**Descartes:** ajustes, reversos, pagos parciales, registros contables complementarios o particularidades del sistema de origen.

## Flujo analítico esperado

`SIGNAL -> supporting transactions -> contexto del receptor/proveedor -> comparación histórica/pares -> evidencia documental -> investigación propuesta`

La salida deseada no es “actor sospechoso”, sino una ficha reproducible que explique **qué patrón cambió, cuánto se desvía, qué lo soporta y qué debería revisarse**.

## Próxima calibración

Se priorizarán señales de concentración HHI por organismo/categoría, proveedor nuevo con salto abrupto, expansión acelerada a múltiples organismos, cambio estructural organismo–proveedor, recurrencia extraordinariamente regular, anomalía geográfica, tiempos de pago atípicos y coocurrencia en OC/BIP/organismos.
