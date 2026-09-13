// 01 · Triage. La cola priorizada, filtrable por tipología en vez de por tipo
// de señal técnico, y con los dos ejes siempre visibles y separados.

import { store } from '../cases.mjs';
import {
  ALIGNMENT_TONE, OPACITY_TONE, axes, chip, emptyState, esc, guardrail, money, notice, num, pct,
} from '../ui.mjs';

export const filters = {
  query: '',
  typology: '',
  alignment: '',
  opacity: '',
  year: '',
  sort: 'review',
  hideOpened: false,
};

export function matching(ctx) {
  const q = filters.query.trim().toLowerCase();
  return ctx.triage.relations.filter((r) => {
    if (filters.typology && (r.top_typology || 'SIN_TIPOLOGIA') !== filters.typology) return false;
    if (filters.alignment && r.laft_alignment !== filters.alignment) return false;
    if (filters.opacity && r.opacity_level !== filters.opacity) return false;
    if (filters.year && String(r.periodo) !== filters.year) return false;
    if (filters.hideOpened && store.byFocus(r.organization_id, r.provider_id, r.periodo)) return false;
    if (!q) return true;
    return [
      r.organization_name, r.provider_name, r.top_typology_name,
      r.provider_rut, ...(r.signal_labels || []),
    ].join(' ').toLowerCase().includes(q);
  });
}

function sorted(rows) {
  const copy = [...rows];
  if (filters.sort === 'laft') {
    copy.sort((a, b) => b.laft_compatibility_score - a.laft_compatibility_score
      || b.review_priority_score - a.review_priority_score);
  } else if (filters.sort === 'amount') {
    copy.sort((a, b) => (b.relation_amount || b.max_transaction_amount || 0)
      - (a.relation_amount || a.max_transaction_amount || 0));
  } else {
    copy.sort((a, b) => b.review_priority_score - a.review_priority_score
      || b.laft_compatibility_score - a.laft_compatibility_score);
  }
  return copy;
}

export function render(ctx) {
  const rows = sorted(matching(ctx));
  const coverage = ctx.triage.coverage;
  const source = ctx.triage.source;
  const facets = ctx.triage.facets;

  const option = (value, label, current) =>
    `<option value="${esc(value)}"${String(current) === String(value) ? ' selected' : ''}>${esc(label)}</option>`;

  return `<div class="stack">
    <div class="pagehead">
      <span class="eyebrow">Triage</span>
      <h2>Qué relación revisar primero</h2>
      <p class="lede">
        Dos ejes independientes: <b>prioridad de revisión</b> (cuánto conviene mirarlo)
        y <b>compatibilidad LA/FT</b> (cuántos patrones de una tipología están presentes).
        Un monto grande y ordinario sube el primero y no el segundo.
      </p>
    </div>

    ${coverageNotice(coverage, source)}

    <section class="filters">
      <input type="search" id="triageQuery" placeholder="Buscar servicio, proveedor, RUT o patrón…"
             value="${esc(filters.query)}" autocomplete="off">
      <select id="triageTypology" aria-label="Tipología">
        ${option('', `Todas las tipologías (${rowsTotal(ctx)})`, filters.typology)}
        ${Object.entries(facets.typologies || {})
          .sort((a, b) => b[1] - a[1])
          .map(([code, count]) => option(code, `${labelFor(ctx, code)} · ${count}`, filters.typology))
          .join('')}
      </select>
      <select id="triageAlignment" aria-label="Alineamiento LA/FT">
        ${option('', 'Todo alineamiento', filters.alignment)}
        ${['ALTO', 'MEDIO', 'BAJO', 'NULO']
          .filter((a) => (facets.alignments || {})[a])
          .map((a) => option(a, `LA/FT ${a.toLowerCase()} · ${facets.alignments[a]}`, filters.alignment))
          .join('')}
      </select>
      <select id="triageOpacity" aria-label="Opacidad de identidad">
        ${option('', 'Toda opacidad', filters.opacity)}
        ${['OPACA', 'PARCIAL', 'TRAZABLE']
          .filter((o) => (facets.opacity || {})[o])
          .map((o) => option(o, `Identidad ${o.toLowerCase()} · ${facets.opacity[o]}`, filters.opacity))
          .join('')}
      </select>
      <select id="triageYear" aria-label="Año">
        ${option('', 'Todos los años', filters.year)}
        ${Object.keys(facets.years || {}).sort().reverse()
          .map((y) => option(y, `${y} · ${facets.years[y]}`, filters.year)).join('')}
      </select>
      <select id="triageSort" aria-label="Orden">
        ${option('review', 'Ordenar por prioridad de revisión', filters.sort)}
        ${option('laft', 'Ordenar por compatibilidad LA/FT', filters.sort)}
        ${option('amount', 'Ordenar por monto de la relación', filters.sort)}
      </select>
      <button class="btn small" id="triageHideOpened" aria-pressed="${filters.hideOpened}">
        ${filters.hideOpened ? 'Mostrando sólo sin expediente' : 'Ocultar los que ya tienen expediente'}
      </button>
    </section>

    ${rows.length
      ? `<div class="tablewrap"><table>
          <thead><tr>
            <th>Relación</th><th>Tipología</th><th>Patrones</th>
            <th>Ejes</th><th class="num">Monto</th><th>Identidad</th><th></th>
          </tr></thead>
          <tbody>${rows.slice(0, 300).map((r) => row(r, ctx)).join('')}</tbody>
        </table></div>
        ${rows.length > 300 ? `<p class="muted" style="font-size:.84rem">Mostrando 300 de ${num(rows.length)} relaciones. Afina los filtros para ver el resto.</p>` : ''}`
      : emptyState({
          title: 'Ningún hallazgo cumple estos filtros',
          body: 'Prueba quitando la tipología o el alineamiento; el resto de la cola sigue disponible.',
          actionLabel: 'Limpiar filtros',
          actionAttr: 'data-clear-filters',
        })}

    ${guardrail(ctx.triage.guardrail)}
  </div>`;
}

