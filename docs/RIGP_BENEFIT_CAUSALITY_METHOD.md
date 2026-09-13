# RIGP · Método de trazabilidad causal del beneficio

## Objetivo

Extender la cadena de beneficiarios para responder una pregunta más exigente: **qué persona o sociedad podría haber capturado un beneficio económico relacionado con un hecho de integridad relevante**, sin convertir una señal analítica en una imputación.

La secuencia obligatoria es:

**Hallazgo analítico → receptor directo → vínculo privado documentado → relevancia temporal → antecedente externo de integridad → disposición de valor documentada → nexo documentado → evaluación jurídica**.

RIGP no admite el salto **hallazgo → beneficiario de delito**.

## 1. Antecedente externo de integridad

Es una fuente oficial o documental que aporta un hecho adicional al hallazgo analítico. Puede corresponder, entre otros, a:

- observación o pronunciamiento de Contraloría;
- sanción o decisión administrativa;
- antecedente judicial o penal;
- invalidación, inhabilidad o decisión formal de contratación;
- informe de auditoría oficial;
- otro antecedente oficial verificable.

El estado `EVIDENCIA_CONFIRMADA` significa únicamente que el documento y el contenido registrado fueron verificados. **No significa que RIGP declare probado un delito, fraude, corrupción o responsabilidad.**

## 2. Disposición del valor

Se utiliza la evidencia económica ya definida en la cadena de beneficiarios: pago relacionado, transferencia posterior, distribución de utilidades, adquisición de activos, control o disposición documentada u otro hecho económico verificable.

La disposición de valor puede ser plenamente legítima. Su registro acredita el hecho económico, no su ilicitud.

## 3. Nexo hecho–beneficio

La coexistencia de un antecedente externo y una disposición de valor **no demuestra causalidad**. El estado `NEXO_DOCUMENTADO` sólo puede registrarse cuando existe una fuente concreta que conecta ambos hechos.

Para cada nexo se conserva:

- antecedente externo asociado;
- persona o sociedad receptora/controladora del valor;
- evidencia económica asociada;
- fuente del nexo;
- documento o referencia;
- explicación breve de qué conexión demuestra la fuente;
- estado de revisión.

## 4. Niveles de trazabilidad

La vista transversal de Actores prioriza profundidad documental, no probabilidad de delito:

1. `VINCULO_PRIVADO`: persona o sociedad vinculada documentalmente al receptor y temporalmente relevante.
2. `CONVERGENCIA_PRIVADA`: la misma entidad aparece detrás de más de un receptor priorizado.
3. `CRUCE_TRANSVERSAL`: existe un vínculo independiente con una persona que intervino en la decisión pública.
4. `VALOR_DOCUMENTADO`: existe disposición de valor hacia la persona o sociedad.
5. `HIPOTESIS_BENEFICIO`: coexisten antecedente externo y disposición de valor, pero el nexo causal aún no está acreditado.
6. `NEXO_DOCUMENTADO`: existe evidencia documental registrada que conecta el antecedente y el beneficio.

Ningún nivel equivale a una conclusión jurídica.

## 5. Regla de priorización

La prioridad de trazabilidad puede aumentar por:

- prioridad del hallazgo original;
- recurrencia entre receptores y servicios;
- cruce público–privado confirmado;
- antecedente externo verificado;
- disposición de valor documentada;
- nexo hecho–beneficio documentado.

El puntaje es una herramienta de ordenamiento investigativo. No es una probabilidad de ilícito, culpabilidad ni beneficio indebido.

## 6. Regla temporal

Un vínculo privado sólo participa en la capa transversal cuando es `COINCIDENTE` o `PARCIAL` respecto del periodo del hallazgo. Los vínculos fuera de periodo no deben elevar convergencias ni prioridad de trazabilidad.

## 7. Regla de atribución

Para sostener una hipótesis de posible beneficio derivado de un hecho ilícito deben existir por separado y ser revisables:

- un hecho o antecedente externo relevante;
- una persona o sociedad vinculada al receptor;
- un beneficio económico documentado;
- un nexo causal documentado entre hecho y beneficio;
- una evaluación jurídica posterior que determine alcance, ilicitud y responsabilidad.

RIGP organiza y prioriza evidencia. **No reemplaza la investigación administrativa, penal, disciplinaria ni la evaluación jurídica especializada.**

## 8. Persistencia piloto

En el piloto, los antecedentes externos y nexos se almacenan localmente en el navegador. La arquitectura de persistencia futura está definida en `schemas/009_benefit_causality.sql`.
