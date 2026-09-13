// El expediente en el navegador.
//
// Mismo contrato que `src/radar_presupuesto/case_model.py` y que
// `schemas/011_case_management.sql`: los mismos estados, las mismas
// transiciones, la misma bitácora append-only y el mismo sobre sellado. Un
// expediente exportado aquí se verifica allá sin transformación.
//
// Antes todo esto vivía en nueve claves sueltas de localStorage, sin
// identidad ni trazabilidad de quién concluyó qué.

import { canonicalRut } from './fmt.mjs';

export const SCHEMA = 'RIGP-CASE-EXPORT-v1';
const STORE_KEY = 'rigp_cases_v2';

export const GUARDRAIL =
  'Un expediente RIGP organiza revisión documental y OSINT sobre gasto público. ' +
  'No acredita irregularidad, delito funcionario, fraude, corrupción ni lavado de activos, ' +
  'y no atribuye responsabilidad a ninguna persona o entidad. Las conclusiones que contenga ' +
  'son del analista que las firma, no del radar.';

export const CASE_STATES = {
  ABIERTO: 'Creado desde un hallazgo priorizado; todavía sin trabajo de análisis.',
  EN_REVISION: 'Un analista lo está trabajando.',
  EN_ESPERA_DOCUMENTO: 'Detenido a la espera de un documento solicitado.',
  ESCALADO: 'Derivado a una instancia superior con hipótesis formulada.',
  CERRADO_EXPLICADO: 'El patrón tiene explicación documentada y no amerita seguir.',
  CERRADO_SIN_MERITO: 'Revisado y descartado por falta de mérito investigativo.',
};

export const STATE_LABEL = {
  ABIERTO: 'Abierto',
  EN_REVISION: 'En revisión',
  EN_ESPERA_DOCUMENTO: 'Esperando documento',
  ESCALADO: 'Escalado',
  CERRADO_EXPLICADO: 'Cerrado · explicado',
  CERRADO_SIN_MERITO: 'Cerrado · sin mérito',
};

export const TRANSITIONS = {
  ABIERTO: ['EN_REVISION', 'CERRADO_SIN_MERITO'],
  EN_REVISION: ['EN_ESPERA_DOCUMENTO', 'ESCALADO', 'CERRADO_EXPLICADO', 'CERRADO_SIN_MERITO'],
  EN_ESPERA_DOCUMENTO: ['EN_REVISION', 'ESCALADO', 'CERRADO_EXPLICADO', 'CERRADO_SIN_MERITO'],
  ESCALADO: ['EN_REVISION', 'CERRADO_EXPLICADO'],
  CERRADO_EXPLICADO: ['EN_REVISION'],
  CERRADO_SIN_MERITO: ['EN_REVISION'],
};

export const CLOSING_STATES = new Set(['CERRADO_EXPLICADO', 'CERRADO_SIN_MERITO']);
export const OPEN_STATES = new Set([
  'ABIERTO', 'EN_REVISION', 'EN_ESPERA_DOCUMENTO', 'ESCALADO',
]);

export const EVIDENCE_KINDS = {
  DOCUMENTO_OFICIAL: 'Documento oficial',
  REGISTRO_PUBLICO: 'Registro público',
  PUBLICACION_PRENSA: 'Publicación de prensa',
  CAPTURA_SISTEMA: 'Captura de sistema',
  ANALISIS_PROPIO: 'Análisis propio',
  RESPUESTA_TRANSPARENCIA: 'Respuesta de transparencia',
};

// Las cuatro etapas se conservan tal como estaban: decir qué no se sabe es lo
// que hace defendible el expediente.
export const VERIFICATION_CHAIN = [
  { stage: 1, name: 'Receptor económico directo', status: 'DISPONIBLE',
    meaning: 'Persona o sociedad que aparece como proveedor o receptor de recursos públicos.' },
  { stage: 2, name: 'Propiedad, control y administración', status: 'POR_INTEGRAR',
    meaning: 'Socios, accionistas, controladores, representantes legales o directores del periodo.' },
  { stage: 3, name: 'Personas y sociedades vinculadas', status: 'POR_VERIFICAR',
    meaning: 'Vínculos documentados que extiendan la trazabilidad más allá del receptor directo.' },
  { stage: 4, name: 'Beneficio final', status: 'NO_DETERMINADO',
    meaning: 'Sólo puede atribuirse con evidencia de propiedad, control o disposición del valor.' },
];

