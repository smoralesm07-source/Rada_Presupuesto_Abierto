(()=>{'use strict';

const DATA_URL='data/investigative_findings.json';
const CASE_KEY='rigp_cases_v1';
const STATUS_LABEL={TRIAGE:'Triage',EN_REVISION:'En revisión',PROFUNDIZAR:'Profundizar',EXPLICADO:'Explicado',ESCALADO:'Escalado',CERRADO:'Cerrado'};
const shell={payload:null,rows:[],loaded:false,started:false,current:'inicio',exploreMode:'provider',exploreQuery:''};
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const fmt=new Intl.NumberFormat('es-CL');
const fmt1=new Intl.NumberFormat('es-CL',{maximumFractionDigits:1});
const idOf=r=>String(r.finding_id||`${r.organization_id}|${r.provider_id}|${r.periodo}`);
const rank=r=>r.attention_level==='ATENCION_INMEDIATA'?0:r.attention_level==='REVISION_PRIORITARIA'?1:2;
const money=v=>{v=Number(v||0);if(!v)return '—';const a=Math.abs(v);if(a>=1e12)return '$'+fmt1.format(v/1e12)+' bill.';if(a>=1e9)return '$'+fmt1.format(v/1e9)+' mil M';if(a>=1e6)return '$'+fmt1.format(v/1e6)+' M';return '$'+fmt.format(Math.round(v));};

function readCases(){try{const x=JSON.parse(localStorage.getItem(CASE_KEY)||'[]');return Array.isArray(x)?x:[]}catch{return []}}
function topGroup(view){if(view==='inicio')return'inicio';if(view==='triage')return'triage';if(view==='explorar'||view==='entidad')return'explorar';return'bandeja'}
function setPrimary(view){document.querySelectorAll('#primaryNav [data-view]').forEach(b=>b.classList.toggle('on',b.dataset.view===view))}
function syncCaseNav(){const banner=$('caseBanner'),nav=$('caseNav');if(!banner||!nav)return;nav.hidden=banner.hidden}
function activeCases(){return readCases().filter(c=>!['EXPLICADO','CERRADO'].includes(c.status)).sort((a,b)=>Number(b.priority_score||0)-Number(a.priority_score||0)||String(b.updated_at||'').localeCompare(String(a.updated_at||'')))}
function prioritizedRows(){return shell.rows.filter(r=>r.attention_level!=='SEGUIMIENTO').sort((a,b)=>rank(a)-rank(b)||Number(b.max_priority_score||0)-Number(a.max_priority_score||0)||Number(b.signal_family_count||0)-Number(a.signal_family_count||0))}
function caseRow(c){return `<button class="case-row" data-open-case="${esc(c.case_id)}"><span class="case-dot ${esc(c.status)}"></span><span class="case-row-main"><b>${esc(c.title||c.case_ref||'Expediente')}</b><small>${esc(c.organization_name||c.organization_id||'Servicio')} → ${esc(c.provider_name||c.provider_id||'Proveedor')} · ${esc(c.period_year||'')}</small></span><span class="case-row-status">${esc(STATUS_LABEL[c.status]||c.status||'')}</span><span class="case-row-score">${Math.round(Number(c.priority_score||0))}</span></button>`}

function renderHome(){
  const workspace=$('workspace');if(!workspace)return;
  if(!shell.loaded){workspace.innerHTML='<div class="empty large"><h2>Cargando inicio RIGP</h2><p>Preparando la vista de trabajo.</p></div>';return}
  if(!shell.payload){workspace.innerHTML='<div class="empty large"><h2>No fue posible cargar la portada</h2><p>La Bandeja y los Hallazgos siguen disponibles desde la navegación superior.</p></div>';return}
  const cases=activeCases(),rows=prioritizedRows(),caseFindings=new Set(readCases().flatMap(c=>c.finding_ids||[]));
  const pending=rows.filter(r=>!caseFindings.has(idOf(r)));
  const candidate=pending[0]||rows[0]||null;
  const immediate=rows.filter(r=>r.attention_level==='ATENCION_INMEDIATA').length;
  const services=new Set(rows.map(r=>r.organization_id).filter(Boolean)).size;
  const providers=new Set(rows.map(r=>r.provider_id).filter(Boolean)).size;
  const years=shell.payload?.analysis_window?.years||[];
  const coverage=years.length?`${years[0]}–${years[years.length-1]}`:'período publicado';
  workspace.innerHTML=`<div class="section-head"><div><div class="eyebrow">Inicio</div><h2>Qué requiere atención ahora</h2><p>Una entrada simple al trabajo analítico: continuar expedientes, revisar nuevos hallazgos o explorar relaciones servicio–proveedor sin perder contexto.</p></div><span>${esc(coverage)} · ${fmt.format(shell.rows.length)} relaciones publicadas</span></div>
  <section class="shell-home-grid">
    <article class="shell-action"><span>Trabajo en curso</span><b>${fmt.format(cases.length)}</b><p>Expedientes abiertos que ya tienen hipótesis, evidencia o revisión en desarrollo.</p><button class="shell-button" data-shell-go="bandeja">Abrir Bandeja</button></article>
    <article class="shell-action"><span>Por decidir</span><b>${fmt.format(pending.length)}</b><p>Hallazgos prioritarios que todavía no han sido convertidos en expediente.</p><button class="shell-button primary" data-shell-go="triage">Revisar Hallazgos</button></article>
    <article class="shell-action"><span>Atención inmediata</span><b>${fmt.format(immediate)}</b><p>Relaciones ubicadas primero en la cola de revisión. La prioridad ordena trabajo; no presume irregularidad.</p><button class="shell-button" data-shell-go="explorar">Explorar universo</button></article>
  </section>
  ${candidate?`<section class="home-next"><div><span class="eyebrow">Siguiente recomendado</span><h3>${esc(candidate.finding_title||'Relación priorizada')}</h3><p>${esc(candidate.organization_name||candidate.organization_id||'Servicio')} → ${esc(candidate.provider_name||candidate.provider_id||'Proveedor')}</p><small>${esc(candidate.why_review||'La relación reúne señales que justifican revisión humana y contraste documental.')}</small></div><div class="home-next-side"><div class="home-next-score"><b>${Math.round(Number(candidate.max_priority_score||0))}</b><span>prioridad / 100</span></div><button class="shell-button primary" data-shell-filter="${esc(candidate.provider_name||candidate.provider_id||candidate.organization_name||candidate.organization_id||'')}">Ver en Hallazgos</button></div></section>`:''}
  <section class="shell-summary"><article><h3>Cobertura disponible</h3><div class="shell-metrics"><div><b>${fmt.format(services)}</b><span>servicios en foco</span></div><div><b>${fmt.format(providers)}</b><span>proveedores en foco</span></div><div><b>${fmt.format(rows.length)}</b><span>relaciones prioritarias</span></div><div><b>${fmt.format(shell.rows.length)}</b><span>relaciones publicadas</span></div></div><p class="shell-context-note">La lectura principal sigue siendo la relación servicio–proveedor. Las vistas de entidad e informe se abren dentro de un expediente, no como módulos separados.</p></article><article><h3>Expedientes para continuar</h3><div class="case-list">${cases.slice(0,5).map(caseRow).join('')||'<div class="empty">No hay expedientes activos. Usa Hallazgos para iniciar una revisión.</div>'}</div></article></section>`;
}

function aggregate(mode){
  const map=new Map();
  for(const r of shell.rows){
    const isProvider=mode==='provider';
    const id=isProvider?r.provider_id:r.organization_id;
    const name=isProvider?r.provider_name:r.organization_name;
    if(!id&&!name)continue;
    const key=String(id||name);
    let x=map.get(key);
    if(!x){x={id:key,name:name||id||'Entidad',counterparties:new Set(),periods:new Set(),findings:0,immediate:0,maxScore:0,maxAmount:0};map.set(key,x)}
    const counterpart=isProvider?(r.organization_name||r.organization_id):(r.provider_name||r.provider_id);
    if(counterpart)x.counterparties.add(String(counterpart));
    if(r.periodo)x.periods.add(String(r.periodo));
    x.findings+=1;
    if(r.attention_level==='ATENCION_INMEDIATA')x.immediate+=1;
    x.maxScore=Math.max(x.maxScore,Number(r.max_priority_score||0));
    x.maxAmount=Math.max(x.maxAmount,Number(r.max_transaction_amount||0));
  }
  return [...map.values()].sort((a,b)=>b.immediate-a.immediate||b.maxScore-a.maxScore||b.findings-a.findings||a.name.localeCompare(b.name,'es'));
}
function renderExplore(){
  const workspace=$('workspace');if(!workspace)return;
  if(!shell.loaded){workspace.innerHTML='<div class="empty large"><h2>Cargando explorador</h2></div>';return}
  const label=shell.exploreMode==='provider'?'proveedores':'servicios';
  const q=shell.exploreQuery.trim().toLocaleLowerCase('es');
  const all=aggregate(shell.exploreMode);
  const items=all.filter(x=>!q||`${x.name} ${x.id}`.toLocaleLowerCase('es').includes(q)).slice(0,36);
  workspace.innerHTML=`<div class="section-head"><div><div class="eyebrow">Explorar</div><h2>Servicios y proveedores en contexto</h2><p>Explora actores desde los hallazgos publicados y vuelve al detalle analítico cuando una relación merezca revisión. No se crean conclusiones por navegar una entidad.</p></div><span>${fmt.format(all.length)} ${label}</span></div><div class="explore-tools"><input id="shellExploreSearch" type="search" autocomplete="off" placeholder="Buscar por nombre o identificador…" value="${esc(shell.exploreQuery)}"><div class="explore-switch"><button data-explore-mode="provider" class="${shell.exploreMode==='provider'?'on':''}">Proveedores</button><button data-explore-mode="service" class="${shell.exploreMode==='service'?'on':''}">Servicios</button></div></div><section class="explore-grid">${items.map(x=>`<article class="explore-card"><div class="explore-card-top"><h3>${esc(x.name)}</h3><span class="score">${Math.round(x.maxScore)}</span></div><div class="id">${esc(x.id)}</div><dl><div><dt>Relaciones</dt><dd>${fmt.format(x.findings)}</dd></div><div><dt>Contrapartes</dt><dd>${fmt.format(x.counterparties.size)}</dd></div><div><dt>Años</dt><dd>${fmt.format(x.periods.size)}</dd></div></dl><button class="shell-button" data-shell-filter="${esc(x.name||x.id)}">Ver hallazgos relacionados</button><div class="shell-context-note">${x.immediate?`${x.immediate} relación(es) en atención inmediata · `:''}mayor monto observado ${money(x.maxAmount)}</div></article>`).join('')||'<div class="explore-empty">No hay coincidencias para esta búsqueda.</div>'}</section>`;
}
function routeToTriage(query=''){
  const btn=document.querySelector('#primaryNav [data-view="triage"]');
  if(!btn)return;
  btn.click();
  requestAnimationFrame(()=>{const input=$('search');if(!input)return;input.value=query;input.dispatchEvent(new Event('input',{bubbles:true}));input.focus()});
}
function maybeStart(){
  if(shell.started||!shell.loaded)return;
  const workspace=$('workspace'),status=$('status');
  if(!workspace||!workspace.childNodes.length||!status||!/relaciones|arquitectura/i.test(status.textContent))return;
  shell.started=true;
  const home=document.querySelector('#primaryNav [data-view="inicio"]');
  if(home)home.click();
}

const observer=new MutationObserver(()=>{syncCaseNav();setPrimary(topGroup(shell.current));maybeStart()});
const workspace=$('workspace'),banner=$('caseBanner'),status=$('status');
if(workspace)observer.observe(workspace,{childList:true});
if(banner)observer.observe(banner,{attributes:true,childList:true,subtree:true});
if(status)observer.observe(status,{childList:true,characterData:true,subtree:true});

document.addEventListener('click',e=>{
  const go=e.target.closest('[data-shell-go]');
  if(go){const target=go.dataset.shellGo;if(target==='inicio'||target==='explorar'){document.querySelector(`#primaryNav [data-view="${target}"]`)?.click()}else if(target==='triage')routeToTriage('');else document.querySelector(`#primaryNav [data-view="${target}"]`)?.click();return}
  const filter=e.target.closest('[data-shell-filter]');if(filter){routeToTriage(filter.dataset.shellFilter||'');return}
  const mode=e.target.closest('[data-explore-mode]');if(mode){shell.exploreMode=mode.dataset.exploreMode;shell.exploreQuery='';renderExplore();return}
  const view=e.target.closest('[data-view]');
  if(view){shell.current=view.dataset.view;queueMicrotask(()=>{setPrimary(topGroup(shell.current));syncCaseNav();if(shell.current==='inicio')renderHome();else if(shell.current==='explorar')renderExplore()});return}
  if(e.target.closest('[data-open-case],[data-create-case]')){shell.current='caso';queueMicrotask(()=>{setPrimary('bandeja');syncCaseNav()})}
});
document.addEventListener('input',e=>{if(e.target.id==='shellExploreSearch'){shell.exploreQuery=e.target.value;renderExplore();const input=$('shellExploreSearch');if(input){input.focus();input.setSelectionRange(input.value.length,input.value.length)}}});

fetch(DATA_URL,{cache:'no-store'})
  .then(r=>{if(!r.ok)throw new Error('HTTP '+r.status);return r.json()})
  .then(d=>{shell.payload=d;shell.rows=Array.isArray(d.relation_findings)?d.relation_findings:[];shell.loaded=true;maybeStart()})
  .catch(()=>{shell.payload=null;shell.rows=[];shell.loaded=true;maybeStart()});

syncCaseNav();setPrimary('inicio');
})();