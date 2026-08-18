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
const nativeJson=Response.prototype.json;
Response.prototype.json=async function(){
  const clone=this.clone();
  try{return await nativeJson.call(this)}catch(firstError){
    const text=await clone.text();
    const clean=sanitizeNonFiniteJson(text);
    try{
      const parsed=JSON.parse(clean);
      console.warn('[Radar Presupuesto] Se normalizaron constantes JSON no finitas heredadas.',firstError);
      return parsed;
    }catch(secondError){throw firstError;}
  }
};
window.__PA_SANITIZE_JSON__=sanitizeNonFiniteJson;
})();
