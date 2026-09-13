# RIGP · Resolución de propiedad, control e identidad

## Objetivo

Resolver quién está detrás de los receptores económicos priorizados sin inferir identidad por semejanza nominal y sin confundir receptor directo con beneficiario final.

La capa trabaja sobre una cola compacta y priorizada de receptores. Su producto es evidencia estructurada sobre propiedad, control, administración, representación u otra relación documentada, con vigencia temporal e identidad verificable.

## Regla principal de identidad

**Mismo nombre no significa misma persona o sociedad.**

RIGP sólo genera una convergencia automática entre receptores cuando:

1. el vínculo está confirmado documentalmente;
2. existe un RUT válido de la persona o sociedad vinculada; y
3. la identidad registrada corresponde al RUT indicado.

Cuando no existe RUT público en la fuente, el analista puede registrar `IDENTIDAD_DOCUMENTADA_SIN_RUT` si el documento identifica inequívocamente a la persona o sociedad. Ese antecedente es útil dentro del receptor, pero **no se utiliza para fusionar automáticamente homónimos entre casos**.

Una coincidencia de nombre sin prueba suficiente permanece como `CANDIDATO_POR_NOMBRE` y no puede transformarse en vínculo confirmado desde la cola Resolver.

## Estados de identidad

- `RUT_CONFIRMADO`: RUT válido y documentalmente asociado a la identidad.
- `IDENTIDAD_DOCUMENTADA_SIN_RUT`: fuente suficiente para identificar a la persona/sociedad dentro del caso, aunque no publique RUT.
- `CANDIDATO_POR_NOMBRE`: coincidencia nominal pendiente; no habilita convergencia.
- `DESCARTADO`: antecedente revisado y descartado.

## Roles privados

- `CONTROL`: propiedad o control.
- `REPRESENTACION`: representación legal.
- `DIRECCION`: dirección o administración.
- `RELACION_ECONOMICA`: relación económica documentada.
- `OTRO`: otra relación respaldada por evidencia.

El rol debe describir exactamente lo que acredita la fuente. Representante legal no equivale necesariamente a propietario o beneficiario final.

## Vigencia temporal

Cada vínculo puede registrar `valid_from` y `valid_to`. RIGP compara esas fechas con el periodo de los hallazgos y clasifica:

- `COINCIDENTE`;
- `PARCIAL`;
- `FUERA_DE_PERIODO`;
- `NO_DETERMINADA`.

Sólo vínculos confirmados y `COINCIDENTE`/`PARCIAL` participan como relaciones temporalmente útiles en la vista transversal.

## Cola de resolución

La cola de Pages es un producto compacto preprocesado y tiene un máximo de 300 receptores. Prioriza, entre otros:

- receptores con hallazgos de mayor prioridad;
- casos de atención inmediata;
- receptores sin controlador/representante temporalmente resuelto;
- receptores sin persona natural confirmada;
- identidades confirmadas sin RUT;
- candidatos que sólo coinciden por nombre.

El puntaje de resolución sirve para ordenar trabajo. **No es probabilidad de delito, corrupción ni beneficio ilícito.**

## Fuentes sugeridas

La cola puede orientar al analista hacia fuentes oficiales abiertas, entre ellas:

- Registro de Empresas y Sociedades (actuaciones y poderes);
- Diario Oficial, sección sociedades;
- Mercado Público y documentos del proceso;
- CMF cuando corresponda.

Las fuentes sugeridas no se consideran evidencia hasta que el analista verifica el documento concreto y registra qué relación acredita.

### Limitación sobre accionistas

La ausencia de accionistas/controladores en una fuente pública no permite concluir que no existan. En particular, el registro de accionistas puede no ser de consulta pública. RIGP debe conservar explícitamente esa falta de cobertura.

## Convergencia transversal

La vista Actores usa RUT confirmado como identificador fuerte para agrupar una persona o sociedad detrás de distintos receptores. Sin RUT, cada vínculo permanece local a su receptor, incluso si el nombre normalizado coincide.

Esto reduce falsos positivos por homónimos y evita construir redes artificiales.

## Relación con la cadena causal

Resolver propiedad/control no acredita beneficio ilícito. Es una etapa de la cadena:

**receptor directo → identidad/control → vigencia → actor público/cruce → antecedente externo → disposición de valor → nexo → evaluación jurídica**.

## Persistencia

En el piloto, la revisión se conserva en `localStorage`. La arquitectura multiusuario futura está definida en `schemas/010_ownership_resolution.sql` y debe mantener trazabilidad de autor, fuente, cambios y estado de revisión.
