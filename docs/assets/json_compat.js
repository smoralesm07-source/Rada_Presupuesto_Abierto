(()=>{'use strict';
function sanitizeNonFiniteJson(text){
  let out='',i=0,inString=false,escape=false;
  const isBoundary=c=>c===undefined||/[\s,:\[\]{}]/.test(c);
  while(i<text.length){
    const c=text[i];
    if(inString){
      out+=c;
      if(escape)escape=false;
      else if(c==='\\')escape=true;
      else if(c==='"')inString=false;
      i++;continue;
    }
    if(c==='"'){inString=true;out+=c;i++;continue;}
    let token=null;
    if(text.startsWith('-Infinity',i))token='-Infinity';
    else if(text.startsWith('Infinity',i))token='Infinity';
    else if(text.startsWith('NaN',i))token='NaN';
    if(token){
      const prev=i===0?undefined:text[i-1],next=text[i+token.length];
      if(isBoundary(prev)&&isBoundary(next)){out+='null';i+=token.length;continue;}
    }
    out+=c;i++;
  }
  return out;
}

function normName(v){
  return String(v||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toUpperCase().replace(/[^A-Z0-9]+/g,' ').trim().replace(/\s+/g,' ');
}
const PUBLIC_PATTERNS=[
  'TESORERIA GENERAL DE LA REPUBLICA','SERVICIO DE IMPUESTOS INTERNOS','SERVICIO DE REGISTRO CIVIL',
  'SERVICIO MEDICO LEGAL','SERVICIO NACIONAL DE','SERVICIO DE SALUD','SUBSECRETARIA DE','MINISTERIO DE',
  'MUNICIPALIDAD DE','ILUSTRE MUNICIPALIDAD','GOBIERNO REGIONAL','CONTRALORIA GENERAL DE LA REPUBLICA',
  'FONDO NACIONAL DE SALUD','INSTITUTO DE PREVISION SOCIAL','DEFENSORIA PENAL PUBLICA','JUNTA NACIONAL DE',
  'DIRECCION GENERAL DE','DIRECCION NACIONAL DE','POLICIA DE INVESTIGACIONES DE CHILE','CARABINEROS DE CHILE',
  'EJERCITO DE CHILE','ARMADA DE CHILE','FUERZA AEREA DE CHILE'
];
function cleanSpendPayload(d){
  if(!d||d.schema!=='PRESUPUESTO_SPEND_VIEW_V2')return d;
  const serviceNames=new Set((d.services||[]).map(s=>normName(s.organization_name)).filter(Boolean));
  const isPublic=f=>{const n=normName(f.provider_name);return !!n&&(serviceNames.has(n)||PUBLIC_PATTERNS.some(p=>n.includes(p)))};
  const before=(d.flows||[]).length;
  d.flows=(d.flows||[]).filter(f=>!isPublic(f));
  const ids=new Set(d.flows.map(f=>String(f.provider_id||'')));
  d.providers=(d.providers||[]).filter(p=>ids.has(String(p.provider_id||'')));
  d.source=d.source||{};
  d.source.provider_scope='PRIVATE_OR_NON_PUBLIC_COUNTERPARTIES';
  d.source.public_provider_flows_excluded_browser=before-d.flows.length;
  d.published=d.published||{};
  d.published.providers=d.providers.length;
  d.published.flows=d.flows.length;
  globalThis.__PA_SPEND_DATA__=d;
  return d;
}

const nativeJson=Response.prototype.json;
Response.prototype.json=async function(){
  const clone=this.clone();
  try{return cleanSpendPayload(await nativeJson.call(this))}catch(firstError){
    const text=await clone.text();
    const clean=sanitizeNonFiniteJson(text);
    try{
      const parsed=cleanSpendPayload(JSON.parse(clean));
      console.warn('[Radar Presupuesto] Se normalizaron constantes JSON no finitas heredadas.',firstError);
      return parsed;
    }catch(secondError){throw firstError;}
  }
};

// Protección de rendimiento del piloto web.
// La cola analítica completa puede contener decenas de miles de señales y no debe
// ser agregada en el navegador. GitHub Pages publica investigative_findings.json
// ya compactado. Si ese archivo faltara, los módulos reciben una cola vacía y
// degradan de forma controlada en vez de bloquear la pestaña.
const nativeFetch=globalThis.fetch.bind(globalThis);
let compactFindings=null;
function requestUrl(input){return String(typeof input==='string'?input:(input&&input.url)||'')}
globalThis.fetch=async function(input,init){
  const url=requestUrl(input);
  if(url.includes('data/investigation_queue.json')){
    console.warn('[RIGP] Se evitó cargar la cola analítica completa en el navegador.');
    return new Response(JSON.stringify({generated_at:null,total_signals:0,priority_tiers:{},queue:[]}),{status:200,headers:{'Content-Type':'application/json'}});
  }
  if(url.includes('data/investigative_findings.json')){
    if(!compactFindings){
      compactFindings=nativeFetch(input,init).then(async r=>{
        if(!r.ok)throw new Error('investigative_findings HTTP '+r.status);
        return {text:await r.text(),status:r.status,statusText:r.statusText,headers:[...r.headers.entries()]};
      }).catch(err=>{compactFindings=null;throw err});
    }
    const c=await compactFindings;
    return new Response(c.text,{status:c.status,statusText:c.statusText,headers:c.headers});
  }
  return nativeFetch(input,init);
};

globalThis.__PA_SANITIZE_JSON__=sanitizeNonFiniteJson;
globalThis.__PA_CLEAN_SPEND__=cleanSpendPayload;
globalThis.__PA_NORM_NAME__=normName;
globalThis.__RIGP_LIGHTWEIGHT_FINDINGS__=true;
})();
