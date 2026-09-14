// 02 · Caso. Absorbe seis destinos de la versión anterior en una vista con
// pestañas, y conserva la ruta guiada de cuatro pasos como columna narrativa.

import {
  CASE_STAGES, CASE_STATES, CLOSING_STATES, EVIDENCE_KINDS, STATE_LABEL, TRANSITIONS, store,
} from '../cases.mjs';
import {
  ACTIONABILITY_LABEL, ACTIONABILITY_TONE, ALIGNMENT_TONE, OPACITY_TONE, STATE_TONE,
  axes, chip, definitionList, esc, evidenceCeilingNote, guardrail, money, notice, num,
  pct, reasoningBlocks,
} from '../ui.mjs';
import { dateTime, formatRut } from '../fmt.mjs';

export const state = { tab: 'resumen' };

const TABS = [
  ['resumen', 'Resumen'],
  ['compra', 'Proceso de compra'],
  ['dinero', 'Flujo de dinero'],
  ['actores', 'Actores y propiedad'],
  ['evidencia', 'Evidencia'],
  ['bitacora', 'Bitácora'],
];

/** Etapa alcanzada: se deriva de lo acreditado, no de dónde hizo clic el usuario. */
export function stageOf(record) {
  if ((record.entities || []).some((e) => e.link_status === 'CONFIRMED')) return 'beneficio';
  if ((record.entities || []).length) return 'actores';
  if ((record.evidence || []).length || (record.hypothesis?.statement || '').trim()) return 'investigar';
  return 'priorizar';
}

export function render(ctx, caseId) {
  const record = store.get(caseId);
  if (!record) {
    return `<div class="stack"><div class="empty">
      <h3>Ese expediente ya no existe</h3>
      <p>Puede haber sido eliminado o abierto en otro navegador.</p>
      <button class="btn primary" data-nav="triage">Volver al triage</button>
    </div></div>`;
  }
  const relation = findRelation(ctx, record);
  const typology = topTypology(relation);

  return `<div class="stack">
    ${header(record, relation)}
    ${stages(record)}
    <div class="tabs">
      ${TABS.map(([key, label]) =>
        `<button data-case-tab="${key}" class="${state.tab === key ? 'on' : ''}">${esc(label)}</button>`).join('')}
    </div>
    ${body(ctx, record, relation, typology)}
    ${guardrail(ctx.triage.guardrail)}
  </div>`;
}

function header(record, relation) {
  const focus = record.focus;
  const transitions = TRANSITIONS[record.state] || [];
  return `<div class="pagehead">
    <span class="eyebrow">Expediente · <span class="mono">${esc(record.case_id)}</span></span>
    <div class="row">
      <h2>${esc(focus.organization_name || focus.organization_id)}</h2>
      ${chip(STATE_LABEL[record.state], STATE_TONE[record.state] || 'bare')}
      ${relation ? chip(`LA/FT ${relation.laft_alignment}`, ALIGNMENT_TONE[relation.laft_alignment] || 'bare') : ''}
      ${relation ? chip(relation.opacity_level, OPACITY_TONE[relation.opacity_level] || 'bare') : ''}
      ${relation?.actionability
        ? chip(ACTIONABILITY_LABEL[relation.actionability] || relation.actionability,
               ACTIONABILITY_TONE[relation.actionability] || 'bare')
        : ''}
    </div>
    <p class="lede">
      ${esc(focus.provider_name || focus.provider_id)} · periodo ${esc(focus.periodo)}
      ${focus.provider_id?.includes('RUT-') ? ` · <span class="mono">${esc(formatRut(focus.provider_id.split('RUT-')[1]))}</span>` : ''}
    </p>
    <div class="filters">
      ${transitions.map((to) =>
        `<button class="btn small ${CLOSING_STATES.has(to) ? '' : 'primary'}" data-transition="${esc(to)}">
           ${esc(STATE_LABEL[to])}
         </button>`).join('')}
      <button class="btn small" data-export-case>Exportar expediente</button>
      <button class="btn small" data-nav="informe">Ver informe</button>
    </div>
  </div>`;
}