function rowsTotal(ctx) {
  return ctx.triage.relations.length;
}

function labelFor(ctx, code) {
  if (code === 'SIN_TIPOLOGIA') return 'Sin tipología configurada';
  const entry = (ctx.triage.typology_catalog || []).find((t) => t.code === code);
  return entry ? entry.name : code.replace(/_/g, ' ');
}

function coverageNotice(coverage, source) {
  const parts = [];
  if (source.signals_total && source.signals_published < source.signals_total) {
    parts.push(
      `Se publican <b>${num(source.signals_published)}</b> de <b>${num(source.signals_total)}</b> señales ` +
      `detectadas, agrupadas en <b>${num(coverage.relations)}</b> relaciones ` +
      `(${num(coverage.services)} servicios, ${num(coverage.providers)} proveedores).`,
    );
  }
  if (source.queue_schema === 'RIGP-INVESTIGATION-QUEUE-v1') {
    parts.push(
      'La cola publicada viene del scoring anterior. Al volver a correr el pipeline se aplica ' +
      'el scoring por rareza y grupo de pares, y la cuota por familia.',
    );
  }
  if (coverage.relations && !coverage.relations_with_typology) {
    parts.push(
      'Ninguna relación de esta cola configura todavía una tipología LA/FT: una tipología ' +
      'exige al menos <b>dos patrones concurrentes</b>, y la cola publicada trae un solo patrón ' +
      'por relación. Es una limitación de la cola, no un resultado negativo.',
    );
  }
  if ((coverage.pending_layers || []).length) {
    const layers = coverage.pending_layers.join(', ').toLowerCase().replace(/_/g, ' ');
    parts.push(
      `Capas todavía no integradas: <b>${esc(layers)}</b>. Las tipologías que dependen de ellas ` +
      'quedan con techo de evidencia y no pueden alcanzar su puntaje máximo.',
    );
  }
  if (!parts.length) return '';
  return notice('Cobertura de esta cola', parts.join(' '), 'warn');
}

function row(relation, ctx) {
  const opened = store.byFocus(relation.organization_id, relation.provider_id, relation.periodo);
  const patterns = (relation.signal_labels || []).slice(0, 3);
  const extra = (relation.signal_labels || []).length - patterns.length;
  const entitySignals = (relation.entity_signals || []).length;
  return `<tr>
    <td><div class="cellmain">
      <b>${esc(relation.organization_name)}</b>
      <small>${esc(relation.provider_name)} · ${esc(relation.periodo)}</small>
      ${relation.provider_rut ? `<small class="mono">${esc(relation.provider_rut)}</small>` : ''}
    </div></td>
    <td><div class="cellmain">
      ${relation.top_typology
        ? `<b>${esc(relation.top_typology_name)}</b><small>${esc(relation.typology_question || '')}</small>`
        : '<span class="muted">Sin tipología configurada</span>'}
    </div></td>
    <td><div class="cellmain">
      ${patterns.map((p) => `<small>${esc(p)}</small>`).join('')}
      ${extra > 0 ? `<small class="muted">+${extra} más</small>` : ''}
      ${entitySignals ? `<small>${chip(`${entitySignals} de contraparte`, 'accent', { plain: true })}</small>` : ''}
    </div></td>
    <td>${axes(relation.review_priority_score, relation.laft_compatibility_score, relation.laft_alignment)}
        ${chip(`LA/FT ${relation.laft_alignment}`, ALIGNMENT_TONE[relation.laft_alignment] || 'bare')}</td>
    <td class="num">${esc(money(relation.relation_amount || relation.max_transaction_amount))}</td>
    <td>${chip(relation.opacity_level, OPACITY_TONE[relation.opacity_level] || 'bare')}
        ${relation.opaque_share ? `<br><small class="muted mono">${esc(pct(relation.opaque_share, 0))} opaco</small>` : ''}</td>
    <td>${opened
      ? `<button class="btn small" data-goto-case="${esc(opened.case_id)}">Ver expediente</button>`
      : `<button class="btn small primary" data-open-case="${esc(relation.finding_id)}">Abrir expediente</button>
         <button class="btn small" data-discard="${esc(relation.finding_id)}">Descartar</button>`}</td>
  </tr>`;
}
