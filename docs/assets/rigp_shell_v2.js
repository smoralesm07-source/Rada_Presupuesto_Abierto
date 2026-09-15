(()=>{'use strict';

const DATA_URL='data/investigative_findings.json';
const caseRepo=window.RIGPCaseRepository;
const STATUS_LABEL={TRIAGE:'Por revisar',EN_REVISION:'En análisis',PROFUNDIZAR:'Profundizar',EXPLICADO:'Explicado',ESCALADO:'Decisión / escalamiento',CERRADO:'Cerrado'};
const shell={payload:null,rows:[],loaded:false,current:'inicio',situation:null,exploreMode:'provider',exploreQuery:''};
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const fmt=new Intl.NumberFormat('es-CL');
const fmt1=new Intl.NumberFormat('es-CL',{maximumFractionDigits:1});
const idOf=r=>String(r?.finding_id||`${r?.organization_id||''}|${r?.provider_id||''}|${r?.periodo||''}`);
const money=v=>{v=Number(v||0);if(!v)return '—';const a=Math.abs(v);if(a>=1e12)return '$'+fmt1.format(v/1e12)+' bill.';if(a>=1e9)return '$'+fmt1.format(v/1e9)+' mil M';if(a>=1e6)return '$'+fmt1.format(v/1e6)+' M';return '$'+fmt.format(Math.round(v));};
const readCases=()=>caseRepo?.list?.()||[];
const caseForFinding=fid=>caseRepo?.findByFinding?.(fid)||null;
const activeCase=()=>{const ref=$('caseBanner')?.querySelector('b')?.textContent?.trim();return ref?(caseRepo?.get?.(ref)||readCases().find(c=>String(c.case_ref||'')===ref)||null):null};

const SITUATIONS={
  INSTRUMENTAL:{
    key:'INSTRUMENTAL',label:'Proveedor posiblemente instrumental',short:'Capacidad e identidad por comprobar',tone:'amber',
    question:'¿La contraparte tenía capacidad, trayectoria y actividad coherentes con los recursos públicos observados?',
    hypothesis:'Hipótesis de revisión: posible uso de una contraparte de reciente creación, baja capacidad observable o actividad poco alineada para canalizar recursos. También puede existir una explicación comercial normal.',
    checks:['Confirmar identidad, RUT validado, antigüedad y continuidad tributaria.','Contrastar giro, tramo de ventas y capacidad operativa con lo efectivamente contratado.','Verificar orden de compra, prestación real y trazabilidad del pago.']
  },
  DIRECCIONAMIENTO:{
    key:'DIRECCIONAMIENTO',label:'Concentración o direccionamiento a revisar',short:'Competencia y dependencia',tone:'blue',
    question:'¿La concentración en un proveedor se explica por mercado, contrato o convenios, o requiere revisar la forma de adjudicación?',
    hypothesis:'Hipótesis de revisión: posible concentración indebida, favorecimiento o direccionamiento. Por sí sola, la concentración no acredita irregularidad ni delito.',
    checks:['Reconstruir modalidad de compra, competencia y oferentes disponibles.','Revisar recurrencia servicio–proveedor y cambios en participación o montos.','Buscar antecedentes objetivos de justificación, excepción o dependencia técnica.']
  },
  DOCUMENTAL:{
    key:'DOCUMENTAL',label:'Fraccionamiento o soporte documental inconsistente',short:'Documentos y pagos',tone:'red',
    question:'¿La secuencia de documentos y pagos corresponde a hitos válidos o podría estar evitando controles o duplicando una obligación?',
    hypothesis:'Hipótesis de revisión: posible fraccionamiento para eludir controles, duplicidad material o inconsistencia documental. La similitud de registros no basta para afirmarlo.',
    checks:['Comparar facturas, OC, fechas, montos y descripción de prestaciones.','Determinar si varios registros corresponden a un mismo hecho económico o a hitos distintos.','Verificar recepción conforme, autorizaciones y eventual umbral de contratación aplicable.']
  },
  EJECUCION:{
    key:'EJECUCION',label:'Ejecución atípica que requiere explicación',short:'Monto, plazo o temporalidad',tone:'violet',
    question:'¿El monto, plazo o momento de ejecución tiene una explicación operativa suficiente frente al comportamiento comparable?',
    hypothesis:'Hipótesis de revisión: ejecución fuera de patrón que podría responder a excepción operativa, error, presión presupuestaria o uso irregular. Requiere reconstrucción documental antes de inferir una causa.',
    checks:['Comparar materialidad con proveedores y períodos equivalentes.','Revisar contrato, modificaciones, recepción y fechas de pago.','Explicar el quiebre temporal o de monto con antecedentes verificables.']
  }
};

function actionState(r){return String(r?.actionability?.state||r?.actionability||'').toUpperCase()}
function isActionable(r){const s=actionState(r);if(s==='SOLO_APRENDIZAJE')return false;if(s==='ACCIONABLE'||s==='EVIDENCIA_EN_RIESGO')return true;return r?.attention_level!=='SEGUIMIENTO'}
function isEvidenceAtRisk(r){return actionState(r)==='EVIDENCIA_EN_RIESGO'}
function attentionRank(r){return r?.attention_level==='ATENCION_INMEDIATA'?0:r?.attention_level==='REVISION_PRIORITARIA'?1:2}
function signalSet(r){return new Set(r?.signal_types||[])}
function situationKey(r){
  const family=String(r?.finding_family||''),s=signalSet(r);
  if(family==='CONVERGENCIA_MULTIFACTOR'){
    if([...s].some(x=>['NEWBORN_SUPPLIER','CAPACITY_MISMATCH','ACTIVITY_MISMATCH','TERMINATION_AFTER_PAYMENT','DORMANT_REACTIVATION','NEW_TO_SERIES_HIGH_SPEND'].includes(x)))return'INSTRUMENTAL';
    if(s.has('POTENTIAL_FRAGMENTATION')||s.has('EXACT_DUPLICATE_CANDIDATE'))return'DOCUMENTAL';
    if(s.has('PROVIDER_CONCENTRATION'))return'DIRECCIONAMIENTO';
    return'EJECUCION';
  }
  if(['CONTRAPARTE_Y_CAPACIDAD','IRRUPCION_CAMBIO_ESCALA'].includes(family)||[...s].some(x=>['NEWBORN_SUPPLIER','CAPACITY_MISMATCH','ACTIVITY_MISMATCH','TERMINATION_AFTER_PAYMENT','DORMANT_REACTIVATION'].includes(x)))return'INSTRUMENTAL';
  if(['COMPETENCIA_ADJUDICACION','CONCENTRACION_DEPENDENCIA'].includes(family)||s.has('PROVIDER_CONCENTRATION'))return'DIRECCIONAMIENTO';
  if(family==='INTEGRIDAD_DOCUMENTAL_PAGOS'||s.has('POTENTIAL_FRAGMENTATION')||s.has('EXACT_DUPLICATE_CANDIDATE'))return'DOCUMENTAL';
  return'EJECUCION';
}
function situationFor(r){return SITUATIONS[situationKey(r)]}
function pair(r){return `${r?.organization_name||r?.organization_id||'Servicio'} → ${r?.provider_name||r?.provider_id||'Proveedor'}`}
function sortedActionable(){return shell.rows.filter(isActionable).sort((a,b)=>attentionRank(a)-attentionRank(b)||Number(b.max_priority_score||0)-Number(a.max_priority_score||0)||Number(b.signal_family_count||0)-Number(a.signal_family_count||0))}
function technicalClues(r){
  const out=[];const signals=signalSet(r);
  if(signals.has('NEWBORN_SUPPLIER'))out.push('inicio reciente');
  if(signals.has('CAPACITY_MISMATCH'))out.push('capacidad por contrastar');
  if(signals.has('ACTIVITY_MISMATCH'))out.push('actividad poco alineada');
  if(signals.has('PROVIDER_CONCENTRATION'))out.push('concentración');
  if(signals.has('NEW_TO_SERIES_HIGH_SPEND'))out.push('irrupción con gasto relevante');
  if(signals.has('POTENTIAL_FRAGMENTATION'))out.push('secuencia compatible con fraccionamiento');
  if(signals.has('EXACT_DUPLICATE_CANDIDATE'))out.push('documentos potencialmente repetidos');
  if(signals.has('AMOUNT_OUTLIER'))out.push('monto fuera de patrón');
  if(signals.has('YEAR_END_SPIKE'))out.push('concentración temporal');
  if(signals.has('PAYMENT_DELAY_OUTLIER'))out.push('plazo atípico');
  return out.slice(0,3);
}
function priorityLabel(r){if(r?.attention_level==='ATENCION_INMEDIATA')return'Atención alta';if(r?.attention_level==='REVISION_PRIORITARIA')return'Revisión prioritaria';return'Seguimiento'}
function topGroup(view){if(view==='inicio'||view==='triage')return'inicio';if(view==='explorar'||view==='entidad')return'explorar';return'bandeja'}
function setPrimary(view){document.querySelectorAll('#primaryNav [data-view]').forEach(b=>b.classList.toggle('on',b.dataset.view===view))}
function syncCaseNav(){const banner=$('caseBanner'),nav=$('caseNav');if(nav&&banner)nav.hidden=banner.hidden}
function situationCounts(rows){const counts={};Object.keys(SITUATIONS).forEach(k=>counts[k]=0);rows.forEach(r=>counts[situationKey(r)]++);return counts}
function findingForCase(c){const fid=(c?.finding_ids||[])[0];return shell.rows.find(r=>idOf(r)===String(fid))||null}

function renderHome(){
  const w=$('workspace');if(!w)return;
  if(!shell.loaded){w.innerHTML='<div class="guided-empty"><h2>Preparando Radar</h2><p>Ordenando sólo lo que puede convertirse en trabajo analítico.</p></div>';return}
  const rows=sortedActionable(),counts=situationCounts(rows),cases=readCases(),caseFindings=new Set(cases.flatMap(c=>c.finding_ids||[]));
  const pending=rows.filter(r=>!caseFindings.has(idOf(r))),candidate=pending[0]||rows[0]||null;
  const riskCount=rows.filter(isEvidenceAtRisk).length,learning=shell.rows.filter(r=>actionState(r)==='SOLO_APRENDIZAJE').length;
  const cards=Object.values(SITUATIONS).map(s=>({...s,count:counts[s.key]||0})).filter(x=>x.count>0).slice(0,4);
  w.innerHTML=`<section class="guided-intro"><div><span class="eyebrow">Radar</span><h2>Qué está pasando y dónde mirar primero</h2><p>RIGP agrupa los hallazgos en <b>situaciones investigables</b>. Cada situación propone una hipótesis para corroborar o descartar y deja las señales técnicas en segundo plano.</p></div><div class="guided-legend"><b>${fmt.format(rows.length)}</b><span>relaciones accionables</span>${riskCount?`<small>${fmt.format(riskCount)} con evidencia en riesgo de perder vigencia</small>`:''}</div></section>
  ${candidate?heroCandidate(candidate):'<section class="guided-hero calm"><div><span class="eyebrow">Sin cola prioritaria</span><h3>No hay una relación accionable pendiente para recomendar.</h3><p>Puedes continuar casos abiertos o explorar el universo publicado.</p></div><button class="guided-button" data-shell-go="bandeja">Abrir casos</button></section>'}
  <div class="guided-section-title"><div><span class="eyebrow">Lectura dirigida</span><h3>Cuatro formas de entender los hallazgos</h3></div><small>Haz clic sólo en la situación que quieras revisar.</small></div>
  <section class="situation-grid">${cards.map(s=>situationCard(s)).join('')||'<div class="guided-empty">No hay situaciones accionables publicadas.</div>'}</section>
  <section class="guided-footnote"><b>Qué queda fuera de esta vista</b><span>${learning?`${fmt.format(learning)} relaciones de aprendizaje histórico no se muestran como casos. `:''}La prioridad ordena revisión; ninguna hipótesis implica que exista delito, fraude, corrupción o lavado de activos.</span></section>`;
}
function heroCandidate(r){
  const s=situationFor(r),existing=caseForFinding(idOf(r));
  return `<section class="guided-hero tone-${s.tone}"><div class="guided-hero-main"><span class="eyebrow">Empieza aquí · ${esc(priorityLabel(r))}</span><h3>${esc(s.label)}</h3><p class="guided-pair">${esc(pair(r))} · ${esc(r.periodo||'')}</p><p>${esc(s.question)}</p><div class="guided-clues">${technicalClues(r).map(x=>`<span>${esc(x)}</span>`).join('')}</div></div><div class="guided-hero-action"><small>Hipótesis para evaluar</small><p>${esc(s.hypothesis)}</p>${existing?`<button class="guided-button primary" data-open-case="${esc(existing.case_id)}">Continuar expediente</button>`:`<button class="guided-button primary" data-create-case="${esc(idOf(r))}">Tomar caso</button>`}</div></section>`;
}
function situationCard(s){return `<button class="situation-card tone-${s.tone}" data-situation="${s.key}"><span class="situation-count">${fmt.format(s.count)}</span><div><span class="eyebrow">${esc(s.short)}</span><h3>${esc(s.label)}</h3><p>${esc(s.question)}</p></div><span class="situation-link">Ver relaciones →</span></button>`}

function renderTriage(){
  const w=$('workspace');if(!w)return;const all=sortedActionable(),key=shell.situation;
  const rows=key?all.filter(r=>situationKey(r)===key):all;const s=key?SITUATIONS[key]:null;
  w.innerHTML=`<div class="guided-focus-head"><button class="guided-back" data-shell-go="inicio">← Volver al Radar</button><div><span class="eyebrow">${s?'Situación investigable':'Relaciones accionables'}</span><h2>${esc(s?.label||'Qué merece revisión ahora')}</h2><p>${esc(s?.hypothesis||'Sólo se muestran relaciones que pueden convertirse en trabajo analítico. Los datos históricos de aprendizaje quedan fuera de la cola.')}</p></div><div class="guided-count"><b>${fmt.format(rows.length)}</b><span>relaciones</span></div></div>
  ${s?`<section class="guided-checks"><div><b>Pregunta central</b><span>${esc(s.question)}</span></div><ol>${s.checks.map(x=>`<li>${esc(x)}</li>`).join('')}</ol></section>`:''}
  <section class="guided-findings">${rows.slice(0,30).map(findingCard).join('')||'<div class="guided-empty"><h3>Sin relaciones en esta situación</h3><p>No hay elementos accionables publicados en este grupo.</p></div>'}</section>
  ${rows.length>30?`<p class="guided-list-note">Mostrando las 30 relaciones de mayor prioridad. Usa Explorar para buscar una entidad específica.</p>`:''}`;
}
function findingCard(r){
  const s=situationFor(r),existing=caseForFinding(idOf(r)),clues=technicalClues(r),atRisk=isEvidenceAtRisk(r);
  return `<article class="guided-finding tone-${s.tone}"><div class="guided-finding-top"><span class="guided-priority">${esc(priorityLabel(r))}</span>${atRisk?'<span class="guided-expiry">Evidencia en riesgo</span>':''}<span class="guided-year">${esc(r.periodo||'')}</span></div><h3>${esc(r.provider_name||r.provider_id||'Proveedor')}</h3><p class="guided-service">${esc(r.organization_name||r.organization_id||'Servicio')}</p><p class="guided-question">${esc(s.question)}</p><div class="guided-clues">${clues.map(x=>`<span>${esc(x)}</span>`).join('')||'<span>requiere contraste documental</span>'}</div><div class="guided-finding-actions">${existing?`<button class="guided-button primary" data-open-case="${esc(existing.case_id)}">Continuar caso</button>`:`<button class="guided-button primary" data-create-case="${esc(idOf(r))}">Tomar caso</button>`}<details><summary>Ver sustento técnico</summary><div class="technical-mini"><span>Prioridad ${Math.round(Number(r.max_priority_score||0))}/100</span><span>Monto máx. ${money(r.max_transaction_amount)}</span><span>${fmt.format(Number(r.signal_family_count||0))} familias</span><p>${esc(r.why_review||'La relación fue priorizada para revisión humana.')}</p></div></details></div></article>`;
}

function caseBucket(c){if(c.status==='TRIAGE')return'REVIEW';if(['EN_REVISION','PROFUNDIZAR'].includes(c.status))return'ANALYSIS';if(['ESCALADO','EXPLICADO'].includes(c.status))return'DECISION';return'CLOSED'}
function renderBandeja(){
  const w=$('workspace');if(!w)return;const cases=readCases().sort((a,b)=>Number(b.priority_score||0)-Number(a.priority_score||0)||String(b.updated_at||'').localeCompare(String(a.updated_at||'')));
  const groups={REVIEW:[],ANALYSIS:[],DECISION:[],CLOSED:[]};cases.forEach(c=>groups[caseBucket(c)].push(c));
  w.innerHTML=`<div class="guided-focus-head cases"><div><span class="eyebrow">Casos</span><h2>Una bandeja para decidir, no para leer señales</h2><p>El trabajo se reduce a tres momentos: entender el caso, comprobar lo que cambia la decisión y cerrar o escalar.</p></div><div class="guided-count"><b>${fmt.format(cases.filter(c=>caseBucket(c)!=='CLOSED').length)}</b><span>activos</span></div></div><section class="guided-board">${caseColumn('Por revisar','Entender qué ocurre antes de profundizar.',groups.REVIEW)}${caseColumn('En análisis','Comprobar hipótesis con evidencia que cambie la decisión.',groups.ANALYSIS)}${caseColumn('Decisión','Cerrar con explicación suficiente o escalar con fundamento.',groups.DECISION)}</section>${groups.CLOSED.length?`<details class="closed-cases"><summary>${groups.CLOSED.length} caso(s) cerrados</summary><div class="guided-case-list">${groups.CLOSED.slice(0,20).map(guidedCaseRow).join('')}</div></details>`:''}`;
}
function caseColumn(title,desc,rows){return `<article class="guided-column"><header><div><h3>${esc(title)}</h3><p>${esc(desc)}</p></div><b>${fmt.format(rows.length)}</b></header><div class="guided-case-list">${rows.map(guidedCaseRow).join('')||'<div class="guided-column-empty">Sin casos en esta etapa.</div>'}</div></article>`}
function guidedCaseRow(c){const r=findingForCase(c),s=r?situationFor(r):null;return `<button class="guided-case-row" data-open-case="${esc(c.case_id)}"><span class="case-dot ${esc(c.status||'TRIAGE')}"></span><span><b>${esc(s?.label||c.title||c.case_ref||'Expediente')}</b><small>${esc(c.organization_name||c.organization_id||'Servicio')} → ${esc(c.provider_name||c.provider_id||'Proveedor')}</small></span><em>${esc(STATUS_LABEL[c.status]||c.status||'')}</em></button>`}

function aggregate(mode){
  const map=new Map();for(const r of sortedActionable()){
    const provider=mode==='provider',id=provider?r.provider_id:r.organization_id,name=provider?r.provider_name:r.organization_name;if(!id&&!name)continue;
    const key=String(id||name),counter=provider?(r.organization_name||r.organization_id):(r.provider_name||r.provider_id);let x=map.get(key);
    if(!x){x={id:key,name:name||id||'Entidad',counterparties:new Set(),findings:0,maxScore:0,situations:new Set()};map.set(key,x)}
    if(counter)x.counterparties.add(String(counter));x.findings++;x.maxScore=Math.max(x.maxScore,Number(r.max_priority_score||0));x.situations.add(situationKey(r));
  }return [...map.values()].sort((a,b)=>b.maxScore-a.maxScore||b.findings-a.findings||a.name.localeCompare(b.name,'es'));
}
function renderExplore(){
  const w=$('workspace');if(!w)return;const all=aggregate(shell.exploreMode),q=shell.exploreQuery.trim().toLocaleLowerCase('es');const items=all.filter(x=>!q||`${x.name} ${x.id}`.toLocaleLowerCase('es').includes(q)).slice(0,36);
  w.innerHTML=`<div class="guided-focus-head"><div><span class="eyebrow">Explorar</span><h2>Buscar una entidad sin convertirla en sospechosa</h2><p>La búsqueda sirve para encontrar relaciones ya priorizadas; no genera una conclusión por el solo hecho de que una entidad aparezca.</p></div></div><div class="explore-tools"><input id="shellExploreSearch" type="search" autocomplete="off" placeholder="Buscar proveedor o servicio…" value="${esc(shell.exploreQuery)}"><div class="explore-switch"><button data-explore-mode="provider" class="${shell.exploreMode==='provider'?'on':''}">Proveedores</button><button data-explore-mode="service" class="${shell.exploreMode==='service'?'on':''}">Servicios</button></div></div><section class="guided-explore-grid">${items.map(x=>`<article class="guided-explore-card"><h3>${esc(x.name)}</h3><small>${esc(x.id)}</small><div><b>${fmt.format(x.findings)}</b><span>relaciones accionables</span></div><p>${fmt.format(x.counterparties.size)} contraparte(s) · ${fmt.format(x.situations.size)} situación(es)</p><button class="guided-button" data-shell-filter="${esc(x.name||x.id)}">Ver relaciones</button></article>`).join('')||'<div class="guided-empty">Sin coincidencias.</div>'}</section>`;
}

function enhanceCase(){
  const w=$('workspace'),head=w?.querySelector('.case-head');if(!w||!head||w.querySelector('[data-guided-case-brief]'))return;
  const c=activeCase();if(!c)return;const r=findingForCase(c),s=r?situationFor(r):SITUATIONS.EJECUCION;
  const brief=document.createElement('section');brief.className=`guided-case-brief tone-${s.tone}`;brief.dataset.guidedCaseBrief='1';
  brief.innerHTML=`<div><span class="eyebrow">1 · Qué está pasando</span><h3>${esc(s.label)}</h3><p>${esc(s.question)}</p></div><div><span class="eyebrow">2 · Hipótesis a evaluar</span><p>${esc(s.hypothesis)}</p></div><div><span class="eyebrow">3 · Comprueba primero</span><ol>${s.checks.map(x=>`<li>${esc(x)}</li>`).join('')}</ol></div>`;
  head.insertAdjacentElement('afterend',brief);
  const layout=w.querySelector('.case-layout');if(!layout)return;
  const panels=[...layout.children].filter(el=>el.classList?.contains('panel'));
  const primary=[],technical=[];
  for(const p of panels){const title=p.querySelector('h3')?.textContent?.trim()||'';if(/Hipótesis de trabajo|Plan de evidencia|Notas del analista|Bitácora/i.test(title))primary.push(p);else technical.push(p)}
  primary.forEach(p=>p.classList.add('guided-primary-panel'));
  if(technical.length){const details=document.createElement('details');details.className='guided-technical';details.innerHTML=`<summary><span><b>Sustento técnico</b><small>Señales, comparables, SII y contratación</small></span><em>${technical.length} bloques</em></summary><div class="guided-technical-grid"></div>`;const grid=details.querySelector('.guided-technical-grid');technical.forEach(p=>grid.appendChild(p));const route=layout.querySelector('.route-card');layout.insertBefore(details,route||null)}
}
function enhanceReport(){const w=$('workspace');if(!w||!w.querySelector('.report')||w.querySelector('[data-guided-report-note]'))return;const note=document.createElement('p');note.dataset.guidedReportNote='1';note.className='guided-report-note';note.innerHTML='<b>Lectura esperada:</b> qué se observó → qué hipótesis se evaluó → qué evidencia la sostuvo o descartó → qué decidió el analista.';w.querySelector('.section-head')?.insertAdjacentElement('afterend',note)}
function postRender(){syncCaseNav();setPrimary(topGroup(shell.current));if(shell.current==='caso')enhanceCase();if(shell.current==='informe')enhanceReport()}
function route(view){const btn=document.querySelector(`[data-view="${view}"]`);btn?.click()}
function routeSituation(key){shell.situation=key;route('triage')}
function routeSearch(q){shell.situation=null;route('triage');requestAnimationFrame(()=>{const rows=sortedActionable().filter(r=>[r.organization_name,r.organization_id,r.provider_name,r.provider_id].join(' ').toLocaleLowerCase('es').includes(String(q||'').toLocaleLowerCase('es')));const w=$('workspace');if(w){w.innerHTML=`<div class="guided-focus-head"><button class="guided-back" data-shell-go="explorar">← Volver a Explorar</button><div><span class="eyebrow">Resultados</span><h2>${fmt.format(rows.length)} relación(es) para “${esc(q)}”</h2><p>Resultados accionables agrupados por relación servicio–proveedor.</p></div></div><section class="guided-findings">${rows.slice(0,30).map(findingCard).join('')||'<div class="guided-empty">Sin relaciones accionables para esta búsqueda.</div>'}</section>`}})}

const observer=new MutationObserver(()=>requestAnimationFrame(postRender));
if($('workspace'))observer.observe($('workspace'),{childList:true,subtree:false});
if($('caseBanner'))observer.observe($('caseBanner'),{attributes:true,childList:true,subtree:true});
caseRepo?.subscribe?.(()=>{if(shell.current==='inicio')renderHome();else if(shell.current==='bandeja')renderBandeja();requestAnimationFrame(postRender)});

document.addEventListener('click',e=>{
  const sit=e.target.closest('[data-situation]');if(sit){routeSituation(sit.dataset.situation);return}
  const go=e.target.closest('[data-shell-go]');if(go){const v=go.dataset.shellGo;if(v==='inicio'){shell.current='inicio';shell.situation=null;renderHome();setPrimary('inicio')}else route(v);return}
  const filter=e.target.closest('[data-shell-filter]');if(filter){routeSearch(filter.dataset.shellFilter||'');return}
  const mode=e.target.closest('[data-explore-mode]');if(mode){shell.exploreMode=mode.dataset.exploreMode;shell.exploreQuery='';renderExplore();return}
  const view=e.target.closest('[data-view]');if(view){shell.current=view.dataset.view;queueMicrotask(()=>{if(shell.current==='inicio')renderHome();else if(shell.current==='triage')renderTriage();else if(shell.current==='bandeja')renderBandeja();else if(shell.current==='explorar')renderExplore();postRender()});return}
  if(e.target.closest('[data-open-case],[data-create-case]')){shell.current='caso';queueMicrotask(postRender)}
});
document.addEventListener('input',e=>{if(e.target.id==='shellExploreSearch'){shell.exploreQuery=e.target.value;renderExplore();const i=$('shellExploreSearch');if(i){i.focus();i.setSelectionRange(i.value.length,i.value.length)}}});

fetch(DATA_URL,{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error('HTTP '+r.status);return r.json()}).then(d=>{shell.payload=d;shell.rows=Array.isArray(d.relation_findings)?d.relation_findings:[];shell.loaded=true;shell.current='inicio';renderHome();setPrimary('inicio')}).catch(()=>{shell.payload=null;shell.rows=[];shell.loaded=true;renderHome();setPrimary('inicio')});

syncCaseNav();
})();
