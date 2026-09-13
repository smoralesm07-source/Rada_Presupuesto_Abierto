# RIGP · Cadena de beneficio y vínculos

## Objetivo

El objetivo final de esta capa es ayudar a identificar **personas o sociedades que ameritan verificación porque podrían haber capturado un beneficio económico asociado a hechos eventualmente impropios**, sin convertir una señal analítica en una imputación.

RIGP separa de forma estricta cinco niveles:

1. **Receptor económico directo**: persona o sociedad que aparece recibiendo recursos públicos en una relación priorizada.
2. **Propiedad, control y administración**: socios/accionistas, controladores, representantes legales, directores o administradores durante el periodo relevante.
3. **Personas y sociedades vinculadas**: relaciones documentadas que permiten extender la trazabilidad más allá del receptor directo.
4. **Cruce con la decisión pública**: personas que intervinieron documentalmente en el proceso y vínculos independientes entre ese lado público y el lado receptor.
5. **Disposición/captura del valor**: evidencia documental de pagos, transferencias, distribución, adquisición de activos u otra forma de control o aprovechamiento económico del valor.

La regla central es:

> **Proveedor/receptor directo ≠ beneficiario final.**

Incluso una disposición de valor documentada puede ser legítima. Para sostener un **beneficio ilícito** debe acreditarse por separado el hecho de base, la intervención relevante y la relación causal con ese beneficio.

## Prioridad de verificación y trazabilidad

La aplicación calcula prioridades para decidir **qué receptor o entidad conviene reconstruir primero**. No representan probabilidad de delito ni probabilidad de beneficio ilícito.

Pueden considerar, de manera explicable:

- prioridad máxima de los hallazgos asociados;
- recurrencia del receptor en distintos servicios;
- convergencia de familias de hallazgo;
- hallazgos de atención inmediata;
- coincidencia temporal de vínculos societarios;
- convergencia de una misma persona o sociedad entre receptores;
- vínculos documentados con actores del proceso público;
- existencia de evidencia económica sobre disposición del valor.

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
- estado de revisión;
- vigencia temporal cuando pueda determinarse.

Estados del piloto:

- `POR_VERIFICAR`
- `VINCULO_CONFIRMADO`
- `DESCARTADO`

Relevancia temporal:

- `COINCIDENTE`
- `PARCIAL`
- `FUERA_DE_PERIODO`
- `NO_DETERMINADA`

Un `VINCULO_CONFIRMADO` confirma exclusivamente la relación documentada; **no confirma que la persona o sociedad haya recibido un beneficio ilícito**.

### Nivel 4 · lado de la decisión pública

RIGP puede registrar personas con funciones documentadas en un proceso, por ejemplo:

- requirente;
- integrante de comisión evaluadora;
- autoridad adjudicadora;
- firmante;
- administrador de contrato;
- responsable de recepción conforme;
- autorizador de pago.

El estado `ROL_CONFIRMADO` exige una fuente concreta —acta, resolución, contrato u otro documento oficial—. Tener uno de estos roles no implica irregularidad.

Un **cruce transversal** entre una persona/sociedad del receptor y una persona del proceso público requiere evidencia independiente propia. RIGP no crea estos vínculos por similitud de nombres.

### Nivel 5 · disposición/captura del valor

Esta etapa está separada de propiedad o representación. Debe existir evidencia concreta de un hecho económico, por ejemplo:

- distribución de utilidades o dividendos;
- transferencia posterior de fondos;
- pago a una persona o sociedad relacionada;
- adquisición de un activo o derecho;
- control o disposición documentada del valor;
- otra conexión económica material documentada.

Estados:

- `POR_VERIFICAR`
- `EVIDENCIA_CONFIRMADA`
- `DESCARTADA`

`EVIDENCIA_CONFIRMADA` significa únicamente que el flujo, pago, distribución o control del valor tiene respaldo documental. **No califica la licitud de ese hecho económico.**

## Convergencia societaria

Una persona o sociedad puede elevarse como nodo común cuando aparece con vínculos `VINCULO_CONFIRMADO` en dos o más receptores y existe relevancia temporal `COINCIDENTE` o `PARCIAL`.

La convergencia sirve para preguntar si existe control común, administración común o una explicación empresarial legítima. **No implica coordinación impropia, colusión ni beneficio ilícito.**

## Ruta societaria oficial del piloto

La reconstrucción de personas detrás de un receptor debe privilegiar fuentes oficiales y conservar la fecha del antecedente.

