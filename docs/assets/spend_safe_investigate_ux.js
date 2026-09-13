(()=>{'use strict';
const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
function txt(el){return (el?.textContent||'').replace(/\s+/g,' ').trim()}
function panelBy(re){return [...document.querySelectorAll('#workspace .explore-grid .panel')].find(p=>re.test(txt(p.querySelector('h3'))))||null}
function make(tag,cls,html){const el=document.createElement(tag);if(cls)el.className=cls;if(html!=null)el.innerHTML=html;return el}
function organize(){
 const ws=document.getElementById('workspace');
 const stage=document.body.dataset.rigpStage;
 document.body.classList.toggle('rigp-investigate-reading',stage==='investigate');
 if(!ws||stage!=='investigate')return;
 if(!ws.querySelector('.explore-grid')){ws.classList.add('investigate-landing');return}
 ws.classList.remove('investigate-landing');
 if(ws.querySelector('.rigp-investigate-story'))return;
 const grid=ws.querySelector('.explore-grid');
 const header=ws.querySelector('.section-head.explore-head');
 const kpis=ws.querySelector('.explore-kpis');
 const availability=ws.querySelector('.availability');
 const notes=[...ws.querySelectorAll('.context-note')];
 const guard=ws.querySelector('.explore-guard');
 const timeline=panelBy(/Línea de tiempo/i);
 const evolution=panelBy(/por año|Evolución/i);
 const concentration=panelBy(/Peso de la relación|Concentración/i);
 const counterparts=[...grid.querySelectorAll('.panel')].filter(p=>![timeline,evolution,concentration].includes(p));
 const kpi=[...(kpis?.querySelectorAll(':scope > div')||[])].map(d=>({value:txt(d.querySelector('b')),label:txt(d.querySelector('span'))}));
 const focus=txt(document.getElementById('contextbar'))||txt(header?.querySelector('p'))||'Foco seleccionado';
 const open=header?.querySelector('[data-open]');
 const story=make('section','rigp-investigate-story');
 const summary=make('div','iu-summary',`<div><div class="eyebrow">Lectura del foco</div><h2>${esc(txt(header?.querySelector('p'))||'Relación bajo revisión')}</h2><p>${esc(focus.replace(/Explorar foco|Quitar foco/g,'').trim())}</p></div><div class="iu-summary-actions">${open?`<button class="open" data-open="${esc(open.dataset.open)}">Abrir expediente</button>`:''}<button class="open secondary" data-gf-go="actors">Ir a actores</button></div>`);
 const progress=make('div','iu-progress',`<div class="done"><i>1</i><span>Foco elegido</span></div><div class="active"><i>2</i><span>Entender qué ocurrió</span></div><div><i>3</i><span>Identificar actores</span></div><div><i>4</i><span>Seguir beneficio</span></div>`);
 const fact=make('section','iu-block iu-fact',`<div class="iu-num">1</div><div class="iu-content"><div class="eyebrow">Hecho observado</div><h3>¿Qué sabemos del comportamiento económico del foco?</h3><div class="iu-facts">${kpi.slice(0,4).map(x=>`<div><b>${esc(x.value||'—')}</b><span>${esc(x.label||'')}</span></div>`).join('')}</div><p class="iu-hint">Estos datos describen magnitud, recurrencia y cobertura. No constituyen por sí solos una conclusión de irregularidad.</p></div>`);
 const why=make('section','iu-block iu-why',`<div class="iu-num">2</div><div class="iu-content"><div class="eyebrow">Por qué importa</div><h3>¿Qué hallazgos justifican revisar esta relación?</h3><div class="iu-slot iu-timeline"></div></div>`);
 const evidenceText=availability?txt(availability):'Contexto histórico disponible según cobertura publicada.';
 const evidence=make('section','iu-block iu-evidence',`<div class="iu-num">3</div><div class="iu-content"><div class="eyebrow">Evidencia disponible</div><h3>¿Qué está disponible y qué debe verificarse?</h3><div class="iu-evidence-grid"><div class="ready"><b>Contexto presupuestario</b><span>${esc(evidenceText)}</span></div><div class="pending"><b>Documentos de contratación y pago</b><span>Contrastar bases, orden de compra o contrato, recepción, factura y pago según corresponda.</span></div><div class="pending"><b>Identidad y rol de los actores</b><span>Determinar quién decidió, representó, controló o recibió valor antes de inferir un vínculo.</span></div></div><div class="iu-notes"></div></div>`);
 const context=make('section','iu-block iu-context',`<div class="iu-num">4</div><div class="iu-content"><div class="eyebrow">Contexto para interpretar</div><h3>Usa el histórico sólo para contrastar la hipótesis</h3><details class="iu-details"><summary>Ver detalle técnico: evolución y concentración</summary><div class="iu-tech"></div></details><details class="iu-details iu-support"><summary>Ver contrapartes y recurrencia</summary><div class="iu-secondary"></div></details></div>`);
 const next=make('section','iu-next',`<div><div class="eyebrow">Antes de avanzar</div><h3>Qué falta acreditar</h3><ol><li>Qué hecho contractual o presupuestario explica la señal.</li><li>Si la recurrencia persiste al comparar periodos y contrapartes equivalentes.</li><li>Qué persona o sociedad tuvo un rol documentado en la decisión, ejecución o recepción del valor.</li></ol></div><div class="iu-next-action"><span>Siguiente pregunta</span><b>¿Quién intervino y cuál fue su rol?</b><button class="open" data-gf-go="actors">Continuar a Actores →</button></div>`);
 story.append(summary,progress,fact,why,evidence,context,next);
 grid.insertAdjacentElement('beforebegin',story);
 if(timeline)why.querySelector('.iu-timeline').append(timeline); else why.querySelector('.iu-timeline').innerHTML='<div class="empty compact">No hay hallazgos publicados para el foco actual.</div>';
 if(evolution)context.querySelector('.iu-tech').append(evolution);
 if(concentration)context.querySelector('.iu-tech').append(concentration);
 counterparts.forEach(p=>context.querySelector('.iu-secondary').append(p));
 notes.forEach(n=>evidence.querySelector('.iu-notes').append(n));
 if(availability)availability.remove();
 if(kpis)kpis.remove();
 if(grid&&!grid.children.length)grid.remove();
 if(header)header.classList.add('iu-original-head');
 if(guard)story.append(guard);
}
function schedule(){requestAnimationFrame(()=>requestAnimationFrame(organize))}
document.addEventListener('click',e=>{if(e.target.closest('button,summary,[data-view],[data-open],[data-service],[data-provider],[data-explore-service],[data-explore-provider],[data-clear-context]'))schedule()},false);
for(const ev of ['rigp-review-updated','rigp-ownership-updated','rigp-value-evidence-updated','rigp-causality-updated'])document.addEventListener(ev,schedule);
window.addEventListener('load',schedule,{once:true});
schedule();
})();