function stages(record) {
  const current = stageOf(record);
  const index = CASE_STAGES.findIndex((s) => s.key === current);
  return `<div class="stages">
    ${CASE_STAGES.map((stage, i) => `<div class="st ${i === index ? 'on' : ''}">
      <span class="n">${i < index ? '✓' : stage.n} · ${esc(stage.title)}</span>
      <b>${esc(stage.question)}</b>
    </div>`).join('')}
  </div>`;
}

function body(ctx, record, relation, typology) {
  switch (state.tab) {
    case 'compra': return tabProcurement(ctx, record, relation);
    case 'dinero': return tabMoney(ctx, record, relation);
    case 'actores': return tabActors(ctx, record, relation);
    case 'evidencia': return tabEvidence(record);
    case 'bitacora': return tabLog(record);
    default: return tabSummary(ctx, record, relation, typology);
  }
}

// --- Resumen ----------------------------------------------------------------

function tabSummary(ctx, record, relation, typology) {
  const hypothesis = record.hypothesis || {};
  return `<div class="stack">
    ${relation?.actionability && relation.actionability !== 'ACCIONABLE'
      ? notice(
          ACTIONABILITY_LABEL[relation.actionability] || relation.actionability,
          esc(relation.actionability_why || ''),
          relation.actionability === 'SOLO_APRENDIZAJE' ? '' : 'warn',
        )
      : ''}

    <section class="grid k2">
      <div class="card">
        <span class="eyebrow">Los dos ejes</span>
        ${axes(
          record.scores?.review_priority_score,
          record.scores?.laft_compatibility_score,
          relation?.laft_alignment || 'NULO',
        )}
        ${relation?.priority_explanation
          ? `<p class="muted" style="font-size:.82rem">${esc(relation.priority_explanation)}</p>`
          : ''}
      </div>
      <div class="card">
        <span class="eyebrow">Qué se observó</span>
        ${relation
          ? `<ul style="margin:0;padding-left:1.05em;display:flex;flex-direction:column;gap:5px;font-size:.87rem">
               ${(relation.signal_labels || []).map((s) => `<li>${esc(s)}</li>`).join('')}
               ${(relation.entity_signals || []).map((s) =>
                 `<li>${esc(s.why)} <span class="muted">(${esc(s.signal_type)})</span></li>`).join('')}
             </ul>`
          : '<p class="muted">El hallazgo de origen ya no está en la cola publicada.</p>'}
      </div>
    </section>

    <section class="card">
      <span class="eyebrow">Hipótesis de trabajo</span>
      ${hypothesis.statement
        ? `<p>${esc(hypothesis.statement)}</p>
           <p class="muted" style="font-size:.8rem">
             ${esc(hypothesis.typology?.replace(/_/g, ' ') || 'Sin tipología')} ·
             ${esc(dateTime(hypothesis.formulated_at))} · ${esc(hypothesis.formulated_by || 'sin firma')}
           </p>`
        : `<p class="muted">Sin formular. Escalar el expediente exige una hipótesis escrita.</p>`}
      <form class="form" data-hypothesis-form>
        <div class="formrow">
          <label>Tipología
            <select name="typology">
              <option value="">Sin tipología</option>
              ${(ctx.triage.typology_catalog || []).map((t) =>
                `<option value="${esc(t.code)}"${hypothesis.typology === t.code ? ' selected' : ''}>${esc(t.name)}</option>`).join('')}
            </select>
          </label>
        </div>
        <label>Enunciado
          <textarea name="statement" placeholder="Qué se sostiene, sobre qué hechos y qué faltaría para confirmarlo o descartarlo.">${esc(hypothesis.statement || '')}</textarea>
        </label>
        <div><button class="btn primary small" type="submit">Guardar hipótesis</button></div>
      </form>
    </section>

    ${typology ? `<section class="stack">
      <div class="card">
        <span class="eyebrow">Tipología · ${esc(typology.typology_name)}</span>
        <p>${esc(typology.question)}</p>
        ${(typology.matched_labels || []).length
          ? `<p class="muted" style="font-size:.85rem">Patrones presentes: ${esc((typology.matched_labels || []).join(' · '))}</p>`
          : ''}
      </div>
      ${evidenceCeilingNote(typology)}
      ${reasoningBlocks(typology)}
    </section>` : ''}

    <section class="card">
      <span class="eyebrow">Cadena de verificación</span>
      <p class="muted" style="font-size:.85rem">
        Decir qué no se sabe es lo que hace defendible el expediente.
      </p>
      ${definitionList((record.verification_chain || []).map((stage) => [
        `Etapa ${stage.stage}`,
        `<b>${esc(stage.name)}</b> — ${chip(stage.status.replace(/_/g, ' '), stage.status === 'DISPONIBLE' ? 'good' : 'warn')}
         <br><span class="muted">${esc(stage.meaning)}</span>`,
      ]))}
    </section>
  </div>`;
}

