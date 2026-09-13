// Formato de datos chilenos y utilidades de presentación.

const CLP = new Intl.NumberFormat('es-CL');

export const esc = (value) =>
  String(value ?? '').replace(/[&<>"']/g, (m) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[m]));

export function money(value) {
  const n = Number(value || 0);
  if (!n) return '—';
  const abs = Math.abs(n);
  if (abs >= 1e12) return `$${(n / 1e12).toFixed(2)} bill.`;
  if (abs >= 1e9) return `$${(n / 1e9).toFixed(1)} mil M`;
  if (abs >= 1e6) return `$${(n / 1e6).toFixed(0)} M`;
  return `$${CLP.format(Math.round(n))}`;
}

export const num = (value) => CLP.format(Number(value || 0));

export function pct(value, digits = 1) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  return new Intl.NumberFormat('es-CL', {
    style: 'percent', maximumFractionDigits: digits,
  }).format(Number(value));
}

export function date(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleDateString('es-CL', { year: 'numeric', month: 'short', day: 'numeric' });
}

export function dateTime(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString('es-CL', {
    year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

export function relativeDays(value) {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return Math.floor((Date.now() - d.getTime()) / 86400000);
}

/** RUT canónico sólo si el dígito verificador valida. Nunca se inventa uno. */
export function canonicalRut(value) {
  const compact = String(value || '').toUpperCase().replace(/[^0-9K]/g, '');
  if (compact.length < 2) return '';
  const body = compact.slice(0, -1);
  const dv = compact.slice(-1);
  if (!/^\d+$/.test(body)) return '';
  let sum = 0;
  let mult = 2;
  for (let i = body.length - 1; i >= 0; i -= 1) {
    sum += Number(body[i]) * mult;
    mult = mult === 7 ? 2 : mult + 1;
  }
  const rest = 11 - (sum % 11);
  const expected = rest === 11 ? '0' : rest === 10 ? 'K' : String(rest);
  return expected === dv ? `${Number(body)}-${dv}` : '';
}

export function formatRut(value) {
  const rut = canonicalRut(value);
  if (!rut) return '';
  const [body, dv] = rut.split('-');
  return `${Number(body).toLocaleString('es-CL')}-${dv}`.replace(/,/g, '.');
}
