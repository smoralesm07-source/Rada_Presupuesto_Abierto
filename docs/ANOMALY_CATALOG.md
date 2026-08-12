# Catálogo de señales v0.1

## Principios
- Una señal prioriza revisión; no presume delito.
- Se compara contra historia o pares antes de usar umbrales absolutos.
- Toda señal conserva valor observado, esperado, desviación y chequeos sugeridos.
- La cobertura agregada/transaccional se controla para evitar falsos positivos.

## AMOUNT_OUTLIER
Monto devengado atípico dentro del mismo organismo + subtítulo + ítem. Se usa logaritmo y z robusto basado en mediana/MAD.

## POTENTIAL_FRAGMENTATION
Tres o más documentos para mismo organismo/proveedor/ítem en una ventana semanal y con baja variación relativa. No afirma fraccionamiento ilegal: debe descartarse pago parcial, facturación periódica e hitos contractuales.

## YEAR_END_SPIKE
Promedio de devengo de noviembre-diciembre significativamente superior al promedio enero-octubre. Debe compararse con años previos porque la estacionalidad de cierre puede ser normal.

## EXACT_DUPLICATE_CANDIDATE
Registros coincidentes en claves documentales principales. Puede ser duplicación, ajuste, pago parcial o característica de origen.

## Próxima calibración
Concentración HHI por organismo/categoría, proveedor nuevo con salto abrupto, expansión acelerada, cambio estructural de relación, recurrencia extraordinariamente regular, anomalía geográfica y coocurrencia en OC/BIP/organismos.
