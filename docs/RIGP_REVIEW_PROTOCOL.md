# RIGP · Protocolo de validación humana v1

## Objetivo

Cerrar el ciclo entre detección automática y juicio analítico. RIGP no debe aprender de una señal por haber sido detectada, sino de lo que ocurrió después de que una persona revisó su contexto y evidencia.

La secuencia operativa es:

`DATO -> SEÑAL -> HALLAZGO -> REVISIÓN HUMANA -> RESULTADO -> APRENDIZAJE`

## Estados del hallazgo

### PENDIENTE

Hallazgo generado por el motor y todavía no revisado por una persona.

### EN_REVISION

Un analista inició el contraste. Este estado no aumenta ni disminuye la relevancia del hallazgo; sólo indica trabajo en curso.

### EXPLICADO

El patrón tiene una explicación razonable y documentada que reduce su interés analítico. Ejemplos: contrato marco, proveedor único técnico, proyecto extraordinario, cierre presupuestario esperado o cambio administrativo trazable.

No equivale a afirmar que la operación sea jurídicamente correcta en todos sus aspectos. Significa que la señal que originó el hallazgo quedó razonablemente explicada para el propósito del radar.

### PROFUNDIZAR

La revisión inicial no permite explicar satisfactoriamente el patrón o aparecen elementos adicionales que justifican buscar más documentación, fuentes abiertas, relaciones o hechos.

### ESCALADO

Existen hechos confirmados suficientes para trasladar el caso a una instancia de análisis especializada, auditoría, control o revisión jurídica según corresponda. RIGP no determina por sí solo cuál es la calificación jurídica final.

## Resultado obligatorio de una revisión

Toda decisión distinta de `PENDIENTE` debe registrar:

- estado;
- fecha y hora;
- revisor;
- nota breve de fundamento;
- evidencia consultada;
- señales que resultaron útiles;
- señales que resultaron explicadas o poco discriminantes.

En el piloto estático, el navegador puede simular este registro localmente. La versión multiusuario deberá persistirlo con identidad de usuario y auditoría de cambios.

## Evidencia mínima sugerida

La revisión debe intentar cubrir, según disponibilidad:

1. **Hecho presupuestario:** monto, fecha, servicio, proveedor, programa/subtítulo y serie histórica.
2. **Contratación:** orden de compra, licitación, trato directo, convenio marco, contrato y modificaciones.
3. **Ejecución:** facturas, recepción conforme, hitos, pagos, notas de crédito y plazos.
4. **Entidad:** RUT, inicio de actividades, actividad económica, cambios societarios observables y capacidad económica aproximada.
5. **Contexto externo:** antecedentes CGR, sanciones, prensa u otras fuentes públicas trazables.
6. **Red:** otros servicios compradores, proveedores relacionados y recurrencia temporal.

## Principio de escalamiento

Un hallazgo sólo debe escalar cuando la revisión agregue **hechos confirmados**, no porque el score sea alto.

Un score alto responde:

> “¿Dónde conviene mirar primero?”

La revisión humana responde:

> “¿Qué ocurrió realmente y qué falta por verificar?”

La eventual evaluación jurídica responde, en una etapa posterior:

> “¿Los hechos confirmados tienen relevancia administrativa, civil o penal?”

## Aprendizaje

RIGP debe medir por tipo de señal y familia de hallazgo:

- tasa de hallazgos explicados;
- tasa de casos que requieren profundización;
- tasa de escalamiento;
- tiempo medio de revisión;
- señales presentes en casos escalados;
- combinaciones de señales con mayor utilidad;
- falsos positivos o señales poco discriminantes.

Estos indicadores deben utilizarse para **calibrar prioridad**, nunca para convertir el sistema en un predictor automático de culpabilidad.

## Guardrail

La decisión humana también debe ser trazable y revisable. Un analista puede equivocarse, por lo que ningún estado debe borrar la evidencia original ni reescribir retroactivamente el resultado del motor. El sistema debe conservar el dato, la señal, el hallazgo y cada decisión como capas separadas.
