// Arranque, enrutado y delegación de eventos.
//
// Un solo punto de entrada y un solo store. La versión anterior coordinaba
// quince módulos aislados simulando clicks entre ellos; aquí las vistas piden
// un repintado y nada más.

import { loadContext, loadEnrichment, loadTriage } from './data.mjs';
import { navigate, onRoute, parseHash, start } from './router.mjs';
import {
  CLOSING_STATES, STATE_LABEL, addEntity, addEvidence, addNote, applyDecision,
  init as initCases, migrateLegacy, seal, setHypothesis, store, subscribe, verify,
} from './cases.mjs';
import { downloadJson, downloadText, esc, toast } from './ui.mjs';
import * as inbox from './views/inbox.mjs';
import * as triage from './views/triage.mjs';
import * as caseview from './views/caseview.mjs';
import * as entity from './views/entity.mjs';
import * as report from './views/report.mjs';

const NAV = [
  ['bandeja', 'Mi bandeja'],
  ['triage', 'Triage'],
  ['caso', 'Caso'],
  ['entidad', 'Entidad'],
  ['informe', 'Informe'],
];

const app = {
  ctx: null,
  route: parseHash(),
  lastCaseId: '',
  lastEntity: '',
};

const el = (id) => document.getElementById(id);

async function boot() {
  initCases();
  try {
    const [triagePayload, context] = await Promise.all([loadTriage(), loadContext()]);
    const enrichment = await loadEnrichment();
    app.ctx = { triage: triagePayload, context, enrichment };
  } catch (error) {
    el('app').innerHTML = `<main class="page"><div class="empty">
      <h3>No fue posible cargar los hallazgos</h3>
      <p>${esc(error.message)}</p>
      <p class="muted">Si el sitio se acaba de publicar, vuelve a intentar en unos segundos.</p>
    </div></main>`;
    return;
  }

  const seeds = Object.fromEntries(app.ctx.triage.relations.map((r) => [r.finding_id, r]));
  app.ctx.migration = await migrateLegacy(seeds);

  subscribe(() => paint());
  onRoute((route) => {
    app.route = route;
    if (route.view === 'caso' && route.id) app.lastCaseId = route.id;
    if (route.view === 'entidad' && route.id) app.lastEntity = route.id;
    paint();
  });
  start();
}

function paint() {
  if (!app.ctx) return;
  const { view, id } = app.route;
  el('app').innerHTML = `
    ${topbar()}
    ${nav(view)}
    <main class="page" id="page">${viewHtml(view, id)}</main>
  `;
  restoreFocus();
}

function topbar() {
  const source = app.ctx.triage.source || {};
  return `<header class="topbar">
    <div class="brand"><span class="dot"></span><h1>RIGP</h1>
      <span class="muted" style="font-size:.82rem">Radar de Integridad del Gasto Público</span></div>
    <span class="spacer"></span>
    <span class="muted mono" style="font-size:.72rem">
      ${esc(source.signals_total ? `${source.signals_total.toLocaleString('es-CL')} señales analizadas` : '')}
    </span>
    <label class="owner">Analista
      <input id="ownerInput" value="${esc(store.owner)}" placeholder="tu nombre" autocomplete="off">
    </label>
  </header>`;
}

function nav(current) {
  const openCount = store.all().filter((c) => !CLOSING_STATES.has(c.state)).length;
  return `<nav class="main">${NAV.map(([key, label]) => {
    const disabled = (key === 'caso' && !app.lastCaseId) || (key === 'entidad' && !app.lastEntity);
    const count = key === 'bandeja' && openCount ? `<span class="count">${openCount}</span>` : '';
    return `<button data-nav="${key}" class="${current === key ? 'on' : ''}"${disabled ? ' disabled' : ''}>
      ${esc(label)}${count}
    </button>`;
  }).join('')}</nav>`;
}

function viewHtml(view, id) {
  switch (view) {
    case 'triage': return triage.render(app.ctx);
    case 'caso': return caseview.render(app.ctx, id || app.lastCaseId);
    case 'entidad': return entity.render(app.ctx, id || app.lastEntity);
    case 'informe': return report.render(app.ctx);
    default: return inbox.render(app.ctx);
  }
}

