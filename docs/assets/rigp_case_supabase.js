(()=>{'use strict';

const PROJECT_URL='https://ldmtlwzqaqmegedktlxr.supabase.co';
const PUBLISHABLE_KEY='sb_publishable_Nu21dZFBM3NwtIvOwIM8ag_9tyfDJyR';
const REPOSITORY=window.RIGPCaseRepository;
const state={client:null,session:null,profile:null,attached:false,error:null};
const remoteHash=new Map();

const esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const clone=v=>typeof structuredClone==='function'?structuredClone(v):JSON.parse(JSON.stringify(v));
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
  if(!host){host=document.createElement('section');host.id='rigpPilotSession';host.className='rigp-pilot-session';document.querySelector('.top')?.insertAdjacentElement('afterend',host)}
  return host;
}
function gateUi(){
  let gate=document.getElementById('rigpAuthGate');
  if(!gate){gate=document.createElement('div');gate.id='rigpAuthGate';gate.className='rigp-auth-gate';document.body.appendChild(gate)}
  return gate;
}
function message(text,error=false){const el=document.getElementById('rigpAuthMessage');if(!el)return;el.textContent=text||'';el.classList.toggle('error',!!error)}
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
  return {
    async load(){
      const {data,error}=await state.client.rpc('rigp_case_workspace_load');
      if(error)throw error;
      remoteHash.clear();
      const source=Array.isArray(data)?data:[];
      return source.map(row=>{
        const payload=row?.payload&&typeof row.payload==='object'?clone(row.payload):{};
        payload.case_id=row.case_id||payload.case_id;payload.case_ref=payload.case_ref||row.case_ref;
        const remoteTs=Date.parse(row.updated_at||0)||0,localTs=Date.parse(payload.updated_at||0)||0;
        if(remoteTs>localTs)payload.updated_at=row.updated_at;
        remoteHash.set(payload.case_id,stable(payload));
        return payload;
      }).filter(c=>c.case_id&&c.case_ref);
    },
    async persist(cases,context={}){
      if(!state.session?.user||!canManage())return;
      const changed=(cases||[]).filter(c=>c?.case_id&&c?.case_ref&&remoteHash.get(c.case_id)!==stable(c));
      if(!changed.length)return;
      const reason=String(context.reason||'SYNC').replace(/[^A-Z0-9_-]/gi,'_').slice(0,80).toUpperCase();
      const {error}=await state.client.rpc('rigp_case_workspace_sync',{
        p_cases:changed,
        p_reason:reason,
        p_repository_version:context.repository_version||null
      });
      if(error)throw error;
      changed.forEach(c=>remoteHash.set(c.case_id,stable(c)));
    }
  };
}
async function attachWorkspace(){
  if(!REPOSITORY||state.attached||!state.session)return;
  try{
    await loadProfile();
    await REPOSITORY.attachRemote(remoteAdapter(),{merge:true});
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
    if(event==='SIGNED_IN'&&session&&!state.attached){setTimeout(()=>setSession(session),0);return}
    if(event==='SIGNED_OUT')setTimeout(()=>setSession(null),0);
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
