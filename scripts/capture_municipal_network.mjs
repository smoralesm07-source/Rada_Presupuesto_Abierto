import { chromium } from 'playwright';
import fs from 'node:fs';

const pages = [
  'https://presupuestoabierto.gob.cl/municipalities',
  'https://presupuestoabierto.gob.cl/municipalities/9/9118?view=providers',
  'https://presupuestoabierto.gob.cl/municipalities/5/5803?view=general',
];

const browser = await chromium.launch({headless: true});
const context = await browser.newContext({
  userAgent: 'ATLAS-UAF municipal-network-capture/1.0',
});
const page = await context.newPage();
const calls = [];
const seen = new Set();

page.on('request', req => {
  const url = req.url();
  if (!url.includes('presupuestoabierto')) return;
  const key = `${req.method()} ${url}`;
  if (seen.has(key)) return;
  seen.add(key);
  calls.push({
    kind: 'request',
    method: req.method(),
    url,
    resourceType: req.resourceType(),
    postData: req.postData(),
  });
});

page.on('response', async res => {
  const url = res.url();
  if (!url.includes('api.presupuestoabierto.gob.cl')) return;
  const headers = res.headers();
  const item = {
    kind: 'response',
    status: res.status(),
    url,
    contentType: headers['content-type'] || '',
  };
  try {
    if ((item.contentType || '').includes('json')) {
      const txt = await res.text();
      item.sample = txt.slice(0, 3000);
    }
  } catch (_) {}
  calls.push(item);
});

const visits = [];
for (const url of pages) {
  const rec = {url};
  try {
    const response = await page.goto(url, {waitUntil: 'networkidle', timeout: 90000});
    rec.status = response?.status() ?? null;
    rec.title = await page.title();
    rec.finalUrl = page.url();
    rec.body = (await page.locator('body').innerText()).slice(0, 5000);
    await page.waitForTimeout(2500);
  } catch (err) {
    rec.error = String(err);
  }
  visits.push(rec);
}

await browser.close();
const out = {capturedAt: new Date().toISOString(), visits, calls};
fs.mkdirSync('docs/data', {recursive: true});
fs.writeFileSync('docs/data/municipal_network_capture.json', JSON.stringify(out, null, 2));
console.log(JSON.stringify({visits: visits.length, calls: calls.length}, null, 2));
for (const call of calls) {
  if (call.url?.includes('api.presupuestoabierto.gob.cl')) {
    console.log(call.kind.toUpperCase(), call.method || '', call.status || '', call.url, call.postData || '');
  }
}
