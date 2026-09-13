# RIGP · Metodología de hallazgos investigables v1

## Propósito

La capa de hallazgos RIGP se ubica entre el motor técnico de señales y la experiencia del analista. Su objetivo es responder una pregunta simple: **¿dónde conviene mirar primero y por qué?**

No transforma una anomalía estadística en una imputación. Una señal aislada puede tener una explicación normal; un hallazgo sólo organiza evidencia y contexto para orientar revisión documental u OSINT.

## Cadena metodológica

`HECHO FUENTE -> SEÑAL TÉCNICA -> PRIORIDAD -> HALLAZGO -> SERVICIO/PROVEEDOR/RED -> REVISIÓN ANALÍTICA`

La diferencia es deliberada:

- **Señal técnica:** patrón reproducible detectado por una regla.
- **Prioridad:** orden de revisión según severidad, materialidad, coocurrencia, evidencia candidata y accionabilidad.
- **Hallazgo RIGP:** agrupación explicable de señales que describe qué merece revisión, sin atribuir ilegalidad.
- **Hipótesis analítica:** pregunta que el analista puede contrastar con documentos y fuentes externas. Nunca se genera como conclusión automática.

## Familias de señales

1. `DOCUMENTOS_Y_PAGOS`: fragmentación potencial y duplicidad documental candidata.
2. `COMPETENCIA_Y_CONCENTRACION`: concentración de proveedor y dependencia económica observable.
3. `ENTRADA_Y_CAMBIO_DE_ESCALA`: proveedor nuevo en la serie o crecimiento material.
4. `MAGNITUD_ATIPICA`: montos extremos frente a pares comparables.
5. `EJECUCION_CONTRACTUAL`: plazos de pago u otros comportamientos contractuales atípicos.
6. `EJECUCION_PRESUPUESTARIA`: concentración temporal o cierre de año.

## Familias de hallazgos

### INTEGRIDAD_DOCUMENTAL_PAGOS

Se activa cuando convergen señales de reiteración documental/pagos. La revisión debe reconstruir OC, facturas, recepción conforme, notas de crédito y pagos. El radar no afirma doble pago, fraude o simulación.

### COMPETENCIA_ADJUDICACION

Combina concentración con irrupción o magnitud material. Orienta a revisar modalidad de contratación, competencia, bases, adjudicaciones y evolución del proveedor. Sólo con evidencia independiente sobre vínculos personales, funcionales, intervención indebida o contraprestaciones procede evaluar hipótesis de conflicto de interés, trato preferente o eventual delito funcionario.

### CONVERGENCIA_MULTIFACTOR

Tres o más familias diferentes aparecen en la misma relación servicio–proveedor–año. Es la principal categoría para navegación inicial, porque reduce la dependencia de una sola regla. Aumenta prioridad de revisión, no probabilidad de delito.

### CONCENTRACION_DEPENDENCIA

Una relación concentra una fracción significativa del gasto. Requiere comparar categoría, estructura de mercado, contratos marco, monopolios técnicos, concesiones y evolución histórica.

### IRRUPCION_CAMBIO_ESCALA

El proveedor aparece con un cambio de escala material o entra con fuerza en la serie observada. Debe confirmarse si el cambio responde a una licitación, programa, cobertura histórica incompleta o crecimiento legítimo.

### EJECUCION_CONTRACTUAL / EJECUCION_PRESUPUESTARIA

Agrupan patrones temporales y contractuales. Son señales de gestión que requieren contexto antes de cualquier interpretación de integridad.

## Niveles de atención

### ATENCION_INMEDIATA

Se asigna cuando se cumple al menos una de estas condiciones:

- dos o más familias y prioridad máxima >= 70;
- dos o más familias y evidencia externa candidata CGR;
- tres o más tipos de señal en la misma relación.

### REVISION_PRIORITARIA

Se asigna con una señal P1, convergencia moderada con prioridad >= 50, o evidencia externa candidata acompañando prioridad suficiente.

### SEGUIMIENTO

Patrón que todavía no reúne convergencia suficiente para escalar. Permanece visible como contexto y puede subir de nivel si aparecen nuevas señales o evidencia.

## Vistas analíticas que alimenta

### 1. Relaciones servicio–proveedor

Unidad principal de hallazgo. Permite saber qué vínculo concreto requiere reconstrucción y por qué.

### 2. Servicios con mayor densidad de hallazgos

Ordena organismos por señales P1/P2, diversidad de familias, proveedores involucrados y evidencia externa candidata. El objetivo es identificar servicios donde se acumulan casos interesantes, no declarar que el servicio sea irregular.

### 3. Proveedores con mayor densidad de hallazgos

Permite observar proveedores que concentran señales en uno o varios servicios, años y familias.

### 4. Redes estrella proveedor–servicios

Detecta proveedores presentes en tres o más servicios, con al menos dos familias de señal y prioridad >= 50. Esta estructura sirve para revisar patrones transversales. **No implica coordinación indebida entre servicios ni entre proveedores.**

## Delitos funcionarios y otras hipótesis jurídicas

RIGP no etiqueta delitos. La interfaz puede mostrar una línea de revisión como **“eventual relevancia para integridad pública / delitos funcionarios, sujeta a verificación”** únicamente cuando exista convergencia suficiente y antecedentes externos que justifiquen revisar vínculos, intervención de funcionarios, pagos improcedentes u otras conductas específicas.

La secuencia obligatoria es:

`PATRÓN -> DOCUMENTOS -> VÍNCULOS -> HECHOS CONFIRMADOS -> EVALUACIÓN JURÍDICA`

Nunca:

`PATRÓN -> DELITO`

## Guardrail transversal

> Un hallazgo RIGP prioriza revisión documental y OSINT. No acredita irregularidad, delito funcionario, fraude, corrupción, lavado de activos ni responsabilidad de una entidad o persona.
