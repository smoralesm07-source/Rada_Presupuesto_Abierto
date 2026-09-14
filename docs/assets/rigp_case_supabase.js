(()=>{'use strict';

const PROJECT_URL='https://ldmtlwzqaqmegedktlxr.supabase.co';
const PUBLISHABLE_KEY='sb_publishable_Nu21dZFBM3NwtIvOwIM8ag_9tyfDJyR';
const PILOT_RUN='RIGP-PILOT-001';
const REPOSITORY=window.RIGPCaseRepository;
const state={client:null,session:null,profile:null,attached:false,error:null,busy:false};
const remoteHash=new Map();
const remoteOwner=new Map();

const esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
function stable(value){
  if(Array.isArray(value))return '['+value.map(stable).join(',')+']';
  if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+stable(value[k])).join(',')+'}';
  return JSON.stringify(value);
}
function canManage(){return ['ADMIN','ANALYST'].includes(String(state.profile?.role||state.profile?.pilot_role||'').toUpperCase())}
function userLabel(){return state.profile?.display_name||state.session?.user?.email||'Usuario RIGP'}
function roleLabel(){const r=String(state.profile?.role||state.profile?.pilot_role||'').toUpperCase();return r==='ADMIN'?'Administrador':r==='ANALYST'?'Analista':r==='VIEWER'?'Viewer':r||'Piloto'}
function pilotUi(){
  let host=document.getElementById('rigpPilotSession');
  if(!host){
    host=document.createElement('section');host.id='rigpPilotSession';host.className='rigp-pilot-session';
    const top=document.querySelector('.top');top?.insertAdjacentElement('afterend',host);
  }
  return host;
}
function gateUi(){
  let gate=document.getElementById('rigpAuthGate');
  if(!gate){gate=document.createElement('div');gate.id='rigpAuthGate';gate.className='rigp-auth-gate';document.body.appendChild(gate)}
  return gate;
}
function message(text,error=false){
  const el=document.getElementById('rigpAuthMessage');if(!el)return;el.textContent=text||'';el.classList.toggle('error',!!error);
}
function render(){
  const host=pilotUi(),gate=gateUi();
  if(state.session){
    document.body.classList.add('rigp-authenticated');document.body.classList.toggle('rigp-readonly',!canManage());
    gate.hidden=true;
    const sync=state.attached?(state.error?'Sincronización con alerta':'Sincronizado'):'Conectando…';
    host.innerHTML=`<div class="rigp-session-identity"><span class="rigp-session-dot ${state.attached&&!state.error?'ok':''}"></span><div><b>${esc(userLabel())}</b><small>${esc(roleLabel())} · ${esc(sync)}</small></div></div><div class="rigp-session-actions"><span>${canManage()?'Edición habilitada':'Solo lectura'}</span><button type="button" data-rigp-signout>Cerrar sesión</button></div>`;
    return;
  }
  document.body.classList.remove('rigp-authenticated','rigp-readonly');
  host.innerHTML='<div class="rigp-session-identity"><span class="rigp-session-dot"></span><div><b>Piloto operativo</b><small>Sesión requerida para gestionar expedientes compartidos</small></div></div>';
  gate.hidden=false;
  gate.innerHTML=`<div class="rigp-auth-card"><div class="eyebrow">RIGP · piloto controlado</div><h2>Ingresar al espacio de trabajo</h2><p>Accede para tomar y trabajar expedientes con persistencia compartida y trazabilidad. Las señales orientan revisión; no acreditan irregularidad ni responsabilidad.</p><label>Correo<input id="rigpAuthEmail" type="email" autocomplete="email" placeholder="nombre@institucion.cl"></label><label>Contraseña<input id="rigpAuthPassword" type="password" autocomplete="current-password" placeholder="Contraseña"></label><div class="rigp-auth-actions"><button type="button" class="primary" data-rigp-password>Ingresar</button><button type="button" data-rigp-otp>Enviar código / enlace</button></div><div class="rigp-auth-code"><label>Código recibido<input id="rigpAuthToken" inputmode="numeric" autocomplete="one-time-code" placeholder="Código de acceso"></label><button type="button" data-rigp-verify>Validar código</button></div><div class="rigp-auth-divider"><span>o</span></div><button type="button" class="rigp-auth-microsoft" data-rigp-azure>Ingresar con Microsoft</button><small id="rigpAuthMessage" class="rigp-auth-message">La sesión queda recordada en este navegador hasta cerrar sesión.</small></div>`;
}
async function loadProfile(){
  const {data,error}=await state.client.rpc('rigp_ops_get_session');
  if(error)throw error;
  state.profile=data||{};
}
function remoteAdapter(){
  let signature='';
  return {
    get signature(){return signature},
    async load(){
      const {data,error}=await state.client.schema('rigp').from('case_workspace_state').select('case_id,case_ref,owner_user_id,payload,updated_at').order('updated_at',{ascending:false});
      if(error)throw error;
      remoteHash.clear();remoteOwner.clear();
      const rows=(data||[]).map(row=>{
        const payload=row.payload&&typeof row.payload==='object'?structuredClone(row.payload):{};
        payload.case_id=row.case_id;payload.case_ref=payload.case_ref||row.case_ref;
        const remoteTs=Date.parse(row.updated_at||0)||0,localTs=Date.parse(payload.updated_at||0)||0;
        if(remoteTs>localTs)payload.updated_at=row.updated_at;
        remoteHash.set(row.case_id,stable(payload));remoteOwner.set(row.case_id,row.owner_user_id||null);
        return payload;
      });
      signature=(data||[]).map(r=>`${r.case_id}:${r.updated_at}`).join('|');
      return rows;
    },
    async persist(cases,context={}){
      if(!state.session?.user)return;
      if(!canManage())return;
      const changed=(cases||[]).filter(c=>c?.case_id&&c?.case_ref&&remoteHash.get(c.case_id)!==stable(c));
      if(!changed.length)return;
      const at=new Date().toISOString(),uid=state.session.user.id;
      const rows=changed.map(c=>({
        case_id:String(c.case_id),case_ref:String(c.case_ref),candidate_id:c?.source_context?.candidate_id||null,
        owner_user_id:remoteOwner.get(c.case_id)||uid,workspace_status:String(c.status||'TRIAGE'),title:c.title||null,
        organization_id:c.organization_id||null,provider_id:c.provider_id||null,
        period_year:Number.isFinite(Number(c.period_year))?Number(c.period_year):null,attention_level:c.attention_level||null,
        priority_score:Number.isFinite(Number(c.priority_score))?Number(c.priority_score):null,payload:c,updated_by:uid,updated_at:at
      }));
      const {error}=await state.client.schema('rigp').from('case_workspace_state').upsert(rows,{onConflict:'case_id'});
      if(error)throw error;
      const reason=String(context.reason||'SYNC').replace(/[^A-Z0-9_-]/gi,'_').slice(0,80).toUpperCase();
      const events=changed.map(c=>({case_id:String(c.case_id),actor_user_id:uid,event_type:reason,detail:{case_ref:c.case_ref,status:c.status||null,repository_version:context.repository_version||null}}));
      const eventResult=await state.client.schema('rigp').from('case_workspace_event').insert(events);
      if(eventResult.error)throw eventResult.error;
      changed.forEach(c=>{remoteHash.set(c.case_id,stable(c));remoteOwner.set(c.case_id,remoteOwner.get(c.case_id)||uid)});
      signature='write:'+at+':'+changed.length;
    }
  };
}
async function attachWorkspace(){
  if(!REPOSITORY||state.attached||!state.session)return;
  const adapter=remoteAdapter();
  try{
    await loadProfile();
    await REPOSITORY.attachRemote(adapter,{merge:true});
    state.attached=true;state.error=null;render();
    window.dispatchEvent(new CustomEvent('rigp-pilot-ready',{detail:{profile:state.profile,repository:REPOSITORY.describe()}}));
    const hydrationKey='rigp_remote_hydrated_v1';
    if(!sessionStorage.getItem(hydrationKey)){
      sessionStorage.setItem(hydrationKey,'1');
      location.reload();
    }
  }catch(err){
    state.error=String(err?.message||err||'No fue posible conectar el workspace remoto.');
    state.attached=false;render();
    const status=document.getElementById('status');if(status)status.textContent=`Sesión activa · workspace remoto no disponible: ${state.error}`;
  }
}
async function setSession(session){
  state.session=session||null;state.profile=null;state.error=null;
  if(!state.session){state.attached=false;REPOSITORY?.detachRemote?.();sessionStorage.removeItem('rigp_remote_hydrated_v1');render();return}
  render();await attachWorkspace();
}
async function init(){
  if(!window.supabase?.createClient){state.error='No se cargó el cliente de sesión.';render();return}
  state.client=window.supabase.createClient(PROJECT_URL,PUBLISHABLE_KEY,{auth:{persistSession:true,autoRefreshToken:true,detectSessionInUrl:true}});
  const {data,error}=await state.client.auth.getSession();
  if(error)state.error=error.message;
  await setSession(data?.session||null);
  state.client.auth.onAuthStateChange((event,session)=>{
    if(event==='TOKEN_REFRESHED'){state.session=session;render();return}
    if(event==='SIGNED_IN'&&session&&!state.attached){setSession(session)}
    if(event==='SIGNED_OUT')setSession(null);
  });
}
async function signInPassword(){
  const email=document.getElementById('rigpAuthEmail')?.value?.trim(),password=document.getElementById('rigpAuthPassword')?.value||'';
  if(!email||!password){message('Ingresa correo y contraseña.',true);return}
  message('Validando acceso…');const {error}=await state.client.auth.signInWithPassword({email,password});if(error)message(error.message,true);
}
async function sendOtp(){
  const email=document.getElementById('rigpAuthEmail')?.value?.trim();if(!email){message('Ingresa tu correo.',true);return}
  message('Enviando acceso…');const {error}=await state.client.auth.signInWithOtp({email,options:{shouldCreateUser:false,emailRedirectTo:location.href}});
  message(error?error.message:'Revisa tu correo: recibirás un código o enlace de acceso.',!!error);
}
async function verifyOtp(){
  const email=document.getElementById('rigpAuthEmail')?.value?.trim(),token=document.getElementById('rigpAuthToken')?.value?.trim();
  if(!email||!token){message('Ingresa correo y código.',true);return}
  message('Validando código…');const {error}=await state.client.auth.verifyOtp({email,token,type:'email'});if(error)message(error.message,true);
}
async function azure(){
  message('Abriendo Microsoft…');const {error}=await state.client.auth.signInWithOAuth({provider:'azure',options:{scopes:'email',redirectTo:location.href}});if(error)message(error.message,true);
}
async function signOut(){if(state.client)await state.client.auth.signOut();sessionStorage.removeItem('rigp_remote_hydrated_v1')}

document.addEventListener('click',event=>{
  const t=event.target.closest('button');if(!t)return;
  if(t.matches('[data-rigp-password]')){signInPassword();return}
  if(t.matches('[data-rigp-otp]')){sendOtp();return}
  if(t.matches('[data-rigp-verify]')){verifyOtp();return}
  if(t.matches('[data-rigp-azure]')){azure();return}
  if(t.matches('[data-rigp-signout]')){signOut();return}
});
window.RIGPPilotAuth={describe:()=>({authenticated:!!state.session,attached:state.attached,role:roleLabel(),can_manage:canManage(),error:state.error}),signOut};
render();init();
})();