### Registro de Empresas y Sociedades · actuaciones

La búsqueda pública del RES permite consultar actuaciones de sociedades constituidas o migradas al régimen simplificado. Las constituciones y modificaciones pueden aportar antecedentes sobre constituyentes, socios cuando consten, administración y cambios societarios.

### Registro de Poderes del RES

Sirve para verificar gerentes, administradores, representantes, delegaciones y vigencia de poderes. Un poder acredita facultades de representación; no acredita por sí solo propiedad económica ni beneficio final.

### Diario Oficial · sociedades

Para sociedades del régimen general, los extractos de constitución, modificación y disolución permiten recuperar información societaria histórica que puede incluir socios, administración, uso de razón social y capital.

### Restricción del Registro de Accionistas

El Registro de Accionistas electrónico del RES no es una fuente pública general. RIGP no debe presentar composición accionaria actual como dato abierto si esa evidencia no se encuentra disponible por otra fuente legítima y trazable.

En esta etapa las fuentes societarias se abren de forma asistida y el analista registra el antecedente documental encontrado. No se hace scraping automatizado ni se crean personas mediante coincidencias de nombre.

## Lado de la decisión pública

La ruta asistida prioriza:

- actas de adjudicación y documentos del proceso en Mercado Público;
- datos abiertos ChileCompra/OCDS para contexto del proceso;
- Transparencia Activa para contrastar persona, cargo, organismo y periodo.

Los documentos del proceso deben prevalecer para establecer quién intervino efectivamente en una decisión concreta.

## Mapa transversal de actores

La vista transversal ordena personas y sociedades privadas con vínculos confirmados y temporalmente relevantes, junto con actores públicos cuyo rol esté documentado.

Puede elevar la prioridad de trazabilidad cuando existe:

1. vínculo privado confirmado;
2. convergencia de la misma entidad entre receptores;
3. cruce transversal confirmado con una persona del proceso público;
4. evidencia confirmada de disposición/captura del valor.

La categoría visible debe entenderse como **“requiere mayor trazabilidad”**, nunca como “persona beneficiaria de delito”.

## Hipótesis guiada

Para cada receptor priorizado, la aplicación plantea una hipótesis condicional:

> Si los hechos que originan los hallazgos fueran posteriormente acreditados como impropios, el receptor económico directo es el primer sujeto que corresponde examinar para reconstruir la eventual cadena de beneficio.

La hipótesis debe responder, en orden:

1. ¿Quién recibió directamente el recurso?
2. ¿Quién controlaba, administraba o representaba al receptor en ese momento?
3. ¿Existían sociedades/personas relacionadas materialmente?
4. ¿Quién intervino efectivamente en la decisión pública?
5. ¿Existe un vínculo documentado entre ambos lados?
6. ¿Hay evidencia de que el valor fue recibido, controlado o dispuesto por otra persona o sociedad?
7. Sólo entonces: ¿existe relevancia jurídica que amerite evaluación especializada?

## Guardrail

La capa organiza antecedentes para investigación. **No acredita irregularidad, fraude, corrupción, delito funcionario, lavado de activos, responsabilidad ni beneficio ilícito.**

La secuencia metodológica obligatoria es:

**Dato → Señal → Hallazgo → Receptor económico → Vínculo documentado → Rol público documentado → Cruce independiente → Evidencia de beneficio → Revisión humana → Evaluación jurídica**

Nunca:

**Hallazgo → Persona beneficiaria de delito**

## Limitación actual del piloto

La versión actual dispone de:

- receptores/proveedores priorizados;
- montos y recurrencia publicados;
- contexto histórico compacto;
- caracterización tributaria cuando existe;
- acceso asistido a RES, Registro de Poderes, Diario Oficial, Mercado Público y Transparencia;
- registro local de vínculos societarios documentados;
- vigencia temporal del vínculo;
- registro local de personas con rol documentado en el proceso público;
- registro local de cruces independientes entre ambos lados;
- registro local de evidencia de disposición/captura de valor;
- vista transversal de personas y sociedades que requieren mayor trazabilidad.

Todavía no existe una fuente automática integrada y completa de:

- socios/accionistas y controladores actuales e históricos;
- representantes, directores y administradores históricos consolidados;
- beneficiarios finales;
- personas de la decisión pública extraídas automáticamente desde todos los procesos;
- transferencias financieras posteriores.

Estas coberturas deben incorporarse progresivamente con fuentes abiertas trazables y sin inferencias societarias débiles.
