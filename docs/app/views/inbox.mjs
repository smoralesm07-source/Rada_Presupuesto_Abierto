// 00 · Mi bandeja. La portada es el trabajo asignado, no un catálogo de señales.

import { store, STATE_LABEL, OPEN_STATES, CLOSING_STATES } from '../cases.mjs';
import { chip, emptyState, esc, guardrail, notice, STATE_TONE, tile } from '../ui.mjs';
import { dateTime, relativeDays } from '../fmt.mjs';

const AGE_WARN_DAYS = 7;

export function render(ctx) {
  const cases = store.all().sort(
    (a, b) => new Date(b.updated_at) - new Date(a.updated_at),
  );
  const open = cases.filter((c) => OPEN_STATES.has(c.state));
  const closed = cases.filter((c) => CLOSING_STATES.has(c.state));
  const stale = open.filter((c) => (relativeDays(c.updated_at) ?? 0) >= AGE_WARN_DAYS);
  const escalated = cases.filter((c) => c.state === 'ESCALADO');

  if (!cases.length) {
    const top = ctx.triage.relations[0];
    return `<div class="stack">
      <div class="pagehead">
        <span class="eyebrow">Bandeja de trabajo</span>
        <h2>Todavía no tienes expedientes abiertos</h2>
      </div>
      ${emptyState({
        title: top
          ? `Empieza por ${esc(top.organization_name)} · ${esc(top.provider_name)}`
          : 'No hay hallazgos publicados para priorizar',
        body: top
          ? `Prioridad de revisión <b>${Number(top.review_priority_score).toFixed(0)}</b> de 100, ` +
            `${top.signals.length} patrón(es) y ` +
            (top.top_typology
              ? `compatibilidad <b>${Number(top.laft_compatibility_score).toFixed(0)}</b> con la tipología ${esc(top.top_typology_name)}.`
              : 'sin tipología LA/FT configurada.')
          : 'Ejecuta el pipeline para publicar la cola priorizada.',
        actionLabel: top ? 'Abrir este expediente' : '',
        actionAttr: top ? `data-open-case="${esc(top.finding_id)}"` : '',
        secondary:
          'Un expediente es la unidad de trabajo: agrupa hallazgo, actores, evidencia y decisiones, ' +
          'y se puede exportar para que otro analista lo continúe.',
      })}
      ${ctx.migration?.imported
        ? notice(
            'Trabajo anterior recuperado',
            `Se importaron ${ctx.migration.imported} revisiones guardadas por la versión anterior y ahora son expedientes con bitácora.`,
          )
        : ''}
      ${guardrail(ctx.triage.guardrail)}
    </div>`;
  }

  return `<div class="stack">
    <div class="pagehead">
      <span class="eyebrow">Bandeja de trabajo</span>
      <h2>${open.length} expediente${open.length === 1 ? '' : 's'} en curso</h2>
      <p class="lede">Ordenados por última actividad. Un expediente sin movimiento no avanza solo.</p>
    </div>

    <section class="grid k4">
      ${tile('Abiertos', String(open.length), 'requieren acción')}
      ${tile('Sin movimiento', String(stale.length), `${AGE_WARN_DAYS}+ días`)}
      ${tile('Escalados', String(escalated.length), 'derivados con hipótesis')}
      ${tile('Cerrados', String(closed.length), 'con motivo registrado')}
    </section>

    ${stale.length
      ? notice(
          `${stale.length} expediente(s) llevan ${AGE_WARN_DAYS} días o más sin movimiento`,
          'Retomarlos o cerrarlos con motivo evita que la bandeja acumule trabajo fantasma.',
          'warn',
        )
      : ''}

    <div class="tablewrap">
      <table>
        <thead><tr>
          <th>Expediente</th><th>Estado</th><th>Hipótesis</th>
          <th class="num">Revisión</th><th class="num">LA/FT</th><th>Última actividad</th>
        </tr></thead>
        <tbody>
          ${cases.map(row).join('')}
        </tbody>
      </table>
    </div>
    ${guardrail(ctx.triage.guardrail)}
  </div>`;
}

function row(record) {
  const days = relativeDays(record.updated_at);
  const focus = record.focus;
  return `<tr class="clickable" data-goto-case="${esc(record.case_id)}">
    <td><div class="cellmain">
      <b>${esc(focus.organization_name || focus.organization_id)}</b>
      <small>${esc(focus.provider_name || focus.provider_id)} · ${esc(focus.periodo)}</small>
    </div></td>
    <td>${chip(STATE_LABEL[record.state] || record.state, STATE_TONE[record.state] || 'bare')}</td>
    <td><div class="cellmain">
      ${record.hypothesis?.typology ? `<b>${esc(record.hypothesis.typology.replace(/_/g, ' '))}</b>` : '<span class="muted">Sin formular</span>'}
      ${record.hypothesis?.statement ? `<small>${esc(record.hypothesis.statement.slice(0, 90))}</small>` : ''}
    </div></td>
    <td class="num">${Number(record.scores?.review_priority_score || 0).toFixed(0)}</td>
    <td class="num">${Number(record.scores?.laft_compatibility_score || 0).toFixed(0)}</td>
    <td><div class="cellmain">
      <small>${esc(dateTime(record.updated_at))}</small>
      ${days !== null && days >= AGE_WARN_DAYS ? `<small class="muted">hace ${days} días</small>` : ''}
    </div></td>
  </tr>`;
}
