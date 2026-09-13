# RIGP · Aprendizaje y calibración v1

> **Vigencia.** Este documento describe la arquitectura anterior a la v2. El método
> operativo vigente está en [`RIGP_METHOD_v2.md`](RIGP_METHOD_v2.md); se conserva aquí
> el razonamiento original porque buena parte sigue siendo válida como método, aunque
> los módulos que menciona ya no existen con ese nombre.

## Propósito

RIGP debe mejorar a partir del resultado de las revisiones humanas, pero sin convertir ese aprendizaje en una caja negra ni en un predictor automático de culpabilidad.

La cadena completa queda así:

`DATO -> SEÑAL -> HALLAZGO -> REVISIÓN HUMANA -> RESULTADO -> CALIBRACIÓN`

La calibración responde a una pregunta operativa:

> ¿Qué señales y combinaciones ayudaron realmente a decidir dónde valía la pena profundizar?

No responde:

> ¿Qué entidad es más probable que haya cometido un delito?

## Unidad de aprendizaje

La unidad principal es el **hallazgo revisado**, conservando por separado:

- resultado original del motor;
- señales que participaron;
- nivel de atención original;
- evidencia consultada;
- decisión humana;
- fundamento;
- señales calificadas como útiles;
- señales calificadas como poco discriminantes.

El resultado humano nunca debe reescribir retroactivamente el cálculo original.

## Indicadores descriptivos

Para el conjunto de hallazgos revisados se calcularán:

1. **Tasa explicada**: proporción con estado `EXPLICADO`.
2. **Tasa de profundización**: proporción en `PROFUNDIZAR` o `ESCALADO`.
3. **Tasa de escalamiento**: proporción en `ESCALADO`.
4. **Utilidad por señal**: número de revisiones donde una señal fue marcada como útil.
5. **Baja discriminación por señal**: número de revisiones donde una señal fue marcada como poco útil.
6. **Utilidad por combinación**: familias o tipos de señal que aparecen conjuntamente en hallazgos que requieren profundización.
7. **Tiempo de revisión**: en la versión persistente, diferencia entre primera toma y decisión actual.

## Regla de prudencia estadística

En el piloto, los indicadores son **descriptivos**. No cambian pesos automáticamente.

Para proponer una recalibración se recomienda, como mínimo:

- 30 hallazgos efectivamente revisados dentro de la familia o segmento que se desea evaluar;
- resultados obtenidos por más de un revisor cuando sea posible;
- comparación contra materialidad, sector, servicio y período para evitar confundir composición de la muestra con utilidad de la señal;
- revisión de falsos positivos y casos relevantes que el motor no priorizó;
- documentación explícita del cambio de umbral o ponderación.

## Cómo se ajustará el motor

La calibración debe generar una **propuesta versionada**, nunca una modificación silenciosa. Por ejemplo:

- bajar prioridad de una señal que suele quedar explicada cuando aparece sola;
- aumentar prioridad de una combinación que recurrentemente conduce a profundización;
- introducir excepciones conocidas, como estructuras de mercado concentradas o contratos marco;
- crear una nueva señal cuando las revisiones revelen un patrón que el motor actual no captura.

Cada ajuste deberá registrar:

- versión anterior y nueva;
- muestra utilizada;
- métrica que motivó el cambio;
- efecto esperado;
- pruebas de regresión;
- fecha de entrada en vigencia.

## Qué no debe hacer RIGP

RIGP no debe:

- aprender que `ESCALADO = delito`;
- utilizar una decisión humana como verdad jurídica;
- ocultar señales que fueron descartadas en revisiones previas;
- recalibrar automáticamente con muestras pequeñas;
- utilizar identidad del revisor como predictor del resultado;
- mezclar score de prioridad con score de culpabilidad o riesgo penal.

## Piloto actual

La versión estática almacena revisiones y evaluación de utilidad de señales sólo en el navegador del usuario. El panel de aprendizaje calcula métricas descriptivas locales y permite exportar la trazabilidad.

La versión multiusuario deberá persistir la revisión en una base auditable y calcular indicadores sobre el universo autorizado, manteniendo control de versiones y segregación entre resultado automático y decisión humana.