// La ruta guiada de cuatro pasos se conserva como columna narrativa del caso.
export const CASE_STAGES = [
  { key: 'priorizar', n: 1, title: 'Priorizar', question: '¿Por qué esta relación y no otra?' },
  { key: 'investigar', n: 2, title: 'Investigar', question: '¿Qué hechos y documentos sostienen el patrón?' },
  { key: 'actores', n: 3, title: 'Actores', question: '¿Quién decidió, quién controla, qué vínculos están confirmados?' },
  { key: 'beneficio', n: 4, title: 'Beneficio', question: '¿Quién recibió o dispuso del valor y con qué nexo documentado?' },
];

const encoder = new TextEncoder();

function nowIso() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, '+00:00');
}

/** Serialización idéntica a la de Python, para que el hash viaje entre ambos. */
export function canonicalJson(value) {
  const normalize = (item) => {
    if (Array.isArray(item)) return item.map(normalize);
    if (item && typeof item === 'object') {
      return Object.keys(item)
        .sort()
        .reduce((acc, key) => {
          acc[key] = normalize(item[key]);
          return acc;
        }, {});
    }
    return item;
  };
  return JSON.stringify(normalize(value));
}

async function sha256Hex(text) {
  if (globalThis.crypto?.subtle) {
    const digest = await globalThis.crypto.subtle.digest('SHA-256', encoder.encode(text));
    return Array.from(new Uint8Array(digest))
      .map((b) => b.toString(16).padStart(2, '0'))
      .join('');
  }
  return '';
}

export async function contentHash(caseRecord) {
  return sha256Hex(canonicalJson(caseRecord));
}

async function shortDigest(...parts) {
  const hex = await sha256Hex(parts.map((p) => (p == null ? '' : String(p))).join('|'));
  return hex.slice(0, 20).toUpperCase();
}

export async function caseId(organizationId, providerId, periodo) {
  return `CASO-RIGP-${await shortDigest(organizationId, providerId, periodo)}`;
}

export async function newCase(seed, owner = '') {
  const now = nowIso();
  return {
    case_id: await caseId(seed.organization_id, seed.provider_id, seed.periodo),
    state: 'ABIERTO',
    opened_at: now,
    updated_at: now,
    owner,
    focus: {
      organization_id: seed.organization_id,
      organization_name: seed.organization_name || '',
      provider_id: seed.provider_id,
      provider_name: seed.provider_name || '',
      periodo: seed.periodo,
      finding_id: seed.finding_id || '',
    },
    scores: {
      review_priority_score: Number(seed.review_priority_score || 0),
      laft_compatibility_score: Number(seed.laft_compatibility_score || 0),
    },
    opacity_level: seed.opacity_level || 'TRAZABLE',
    hypothesis: {
      typology: seed.top_typology || '',
      statement: '',
      formulated_at: '',
      formulated_by: '',
    },
    source_signals: Array.isArray(seed.observed_patterns) ? [...seed.observed_patterns] : [],
    entities: [],
    evidence: [],
    notes: [],
    decisions: [],
    verification_chain: VERIFICATION_CHAIN.map((stage) => ({ ...stage })),
  };
}

export function canTransition(from, to) {
  return (TRANSITIONS[from] || []).includes(to);
}

export function applyDecision(caseRecord, { toState, rationale = '', actor = '' }) {
  const from = caseRecord.state;
  if (!CASE_STATES[toState]) throw new Error(`Estado desconocido: ${toState}`);
  if (!canTransition(from, toState)) {
    throw new Error(`Transición no permitida: ${STATE_LABEL[from]} → ${STATE_LABEL[toState]}`);
  }
  if (CLOSING_STATES.has(toState) && !rationale.trim()) {
    throw new Error('Cerrar un expediente exige escribir el motivo.');
  }
  if (toState === 'ESCALADO' && !(caseRecord.hypothesis?.statement || '').trim()) {
    throw new Error('Escalar exige una hipótesis formulada.');
  }
  caseRecord.decisions.push({
    decision_id: `DEC-${from}-${toState}-${caseRecord.decisions.length}`,
    at: nowIso(),
    actor,
    from_state: from,
    to_state: toState,
    rationale,
  });
  caseRecord.state = toState;
  caseRecord.updated_at = nowIso();
  return caseRecord;
}