/** Devuelve el cursor al buscador tras repintar, para no romper el tecleo. */
let pendingFocus = null;
function restoreFocus() {
  if (!pendingFocus) return;
  const target = el(pendingFocus.id);
  if (target) {
    target.focus();
    if (target.setSelectionRange && pendingFocus.pos != null) {
      target.setSelectionRange(pendingFocus.pos, pendingFocus.pos);
    }
  }
  pendingFocus = null;
}

function rememberFocus(target) {
  pendingFocus = { id: target.id, pos: target.selectionStart };
}

// --- eventos ----------------------------------------------------------------

document.addEventListener('click', async (event) => {
  const target = event.target.closest('[data-nav],[data-open-case],[data-goto-case],[data-discard],' +
    '[data-case-tab],[data-transition],[data-export-case],[data-export-report],[data-clear-filters],' +
    '[data-confirm-entity],[data-entity-link]');
  if (!target) return;

  if (target.dataset.nav) {
    event.preventDefault();
    const view = target.dataset.nav;
    const id = view === 'caso' ? app.lastCaseId : view === 'entidad' ? app.lastEntity : '';
    navigate(view, id);
    return;
  }

  if (target.dataset.openCase) {
    const relation = app.ctx.triage.relations.find((r) => r.finding_id === target.dataset.openCase);
    if (!relation) return;
    const record = await store.open(relation);
    app.lastCaseId = record.case_id;
    if (relation.provider_rut) app.lastEntity = relation.provider_rut;
    caseview.state.tab = 'resumen';
    navigate('caso', record.case_id);
    return;
  }

  if (target.dataset.gotoCase) {
    app.lastCaseId = target.dataset.gotoCase;
    caseview.state.tab = 'resumen';
    navigate('caso', target.dataset.gotoCase);
    return;
  }

  if (target.dataset.discard) {
    const relation = app.ctx.triage.relations.find((r) => r.finding_id === target.dataset.discard);
    if (!relation) return;
    const rationale = window.prompt(
      'Motivo del descarte. Queda registrado en la bitácora y es el único insumo honesto ' +
      'para recalibrar el score:',
    );
    if (!rationale || !rationale.trim()) {
      toast('Descartar exige un motivo. No se registró nada.');
      return;
    }
    const record = await store.open(relation);
    store.update(record.case_id, (c) => {
      applyDecision(c, { toState: 'CERRADO_SIN_MERITO', rationale, actor: store.owner });
    });
    toast('Descartado con motivo registrado.');
    return;
  }

  if (target.dataset.caseTab) {
    caseview.state.tab = target.dataset.caseTab;
    paint();
    return;
  }

  if (target.dataset.transition) {
    const toState = target.dataset.transition;
    let rationale = '';
    if (CLOSING_STATES.has(toState)) {
      rationale = window.prompt(`Motivo para ${STATE_LABEL[toState]}:`) || '';
      if (!rationale.trim()) {
        toast('Cerrar un expediente exige escribir el motivo.');
        return;
      }
    } else {
      rationale = window.prompt(`Nota del cambio a ${STATE_LABEL[toState]} (opcional):`) || '';
    }
    try {
      store.update(app.lastCaseId, (c) => applyDecision(c, { toState, rationale, actor: store.owner }));
      toast(`Expediente ${STATE_LABEL[toState].toLowerCase()}.`);
    } catch (error) {
      toast(error.message);
    }
    return;
  }

  if (target.hasAttribute('data-confirm-entity')) {
    const index = Number(target.dataset.confirmEntity);
    const source = window.prompt('¿Dónde consta el vínculo? Sin fuente no se confirma:');
    if (!source || !source.trim()) {
      toast('Confirmar un vínculo exige indicar la fuente.');
      return;
    }
    store.update(app.lastCaseId, (c) => {
      const actor = c.entities[index];
      if (actor) {
        actor.link_status = 'CONFIRMED';
        actor.source = source;
        c.updated_at = new Date().toISOString();
      }
    });
    toast('Vínculo confirmado con fuente registrada.');
    return;
  }

  if (target.hasAttribute('data-export-case')) {
    const record = store.get(app.lastCaseId);
    if (record) {
      downloadJson(`${record.case_id}.json`, await seal(record, store.owner));
      toast('Expediente exportado con hash de integridad.');
    }
    return;
  }

  if (target.dataset.exportReport) {
    await exportReport(target.dataset.exportReport);
    return;
  }

  if (target.hasAttribute('data-clear-filters')) {
    Object.assign(triage.filters, {
      query: '', typology: '', alignment: '', opacity: '', year: '',
      actionability: '', hideOpened: false,
    });
    paint();
  }
});

