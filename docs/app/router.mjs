// Router por hash: cinco destinos, sin dependencias y sin simular clicks.

const listeners = new Set();

export const ROUTES = ['bandeja', 'triage', 'caso', 'entidad', 'informe'];

export function parseHash(hash = window.location.hash) {
  const raw = String(hash || '').replace(/^#\/?/, '');
  const [path, query = ''] = raw.split('?');
  const segments = path.split('/').filter(Boolean);
  const view = ROUTES.includes(segments[0]) ? segments[0] : 'bandeja';
  return {
    view,
    id: segments[1] ? decodeURIComponent(segments[1]) : '',
    params: Object.fromEntries(new URLSearchParams(query)),
  };
}

export function navigate(view, id = '', params = {}) {
  const query = new URLSearchParams(params).toString();
  const path = `#/${view}${id ? `/${encodeURIComponent(id)}` : ''}${query ? `?${query}` : ''}`;
  if (window.location.hash === path) {
    emit();
    return;
  }
  window.location.hash = path;
}

function emit() {
  const route = parseHash();
  listeners.forEach((fn) => fn(route));
}

export function onRoute(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function start() {
  window.addEventListener('hashchange', emit);
  emit();
}