export function setHypothesis(caseRecord, { typology, statement, author = '' }) {
  if (!statement.trim()) throw new Error('La hipótesis requiere un enunciado.');
  caseRecord.hypothesis = {
    typology: typology || '',
    statement,
    formulated_at: nowIso(),
    formulated_by: author,
  };
  caseRecord.updated_at = nowIso();
  return caseRecord;
}

export function addNote(caseRecord, text, author = '') {
  if (!text.trim()) throw new Error('Una nota vacía no aporta al expediente.');
  caseRecord.notes.push({
    note_id: `NT-${caseRecord.notes.length}`,
    text,
    author,
    at: nowIso(),
  });
  caseRecord.updated_at = nowIso();
  return caseRecord;
}

export function addEvidence(caseRecord, evidence) {
  if (!EVIDENCE_KINDS[evidence.kind]) throw new Error('Tipo de evidencia desconocido.');
  if (!(evidence.title || '').trim()) throw new Error('La evidencia requiere un título.');
  caseRecord.evidence.push({
    evidence_id: `EV-${caseRecord.evidence.length}`,
    kind: evidence.kind,
    title: evidence.title,
    source_url: evidence.source_url || '',
    captured_at: evidence.captured_at || nowIso(),
    sha256: evidence.sha256 || '',
    note: evidence.note || '',
    added_by: evidence.added_by || caseRecord.owner || '',
    added_at: nowIso(),
  });
  caseRecord.updated_at = nowIso();
  return caseRecord;
}

export function addEntity(caseRecord, entity) {
  const rut = canonicalRut(entity.rut || '');
  caseRecord.entities.push({
    entity_id: entity.entity_id || (rut ? `ENT-RUT-${rut}` : `ENT-LOCAL-${caseRecord.entities.length}`),
    name: entity.name || '',
    rut,
    role: entity.role,
    // Todo vínculo nace CANDIDATE; sólo un analista puede confirmarlo.
    identity_status: rut ? 'RESOLVED' : 'UNRESOLVED',
    link_status: 'CANDIDATE',
    source: entity.source || '',
    added_at: nowIso(),
  });
  caseRecord.updated_at = nowIso();
  return caseRecord;
}

export async function seal(caseRecord, exportedBy = '') {
  return {
    schema: SCHEMA,
    exported_at: nowIso(),
    exported_by: exportedBy,
    generator: 'RIGP',
    guardrail: GUARDRAIL,
    integrity: { algorithm: 'SHA-256', content_sha256: await contentHash(caseRecord) },
    case: caseRecord,
  };
}

export async function verify(envelope) {
  const problems = [];
  if (envelope?.schema !== SCHEMA) problems.push(`Esquema inesperado: ${envelope?.schema}`);
  const record = envelope?.case;
  if (!record || typeof record !== 'object') {
    return { valid: false, problems: [...problems, 'El sobre no contiene un expediente.'] };
  }
  const declared = envelope?.integrity?.content_sha256 || '';
  const actual = await contentHash(record);
  if (actual && declared !== actual) problems.push('El hash de integridad no corresponde al contenido.');
  let state = 'ABIERTO';
  for (const decision of record.decisions || []) {
    if (decision.from_state !== state) {
      problems.push(`La traza de decisiones se rompe en ${decision.decision_id}.`);
      break;
    }
    if (!canTransition(state, decision.to_state)) {
      problems.push(`Transición no permitida registrada: ${state} → ${decision.to_state}`);
      break;
    }
    if (CLOSING_STATES.has(decision.to_state) && !(decision.rationale || '').trim()) {
      problems.push('Hay un cierre sin motivo registrado.');
    }
    state = decision.to_state;
  }
  return {
    valid: problems.length === 0,
    problems,
    case_id: record.case_id,
    state: record.state,
    decisions: (record.decisions || []).length,
    evidence: (record.evidence || []).length,
    content_sha256: actual,
  };
}

// --- Persistencia local -----------------------------------------------------

const listeners = new Set();
let state = { version: 2, owner: '', cases: {} };

function read() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === 'object' && parsed.cases) return parsed;
  } catch {
    /* almacenamiento no disponible: la app sigue funcionando en memoria */
  }
  return null;
}

function write() {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(state));
  } catch {
    /* cuota o modo privado: no se pierde la sesión en curso */
  }
}

