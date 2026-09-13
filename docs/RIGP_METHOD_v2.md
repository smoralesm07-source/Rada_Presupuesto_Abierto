# Método RIGP v2

Documento canónico del radar. Reemplaza como referencia operativa a los métodos
por módulo escritos para la arquitectura anterior, que se conservan por su valor
metodológico con un aviso de vigencia.

## El problema que corrige esta versión

El motor detectaba **79.871 señales** y el analista veía **105 relaciones**, de
47 proveedores. Tres decisiones encadenadas producían ese embudo: un corte de
publicación en 250 señales, un score que pagaba puntos fijos por tipo de patrón
sin considerar cuán común era, y una agrupación posterior que partía de un
insumo ya recortado. El 93 % del volumen detectado —fraccionamiento y
duplicados— nunca llegaba a la bandeja, y la señal mejor rankeada del sistema
era una factura de combustible.

Nada de eso era un error de implementación. Era el diseño.

## Los dos ejes

La causa de fondo era mezclar dos preguntas distintas en un solo número:

| Eje | Pregunta | Dónde se calcula |
|---|---|---|
| `review_priority_score` | ¿Cuánto conviene mirar esto primero? | `prioritization.py` |
| `laft_compatibility_score` | ¿Cuántos patrones de una tipología LA/FT están presentes? | `typologies.py` |

Una relación puede merecer revisión por razones que nada tienen que ver con
lavado, y al revés. Un pago grande y ordinario sube el primero y no el segundo:
eso es exactamente lo que ordena la cola correctamente.

### Prioridad de revisión (0–100)

| Componente | Rango | Qué mide |
|---|---|---|
| `rarity_component` | 0–30 | `−ln(prevalencia del patrón en su grupo de pares)` |
| `convergence_component` | 0–25 | Familias independientes que coinciden en la contraparte |
| `relative_materiality_component` | 0–20 | Monto frente a la mediana del grupo de pares, no en pesos absolutos |
| `external_evidence_component` | 0–18 | Evidencia CGR candidata, ponderada por calidad del match |
| `entity_context_component` | 0–10 | Señales registrales de la contraparte |

**Grupo de pares.** Subtítulo dominante de la relación × quintil de escala de
gasto del organismo en el año. Para señales sin proveedor, quintil de escala.
Sin grupo de comparación explícito, «atípico» no significa nada.

**Rareza empírica.** La prevalencia se mide sobre *todas* las relaciones del
grupo de pares, incluidas las limpias. Así el número responde «cuán inusual es
esto» y no «cuán común es entre lo que ya marcamos».

**Cuota por familia.** El corte de publicación reserva una fracción mínima a
cada familia de señal. Sin ella, las familias individualmente más débiles
desaparecen enteras del corte y la lógica de convergencia se queda sin nada que
converger.

## Las cinco capas

| Capa | Estado | Módulo |
|---|---|---|
| 1 · Integridad del dato | Operativa | `normalize.py`, `quality.py`, `relation_context.py` |
| 2 · Proceso de compra | Adaptador listo, fuente pendiente | `procurement.py` |
| 3 · Entidad y red | Operativa sobre el enriquecimiento SII | `entity_signals.py` |
| 4 · Tipologías LA/FT | Operativa | `typologies.py` |
| 5 · Cuantificación | Operativa | `prioritization.py` |

### Capa 2 · Proceso de compra

Presupuesto Abierto responde *a quién se le pagó*; no responde *cómo se decidió
contratarle*. La llave hacia esa respuesta ya estaba en el esquema canónico sin
usarse: `orden_compra`.

`procurement.py` define el esquema canónico del proceso, la unión por
`orden_compra` y ocho detectores probados: `SINGLE_BIDDER`,
`DIRECT_AWARD_DEPENDENCE`, `DIRECT_AWARD_RECURRENCE`,
`AWARD_TO_PAYMENT_INFLATION`, `THRESHOLD_HUGGING`, `SPLIT_PROCUREMENT`,
`BID_ROTATION` y `SPEED_ANOMALY`.

`THRESHOLD_HUGGING` es el equivalente al *structuring* en compras públicas: se
mide como discontinuidad de densidad justo bajo cada umbral de modalidad. Los
umbrales se configuran en UTM en `config/procurement_thresholds.yaml` y deben
fijarse contra el texto vigente de la Ley 19.886 y su reglamento. Si un umbral
queda mal configurado el detector no encuentra nada: nunca inventa un hallazgo.

### Capa 3 · Entidad

