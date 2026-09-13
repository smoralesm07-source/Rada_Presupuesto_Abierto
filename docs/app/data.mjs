// Carga de payloads publicados. Un payload ausente no es cero: es desconocido,
// y la interfaz tiene que poder decirlo.

const CACHE = new Map();

async function loadJson(path, { required = false } = {}) {
  if (CACHE.has(path)) return CACHE.get(path);
  const promise = fetch(path, { cache: 'no-store' })
    .then((response) => {
      if (!response.ok) {
        if (required) throw new Error(`No fue posible cargar ${path} (${response.status})`);
        return null;
      }
      return response.json();
    })
    .catch((error) => {
      if (required) throw error;
      return null;
    });
  CACHE.set(path, promise);
  return promise;
}

export async function loadTriage() {
  return loadJson('data/triage.json', { required: true });
}

export async function loadContext() {
  const [explore, entitySignals, opacity, procurement, quality, manifest] = await Promise.all([
    loadJson('data/explore_context.json'),
    loadJson('data/entity_signals.json'),
    loadJson('data/opacity_index.json'),
    loadJson('data/procurement_status.json'),
    loadJson('data/quality.json'),
    loadJson('data/snapshot_manifest.json'),
  ]);
  return { explore, entitySignals, opacity, procurement, quality, manifest };
}

export async function loadEnrichment() {
  return loadJson('data/entity_enrichment_v1.json');
}
