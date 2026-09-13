// Componentes compartidos. Todo devuelve HTML como texto; el estado vive en el
// store y las vistas se vuelven a pintar completas. Sin MutationObserver ni
// temporizadores: la versión anterior los usaba para coordinar módulos y era
// exactamente lo que hacía impredecible la interfaz.

import { esc, money, num, pct } from './fmt.mjs';

export const ALIGNMENT_TONE = { ALTO: 'crit', MEDIO: 'warn', BAJO: 'info', NULO: 'bare' };
export const OPACITY_TONE = { OPACA: 'warn', PARCIAL: 'info', TRAZABLE: 'good' };
export const STATE_TONE = {
  ABIERTO: 'info',
  EN_REVISION: 'accent',
  EN_ESPERA_DOCUMENTO: 'warn',
  ESCALADO: 'crit',
  CERRADO_EXPLICADO: 'good',
  CERRADO_SIN_MERITO: 'bare',
};

export function chip(text, tone = 'bare', { plain = false } = {}) {
  return `<span class="chip ${tone}${plain ? ' plain' : ''}">${esc(text)}</span>`;
}

export function tile(label, value, sub = '') {
  return `<div class="card tile">
    <span class="k">${esc(label)}</span>
    <span class="v">${esc(value)}</span>
    ${sub ? `<span class="s">${esc(sub)}</span>` : ''}
  </div>`;
}

/** Los dos ejes, siempre juntos y siempre distinguibles. */
export function axes(review, laft, alignment) {
  const r = Math.max(0, Math.min(100, Number(review || 0)));
  const l = Math.max(0, Math.min(100, Number(laft || 0)));
  return `<div class="axis">
    <span class="lab">revisión <b>${r.toFixed(0)}</b></span>
    <span class="meter"><span class="review" style="width:${r}%"></span></span>
    <span class="lab">LA/FT <b>${l.toFixed(0)}</b></span>
    <span class="meter"><span class="laft-${esc(alignment || 'NULO')}" style="width:${l}%"></span></span>
  </div>`;
}

export function emptyState({ title, body, actionLabel, actionAttr = '', secondary = '' }) {
  return `<div class="empty">
    <h3>${esc(title)}</h3>
    <p>${body}</p>
    ${actionLabel ? `<button class="btn primary" ${actionAttr}>${esc(actionLabel)}</button>` : ''}
    ${secondary ? `<p class="muted" style="font-size:.85rem">${secondary}</p>` : ''}
  </div>`;
}

export function notice(title, body, tone = '') {
  return `<div class="notice ${tone}"><b>${esc(title)}</b><p>${body}</p></div>`;
}

export function definitionList(pairs) {
  const rows = pairs
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([key, value]) => `<dt>${esc(key)}</dt><dd>${value}</dd>`)
    .join('');
  return `<dl class="dl">${rows}</dl>`;
}

/** Qué sostiene la hipótesis, qué la descarta y qué documento pedir. */
export function reasoningBlocks(typology) {
  if (!typology) return '';
  const list = (items) => `<ul>${items.map((i) => `<li>${esc(i)}</li>`).join('')}</ul>`;
  return `<div class="reason">
    <div class="blk sust"><span class="eyebrow">Qué la sostendría</span>${list(typology.sustains || [])}</div>
    <div class="blk disc"><span class="eyebrow">Qué la descartaría</span>${list(typology.discards || [])}</div>
    <div class="blk docs"><span class="eyebrow">Qué documento pedir</span>${list(typology.documents || [])}</div>
  </div>`;
}

export function evidenceCeilingNote(typology) {
  if (!typology || (typology.evidence_ceiling ?? 1) >= 1) return '';
  const layers = (typology.missing_layers || []).join(', ').toLowerCase().replace(/_/g, ' ');
  return notice(
    `Techo de evidencia: ${pct(typology.evidence_ceiling, 0)}`,
    `Esta tipología necesita datos de <b>${esc(layers)}</b> que el radar todavía no integra. ` +
      'Su puntaje no puede subir más mientras esa fuente falte: un valor bajo aquí no es un resultado negativo.',
    'warn',
  );
}

export function guardrail(text) {
  return `<p class="guardline">${esc(text)}</p>`;
}

export function toast(message) {
  document.querySelector('.toast')?.remove();
  const el = document.createElement('div');
  el.className = 'toast';
  el.setAttribute('role', 'status');
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

export function downloadJson(filename, payload) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export function downloadText(filename, text, type = 'text/markdown') {
  const blob = new Blob([text], { type: `${type};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export { esc, money, num, pct };