Cinco señales derivadas del enriquecimiento SII publicado, con el supuesto
declarado en cada registro: `NEWBORN_SUPPLIER`, `CAPACITY_MISMATCH`,
`ACTIVITY_MISMATCH`, `TERMINATION_AFTER_PAYMENT`, `DORMANT_REACTIVATION`.

El perfil de actividades esperadas por subtítulo se **aprende del gasto
observado**, no de una taxonomía externa. Los RUT comodín que la fuente usa para
agregar receptores sin RUT propio se excluyen: son cubos contables, no
entidades.

### Capa 4 · Tipologías

Un analista no piensa en `AMOUNT_OUTLIER`; piensa en «¿es un proveedor de
fachada?». Cada tipología trae tres cosas, no una:

- **qué la sostendría**
- **qué la descartaría**
- **qué documento pedir**

Siete tipologías: `PROVEEDOR_FACHADA`, `FRACCIONAMIENTO_CONTROL`,
`EXTRACCION_Y_DISOLUCION`, `INTERPOSICION_DE_PERSONAS`, `SOBREPRECIO_Y_DESVIO`,
`CAPTURA_DEL_COMPRADOR`, `COLUSION_DE_OFERENTES`.

Dos reglas la mantienen honesta:

1. **Corroboración.** Un patrón aislado nunca configura una tipología. Sin al
   menos dos patrones concurrentes la hipótesis no se propone.
2. **Techo de evidencia.** Cada tipología declara qué fracción de sus patrones
   es observable hoy. Una que depende del proceso de compra o de propiedad y
   control queda limitada y **lo dice**, en vez de puntuar bajo y parecer un
   resultado negativo.

### Opacidad de identidad

Alrededor de un quinto de las contrapartes llega pseudonimizada desde la fuente,
concentrado en pagos a personas naturales. Una relación construida sobre
identidades opacas no es de bajo riesgo: es **inmedible**, y la interfaz lo
declara en vez de puntuarla como cualquier otra.

## El expediente

La unidad de trabajo es el expediente, no la señal.

Contrato compartido por `case_model.py` (Python), `docs/app/cases.mjs`
(navegador) y `schemas/011_case_management.sql` (base de datos). Un expediente
exportado en el navegador se verifica en Python sin transformación: ambos lados
serializan idénticamente y calculan el mismo SHA-256.

**Estados:** `ABIERTO` → `EN_REVISION` → (`EN_ESPERA_DOCUMENTO` | `ESCALADO` |
`CERRADO_EXPLICADO` | `CERRADO_SIN_MERITO`).

**Reglas que no se pueden eludir:**

- Cerrar exige motivo escrito. Ese motivo es el único insumo honesto para
  recalibrar el score, y antes se perdía al limpiar el navegador.
- Escalar exige una hipótesis formulada.
- Todo vínculo entre actores nace `CANDIDATE`; confirmarlo exige indicar fuente.
- El RUT sólo se guarda si su dígito verificador valida.
- La bitácora sólo crece: es la cadena de custodia y viaja con el expediente.

**Cadena de verificación.** Se conserva sin cambios, porque decir qué no se sabe
es lo que hace defendible el expediente:

| Etapa | Estado |
|---|---|
| 1 · Receptor económico directo | `DISPONIBLE` |
| 2 · Propiedad, control y administración | `POR_INTEGRAR` |
| 3 · Personas y sociedades vinculadas | `POR_VERIFICAR` |
| 4 · Beneficio final | `NO_DETERMINADO` |

## La aplicación

Cinco destinos, un solo punto de entrada, un solo store.

| Pantalla | Qué responde |
|---|---|
| Mi bandeja | ¿Qué tengo que trabajar hoy? |
| Triage | ¿Qué relación revisar primero? |
| Caso | Resumen · Proceso de compra · Flujo de dinero · Actores y propiedad · Evidencia · Bitácora |
| Entidad 360 | Todo lo público sobre un RUT y todos los casos donde aparece |
| Informe | El expediente entregable, con hash de integridad |

La ruta guiada de cuatro pasos —priorizar, investigar, actores, beneficio— se
conserva como columna narrativa del caso, y la etapa alcanzada se **deriva de lo
acreditado**, no de dónde hizo clic el usuario.

## Lo que el radar sigue sin hacer

- No califica delitos ni declara sospecha de LA/FT.
- No atribuye beneficio final: la etapa 4 está declarada como no determinada.
- No integra propiedad ni control societario.
- No observa el proceso de compra hasta que se conecte Mercado Público.
- La serie procesada cubre 2024–2026; las señales que dependen de línea base
  histórica deben leerse con esa limitación a la vista.
