# RIGP · Radar de Integridad del Gasto Público

Radar sobre datos de Presupuesto Abierto (DIPRES) con enfoque de integridad del
gasto e inteligencia financiera. Publica payloads JSON estáticos a GitHub Pages;
la app los lee desde el navegador. Método vigente: `docs/RIGP_METHOD_v2.md`.

---

## Coordinación entre sesiones

**Este repositorio ha tenido más de una sesión de Claude trabajando en paralelo,
y el resultado fue una implementación duplicada del mismo diagnóstico.** Lo que
sigue existe para que no vuelva a pasar.

### Regla primera: una misión activa a la vez

El choque no fue por compartir carpetas. Fue porque dos sesiones recibieron la
**misma misión** —«mejora el radar»— sin saber una de la otra, y ambas tocaron
casi todas las zonas del repositorio.

Antes de empezar trabajo de alcance amplio, declara tu misión abajo. Si ya hay
una declarada y se solapa con la tuya, **pregunta al usuario antes de escribir
código**. Dos sesiones pueden convivir sólo si sus misiones son genuinamente
disjuntas (por ejemplo «arregla el cruce CGR» y «añade la pantalla de informe»),
nunca si ambas son «mejora el sistema».

### Misión activa

| Sesión | Misión | Zonas | Desde |
|---|---|---|---|
| Claude · motor RIGP | Portar el motor analítico del PR #6 a `main`, una pieza por PR: scoring relativo a pares, dos ejes de score, ventanas de acción y aprendizaje, tipologías, cruce CGR por RUT. | `src/radar_presupuesto/**`; `config/**`; `scripts/**`; `tests/**` de motor; `.github/workflows/ci.yml` sólo donde el contrato de pruebas sigue al motor. | 2026-09-14 |
| ChatGPT · RIGP case-first | Consolidar la experiencia de trabajo por expediente: `Inicio → Bandeja → Hallazgos → Explorar`, mantener `Expediente / Entidad / Informe` como vistas contextuales y preparar la evolución del caso hacia persistencia durable sin alterar el motor analítico ni los desarrollos paralelos. | `docs/index.html`; `docs/assets/rigp_case_app.*`; `docs/assets/rigp_case_explain.*`; `docs/assets/rigp_shell_*`; pruebas estrictamente necesarias para estas superficies. | 2026-09-14 |

### Límites explícitos de la misión Claude · motor RIGP

Es la contraparte de la frontera de abajo: la otra misión no entra al motor, y
ésta no entra a la interfaz.

- **No tocar `docs/index.html` ni `docs/assets/**`.** El PR #6 los reescribe
  entero y esa es una decisión de producto del usuario, no de una sesión.
- **No mutar en silencio la forma de `docs/data/**`.** Si una pieza portada
  cambia un payload, el mismo PR sube la versión del esquema y lo declara.
  Renombrar una columna que nadie lee se verifica antes con una búsqueda, no con
  una suposición.
- **`.github/workflows/ci.yml` se toca sólo por dos motivos**: cuando el
  contrato de pruebas sigue al motor —por ejemplo, una aserción que fijaba el
  número de señales— y cuando el CI no está cubriendo algo que debería, como un
  PR apilado que no corría por el filtro de rama base. Siempre validando el YAML
  antes de commitear. Ningún otro workflow.
- **No fusionar el PR #6 en bloque.** Se conserva abierto como referencia y se
  porta de a una pieza, cada una con su prueba.
- **No borrar ni renombrar módulos del otro desarrollo** aunque el mapa de
  duplicados los liste como equivalentes. Portar significa hacer que el módulo
  que ya existe en `main` haga el trabajo, no reemplazarlo por el homónimo del
  PR #6.
- Todo cambio sale desde ramas `claude/*` y entra a `main` por pull request.

### Límites explícitos de la misión ChatGPT · RIGP case-first

Para evitar traslapes con otros desarrollos activos, esta sesión asume por defecto
las siguientes fronteras:

- **No tocar `src/radar_presupuesto/**`**, salvo que el usuario amplíe explícitamente
  la misión y se actualice antes esta sección.
- **No tocar `config/**` ni umbrales analíticos.**
- **No tocar `.github/workflows/**`** como parte de esta misión de producto/UX.
- **No mutar esquemas ni contenido de `docs/data/**`**; se consumen como contrato de
  lectura. Si una futura persistencia durable exige un nuevo contrato, debe
  declararse aquí y coordinarse antes de escribirlo.
- **No reemplazar, borrar ni renombrar módulos del otro desarrollo**, aunque parezcan
  redundantes. Primero se revisa la misión declarada y se resuelve el solapamiento.
- **No portar en bloque el PR #6** ni recrear módulos que ya existan bajo otro nombre.
- La siguiente evolución prevista —persistencia durable del expediente— se limita,
  por ahora, a diseño de modelo e integración desde la capa case-first. Cualquier
  backend, tabla, servicio o módulo nuevo queda fuera de alcance hasta que se
  declare su zona exacta en este archivo.
