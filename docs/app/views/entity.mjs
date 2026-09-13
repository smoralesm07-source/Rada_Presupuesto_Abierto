// 03 · Entidad 360. Un RUT, todo lo público sobre él, todos los casos donde
// aparece. Accesible desde cualquier expediente.

import { store } from '../cases.mjs';
import {
  chip, definitionList, emptyState, esc, guardrail, money, notice, num, pct,
} from '../ui.mjs';
import { date, formatRut, canonicalRut } from '../fmt.mjs';

const MARK_TONE = { HIGH: 'crit', MEDIUM: 'warn', LOW: 'info' };

export function render(ctx, rutOrId) {
  const rut = canonicalRut(String(rutOrId || '').replace(/^.*RUT-/, ''));
  if (!rut) {
    return `<div class="stack">
      <div class="pagehead"><span class="eyebrow">Entidad</span><h2>Perfil de contraparte</h2></div>
      ${emptyState({
        title: 'Elige una entidad desde el triage o un expediente',
        body: 'Esta vista reúne el registro tributario publicado, el gasto recibido y todos los ' +
              'expedientes donde la entidad aparece. Requiere un RUT con dígito verificador válido.',
        actionLabel: 'Ir al triage',
        actionAttr: 'data-nav="triage"',
      })}
    </div>`;
  }

  const providerId = `PRV-RUT-${rut}`;
  const entity = (ctx.enrichment?.entities || {})[rut] || null;
  const provider = (ctx.context.explore?.providers || {})[providerId] || {};
  const relations = ctx.triage.relations.filter((r) => r.provider_id === providerId);
  const cases = store.all().filter((c) => c.focus.provider_id === providerId);
  const entitySignals = (ctx.context.entitySignals?.providers || {})[providerId]?.signals || [];
  const name = entity?.legal_name || relations[0]?.provider_name || provider.name || rut;

  return `<div class="stack">
    <div class="pagehead">
      <span class="eyebrow">Entidad · <span class="mono">${esc(formatRut(rut))}</span></span>
      <div class="row">
        <h2>${esc(name)}</h2>
        ${entity ? chip(entity.tax_status === 'TERMINATED_AS_PUBLISHED' ? 'Término de giro' : 'Vigente',
            entity.tax_status === 'TERMINATED_AS_PUBLISHED' ? 'crit' : 'good') : chip('Sin perfil registral', 'bare')}
      </div>
    </div>

    ${entity ? registryCard(entity) : notice(
      'Sin perfil registral publicado',
      'El enriquecimiento SII cubre sólo una parte del universo de contrapartes. ' +
      'Que falte no significa que la entidad no exista: significa que todavía no se consultó.',
      'warn',
    )}

    ${entitySignals.length ? `<section class="card">
      <span class="eyebrow">Señales de contraparte</span>
      <div class="log">${entitySignals.map((s) => `<div class="item">
        <span class="when">${esc(s.periodo ?? '—')}</span>
        <span class="what">
          <span>${chip(s.signal_type.replace(/_/g, ' '), MARK_TONE[s.severity] || 'bare')}</span>
          <span class="why">${esc(s.why)}</span>
          <span class="muted" style="font-size:.78rem">${esc(s.assumption || '')}</span>
        </span>
      </div>`).join('')}</div>
    </section>` : ''}

    ${(entity?.marks || []).length ? `<section class="card">
      <span class="eyebrow">Marcas del catálogo Radar SII</span>
      <div class="log">${entity.marks.slice(0, 12).map((m) => `<div class="item">
        <span class="when">${esc(m.year ?? '—')}</span>
        <span class="what">
          <span>${chip(String(m.signal_type || '').replace(/_/g, ' '), MARK_TONE[m.severity] || 'bare')}</span>
          <span class="why">${esc(m.why || '')}</span>
        </span>
      </div>`).join('')}</div>
    </section>` : ''}

    <section class="grid k2">
      <div class="card">
        <span class="eyebrow">Gasto público recibido</span>
        ${definitionList([
          ['Total publicado', esc(money(
            (provider.yearly || []).reduce((acc, y) => acc + Number(y.amount_clp || 0), 0),
          ))],
          ['Servicios', num((provider.top_services || []).length || new Set(relations.map((r) => r.organization_id)).size)],
          ['Relaciones priorizadas', num(relations.length)],
        ])}
        ${(provider.top_services || []).length
          ? `<div class="tablewrap"><table>
              <thead><tr><th>Servicio</th><th class="num">Monto</th></tr></thead>
              <tbody>${provider.top_services.slice(0, 8).map((s) =>
                `<tr><td>${esc(s.organization_name || s.organization_id)}</td>
                     <td class="num">${esc(money(s.amount_clp))}</td></tr>`).join('')}</tbody>
            </table></div>`
          : ''}
      </div>
      <div class="card">
        <span class="eyebrow">Expedientes donde aparece</span>
        ${cases.length
          ? `<div class="log">${cases.map((c) => `<div class="item">
              <span class="when">${esc(c.focus.periodo)}</span>
              <span class="what">
                <span><a href="#/caso/${esc(c.case_id)}">${esc(c.focus.organization_name || c.focus.organization_id)}</a></span>
                <span class="muted" style="font-size:.8rem">${esc(c.state.replace(/_/g, ' '))}</span>
              </span>
            </div>`).join('')}</div>`
          : '<p class="muted">Todavía no hay expedientes abiertos sobre esta entidad.</p>'}
      </div>
    </section>

    ${relations.length ? `<section class="card">
      <span class="eyebrow">Relaciones priorizadas</span>
      <div class="tablewrap"><table>
        <thead><tr><th>Servicio</th><th>Año</th><th>Tipología</th><th class="num">Revisión</th><th class="num">LA/FT</th><th></th></tr></thead>
        <tbody>${relations.map((r) => `<tr>
          <td>${esc(r.organization_name)}</td>
          <td class="num">${esc(r.periodo)}</td>
          <td>${esc(r.top_typology_name || '—')}</td>
          <td class="num">${Number(r.review_priority_score).toFixed(0)}</td>
          <td class="num">${Number(r.laft_compatibility_score).toFixed(0)}</td>
          <td><button class="btn small" data-open-case="${esc(r.finding_id)}">Abrir expediente</button></td>
        </tr>`).join('')}</tbody>
      </table></div>
    </section>` : ''}

    ${guardrail(ctx.triage.guardrail)}
  </div>`;
}

function registryCard(entity) {
  return `<section class="card">
    <span class="eyebrow">Registro tributario publicado</span>
    ${definitionList([
      ['Razón social', esc(entity.legal_name || '—')],
      ['Inicio de actividades', esc(date(entity.start_date))],
      ['Término de giro', entity.termination_date ? esc(date(entity.termination_date)) : 'Sin registro'],
      ['Tipo de contribuyente', esc(entity.taxpayer_type || '—')],
      ['Tramo de ventas', esc(entity.sales_band_label || '—')],
      ['Trabajadores', entity.workers != null ? num(entity.workers) : '—'],
      ['Actividad principal', esc(entity.main_activity || '—')],
      ['Región', esc(entity.main_region || '—')],
      ['Año comercial del tramo', esc(entity.commercial_year ?? '—')],
    ])}
    <p class="muted" style="font-size:.8rem">
      Snapshot registral publicado. El tramo de ventas corresponde al último año comercial disponible
      y puede no coincidir con el año del pago analizado.
    </p>
  </section>`;
}
