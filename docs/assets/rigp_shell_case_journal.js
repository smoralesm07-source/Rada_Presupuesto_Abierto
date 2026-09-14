(()=>{'use strict';

const BACKUP_SCHEMA='RIGP-CASE-BACKUP-v1';
const caseRepo=window.RIGPCaseRepository;
const NOTE_TYPES={ANALISIS:'Análisis',HIPOTESIS:'Hipótesis',PENDIENTE:'Pendiente',DECISION:'Decisión',CONCLUSION:'Conclusión'};
const EVENT_LABELS={
  EXPEDIENTE_CREADO:'Expediente creado',ACTUALIZACION:'Expediente actualizado',ESTADO_CAMBIADO:'Estado del expediente actualizado',EVIDENCIA_ACTUALIZADA:'Plan de evidencia actualizado',HIPOTESIS_ACTUALIZADA:'Hipótesis de trabajo actualizada',NOTA_ACTUALIZADA:'Notas de trabajo actualizadas',CONCLUSION_ACTUALIZADA:'Conclusión actualizada',NOTA_ESTRUCTURADA_REGISTRADA:'Nota incorporada a la bitácora'
};
const STATUS_VALUES=new Set(['TRIAGE','EN_REVISION','PROFUNDIZAR','EXPLICADO','ESCALADO','CERRADO']);
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const now=()=>new Date().toISOString();
const uuid=()=>globalThis.crypto?.randomUUID?crypto.randomUUID():'note-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,10);

function readCases(){return caseRepo?.list?.()||[]}
function writeCases(rows,reason='journal-write'){const result=caseRepo?.replaceAll?.(rows,{reason});return !!result?.ok}
function activeCase(){
  const ref=$('caseBanner')?.querySelector('b')?.textContent?.trim();if(!ref)return null;
  return caseRepo?.get?.(ref)||readCases().find(c=>String(c.case_ref||'')===ref)||null;
}
function saveCase(next){return !!caseRepo?.upsert?.(next,{reason:'journal-save'})}
function toast(message,error=false){
  document.querySelector('.case-backup-toast')?.remove();const el=document.createElement('div');el.className='case-backup-toast'+(error?' error':'');el.textContent=message;document.body.appendChild(el);setTimeout(()=>el.remove(),3200);
}
function fileStamp(){return new Date().toISOString().slice(0,10)}
function downloadJson(payload,name){const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),500)}
function repositoryState(){return caseRepo?.describe?.()||{mode:'local-cache',remote_attached:false,remote_state:'detached'}}
function backupPayload(cases){
  const state=repositoryState();
  return {schema:BACKUP_SCHEMA,generated_at:now(),storage:state.remote_attached?'case-repository-synced':'case-repository-local-cache',repository_version:caseRepo?.version||null,guardrail:'Este respaldo contiene expedientes de revisión. Las señales y estados del expediente no acreditan irregularidad, delito ni responsabilidad.',cases};
}
function exportAll(){const rows=readCases();downloadJson(backupPayload(rows),`rigp-expedientes-${fileStamp()}.json`);toast(`Respaldo exportado: ${rows.length} expediente(s).`)}
function exportActive(){const c=activeCase();if(!c){toast('No hay un expediente activo para exportar.',true);return}downloadJson(backupPayload([c]),`rigp-${String(c.case_ref||'expediente').replace(/[^a-z0-9_-]+/gi,'-')}.json`);toast('Expediente exportado con su historial.')}
function validCase(c){return !!c&&typeof c==='object'&&typeof c.case_id==='string'&&typeof c.case_ref==='string'&&STATUS_VALUES.has(String(c.status||''))&&Array.isArray(c.finding_ids)&&Array.isArray(c.evidence)}
function mergeImported(imported){
  const current=readCases(),byKey=new Map();
  current.forEach((c,i)=>{if(c.case_id)byKey.set(c.case_id,i);if(c.case_ref)byKey.set('ref:'+c.case_ref,i)});
  let added=0,updated=0,skipped=0;
  for(const raw of imported){
    if(!validCase(raw)){skipped++;continue}
    const c=typeof structuredClone==='function'?structuredClone(raw):JSON.parse(JSON.stringify(raw));c.case_notes=Array.isArray(c.case_notes)?c.case_notes:[];c.events=Array.isArray(c.events)?c.events:[];
    const idx=byKey.get(c.case_id)??byKey.get('ref:'+c.case_ref);
    if(idx==null){current.push(c);const ni=current.length-1;byKey.set(c.case_id,ni);byKey.set('ref:'+c.case_ref,ni);added++;continue}
    const local=current[idx],incomingTs=Date.parse(c.updated_at||c.created_at||0)||0,localTs=Date.parse(local.updated_at||local.created_at||0)||0;
    if(incomingTs>localTs){current[idx]=c;updated++}else skipped++;
  }
  if(!writeCases(current,'backup-import'))throw new Error('No fue posible guardar los expedientes importados.');
  return {added,updated,skipped};
}
async function importFile(file){
  try{const payload=JSON.parse(await file.text());if(payload?.schema!==BACKUP_SCHEMA||!Array.isArray(payload.cases))throw new Error('El archivo no corresponde a un respaldo RIGP compatible.');const result=mergeImported(payload.cases);toast(`Importación lista: ${result.added} nuevos, ${result.updated} actualizados, ${result.skipped} conservados.`);setTimeout(()=>location.reload(),700)}
  catch(err){toast(err?.message||'No fue posible importar el respaldo.',true)}
}
function ensureImportInput(){let input=$('caseBackupImportInput');if(input)return input;input=document.createElement('input');input.type='file';input.accept='application/json,.json';input.id='caseBackupImportInput';input.hidden=true;document.body.appendChild(input);return input}
function portabilityBar(active=false){
  const state=repositoryState(),synced=!!state.remote_attached;
  const el=document.createElement('section');el.className='case-portability-bar';el.dataset.rigpCasePortable='1';
  el.innerHTML=`<div><b>${synced?'Repositorio de expedientes sincronizado':'Persistencia del piloto: repositorio local'}</b><small>${synced?'Los cambios se gestionan mediante el adaptador remoto y mantienen caché local de continuidad.':'El expediente aún no está sincronizado con backend. El respaldo JSON permite moverlo o recuperarlo sin alterar los datos analíticos publicados.'}</small></div><div class="case-portability-actions">${active?'<button data-case-export-active>Exportar expediente</button>':''}<button data-case-export-all>Exportar todos</button><button data-case-import>Importar respaldo</button></div>`;
  return el;
}
function dateLabel(value){const d=new Date(value);if(Number.isNaN(d.getTime()))return '—';return new Intl.DateTimeFormat('es-CL',{dateStyle:'short',timeStyle:'short'}).format(d)}
function journalItems(c){
  const notes=(Array.isArray(c.case_notes)?c.case_notes:[]).map(n=>({at:n.created_at,kind:NOTE_TYPES[n.note_type]||n.note_type||'Nota',text:n.body||''}));
  const events=(Array.isArray(c.events)?c.events:[]).filter(e=>e.event_type!=='NOTA_ESTRUCTURADA_REGISTRADA').map(e=>({at:e.created_at,kind:'Evento',text:EVENT_LABELS[e.event_type]||String(e.event_type||'Actualización').replaceAll('_',' ').toLowerCase()}));
  return [...notes,...events].filter(x=>x.at||x.text).sort((a,b)=>String(b.at||'').localeCompare(String(a.at||''))).slice(0,18);
}
function journalPanel(c){
  const panel=document.createElement('section');panel.className='panel span2 case-journal-panel';panel.dataset.rigpCaseJournal='1';const items=journalItems(c),state=repositoryState();
  panel.innerHTML=`<div class="case-journal-head"><div class="panel-head"><h3>Bitácora del expediente</h3><span>Notas y decisiones con marca temporal</span></div><div class="case-journal-state">${state.remote_attached?'Repositorio sincronizado':'Repositorio local · preparado para backend'}</div></div><div class="case-journal-editor"><label>Tipo<select id="caseJournalType">${Object.entries(NOTE_TYPES).map(([v,l])=>`<option value="${v}">${l}</option>`).join('')}</select></label><label>Registro<textarea id="caseJournalBody" rows="2" placeholder="Registra un argumento, pendiente o decisión que deba quedar en la historia del expediente."></textarea></label><button data-case-note-save>Registrar</button></div>${c.notes?`<div class="case-journal-legacy"><b>Notas de trabajo actuales:</b> ${esc(c.notes)}</div>`:''}<div class="case-journal-list">${items.length?items.map(x=>`<div class="case-journal-item"><span class="case-journal-kind">${esc(x.kind)}</span><p>${esc(x.text)}</p><time>${esc(dateLabel(x.at))}</time></div>`).join(''):'<div class="case-journal-empty">El expediente aún no tiene hitos registrados fuera de su creación.</div>'}</div>`;
  return panel;
}
function reportJournal(c){
  const notes=(Array.isArray(c.case_notes)?c.case_notes:[]).slice(0,8);if(!notes.length)return null;const section=document.createElement('section');section.dataset.rigpJournalReport='1';section.innerHTML=`<h4>Bitácora analítica</h4>${notes.map(n=>`<p><b>${esc(NOTE_TYPES[n.note_type]||n.note_type||'Nota')} · ${esc(dateLabel(n.created_at))}</b><br>${esc(n.body||'')}</p>`).join('')}`;return section;
}
function saveStructuredNote(){
  const c=activeCase(),body=$('caseJournalBody')?.value?.trim(),type=$('caseJournalType')?.value||'ANALISIS';
  if(!c){toast('No se pudo resolver el expediente activo.',true);return}if(!body){toast('Escribe una nota antes de registrarla.',true);return}
  const at=now(),note={note_id:uuid(),note_type:NOTE_TYPES[type]?type:'ANALISIS',body,author_id:null,created_at:at};
  c.case_notes=Array.isArray(c.case_notes)?c.case_notes:[];c.case_notes.unshift(note);c.case_notes=c.case_notes.slice(0,200);
  c.events=Array.isArray(c.events)?c.events:[];c.events.unshift({event_type:'NOTA_ESTRUCTURADA_REGISTRADA',event_payload:{note_id:note.note_id,note_type:note.note_type},created_at:at});c.events=c.events.slice(0,100);
  c.updated_at=at;c.local_contract_version='RIGP-CASE-LOCAL-v2';
  if(!saveCase(c)){toast('No fue posible guardar la nota en el repositorio de expedientes.',true);return}
  toast('Nota incorporada a la bitácora.');document.querySelector('[data-rigp-case-journal]')?.remove();refresh();
}
function enhanceCase(){
  const workspace=$('workspace');if(!workspace||!workspace.querySelector('.case-head'))return;const c=activeCase();if(!c)return;
  if(!workspace.querySelector('[data-rigp-case-portable]'))workspace.querySelector('.case-head')?.insertAdjacentElement('afterend',portabilityBar(true));
  if(!workspace.querySelector('[data-rigp-case-journal]')){const route=workspace.querySelector('.route-card');if(route?.parentNode)route.parentNode.insertBefore(journalPanel(c),route)}
}
function enhanceReport(){
  const report=$('reportText');if(!report||report.querySelector('[data-rigp-journal-report]'))return;const c=activeCase();if(!c)return;const journal=reportJournal(c);if(!journal)return;
  const conclusion=[...report.querySelectorAll('section')].find(s=>s.querySelector('h4')?.textContent?.trim()==='Conclusión');if(conclusion)report.insertBefore(journal,conclusion);else report.appendChild(journal);
}
function enhanceInbox(){
  const workspace=$('workspace');if(!workspace||workspace.querySelector('[data-rigp-case-portable]'))return;const eyebrow=[...workspace.querySelectorAll('.eyebrow')].find(x=>x.textContent.trim().toLowerCase()==='mi bandeja');if(!eyebrow)return;eyebrow.closest('.section-head')?.insertAdjacentElement('afterend',portabilityBar(false));
}
let queued=false;
function refresh(){if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;enhanceCase();enhanceReport();enhanceInbox()})}
const workspace=$('workspace');if(workspace)new MutationObserver(refresh).observe(workspace,{childList:true,subtree:true});
caseRepo?.subscribe?.(()=>refresh());

document.addEventListener('click',e=>{
  if(e.target.closest('[data-case-export-active]')){exportActive();return}if(e.target.closest('[data-case-export-all]')){exportAll();return}if(e.target.closest('[data-case-import]')){const input=ensureImportInput();input.value='';input.click();return}if(e.target.closest('[data-case-note-save]')){saveStructuredNote();return}
});
document.addEventListener('change',e=>{if(e.target.id==='caseBackupImportInput'&&e.target.files?.[0])importFile(e.target.files[0])});
ensureImportInput();refresh();
})();
