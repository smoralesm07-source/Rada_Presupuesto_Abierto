# Cierres del analista — insumo de calibración

Aquí van los respaldos `RIGP-CASE-BACKUP-v1` que exporta la app case-first
(botón **Exportar todos** en la bandeja, o **Exportar expediente** en uno).

El motor lee estos archivos y mide, por tipo de señal, con qué frecuencia
revisar ese patrón terminó en una escalada. Es la única supervisión honesta que
el radar puede recibir: nadie más que el analista puede decir si un patrón valió
el viaje.

## Cómo alimentarlo

1. En la app, **Exportar todos** desde la bandeja.
2. Deja el JSON en esta carpeta.
3. La siguiente corrida del pipeline lo incorpora, y `docs/data/calibration.json`
   informa qué midió y qué ajustó.

## Qué esperar

- **Menos de 10 expedientes cerrados por tipo de señal**: el multiplicador queda
  en 1.0 y el payload dice por qué. Una muestra corta no es una medición.
- Sólo cuentan los estados de cierre (`ESCALADO`, `EXPLICADO`, `CERRADO`). Un
  expediente abierto no es un resultado negativo: es uno inconcluso.
- Un cierre explicado cuenta en el denominador pero no en el numerador:
  encontrar una explicación legítima no es un fracaso del patrón.

## Antes de commitear

Estos archivos contienen las notas y decisiones del analista. Decide
conscientemente si deben versionarse: para que la calibración opere en la
corrida mensual del CI tienen que estar en el repositorio, pero eso los hace
públicos si el repositorio lo es.

## Probar el mecanismo sin analistas

Mientras no haya cierres reales, `scripts/generate_synthetic_cases.py` arma un
escenario de prueba y muestra cómo respondería la calibración:

```
python3 scripts/generate_synthetic_cases.py --simular
```

Escribe en `data/calibration/synthetic/`, no aquí, y **esos casos no pueden
mover el ranking**: cada uno lleva una marca `synthetic` que viaja con el caso,
de modo que cualquier calibración que los toque queda en estado `SIMULACION` y
`load_multipliers` la rechaza. Reescribir el esquema del archivo no alcanza para
colarlos.