// --- Proceso de compra ------------------------------------------------------

function tabProcurement(ctx, record, relation) {
  const status = ctx.context.procurement;
  const integrated = status?.integration_state === 'SNAPSHOT_PRESENT';
  if (!integrated) {
    return `<div class="stack">
      ${notice(
        'El proceso de compra todavía no está integrado',
        'Presupuesto Abierto responde a quién se le pagó, no cómo se decidió contratarle. ' +
        'El adaptador de Mercado Público está construido y unido por <code>orden_compra</code>, ' +
        'pero falta conectar el feed. Mientras tanto, las tipologías que dependen de competencia, ' +
        'modalidad o umbrales no pueden alcanzar su puntaje máximo.',
        'warn',
      )}
      <section class="card">
        <span class="eyebrow">Qué aportará esta pestaña cuando se conecte</span>
        <ul style="margin:0;padding-left:1.05em;display:flex;flex-direction:column;gap:5px;font-size:.88rem">
          ${(status?.detectors || []).map((d) => `<li class="mono">${esc(d)}</li>`).join('')}
        </ul>
        ${status?.threshold_note ? `<p class="muted" style="font-size:.82rem">${esc(status.threshold_note)}</p>` : ''}
      </section>
      ${coverageCard(status)}
    </div>`;
  }
  return `<div class="stack">${coverageCard(status)}</div>`;
}

function coverageCard(status) {
  const coverage = status?.coverage || {};
  return `<section class="card">
    <span class="eyebrow">Trazabilidad documental del gasto</span>
    ${definitionList([
      ['Con orden de compra', `${esc(pct(coverage.purchase_order_amount_share, 1))} del monto`],
      ['Unido a un proceso', coverage.snapshot_available
        ? `${esc(pct(coverage.procurement_match_share, 1))} de lo que trae orden de compra`
        : 'Sin snapshot de compras'],
      ['Llave de unión', `<code>${esc(status?.join_key || 'orden_compra')}</code>`],
    ])}
    <p class="muted" style="font-size:.82rem">
      Un pago material sin orden de compra asociada no tiene proceso que pedir: eso cambia qué
      puede exigir el analista.
    </p>
  </section>`;
}

// --- Flujo de dinero --------------------------------------------------------

function tabMoney(ctx, record, relation) {
  const explore = ctx.context.explore || {};
  const key = `${record.focus.organization_id}|${record.focus.provider_id}`;
  const rel = (explore.relations || {})[key] || {};
  const provider = (explore.providers || {})[record.focus.provider_id] || {};
  const yearly = rel.yearly || [];

  return `<div class="stack">
    <section class="grid k3">
      <div class="card tile"><span class="k">Monto de la relación</span>
        <span class="v">${esc(money(relation?.relation_amount || rel.amount_clp || 0))}</span>
        <span class="s">en los años publicados</span></div>
      <div class="card tile"><span class="k">Gasto público total del proveedor</span>
        <span class="v">${esc(money(relation?.provider_total_spend || 0))}</span>
        <span class="s">todos los servicios</span></div>
      <div class="card tile"><span class="k">Transacción mayor</span>
        <span class="v">${esc(money(relation?.max_transaction_amount || 0))}</span>
        <span class="s">del hallazgo</span></div>
    </section>

    ${yearly.length
      ? `<div class="tablewrap"><table>
           <thead><tr><th>Año</th><th class="num">Monto</th></tr></thead>
           <tbody>${yearly.map((y) =>
             `<tr><td>${esc(y.periodo ?? y.year ?? '—')}</td>
                  <td class="num">${esc(money(y.amount_clp))}</td></tr>`).join('')}</tbody>
         </table></div>`
      : notice('Sin desglose anual publicado',
          'El contexto compacto no trae serie anual para esta relación. El monto agregado sí está disponible.')}

    ${(provider.top_services || []).length
      ? `<section class="card">
           <span class="eyebrow">Dónde más cobra este proveedor</span>
           <div class="tablewrap"><table>
             <thead><tr><th>Servicio</th><th class="num">Monto</th></tr></thead>
             <tbody>${provider.top_services.slice(0, 8).map((s) =>
               `<tr><td>${esc(s.organization_name || s.organization_id)}</td>
                    <td class="num">${esc(money(s.amount_clp))}</td></tr>`).join('')}</tbody>
           </table></div>
         </section>`
      : ''}
  </div>`;
}

