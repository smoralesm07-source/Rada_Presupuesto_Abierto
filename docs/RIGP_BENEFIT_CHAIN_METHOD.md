# RIGP · Cadena de beneficio y vínculos

## Objetivo

El objetivo final de esta capa es ayudar a identificar **personas o sociedades que ameritan verificación porque podrían haber capturado un beneficio económico asociado a hechos eventualmente impropios**, sin convertir una señal analítica en una imputación.

RIGP separa de forma estricta cuatro niveles:

1. **Receptor económico directo**: persona o sociedad que aparece recibiendo recursos públicos en una relación priorizada.
2. **Propiedad, control y administración**: socios/accionistas, controladores, representantes legales, directores o administradores durante el periodo relevante.
3. **Personas y sociedades vinculadas**: relaciones documentadas que permiten extender la trazabilidad más allá del receptor directo.
4. **Beneficio final**: sólo puede atribuirse cuando exista evidencia suficiente de propiedad/control, disposición del valor o transferencias posteriores.

La regla central es:

> **Proveedor/receptor directo ≠ beneficiario final.**

## Prioridad de verificación

La aplicación calcula una prioridad 0–100 para decidir **a qué receptor conviene reconstruir primero**. No representa probabilidad de delito ni probabilidad de beneficio ilícito.

La prioridad considera de forma explicable:

- prioridad máxima de los hallazgos asociados;
- recurrencia del receptor en distintos servicios;
- convergencia de familias de hallazgo;
- cantidad de hallazgos de atención inmediata;
- contexto tributario publicado cuando existe.

El score sólo ordena trabajo de verificación.

## Evidencia mínima por nivel

### Nivel 1 · receptor directo

Puede sostenerse con información presupuestaria/transaccional publicada que identifique proveedor o receptor y monto.

### Nivel 2 · propiedad/control

Debe provenir de una fuente societaria o registral verificable y referirse, idealmente, al periodo del hecho. No se infiere control por coincidencias débiles de nombre, actividad o domicilio.

### Nivel 3 · personas/sociedades vinculadas

Cada vínculo debe registrar al menos:

- nombre de persona o sociedad;
- tipo de vínculo;
- fuente o documento;
- estado de revisión.

Estados del piloto:

- `POR_VERIFICAR`
- `VINCULO_CONFIRMADO`
- `DESCARTADO`

Un `VINCULO_CONFIRMADO` confirma exclusivamente la relación documentada; **no confirma que la persona o sociedad haya recibido un beneficio ilícito**.

### Nivel 4 · beneficio final

Requiere evidencia adicional que permita sostener al menos una de estas hipótesis:

- propiedad/control efectivo del receptor durante el periodo relevante;
- disposición o aprovechamiento económico del valor recibido;
- transferencia posterior del valor;
- otra conexión económica material documentada.

RIGP no debe etiquetar automáticamente a una persona como beneficiario final.

## Ruta societaria oficial del piloto

La reconstrucción de personas detrás de un receptor debe privilegiar fuentes oficiales y conservar la fecha del antecedente.

### Registro de Empresas y Sociedades · actuaciones

La búsqueda pública del RES permite consultar, sin iniciar sesión, actuaciones de sociedades constituidas o migradas al régimen simplificado. Las constituciones y modificaciones pueden aportar antecedentes sobre constituyentes, socios cuando consten, administración y cambios societarios.

### Registro de Poderes del RES

Es un registro público aplicable a sociedades del RES. Sirve para verificar gerentes, administradores, representantes, delegaciones y vigencia de poderes. Un poder acredita facultades de representación; no acredita por sí solo propiedad económica ni beneficio final.

### Diario Oficial · sociedades

Para sociedades del régimen general, los extractos de constitución, modificación y disolución permiten recuperar información societaria histórica que puede incluir socios, administración, uso de razón social y capital.

### Restricción del Registro de Accionistas

El Registro de Accionistas electrónico del RES no es una fuente pública general: su consulta está restringida a sujetos habilitados por la sociedad. RIGP no debe presentar composición accionaria actual como dato abierto si esa evidencia no se encuentra disponible por otra fuente legítima y trazable.

En esta etapa las fuentes societarias se abren de forma asistida y el analista registra el antecedente documental encontrado. No se hace scraping automatizado ni se crean personas mediante coincidencias de nombre.

## Hipótesis guiada

Para cada receptor priorizado, la aplicación plantea una hipótesis condicional:

> Si los hechos que originan los hallazgos fueran posteriormente acreditados como impropios, el receptor económico directo es el primer sujeto que corresponde examinar para reconstruir la eventual cadena de beneficio.

La hipótesis debe responder, en orden:

1. ¿Quién recibió directamente el recurso?
2. ¿Quién controlaba, administraba o representaba al receptor?
3. ¿Existían sociedades/personas relacionadas materialmente?
4. ¿Hay evidencia de que el valor terminó beneficiando a otra persona o sociedad?
5. Sólo entonces: ¿existe relevancia jurídica que amerite evaluación especializada?

## Guardrail

La capa de Beneficiarios y vínculos organiza antecedentes para investigación. **No acredita irregularidad, fraude, corrupción, delito funcionario, lavado de activos, responsabilidad ni beneficio ilícito.**

La secuencia metodológica obligatoria es:

**Dato → Señal → Hallazgo → Receptor económico → Vínculo documentado → Evidencia de beneficio → Revisión humana → Evaluación jurídica**

Nunca:

**Hallazgo → Persona beneficiaria de delito**

## Limitación actual del piloto

La versión actual dispone de:

- receptores/proveedores priorizados;
- montos y recurrencia publicados;
- contexto histórico compacto;
- caracterización tributaria SII cuando existe;
- acceso asistido a RES, Registro de Poderes y Diario Oficial;
- registro local de vínculos documentados por el analista.

Todavía no existe una fuente automática integrada de:

- socios/accionistas y controladores;
- representantes legales históricos consolidados;
- directores/administradores consolidados;
- beneficiarios finales;
- personas que intervinieron en la decisión pública;
- transferencias financieras posteriores.

Estas coberturas deben incorporarse progresivamente con fuentes abiertas trazables y sin inferencias societarias débiles.
