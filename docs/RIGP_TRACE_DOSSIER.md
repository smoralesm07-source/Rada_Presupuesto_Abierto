# RIGP · Dossier de trazabilidad por receptor

> **Vigencia.** Este documento describe la arquitectura anterior a la v2. El método
> operativo vigente está en [`RIGP_METHOD_v2.md`](RIGP_METHOD_v2.md); se conserva aquí
> el razonamiento original porque buena parte sigue siendo válida como método, aunque
> los módulos que menciona ya no existen con ese nombre.

## Propósito

El dossier concentra en una sola lectura la cadena investigativa disponible para un receptor priorizado. Su objetivo es mostrar **qué está documentado, qué falta por comprobar y hasta qué nivel de trazabilidad puede sostenerse la investigación**, sin convertir profundidad documental en probabilidad de delito.

El dossier reutiliza exclusivamente el contexto compacto y los antecedentes registrados por el analista. No carga el universo histórico masivo ni realiza inferencias automáticas de propiedad, parentesco, colusión o beneficio ilícito.

## Niveles de trazabilidad

### L1 · Receptor identificado

Existe un receptor económico directo asociado a uno o más hallazgos priorizados. Este nivel permite responder quién recibió directamente recursos públicos en las relaciones publicadas.

### L2 · Vínculo privado confirmado

Existe al menos una persona o sociedad vinculada documentalmente con el receptor, con estado `VINCULO_CONFIRMADO` y relevancia temporal `COINCIDENTE` o `PARCIAL`.

L2 no demuestra que esa persona o sociedad haya recibido el valor económico ni que exista irregularidad.

### L3 · Cruce público–privado confirmado

Existe un vínculo independiente documentado entre el lado receptor y una persona del proceso público. El rol público y el vínculo transversal deben estar respaldados separadamente.

L3 justifica profundizar intervención, conflicto de interés, temporalidad y causalidad. No acredita favorecimiento ni corrupción.

### L4 · Disposición del valor documentada

Existe al menos una evidencia con estado `EVIDENCIA_CONFIRMADA` sobre recepción, transferencia, distribución, adquisición de activo, control o disposición posterior del valor por una persona o sociedad vinculada.

L4 confirma únicamente la existencia del hecho económico documentado. **Una disposición del valor puede ser legítima.** Para hablar de beneficio ilícito es necesario demostrar separadamente el hecho de base y la relación causal entre ese hecho y el valor recibido o dispuesto.

## Contenido del dossier

Cada dossier muestra, con un máximo de 20 antecedentes por bloque:

1. receptor económico directo, RUT, actividad, periodo, hallazgos, servicios y montos publicados;
2. personas y sociedades privadas vinculadas, rol, fuente, estado y vigencia temporal;
3. actores del proceso público, rol, servicio/proceso y fuente;
4. cruces documentados entre ambos lados;
5. evidencia registrada de disposición/captura del valor;
6. nivel L1–L4 alcanzado;
7. preguntas que continúan abiertas;
8. fuentes y procedencia de los antecedentes.

## Preguntas obligatorias

El dossier debe mantener visibles las brechas relevantes, entre ellas:

- ¿quién controlaba, administraba o representaba al receptor durante el periodo de los hallazgos?;
- ¿quién intervino efectivamente en requerimiento, evaluación, adjudicación, contrato, recepción o pago?;
- ¿existe un vínculo independiente entre el lado público y el lado receptor?;
- ¿el valor fue transferido, distribuido o dispuesto posteriormente por una persona o sociedad vinculada?;
- ¿cuál es la causa económica y jurídica del flujo observado?;
- ¿existe una relación causal demostrable entre un eventual hecho impropio y el beneficio económico?;
- ¿qué explicación legítima alternativa debe descartarse antes de una evaluación jurídica?

## Salidas

El piloto permite:

- **Copiar dossier**: genera una versión textual de la trazabilidad actual;
- **Imprimir dossier**: genera una vista limpia del expediente para revisión o respaldo.

Estas salidas reflejan el estado local del piloto al momento de su generación. Todavía no sustituyen un expediente institucional persistente y multiusuario.

## Rendimiento

La capa es deliberadamente pasiva:

- no utiliza `MutationObserver`;
- no utiliza polling ni `setInterval`;
- no carga `spend_years_v1.json`;
- no agrega un nuevo dataset;
- utiliza `benefit_context.json` y estados locales ya existentes;
- limita el DOM mediante topes por sección.

## Guardrail

Los niveles L1–L4 son **niveles de profundidad documental**, no una escala de culpabilidad.

El dossier no acredita irregularidad, fraude, corrupción, delito funcionario, lavado de activos, responsabilidad individual ni beneficio ilícito. Incluso en L4, la licitud del hecho económico debe evaluarse separadamente.
