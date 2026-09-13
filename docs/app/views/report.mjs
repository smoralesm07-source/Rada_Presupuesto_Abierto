// 04 · Informe. Lo que efectivamente se entrega, y lo que permite que otro
// analista continúe el trabajo. No existía en la versión anterior.

import {
  CLOSING_STATES, EVIDENCE_KINDS, GUARDRAIL, STATE_LABEL, seal, store, verify,
} from '../cases.mjs';
import {
  chip, definitionList, emptyState, esc, guardrail, notice, num, STATE_TONE,
} from '../ui.mjs';
import { dateTime, formatRut, money } from '../fmt.mjs';

export const state = { selected: '' };

export function render(ctx) {
  const cases = store.all().sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
  if (!cases.length) {
    return `<div class="stack">
      <div class="pagehead"><span class="eyebrow">Informe</span><h2>Expediente entregable</h2></div>
      ${emptyState({
        title: 'Todavía no hay expedientes que informar',
        body: 'Abre uno desde el triage. El informe reúne hipótesis, hechos, evidencia con su hash, ' +
              '<b>lo que se descartó y por qué</b>, y los guardrails.',
        actionLabel: 'Ir al triage',
        actionAttr: 'data-nav="triage"',
      })}
      ${importCard()}
    </div>`;
  }

  const selected = store.get(state.selected) || cases[0];
  state.selected = selected.case_id;

  return `<div class="stack">
    <div class="pagehead">
      <span class="eyebrow">Informe</span>
      <h2>Expediente entregable</h2>
      <p class="lede">
        Esto es lo que se entrega a un fiscal, a la UAF o a un comité interno. Sale con la bitácora
        completa y un hash que permite verificar que nadie lo editó después.
      </p>
    </div>

    <section class="filters">
      <select id="reportPick" aria-label="Expediente">
        ${cases.map((c) => `<option value="${esc(c.case_id)}"${c.case_id === selected.case_id ? ' selected' : ''}>
          ${esc(c.focus.organization_name || c.focus.organization_id)} · ${esc(c.focus.provider_name || c.focus.provider_id)} · ${esc(c.focus.periodo)}
        </option>`).join('')}
      </select>
      <button class="btn primary small" data-export-report="markdown">Descargar informe (Markdown)</button>
      <button class="btn small" data-export-report="json">Descargar sobre sellado (JSON)</button>
      <button class="btn small" data-export-report="all">Exportar todos los expedientes</button>
    </section>

    ${preview(ctx, selected)}
    ${importCard()}
    ${guardrail(ctx.triage.guardrail)}
  </div>`;
}

function preview(ctx, record) {
  const closing = (record.decisions || []).filter((d) => CLOSING_STATES.has(d.to_state));
  return `<section class="card">
    <span class="eyebrow">Vista previa · <span class="mono">${esc(record.case_id)}</span></span>
    ${definitionList([
      ['Estado', chip(STATE_LABEL[record.state], STATE_TONE[record.state] || 'bare')],
      ['Foco', `${esc(record.focus.organization_name || record.focus.organization_id)} · ${esc(record.focus.provider_name || record.focus.provider_id)} · ${esc(record.focus.periodo)}`],
      ['Responsable', esc(record.owner || 'sin asignar')],
      ['Hipótesis', record.hypothesis?.statement
        ? esc(record.hypothesis.statement)
        : '<span class="muted">Sin formular</span>'],
      ['Evidencia', `${num((record.evidence || []).length)} pieza(s)`],
      ['Actores', `${num((record.entities || []).length)} registrado(s)`],
      ['Decisiones', `${num((record.decisions || []).length)} en bitácora`],
      ['Abierto', esc(dateTime(record.opened_at))],
    ])}
    ${closing.length
      ? notice('Motivo de cierre registrado', esc(closing[closing.length - 1].rationale))
      : ''}
  </section>`;
}

function importCard() {
  return `<section class="card">
    <span class="eyebrow">Recibir un expediente</span>
    <p class="muted" style="font-size:.87rem">
      Carga un sobre exportado por otro analista. Se verifica el hash antes de incorporarlo:
      si el contenido fue editado después de sellarse, la carga lo dice.
    </p>
    <input type="file" id="reportImport" accept="application/json">
  </section>`;
}

// --- Generación del informe -------------------------------------------------