/**
 * Recupera el trabajo guardado por la versión anterior.
 * Las nueve claves sueltas se consolidan en expedientes reales en vez de
 * descartarse, y la migración queda registrada en la bitácora del caso.
 */
const LEGACY_KEYS = [
  'rigp_findings_review_v1', 'rigp_benefit_links_v1', 'rigp_benefit_value_evidence_v1',
  'rigp_benefit_causal_links_v1', 'rigp_decision_actors_v1', 'rigp_cross_side_links_v1',
  'rigp_integrity_basis_evidence_v1', 'rigp_societary_checks_v1',
];

const LEGACY_STATE = {
  PENDIENTE: 'ABIERTO',
  EN_REVISION: 'EN_REVISION',
  PROFUNDIZAR: 'EN_REVISION',
  EXPLICADO: 'CERRADO_EXPLICADO',
  ESCALADO: 'ESCALADO',
};

export function legacyPayload() {
  const found = {};
  for (const key of LEGACY_KEYS) {
    try {
      const raw = localStorage.getItem(key);
      if (!raw) continue;
      const parsed = JSON.parse(raw);
      if (parsed && Object.keys(parsed).length) found[key] = parsed;
    } catch {
      /* clave ilegible: se ignora sin romper la migración */
    }
  }
  return found;
}

export async function migrateLegacy(seedsById = {}) {
  const legacy = legacyPayload();
  const reviews = legacy.rigp_findings_review_v1 || {};
  let imported = 0;
  for (const [findingId, review] of Object.entries(reviews)) {
    const parts = String(findingId).split('|');
    const seed = seedsById[findingId] || {
      organization_id: parts[0] || findingId,
      provider_id: parts[1] || '',
      periodo: Number(parts[2] || 0),
      finding_id: findingId,
    };
    const record = await newCase(seed, state.owner);
    if (state.cases[record.case_id]) continue;
    const target = LEGACY_STATE[review.status] || 'ABIERTO';
    if (target !== 'ABIERTO' && canTransition('ABIERTO', target)) {
      applyDecision(record, {
        toState: target,
        rationale: review.rationale || 'Importado desde la revisión guardada en la versión anterior.',
        actor: review.reviewer || 'migración',
      });
    } else if (target !== 'ABIERTO') {
      applyDecision(record, {
        toState: 'EN_REVISION',
        rationale: 'Importado desde la revisión guardada en la versión anterior.',
        actor: 'migración',
      });
      if (canTransition('EN_REVISION', target)) {
        applyDecision(record, {
          toState: target,
          rationale: review.rationale || 'Estado recuperado de la versión anterior.',
          actor: review.reviewer || 'migración',
        });
      }
    }
    if (review.note) addNote(record, review.note, review.reviewer || 'migración');
    state.cases[record.case_id] = record;
    imported += 1;
  }
  if (imported) {
    state.migrated_at = nowIso();
    commit();
  }
  return { imported, legacyKeys: Object.keys(legacy) };
}

export function init() {
  state = read() || state;
  return state;
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function commit() {
  write();
  listeners.forEach((fn) => fn(state));
}

export const store = {
  get owner() {
    return state.owner || '';
  },
  setOwner(owner) {
    state.owner = owner;
    commit();
  },
  all() {
    return Object.values(state.cases);
  },
  get(id) {
    return state.cases[id] || null;
  },
  byFocus(organizationId, providerId, periodo) {
    return this.all().find(
      (c) =>
        c.focus.organization_id === organizationId &&
        c.focus.provider_id === providerId &&
        String(c.focus.periodo) === String(periodo),
    ) || null;
  },
  async open(seed) {
    const existing = this.byFocus(seed.organization_id, seed.provider_id, seed.periodo);
    if (existing) return existing;
    const record = await newCase(seed, state.owner);
    state.cases[record.case_id] = record;
    commit();
    return record;
  },
  update(id, mutate) {
    const record = state.cases[id];
    if (!record) throw new Error('Expediente no encontrado.');
    mutate(record);
    commit();
    return record;
  },
  /** Inserta un expediente ya verificado (llegado desde otro analista). */
  put(record) {
    state.cases[record.case_id] = record;
    commit();
    return record;
  },
  remove(id) {
    delete state.cases[id];
    commit();
  },
  snapshot() {
    return state;
  },
};