// --- Actores y propiedad ----------------------------------------------------

function tabActors(ctx, record, relation) {
  const entities = record.entities || [];
  return `<div class="stack">
    ${notice(
      'Propiedad y control no están integrados',
      'Las fuentes publicadas no traen socios, controladores ni representantes legales. ' +
      'Todo vínculo que registres aquí nace como <b>CANDIDATO</b> y sólo tú puedes confirmarlo, ' +
      'dejando constancia de la fuente.',
      'warn',
    )}

    ${entities.length
      ? `<div class="tablewrap"><table>
           <thead><tr><th>Actor</th><th>Rol</th><th>Identidad</th><th>Vínculo</th><th>Fuente</th><th></th></tr></thead>
           <tbody>${entities.map((e, i) => `<tr>
             <td><div class="cellmain"><b>${esc(e.name || e.entity_id)}</b>
               ${e.rut ? `<small class="mono">${esc(formatRut(e.rut))}</small>` : ''}</div></td>
             <td>${esc(e.role)}</td>
             <td>${chip(e.identity_status === 'RESOLVED' ? 'RUT validado' : 'Sin RUT', e.identity_status === 'RESOLVED' ? 'good' : 'warn')}</td>
             <td>${chip(e.link_status, e.link_status === 'CONFIRMED' ? 'good' : 'bare')}</td>
             <td><small>${esc(e.source || '—')}</small></td>
             <td>${e.link_status === 'CANDIDATE'
               ? `<button class="btn small" data-confirm-entity="${i}">Confirmar vínculo</button>`
               : ''}</td>
           </tr>`).join('')}</tbody>
         </table></div>`
      : `<p class="muted">Todavía no registras actores en este expediente.</p>`}

    <section class="card">
      <span class="eyebrow">Registrar un actor</span>
      <form class="form" data-entity-form>
        <div class="formrow">
          <label>Nombre<input name="name" placeholder="Nombre o razón social" required></label>
          <label>RUT<input name="rut" placeholder="76.071.943-9" inputmode="text"></label>
          <label>Rol
            <select name="role">
              <option value="SOCIO">Socio o accionista</option>
              <option value="REPRESENTANTE_LEGAL">Representante legal</option>
              <option value="CONTROLADOR">Controlador</option>
              <option value="DIRECTOR">Director o administrador</option>
              <option value="DECISOR_PUBLICO">Decisor público</option>
              <option value="SOCIEDAD_VINCULADA">Sociedad vinculada</option>
            </select>
          </label>
        </div>
        <label>Fuente<input name="source" placeholder="Dónde consta el vínculo (URL, registro, documento)"></label>
        <div><button class="btn primary small" type="submit">Agregar como candidato</button></div>
      </form>
      <p class="muted" style="font-size:.8rem">
        El RUT sólo se guarda si su dígito verificador valida. Sin RUT, el actor queda con identidad sin resolver.
      </p>
    </section>
  </div>`;
}

// --- Evidencia --------------------------------------------------------------