export function toMarkdown(record, ctx) {
  const focus = record.focus;
  const lines = [];
  const push = (...rows) => lines.push(...rows, '');

  push(`# Expediente ${record.case_id}`);
  push(
    `**Estado:** ${STATE_LABEL[record.state] || record.state}  `,
    `**Responsable:** ${record.owner || 'sin asignar'}  `,
    `**Abierto:** ${dateTime(record.opened_at)}  `,
    `**Última actividad:** ${dateTime(record.updated_at)}`,
  );

  push('## Foco');
  push(
    `- **Servicio:** ${focus.organization_name || focus.organization_id}`,
    `- **Proveedor o receptor:** ${focus.provider_name || focus.provider_id}`,
    `- **Periodo:** ${focus.periodo}`,
    `- **Prioridad de revisión:** ${Number(record.scores?.review_priority_score || 0).toFixed(0)}/100`,
    `- **Compatibilidad LA/FT:** ${Number(record.scores?.laft_compatibility_score || 0).toFixed(0)}/100`,
    `- **Opacidad de identidad:** ${record.opacity_level}`,
  );

  push('## Hipótesis');
  push(record.hypothesis?.statement
    ? `${record.hypothesis.statement}\n\n_Tipología:_ ${record.hypothesis.typology || 'sin tipología'} · formulada ${dateTime(record.hypothesis.formulated_at)} por ${record.hypothesis.formulated_by || 'sin firma'}`
    : '_Sin hipótesis formulada._');

  const relation = ctx?.triage?.relations?.find(
    (r) => r.organization_id === focus.organization_id
      && r.provider_id === focus.provider_id
      && String(r.periodo) === String(focus.periodo),
  );
  const typology = relation?.typologies?.[0];

  push('## Patrones observados');
  const patterns = [
    ...(relation?.signal_labels || []),
    ...((relation?.entity_signals || []).map((s) => s.why)),
  ];
  push(patterns.length ? patterns.map((p) => `- ${p}`).join('\n') : '_Sin patrones publicados para esta relación._');

  if (typology) {
    push(`## Tipología evaluada · ${typology.typology_name}`);
    push(`_${typology.question}_`);
    push('### Qué la sostendría');
    push((typology.sustains || []).map((s) => `- ${s}`).join('\n'));
    push('### Qué la descartaría');
    push((typology.discards || []).map((s) => `- ${s}`).join('\n'));
    push('### Documentos a requerir');
    push((typology.documents || []).map((s) => `- ${s}`).join('\n'));
    if ((typology.evidence_ceiling ?? 1) < 1) {
      push(
        `> **Techo de evidencia ${(typology.evidence_ceiling * 100).toFixed(0)}%.** ` +
        `Esta tipología requiere datos de ${(typology.missing_layers || []).join(', ').toLowerCase().replace(/_/g, ' ')} ` +
        'que el radar todavía no integra. Un puntaje bajo aquí no es un resultado negativo.',
      );
    }
  }

  push('## Actores');
  push((record.entities || []).length
    ? (record.entities || []).map((e) =>
        `- **${e.name || e.entity_id}** — ${e.role} · identidad ${e.identity_status === 'RESOLVED' ? formatRut(e.rut) : 'sin resolver'} · vínculo ${e.link_status}${e.source ? ` · fuente: ${e.source}` : ''}`).join('\n')
    : '_Sin actores registrados._');

  push('## Evidencia');
  push((record.evidence || []).length
    ? (record.evidence || []).map((e) =>
        `- **${e.title}** (${EVIDENCE_KINDS[e.kind] || e.kind}) · capturada ${dateTime(e.captured_at)}${e.sha256 ? ` · SHA-256 \`${e.sha256}\`` : ''}${e.source_url ? `\n  - ${e.source_url}` : ''}${e.note ? `\n  - ${e.note}` : ''}`).join('\n')
    : '_Sin evidencia incorporada._');

  push('## Cadena de verificación');
  push((record.verification_chain || []).map((s) =>
    `- **Etapa ${s.stage} · ${s.name}:** ${s.status.replace(/_/g, ' ')} — ${s.meaning}`).join('\n'));

  push('## Bitácora');
  push((record.decisions || []).length
    ? (record.decisions || []).map((d) =>
        `- ${dateTime(d.at)} · ${STATE_LABEL[d.from_state] || d.from_state} → ${STATE_LABEL[d.to_state] || d.to_state}${d.actor ? ` · ${d.actor}` : ''}\n  - Motivo: ${d.rationale || '—'}`).join('\n')
    : '_Sin decisiones registradas._');

  if ((record.notes || []).length) {
    push('## Notas');
    push(record.notes.map((n) => `- ${dateTime(n.at)}${n.author ? ` · ${n.author}` : ''}: ${n.text}`).join('\n'));
  }

  push('---');
  push(`_${GUARDRAIL}_`);
  return lines.join('\n');
}

export { seal, verify };
