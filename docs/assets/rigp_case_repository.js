(()=>{'use strict';

const CASE_KEY='rigp_cases_v1';
const VERSION='RIGP-CASE-REPOSITORY-v1';
const CHANGE_EVENT='rigp-case-repository-changed';
const subscribers=new Set();
let storage=null;
let storageAvailable=false;
let memoryRaw='[]';
let remoteAdapter=null;
let remoteState='detached';
let remoteError=null;
let writeChain=Promise.resolve();

try{
  storage=window.localStorage;
  const probe='__rigp_case_repository_probe__';
  storage.setItem(probe,'1');
  storage.removeItem(probe);
  storageAvailable=true;
}catch{
  storage=null;
}

const StorageCtor=window.Storage;
const nativeGet=StorageCtor?.prototype?.getItem;
const nativeSet=StorageCtor?.prototype?.setItem;
const nativeRemove=StorageCtor?.prototype?.removeItem;

function clone(value){
  if(typeof structuredClone==='function')return structuredClone(value);
  return JSON.parse(JSON.stringify(value));
}
function safeNativeGet(){
  if(!storageAvailable||!storage||!nativeGet)return memoryRaw;
  try{return nativeGet.call(storage,CASE_KEY)||'[]'}catch{return memoryRaw}
}
function safeNativeSet(raw){
  memoryRaw=raw;
  if(!storageAvailable||!storage||!nativeSet)return false;
  try{nativeSet.call(storage,CASE_KEY,raw);return true}catch{return false}
}
function safeNativeRemove(){
  memoryRaw='[]';
  if(!storageAvailable||!storage||!nativeRemove)return false;
  try{nativeRemove.call(storage,CASE_KEY);return true}catch{return false}
}
function normalizeCase(row){
  if(!row||typeof row!=='object')return null;
  const c=clone(row);
  c.finding_ids=Array.isArray(c.finding_ids)?c.finding_ids:[];
  c.evidence=Array.isArray(c.evidence)?c.evidence:[];
  c.events=Array.isArray(c.events)?c.events:[];
  c.case_notes=Array.isArray(c.case_notes)?c.case_notes:[];
  return c;
}
function normalizeRows(rows){
  if(!Array.isArray(rows))return [];
  return rows.map(normalizeCase).filter(Boolean);
}
function parseRows(raw){
  try{return normalizeRows(JSON.parse(raw||'[]'))}catch{return []}
}
function timestamp(row){
  const t=Date.parse(row?.updated_at||row?.created_at||0);
  return Number.isFinite(t)?t:0;
}
function identity(row){return String(row?.case_id||row?.case_ref||'')}

let cache=parseRows(safeNativeGet());

function emit(reason='updated'){
  const detail={reason,count:cache.length,repository:describe()};
  subscribers.forEach(fn=>{try{fn(snapshot(),detail)}catch{}});
  try{window.dispatchEvent(new CustomEvent(CHANGE_EVENT,{detail}))}catch{}
}
function snapshot(){return clone(cache)}
function list(){return snapshot()}
function get(id){return clone(cache.find(c=>c.case_id===id||c.case_ref===id)||null)}
function findByFinding(findingId){
  const fid=String(findingId||'');
  return clone(cache.find(c=>(c.finding_ids||[]).map(String).includes(fid))||null);
}
function persistLocal(){return safeNativeSet(JSON.stringify(cache))}
function mergeRows(localRows,remoteRows){
  const merged=new Map();
  for(const row of [...normalizeRows(localRows),...normalizeRows(remoteRows)]){
    const key=identity(row);
    if(!key)continue;
    const current=merged.get(key);
    if(!current||timestamp(row)>timestamp(current))merged.set(key,row);
  }
  return [...merged.values()].sort((a,b)=>timestamp(b)-timestamp(a));
}
function queueRemote(reason){
  if(!remoteAdapter||typeof remoteAdapter.persist!=='function')return;
  const payload=snapshot();
  remoteState='syncing';remoteError=null;
  writeChain=writeChain.catch(()=>{}).then(()=>remoteAdapter.persist(payload,{reason,repository_version:VERSION})).then(()=>{
    remoteState='ready';remoteError=null;emit('remote-synced');
  }).catch(err=>{
    remoteState='error';remoteError=String(err?.message||err||'Error remoto');emit('remote-error');
  });
}
function replaceAll(rows,{reason='replace-all',skipRemote=false}={}){
  cache=normalizeRows(rows);
  const localPersisted=persistLocal();
  emit(reason);
  if(!skipRemote)queueRemote(reason);
  return {ok:true,count:cache.length,local_persisted:localPersisted||!storageAvailable};
}
function upsert(row,{reason='upsert',skipRemote=false}={}){
  const next=normalizeCase(row);if(!next)return null;
  const key=identity(next);if(!key)return null;
  const rows=snapshot();
  const idx=rows.findIndex(c=>identity(c)===key||((c.case_ref&&next.case_ref)&&c.case_ref===next.case_ref));
  if(idx>=0)rows[idx]=next;else rows.unshift(next);
  replaceAll(rows,{reason,skipRemote});
  return clone(next);
}
function patch(id,changes,eventType='ACTUALIZACION'){
  const current=get(id);if(!current)return null;
  const updatedAt=new Date().toISOString();
  Object.assign(current,clone(changes||{}),{updated_at:updatedAt});
  current.events=Array.isArray(current.events)?current.events:[];
  current.events.unshift({event_type:eventType,created_at:updatedAt});
  current.events=current.events.slice(0,100);
  return upsert(current,{reason:eventType});
}
function remove(id,{reason='remove'}={}){
  const before=cache.length;
  const rows=cache.filter(c=>c.case_id!==id&&c.case_ref!==id);
  if(rows.length===before)return false;
  replaceAll(rows,{reason});return true;
}
function clear({reason='clear'}={}){
  cache=[];safeNativeRemove();emit(reason);queueRemote(reason);return true;
}
function subscribe(fn){
  if(typeof fn!=='function')return()=>{};
  subscribers.add(fn);return()=>subscribers.delete(fn);
}
function describe(){
  return {
    version:VERSION,
    mode:remoteAdapter?'remote-ready-cache':'local-cache',
    local_backend:storageAvailable?'localStorage':'memory',
    remote_state:remoteState,
    remote_attached:!!remoteAdapter,
    remote_error:remoteError,
    case_count:cache.length
  };
}
async function attachRemote(adapter,{merge=true}={}){
  if(!adapter||typeof adapter.load!=='function'||typeof adapter.persist!=='function')throw new Error('El adaptador remoto debe implementar load() y persist().');
  remoteAdapter=adapter;remoteState='hydrating';remoteError=null;emit('remote-attaching');
  try{
    const remoteRows=normalizeRows(await adapter.load({repository_version:VERSION}));
    cache=merge?mergeRows(cache,remoteRows):remoteRows;
    persistLocal();
    remoteState='ready';emit('remote-hydrated');
    return describe();
  }catch(err){
    remoteState='error';remoteError=String(err?.message||err||'Error remoto');emit('remote-error');throw err;
  }
}
function detachRemote(){remoteAdapter=null;remoteState='detached';remoteError=null;emit('remote-detached');return describe()}
async function flush(){await writeChain;return describe()}

const repository={
  version:VERSION,key:CASE_KEY,changeEvent:CHANGE_EVENT,
  list,get,findByFinding,replaceAll,upsert,patch,remove,clear,subscribe,describe,
  attachRemote,detachRemote,flush,
  contract:{
    adapter:'RIGP-CASE-ADAPTER-v1',
    required:['load','persist'],
    semantics:'cache-local-con-hidratacion-y-escritura-remota-serializada'
  }
};
window.RIGPCaseRepository=repository;

// Puente de compatibilidad: la UI case-first existente todavía invoca localStorage.
// Sólo se intercepta la clave de expedientes. El resto del Storage nativo queda intacto.
if(storageAvailable&&storage&&StorageCtor&&nativeGet&&nativeSet&&nativeRemove){
  StorageCtor.prototype.getItem=function(key){
    if(this===storage&&key===CASE_KEY)return JSON.stringify(cache);
    return nativeGet.call(this,key);
  };
  StorageCtor.prototype.setItem=function(key,value){
    if(this===storage&&key===CASE_KEY){
      replaceAll(parseRows(String(value)),{reason:'legacy-storage-write'});return;
    }
    return nativeSet.call(this,key,value);
  };
  StorageCtor.prototype.removeItem=function(key){
    if(this===storage&&key===CASE_KEY){clear({reason:'legacy-storage-remove'});return;}
    return nativeRemove.call(this,key);
  };
  window.addEventListener('storage',event=>{
    if(event.storageArea===storage&&event.key===CASE_KEY){
      cache=parseRows(event.newValue||'[]');memoryRaw=event.newValue||'[]';emit('external-storage');
    }
  });
}

emit('repository-ready');
})();