function tabEvidence(record) {
  const evidence = record.evidence || [];
  return `<div class="stack">
    ${evidence.length
      ? `<div class="tablewrap"><table>
          <thead><tr><th>Evidencia</th><th>Tipo</th><th>Capturada</th><th>Hash</th><th>Quién</th></tr></thead>
          <tbody>${evidence.map((e) => `<tr>
            <td><div class="cellmain"><b>${esc(e.title)}</b>
              ${e.source_url ? `<small><a href="${esc(e.source_url)}" target="_blank" rel="noopener">${esc(e.source_url.slice(0, 60))}</a></small>` : ''}
              ${e.note ? `<small class="muted">${esc(e.note)}</small>` : ''}</div></td>
            <td><small>${esc(EVIDENCE_KINDS[e.kind] || e.kind)}</small></td>
            <td><small>${esc(dateTime(e.captured_at))}</small></td>
            <td><small class="mono">${esc((e.sha256 || '—').slice(0, 16))}</small></td>
            <td><small>${esc(e.added_by || '—')}</small></td>
          </tr>`).join('')}</tbody>
        </table></div>`
      : `<p class="muted">Sin evidencia incorporada. Cada pieza queda con fuente, fecha de captura y autor.</p>`}

    <section class="card">
      <span class="eyebrow">Incorporar evidencia</span>
      <form class="form" data-evidence-form>
        <div class="formrow">
          <label>Título<input name="title" placeholder="Qué documento es" required></label>
          <label>Tipo
            <select name="kind">
              ${Object.entries(EVIDENCE_KINDS).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join('')}
            </select>
          </label>
        </div>
        <div class="formrow">
          <label>URL de origen<input name="source_url" placeholder="https://…"></label>
          <label>SHA-256 del archivo<input name="sha256" placeholder="opcional, para acreditar integridad"></label>
        </div>
        <label>Nota<textarea name="note" placeholder="Qué acredita y qué no."></textarea></label>
        <div><button class="btn primary small" type="submit">Agregar evidencia</button></div>
      </form>
    </section>

    <section class="card">
      <span class="eyebrow">Nota de trabajo</span>
      <form class="form" data-note-form>
        <label><textarea name="text" placeholder="Observación, pendiente o resultado de una gestión."></textarea></label>
        <div><button class="btn small" type="submit">Agregar nota</button></div>
      </form>
    </section>
  </div>`;
}

// --- Bitácora ---------------------------------------------------------------

function tabLog(record) {
  const items = [
    ...(record.decisions || []).map((d) => ({
      at: d.at,
      title: `${STATE_LABEL[d.from_state] || d.from_state} → ${STATE_LABEL[d.to_state] || d.to_state}`,
      why: d.rationale,
      who: d.actor,
      tone: CLOSING_STATES.has(d.to_state) ? 'good' : 'accent',
    })),
    ...(record.notes || []).map((n) => ({ at: n.at, title: 'Nota', why: n.text, who: n.author, tone: 'bare' })),
    ...(record.evidence || []).map((e) => ({
      at: e.added_at, title: `Evidencia · ${EVIDENCE_KINDS[e.kind] || e.kind}`, why: e.title, who: e.added_by, tone: 'info',
    })),
    ...(record.entities || []).map((e) => ({
      at: e.added_at, title: `Actor · ${e.role}`, why: `${e.name} (${e.link_status})`, who: '', tone: 'info',
    })),
  ].sort((a, b) => new Date(b.at) - new Date(a.at));

  return `<div class="stack">
    <p class="muted" style="font-size:.86rem">
      La bitácora sólo crece: es la cadena de custodia del expediente y viaja con él al exportarlo.
    </p>
    <section class="card"><div class="log">
      ${items.length
        ? items.map((i) => `<div class="item">
            <span class="when">${esc(dateTime(i.at))}</span>
            <span class="what">
              <span>${chip(i.title, i.tone, { plain: true })}</span>
              ${i.why ? `<span class="why">${esc(i.why)}</span>` : ''}
              ${i.who ? `<span class="muted" style="font-size:.78rem">${esc(i.who)}</span>` : ''}
            </span>
          </div>`).join('')
        : '<p class="muted">Sin movimientos registrados.</p>'}
    </div></section>
  </div>`;
}

// --- helpers ----------------------------------------------------------------

export function findRelation(ctx, record) {
  return ctx.triage.relations.find(
    (r) =>
      r.organization_id === record.focus.organization_id &&
      r.provider_id === record.focus.provider_id &&
      String(r.periodo) === String(record.focus.periodo),
  ) || null;
}

export function topTypology(relation) {
  if (!relation) return null;
  return (relation.typologies || [])[0] || null;
}
