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
| ChatGPT · RIGP case-first | Consolidar la experiencia por expediente y llevarla a un piloto operativo multiusuario: sesión persistente, bandeja compartida, toma y edición de expediente, trazabilidad y reanudación desde otro navegador, sin alterar el motor analítico. | `docs/index.html`; `docs/assets/rigp_case_app.*`; `docs/assets/rigp_case_explain.*`; `docs/assets/rigp_shell_*`; `docs/assets/rigp_case_repository.js`; `docs/assets/rigp_case_supabase.*`; `.github/workflows/check-case-app.yml` para el contrato case-first; `.github/workflows/pages.yml` sólo para empaquetar/publicar los assets case-first ya referenciados por `docs/index.html`; `schemas/012_case_workspace.sql`; pruebas estrictamente necesarias. En Supabase: proyecto `ldmtlwzqaqmegedktlxr`; tablas/políticas `rigp.case_workspace_state`, `rigp.case_workspace_event`; RPC públicos `rigp_case_workspace_load()` y `rigp_case_workspace_sync(...)` sólo como fachada SECURITY INVOKER del workspace. | 2026-09-14 |

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
  antes de commitear.
- **`.github/workflows/radar-monthly.yml`, ampliación autorizada por el usuario
  el 2026-09-15**, y sólo para que la corrida no destruya su propio resultado.
  La corrida #32 calculó once años de serie durante 3h37m, pasó la validación y
  murió al empujar a `main`: la protección de rama exige pull request y check
  `test`, y el bot empujaba directo. Cuatro horas de cómputo perdidas en el
  último paso. La corrida ahora asegura sus payloads en una rama y abre un pull
  request. La regla «nadie escribe a `main` directo» deja de tener excepción,
  incluso para el bot. Cualquier otro cambio a este workflow —el pipeline
  analítico, sus disparadores, su ventana— sigue fuera de esta misión.
- **`.github/workflows/mercado-publico-enrichment.yml`, ampliación autorizada por
  el usuario el 2026-09-16**, y por el mismo motivo: que la corrida no destruya
  su propio resultado. Tres corridas seguidas murieron en el último paso —dos
  por la protección de rama, una por una aserción de cobertura—, y la última se
  llevó 349 órdenes resueltas y nueve minutos de API. Ahora la evidencia se
  asegura en una rama **antes** de validarse y antes de proponerse por pull
  request; un payload inválido también se guarda, porque revisarlo exige
  tenerlo, y en ese caso no se abre el PR. Cualquier otro cambio a este
  workflow —qué se consulta, sus disparadores, sus topes— sigue fuera de esta
  misión.
- Ningún otro workflow.
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
- **No tocar `.github/workflows/**`** como parte de esta misión de producto/UX,
  **salvo `.github/workflows/check-case-app.yml`** para mantener el contrato de
  validación y **`.github/workflows/pages.yml`** exclusivamente para que el artefacto
  publicado incluya los assets case-first que `docs/index.html` referencia. No se
  modifica desde esta misión el pipeline analítico, sus disparadores ni CI del motor.
- **No mutar esquemas ni contenido de `docs/data/**`**; se consumen como contrato de lectura.
- La persistencia multiusuario queda autorizada únicamente en el proyecto Supabase
  `ldmtlwzqaqmegedktlxr` mediante `rigp.case_workspace_state`,
  `rigp.case_workspace_event`, sus índices/RLS/grants, y las fachadas públicas
  `public.rigp_case_workspace_load()` y `public.rigp_case_workspace_sync(...)`.
  Estas dos funciones deben ser **SECURITY INVOKER**, estar revocadas para `anon` y
  `PUBLIC`, y concederse sólo a `authenticated`; no pueden saltarse RLS.
- **No modificar `candidate_case`, `candidate_evidence`, `case_assignment`,
  `case_review_event`, `pilot_member` ni otros objetos preexistentes**. La membresía
  se resuelve reutilizando `public.rigp_ops_get_session()` sin cambiarlo.
- El frontend puede usar únicamente la **publishable key**. **Nunca** se expone ni
  versiona una secret key, `service_role`, contraseña, token de usuario o connection string.
- Antes de cualquier grant al rol `authenticated`, el objeto correspondiente debe
  tener RLS habilitado y una política explícita. `anon` no recibe acceso a la
  persistencia de expedientes.
- `case_workspace_state` es estado de trabajo de la interfaz, no reemplaza ni
  recalcula el `candidate_case` analítico. Un expediente de interfaz sin
  `candidate_id` debe conservar esa distinción de forma explícita.
- **No reemplazar, borrar ni renombrar módulos del otro desarrollo**, aunque parezcan
  redundantes. Primero se revisa la misión declarada y se resuelve el solapamiento.
- **No portar en bloque el PR #6** ni recrear módulos que ya existan bajo otro nombre.
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
| Expediente analítico | `rigp.candidate_case` + `schemas/011_cases.sql` | `case_model.py` |
| Estado de trabajo case-first | `rigp.case_workspace_state` (misión ChatGPT) | — |
| Señales de contraparte SII | `entity_signals.py` ✅ portado | `entity_signals.py` |
| Enlace CGR por entidad (scoring) | `cgr_correlation.py` | dentro de `typologies.py` |
| Exposición a auditoría por servicio | `public_service_audits.py` | — |
| Índice de opacidad por servicio | `opacity_index.py` ✅ portado | dentro de `relation_context.py` |
| Cuotas vs. compras separadas en un grupo semanal | `split_discrimination.py` | — |
| Fuentes de compras públicas disponibles | `procurement_discovery.py` | — |
| Modalidad de contratación y licitación vinculada | `procurement_modality.py` | — |

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
| Supabase `rigp` | Persistencia y trazabilidad; cada misión declara objetos exactos antes de mutarlos |

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
- **Estado de trabajo ≠ candidato analítico.** Persistir notas, evidencia o
  avance de un expediente no crea ni valida por sí mismo un `candidate_case`.

## Antes de entregar

```bash
PYTHONPATH=src pytest -q
python3 -c "import yaml,glob;[yaml.safe_load(open(f)) for f in glob.glob('.github/workflows/*.yml')]"
```

Editar YAML de workflows a mano es la causa más frecuente de caída en este
repositorio: una clave desalineada deja de parsear el archivo entero y GitHub
deja de mostrar el workflow por su nombre.