document.addEventListener('input', (event) => {
  const target = event.target;
  if (target.id === 'ownerInput') {
    rememberFocus(target);
    store.setOwner(target.value);
    return;
  }
  if (target.id === 'triageQuery') {
    rememberFocus(target);
    triage.filters.query = target.value;
    paint();
  }
});

document.addEventListener('change', async (event) => {
  const target = event.target;
  const map = {
    triageTypology: 'typology',
    triageAlignment: 'alignment',
    triageOpacity: 'opacity',
    triageYear: 'year',
    triageActionability: 'actionability',
    triageSort: 'sort',
  };
  if (map[target.id]) {
    triage.filters[map[target.id]] = target.value;
    paint();
    return;
  }
  if (target.id === 'reportPick') {
    report.state.selected = target.value;
    paint();
    return;
  }
  if (target.id === 'reportImport' && target.files?.[0]) {
    await importCase(target.files[0]);
  }
});

document.addEventListener('click', (event) => {
  const button = event.target.closest('#triageHideOpened');
  if (!button) return;
  triage.filters.hideOpened = !triage.filters.hideOpened;
  paint();
});

document.addEventListener('submit', (event) => {
  const form = event.target;
  const data = Object.fromEntries(new FormData(form).entries());
  event.preventDefault();
  try {
    if (form.hasAttribute('data-hypothesis-form')) {
      store.update(app.lastCaseId, (c) =>
        setHypothesis(c, { typology: data.typology, statement: data.statement, author: store.owner }));
      toast('Hipótesis guardada.');
    } else if (form.hasAttribute('data-evidence-form')) {
      store.update(app.lastCaseId, (c) => addEvidence(c, { ...data, added_by: store.owner }));
      toast('Evidencia incorporada.');
    } else if (form.hasAttribute('data-note-form')) {
      store.update(app.lastCaseId, (c) => addNote(c, data.text, store.owner));
      toast('Nota agregada.');
    } else if (form.hasAttribute('data-entity-form')) {
      store.update(app.lastCaseId, (c) => addEntity(c, data));
      toast('Actor agregado como candidato.');
    }
  } catch (error) {
    toast(error.message);
  }
});

async function exportReport(kind) {
  const record = store.get(report.state.selected);
  if (kind === 'all') {
    const sealed = await Promise.all(store.all().map((c) => seal(c, store.owner)));
    downloadJson('rigp-expedientes.json', {
      schema: 'RIGP-CASE-BUNDLE-v1',
      exported_at: new Date().toISOString(),
      cases: sealed,
    });
    toast(`${sealed.length} expediente(s) exportados.`);
    return;
  }
  if (!record) return;
  if (kind === 'json') {
    downloadJson(`${record.case_id}.json`, await seal(record, store.owner));
    toast('Sobre sellado descargado.');
    return;
  }
  downloadText(`${record.case_id}.md`, report.toMarkdown(record, app.ctx));
  toast('Informe descargado.');
}

async function importCase(file) {
  try {
    const envelope = JSON.parse(await file.text());
    const envelopes = envelope.schema === 'RIGP-CASE-BUNDLE-v1' ? envelope.cases : [envelope];
    let imported = 0;
    const problems = [];
    for (const item of envelopes) {
      // Nada entra al store sin verificar el hash: un expediente editado
      // después de sellarse se rechaza y se dice por qué.
      const check = await verify(item);
      if (!check.valid) {
        problems.push(`${check.case_id || 'expediente'}: ${check.problems.join(' ')}`);
        continue;
      }
      store.put(item.case);
      imported += 1;
    }
    toast(problems.length
      ? `Importados ${imported}. Rechazados — ${problems.join(' | ')}`
      : `Importados ${imported} expediente(s) verificados.`);
  } catch (error) {
    toast(`No fue posible leer el archivo: ${error.message}`);
  }
}

boot();