- Todo cambio de esta sesión debe salir desde ramas `chatgpt/rigp-*` y entrar a
  `main` por pull request. Antes de fusionar, se compara con `main`; ante conflicto
  con trabajo ajeno, se detiene la fusión y se coordina en vez de forzarla.

### Reglas operativas

1. **Nadie escribe a `main` directo.** Todo por pull request. Si el choque de
   septiembre hubiera pasado por PR, se habría visto el primer día en vez de a
   los 89 commits.
2. **Ramas cortas.** Una rama que vive más de un día contra un `main` activo ya
   es deuda de fusión. Integra temprano y seguido.
3. **No borres zonas ajenas.** Si tu cambio elimina archivos que otra misión
   está usando, no es un cambio: es una decisión de producto. Pregunta primero.
4. **Antes de crear un módulo, busca si ya existe con otro nombre.** Ver el mapa
   de duplicados más abajo.

---

## Estado: dos implementaciones del mismo diagnóstico

`main` es la base vigente. El PR #6 (`claude/wonderful-faraday-nmv7dc`) contiene
una implementación paralela y completa de las mismas ideas. **No fusionarlo tal
cual**: borra 67 archivos que `main` usa y choca en 8. Se conserva abierto como
referencia mientras se portan sus piezas de a una.

### Mapa de duplicados

Mismo concepto, dos nombres. Antes de escribir uno nuevo, revisa esta tabla.

| Concepto | En `main` | En PR #6 |
|---|---|---|
| Ventana de años | `analysis_window.py` | `windows.py` |
| Grupos de pares | `peer_groups.py` | dentro de `prioritization.py` |
| Selección para publicar | `publication_selection.py` | dentro de `prioritization.py` |
| Tipologías / patrones | `pattern_compatibility.py` | `typologies.py` |
| Revisión de salud de la corrida | `calibration_review.py` | — |
| Calibración con cierres del analista | `calibration.py` ✅ portado | `calibration.py` |
| Contexto de compras | `procurement_context.py` | `relation_context.py` |
| Mercado Público | `mercado_publico_bridge.py` ✅ operativo | `procurement.py` (sin cliente) |
| Expediente | `schemas/011_cases.sql` + `docs/assets/rigp_case_repository.js` | `case_model.py` |
| Señales de contraparte SII | `entity_signals.py` ✅ portado | `entity_signals.py` |

---

## El contrato entre motor e interfaz

La costura del sistema son los payloads de `docs/data/*.json`. El motor los
produce; la app los consume; nadie más los toca.

- **Cambiar la forma de un payload rompe la app.** Si cambias un esquema, el
  mismo PR actualiza a los dos lados, o no va.
- Cada payload declara su `schema`. Si cambia la forma, sube la versión del
  esquema en vez de mutar la existente en silencio.
- Los payloads pesados (`spend_years_v1.json`, `spend_view_v2.json`) son insumos
  de construcción, no activos web: se quedan en el repositorio y salen del
  artefacto publicado.

## Zonas

| Zona | Qué es |
|---|---|
| `src/radar_presupuesto/**` | Motor analítico |
| `config/**` | Umbrales y ventanas. Cambiar un valor cambia resultados: documenta por qué |
| `docs/data/**` | El contrato. Producido por el motor |
| `docs/index.html`, `docs/assets/**` | Interfaz |
| `.github/workflows/**` | Operación. Valida el YAML antes de commitear |
| `tests/**` | Cobertura de ambos lados |

---

## Invariantes que no se tocan

Estas decisiones son lo que hace defendible el producto frente a un fiscal o un
supervisor. No las revierta ninguna misión sin decisión explícita del usuario.

- **Los guardrails viajan en cada payload.** Ninguna señal acredita
  irregularidad, delito funcionario, fraude, corrupción ni lavado de activos.
- **`transaction_id` ≠ `transaction_fingerprint`.** La fila física y el hecho
  documental son cosas distintas; una repetición documental no puede colisionar
  en la clave primaria.
- **RUT sólo con dígito verificador validado.** Un SHA1 nunca se convierte en
  RUT.
- **SHA-256 del bulk en el manifiesto de snapshots.**
- **Todo enlace externo nace `CANDIDATE`.** Una coincidencia de entidad no
  atribuye un hallazgo a una transacción.
- **La cadena de verificación declara lo que no se sabe:** propiedad y control
  `POR_INTEGRAR`, beneficio final `NO_DETERMINADO`. Decirlo es lo que la hace
  defendible.
- **Una capa que no puede calcularse lo declara**, en vez de publicar cero y
  parecer un resultado negativo.

## Antes de entregar

```bash
PYTHONPATH=src pytest -q
python3 -c "import yaml,glob;[yaml.safe_load(open(f)) for f in glob.glob('.github/workflows/*.yml')]"
```

Editar YAML de workflows a mano es la causa más frecuente de caída en este
repositorio: una clave desalineada deja de parsear el archivo entero y GitHub
deja de mostrar el workflow por su nombre.
