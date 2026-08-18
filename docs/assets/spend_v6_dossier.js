(()=>{'use strict';
const MONTHS=['ene','feb','mar','abr','may','jun','jul','ago','sept','oct','nov','dic'];
const SALES={
  1:'Sin información de ventas',
  2:'0,01–200,00 UF/año',
  3:'200,01–600,00 UF/año',
  4:'600,01–2.400,00 UF/año',
  5:'2.400,01–5.000,00 UF/año',
  6:'5.000,01–10.000,00 UF/año',
  7:'10.000,01–25.000,00 UF/año',
  8:'25.000,01–50.000,00 UF/año',
  9:'50.000,01–100.000,00 UF/año',
  10:'100.000,01–200.000,00 UF/año',
  11:'200.000,01–600.000,00 UF/año',
  12:'600.000,01–1.000.000,00 UF/año',
  13:'Más de 1.000.000,01 UF/año'
};
const S={history:null,sii:new Map(),providerByRut:new Map(),providerByName:new Map(),loaded:false,lastKey:''};
let UAF_WRAP=null;
const norm=v=>String(v||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toUpperCase().replace(/[^A-Z0-9]+/g,' ').trim();
const rutKey=v=>String(v||'').toUpperCase().replace(/[^0-9K]/g,'');
const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
async function j(url){const r=await fetch(url+(url.includes('?')?'&':'?')+'v='+Date.now(),{cache:'no-store'});if(!r.ok)throw new Error(url+' HTTP '+r.status);return r.json()}
async function load(){const [h,e]=await Promise.allSettled([j('data/spend_years_v1.json'),j('data/entity_enrichment_v1.json')]);if(h.status==='fulfilled')S.history=h.value;if(e.status==='fulfilled'){for(const [k,v] of Object.entries(e.value.entities||{})){const rk=rutKey(v?.rut||k);if(rk)S.sii.set(rk,v)}}for(const p of S.history?.providers||[]){const rk=rutKey(p.rut);if(rk)S.providerByRut.set(rk,p);S.providerByName.set(norm(p.provider_name),p)}S.loaded=true;patchOpen()}
function years(){const all=(S.history?.years||[]).map(Number);if(document.querySelector('.yearBtn.all.on'))return new Set(all);const ys=[...document.querySelectorAll('.yearBtn.on[data-year]')].map(x=>Number(x.dataset.year)).filter(Number.isFinite);return new Set(ys.length?ys:all)}
function providerFromDrawer(d){const id=d.querySelector('.idline')?.textContent||'';const rut=id.match(/RUT\s+([0-9\.\-Kk]+)/i)?.[1];if(rut&&S.providerByRut.has(rutKey(rut)))return S.providerByRut.get(rutKey(rut));const name=norm(d.querySelector('.dh h2')?.textContent);return S.providerByName.get(name)||null}
function paymentMonths(p){const ys=years();let rows=(p?.monthly||[]).filter(x=>ys.has(Number(x.year||String(x.period||'').slice(0,4)))&&Number(x.amount_clp||0)!==0);if(!rows.length){const base=(globalThis.__PA_SPEND_DATA__?.providers||[]).find(x=>String(x.provider_id)===String(p?.provider_id));rows=(base?.monthly||[]).filter(x=>ys.has(Number(String(x.period||'').slice(0,4)))&&Number(x.amount_clp||0)!==0).map(x=>({year:Number(String(x.period).slice(0,4)),month:Number(String(x.period).slice(5,7)),period:x.period,amount_clp:x.amount_clp}))}rows.sort((a,b)=>String(a.period).localeCompare(String(b.period)));if(!rows.length)return 'Sin meses publicados en los años seleccionados';const by=new Map();for(const r of rows){const y=Number(r.year||String(r.period).slice(0,4)),m=Number(r.month||String(r.period).slice(5,7));if(!by.has(y))by.set(y,[]);if(m>=1&&m<=12&&!by.get(y).includes(m))by.get(y).push(m)}const parts=[...by].map(([y,ms])=>`${y}: ${ms.map(m=>MONTHS[m-1]).join(', ')}`);return `${rows.length} ${rows.length===1?'mes':'meses'} · ${parts.join(' · ')}`}
function salesNumeric(sii){const code=Number(sii?.sales_band_code);if(Number.isFinite(code)&&SALES[code])return SALES[code];const raw=String(sii?.sales_band||'').trim();const n=Number(raw);if(Number.isFinite(n)&&SALES[n])return SALES[n];return 'Sin dato publicado';}
function activitiesHtml(sii){const xs=Array.isArray(sii?.acteco)?sii.acteco:[];if(!xs.length)return '<span class="emptyValue">Sin actividades publicadas en el extracto</span>';return `<div class="activityInline">${xs.slice(0,10).map(x=>`<span><b>${esc(x.codigo||'')}</b>${esc(x.glosa||'')}</span>`).join('')}${xs.length>10?`<small>+${xs.length-10} actividades vigentes/publicadas</small>`:''}</div>`}
function removePair(dl,label){const dts=[...dl.querySelectorAll(':scope > dt')];for(const dt of dts){if(norm(dt.textContent)===norm(label)||norm(dt.textContent).includes(norm(label))){const dd=dt.nextElementSibling;if(dd?.tagName==='DD')dd.remove();dt.remove()}}}
function setPair(dl,label,value,html=false){const dt=[...dl.querySelectorAll(':scope > dt')].find(x=>norm(x.textContent)===norm(label));if(dt){const dd=dt.nextElementSibling;if(dd?.tagName==='DD'){if(html)dd.innerHTML=value;else dd.textContent=value;return}}const ndt=document.createElement('dt');ndt.textContent=label;const ndd=document.createElement('dd');if(html)ndd.innerHTML=value;else ndd.textContent=value;dl.append(ndt,ndd)}
function patchOpen(){if(!S.loaded)return;const d=document.getElementById('drawer');if(!d||!d.classList.contains('open'))return;const hero=d.querySelector('.eyebrow')?.textContent||'';if(!norm(hero).includes('PROVEEDOR'))return;const p=providerFromDrawer(d);if(!p)return;const rk=rutKey(p.rut),sii=S.sii.get(rk);const key=`${p.provider_id}|${[...years()].join(',')}|${d.querySelector('.dh h2')?.textContent}`;if(key===S.lastKey&&d.dataset.v6Patched==='1')return;S.lastKey=key;
  const blocks=[...d.querySelectorAll('.entityBlock')];
  const flow=blocks.find(b=>norm(b.querySelector('h3')?.textContent).includes('FLUJO CON EL ESTADO'));
  if(flow){const dl=flow.querySelector('dl.kv');if(dl){removePair(dl,'Relación con UAF');setPair(dl,'Meses con pagos',paymentMonths(p));}}
  const tax=blocks.find(b=>norm(b.querySelector('h3')?.textContent).includes('SITUACION TRIBUTARIA'));
  if(tax){const h=tax.querySelector('h3');if(h)h.textContent='Situación tributaria';const dl=tax.querySelector('dl.kv');if(dl){removePair(dl,'Último año comercial SII');setPair(dl,'Nivel de ventas',salesNumeric(sii));setPair(dl,'Actividades vigentes',activitiesHtml(sii),true);}const note=tax.querySelector('.coverageLine');if(note)note.textContent='Estado y actividades: snapshot SII vigente. Ventas: rango numérico oficial en UF/año; SII no publica un monto individual exacto en esta nómina.';}
  for(const b of blocks){const h=norm(b.querySelector('h3')?.textContent);if(h.startsWith('ACTECO VIGENTES')||h==='ACTECO')b.remove()}
  d.dataset.v6Patched='1';
}
function captureUafWrap(node){if(!node||node.nodeType!==1)return;const b=node.id==='uafRefToggle'?node:node.querySelector?.('#uafRefToggle');if(b)UAF_WRAP=b.closest('.uafRefField')||b.parentElement}
function restoreUafToggle(){const tb=document.getElementById('toolbar');if(!tb)return;const current=document.getElementById('uafRefToggle');if(current){UAF_WRAP=current.closest('.uafRefField')||current.parentElement;if(UAF_WRAP){UAF_WRAP.hidden=false;UAF_WRAP.style.display=''}return}if(!UAF_WRAP)return;const reset=document.getElementById('reset');if(reset&&reset.parentElement===tb)tb.insertBefore(UAF_WRAP,reset);else tb.appendChild(UAF_WRAP);UAF_WRAP.hidden=false;UAF_WRAP.style.display=''}
function watchUafToggle(){let observer=null;const attach=()=>{const tb=document.getElementById('toolbar');if(!tb)return false;if(observer)return true;observer=new MutationObserver(ms=>{for(const m of ms){for(const n of m.removedNodes||[])captureUafWrap(n);for(const n of m.addedNodes||[])captureUafWrap(n)}setTimeout(restoreUafToggle,0)});observer.observe(tb,{childList:true,subtree:true});restoreUafToggle();return true};let tries=0;const t=setInterval(()=>{tries++;attach();restoreUafToggle();if(tries>600)clearInterval(t)},100)}
function observe(){const d=document.getElementById('drawer');if(!d)return;new MutationObserver(()=>setTimeout(patchOpen,20)).observe(d,{childList:true,subtree:true,attributes:true,attributeFilter:['class']});document.addEventListener('click',e=>{if(e.target.closest('[data-v4-row-p],[data-v4-provider],[data-v4-growth],[data-v4-scatter],[data-v4-read-p],[data-v5-provider]'))setTimeout(()=>{if(d)d.dataset.v6Patched='0';patchOpen()},140)});document.addEventListener('click',e=>{if(e.target.closest('.yearBtn'))setTimeout(()=>{if(d)d.dataset.v6Patched='0';patchOpen()},120)})}
function boot(){watchUafToggle();observe();load().catch(()=>{S.loaded=true})}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();