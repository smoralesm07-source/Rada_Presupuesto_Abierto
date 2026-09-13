# RIGP · Actores de decisión pública y cruces documentados

> **Vigencia.** Este documento describe la arquitectura anterior a la v2. El método
> operativo vigente está en [`RIGP_METHOD_v2.md`](RIGP_METHOD_v2.md); se conserva aquí
> el razonamiento original porque buena parte sigue siendo válida como método, aunque
> los módulos que menciona ya no existen con ese nombre.

## Propósito

Esta capa conecta dos cadenas que deben mantenerse separadas hasta que exista evidencia suficiente:

**Lado receptor**

`Proveedor/receptor → propiedad/control/representación → persona o sociedad vinculada`

**Lado público**

`Servicio/proceso → persona que intervino → rol documentado → evidencia`

Sólo después puede registrarse un tercer objeto:

`vínculo entre ambos lados → evidencia independiente → revisión humana`

La existencia de una persona en una comisión evaluadora, resolución, contrato o flujo de pago no implica irregularidad. De igual forma, un vínculo entre una persona del receptor y una persona del lado público puede ser legítimo.

## Roles del lado público

El piloto permite registrar, cuando la fuente lo respalda:

- unidad o persona requirente;
- integrante de comisión evaluadora;
- autoridad que adjudica;
- firmante de resolución o contrato;
- administrador del contrato;
- persona asociada a recepción conforme;
- persona asociada a autorización de pago;
- contacto comprador;
- otro rol documentado.

Cada registro debe conservar servicio, proceso si está disponible, documento/fuente y fecha cuando corresponda.

## Fuentes oficiales prioritarias

### Mercado Público · acta de adjudicación

Las actas públicas de adjudicación pueden contener integrantes de la comisión evaluadora, cargo, resolución de adjudicación, anexos, actas de evaluación y declaraciones de ausencia de conflictos de interés. La disponibilidad varía por proceso.

### ChileCompra · procesos OCDS y datos abiertos

ChileCompra publica procesos de compra en formato OCDS y datos abiertos reutilizables. Esta fuente sirve para mantener trazabilidad del proceso, comprador, adjudicación, contratos y documentos asociados.

### Transparencia Activa

La publicación de personal permite contrastar si una persona y su función/cargo corresponden al organismo y periodo relevante. Este contraste es complementario: pertenecer al servicio no acredita participación en una compra concreta.

## Estados

Persona del lado público:

- `POR_VERIFICAR`
- `ROL_CONFIRMADO`
- `DESCARTADO`

`ROL_CONFIRMADO` significa exclusivamente que una fuente verificable acredita el rol de esa persona en el proceso o función registrada.

Cruce entre ambos lados:

- `POR_VERIFICAR`
- `VINCULO_CONFIRMADO`
- `DESCARTADO`

Un `VINCULO_CONFIRMADO` exige evidencia propia del vínculo transversal. No basta una similitud de nombre, domicilio, profesión, apellido o coincidencia contextual.

## Vínculos transversales admitidos

- misma persona, sólo cuando la identidad está documentada;
- relación societaria documentada;
- relación laboral o profesional documentada;
- parentesco documentado;
- representación o mandato documentado;
- otro vínculo con fuente verificable.

## Prohibición de inferencia automática

RIGP no debe crear un cruce entre ambos lados sólo porque dos nombres son iguales o similares. Tampoco debe inferir parentesco por apellido, control por domicilio, coordinación por coincidencia temporal ni conflicto de interés por una relación no comprobada.

La coincidencia puede orientar una búsqueda, pero no se almacena como vínculo hasta contar con evidencia.

## Interpretación investigativa

Cuando exista un vínculo transversal confirmado, la pregunta correcta no es “¿hay corrupción?”, sino:

1. ¿El vínculo estaba vigente durante el proceso relevante?
2. ¿La persona pública tuvo intervención material en la decisión, ejecución, recepción o pago?
3. ¿La persona/sociedad del lado receptor tenía propiedad, control, administración o interés económico material?
4. ¿El proceso generó una ventaja económica concreta al receptor?
5. ¿Existían deberes de abstención, declaración o control aplicables?
6. ¿Qué evidencia adicional falta antes de una evaluación jurídica?

## Guardrail

La secuencia obligatoria es:

`Hallazgo → receptor directo → persona/sociedad vinculada → persona pública con rol documentado → vínculo transversal documentado → temporalidad → evidencia de ventaja/beneficio → revisión humana → evaluación jurídica`

Nunca:

`Coincidencia de nombre → conflicto de interés → delito`

ni:

`Proveedor adjudicado → beneficiario ilícito`
