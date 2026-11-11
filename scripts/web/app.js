'use strict';
const $ = id => document.getElementById(id);
let tree = null, selected = null, generation = 0, graphZoom = 1;
let focusRoot = null;
const collapsed = new Set();
const stateNames={open:'进行中',closed:'已结束',planned:'待启动',paused:'已暂停',abandoned:'已放弃',active:'活跃',returned:'已返回',finished:'已完成'};
function dateText(text){const date=new Date(text);return text&&!Number.isNaN(date.valueOf())?date.toLocaleString('zh-CN',{hour12:false}):text||'未知';}
function saveLocation(){
 const hash=activeProject&&activeTree?new URLSearchParams({project:activeProject,tree:activeTree,...(selected?{node:selected}:{}),...(focusRoot?{focus:focusRoot}:{})}).toString():'';
 if(location.hash.slice(1)!==hash)location.hash=hash;
}
async function copyText(text,button){
 try{await navigator.clipboard.writeText(text);button.textContent='已复制';}
 catch{button.textContent='复制失败，请手动选取文本';}
}

const labels = {scope:'范围',constraints:'约束',sources:'来源',parent_link:'与父问题的关系',return_when:'返回条件',case:'实验场景',coverage:'覆盖范围',decision_effect:'决策影响',notes:'备注',activation_trigger:'启动条件',deferred_because:'推迟原因',followup_reason:'后续原因',summary:'结论',evidence:'证据',conditions:'适用条件',limitations:'限制',unknowns:'未知项',uncovered:'未覆盖范围',execution:'执行环境',answers:'对父问题的回答',local_only:'仅局部成立',next:'下一步',at:'时间',source_results:'来源结果',reason:'原因'};
function el(tag, text, cls) {const e=document.createElement(tag); if(text!==undefined)e.textContent=text; if(cls)e.className=cls; return e;}
function badge(status){const b=el('span',stateNames[status]||status||'未知','badge '+String(status).replace(/[^a-z]/g,''));b.title=status||'unknown';return b;}
function value(v){return typeof v==='object'?JSON.stringify(v,null,2):String(v);}
function fields(obj, keys){
 const dl=el('dl');
 for(const key of keys){
  const v=obj[key];if(v===undefined||v===null||v===''||(Array.isArray(v)&&!v.length))continue;
  const dd=el('dd');
  if(['sources','evidence'].includes(key)){
   for(const ref of Array.isArray(v)?v:[v]){
    const text=value(ref),row=el('div',undefined,'reference');
    if(/^https?:\/\//i.test(text)){const link=el('a',text);link.href=text;link.target='_blank';link.rel='noopener noreferrer';row.append(link);}
    else row.append(el('span',text));
    const copy=el('button','复制引用');copy.onclick=()=>copyText(text,copy);row.append(copy);dd.append(row);
   }
  }else dd.textContent=key==='at'?dateText(v):Array.isArray(v)?v.map(value).join('\n'):value(v);
  dl.append(el('dt',labels[key]||key),dd);
 }
 return dl;
}
async function api(path, params={}){const r=await fetch('/api/'+path+'?'+new URLSearchParams(params)); const data=await r.json();if(!r.ok)throw Error(data.error||'读取失败');return data;}
let catalog = [], activeProject = null, activeTree = null, refreshGeneration = 0;
const expanded = new Set();
function availableTrees(project) {
 const term=$('filter').value.trim().toLowerCase();
 const projectMatches=[project.id,project.repository].join(' ').toLowerCase().includes(term);
 return (project.trees||[]).filter(t => (!$('hide-ended').checked || !['closed','abandoned'].includes(t.status)) &&
  (!term || projectMatches || [t.question,t.id].join(' ').toLowerCase().includes(term)));
}
function renderSidebar(){
 const nav=$('projects');nav.replaceChildren();let total=0;
 for(const project of catalog){
  const items=availableTrees(project);total+=items.length;
  if(!items.length&&!project.error&&($('filter').value.trim()||$('hide-ended').checked))continue;
  const group=el('details',undefined,'project');group.open=expanded.has(project.id)||!!$('filter').value;
  group.ontoggle=()=>{if(!group.isConnected)return;if(group.open)expanded.add(project.id);else expanded.delete(project.id);};
  const title=el('summary');title.title=project.repository;title.append(el('span',project.id.replace(/-[a-f0-9]{8}$/,'')),el('span',items.length,'meta'));group.append(title);
  if(project.error)group.append(el('p',project.error,'error'));
  else if(!items.length)group.append(el('p','没有符合筛选的探索树','hint'));
  for(const item of items){const button=el('button',undefined,'tree-link'+(activeProject===project.id&&activeTree===item.id?' selected':''));button.title=item.question||item.error;button.setAttribute('aria-pressed',String(activeProject===project.id&&activeTree===item.id));button.append(el('span',item.question||item.id,'tree-name'),badge(item.status));if(item.error)button.append(el('span',item.error,'error'));button.onclick=()=>loadTree(project.id,item.id);group.append(button);}
  nav.append(group);
 }
 if(!catalog.length)nav.append(el('p','尚无已登记项目。','empty'));
 else if(!total)nav.prepend(el('p','没有符合筛选的探索树。','empty'));
}
function clearTree(){tree=null;selected=null;activeProject=null;activeTree=null;focusRoot=null;collapsed.clear();render();}
function selectNode(id,reveal=false){
 if(!tree?.nodes[id])return;
 selected=id;setPanel(null);
 if(reveal){
  graphZoom=1;
  $('search').value='';focusRoot=null;
  let n=tree.nodes[id];const seen=new Set();
  while(n&&!seen.has(n.id)){seen.add(n.id);collapsed.delete(n.id);n=tree.nodes[n.parent];}
 }
 render();saveLocation();$('detail').scrollTop=0;
 if(reveal)centerNode(id);
}
function centerNode(id){
 requestAnimationFrame(()=>{
  const button=Array.from(document.querySelectorAll('.node')).find(b=>b.dataset.node===id);
  if(!button)return;const view=$('outline'),r=button.getBoundingClientRect(),v=view.getBoundingClientRect();
  view.scrollLeft+=r.left-v.left-(v.width-r.width)/2;
  view.scrollTop+=r.top-v.top-(v.height-r.height)/2;
 });
}
function showAll(){focusRoot=null;collapsed.clear();render();saveLocation();centerNode(selected||tree?.root);}
function render(){
 document.querySelector('.content').classList.toggle('no-selection',!selected);
 $('show-all').textContent=focusRoot?'返回完整树':'展开全树';
 $('outline').replaceChildren();$('count').textContent='';$('updated').textContent='';$('tree-title').textContent=tree?tree.nodes[tree.root].question:'问题树';
 if(!tree){$('outline').append(el('p','从左侧选择一棵探索树。Branchback 用问题树记录研究目标、分支、证据和结论。','empty'));renderDetail();return;}
 const nodes=Object.values(tree.nodes),term=$('search').value.trim().toLowerCase(),visible=new Set();
 for(const n of nodes){if(!term||[n.question,n.id,n.status].join(' ').toLowerCase().includes(term)){let cursor=n;const seen=new Set();while(cursor&&!seen.has(cursor.id)){seen.add(cursor.id);visible.add(cursor.id);cursor=tree.nodes[cursor.parent];}}}
 const children=new Map();for(const n of nodes){if(!children.has(n.parent))children.set(n.parent,[]);children.get(n.parent).push(n);}
 const visited=new Set();
 function branch(n){
  if(!visible.has(n.id)||visited.has(n.id))return null;visited.add(n.id);
  const li=el('li'),button=el('button',undefined,'node'+(n.id===selected?' selected':''));button.dataset.node=n.id;button.setAttribute('aria-pressed',String(n.id===selected));button.title=n.question;
  button.append(badge(n.status),el('span',n.question,'question'));
  const sessions=Object.values(tree.sessions).filter(s=>s.node===n.id);
  button.append(el('span',`${(n.results||[]).length} 个结果 · ${sessions.length} 个会话`,'meta'));
  button.onclick=()=>selectNode(n.id);li.append(button);
  const descendants=children.get(n.id)||[];
  if(descendants.length){const toggle=el('button',collapsed.has(n.id)&&!term?'展开 '+descendants.length+' 个分支':'收起分支','branch-toggle');toggle.setAttribute('aria-expanded',String(!collapsed.has(n.id)||!!term));toggle.onclick=()=>{if(collapsed.has(n.id))collapsed.delete(n.id);else collapsed.add(n.id);render();centerNode(n.id);};toggle.disabled=!!term;li.append(toggle);}
  if(collapsed.has(n.id)&&!term)return li;
  const ul=el('ul');for(const child of children.get(n.id)||[]){const item=branch(child);if(item)ul.append(item);}if(ul.childNodes.length)li.append(ul);return li;
 }
 const graph=el('div',undefined,'graph'),list=el('ul'),root=branch(tree.nodes[term?tree.root:(focusRoot||tree.root)]);if(root)list.append(root);graph.append(list);$('outline').append(graph);
 if(!visited.size)$('outline').append(el('p','没有匹配的节点。','empty'));
 setZoom(graphZoom,false);renderDetail();
 $('count').textContent=term?`${visited.size} / ${nodes.length} 节点（含祖先）`:`${visited.size} / ${nodes.length} 个节点`; $('view-mode').textContent=focusRoot?'当前显示聚焦分支':collapsed.size?'部分分支已收起':'完整问题树';$('updated').textContent='更新于 '+dateText(tree.updated_at);
}
function setZoom(scale,center=true){
 const graph=document.querySelector('.graph');if(!graph)return;
 graphZoom=Math.max(0.005,Math.min(2,scale));graph.style.zoom=String(graphZoom);
 $('zoom-reset').textContent=(graphZoom<0.1?(graphZoom*100).toFixed(1):Math.round(graphZoom*100))+'%';
 const viewport=$('outline');if(center)viewport.scrollLeft=Math.max(0,(viewport.scrollWidth-viewport.clientWidth)/2);
}
function fitGraph(){
 const graph=document.querySelector('.graph');if(!graph)return;
 graph.style.zoom='1';
 const viewport=$('outline');
 setZoom(Math.min(1,(viewport.clientWidth-16)/graph.offsetWidth,(viewport.clientHeight-16)/graph.offsetHeight));
 viewport.scrollTop=0;
}
function renderDetail(){
 const panel=$('detail');panel.replaceChildren();
 if(!tree||!selected||!tree.nodes[selected]){panel.append(el('p','点击图中的节点查看详情。进行中表示问题仍在推进；已结束表示探索已关闭，不等于所有未知项均已解决。','empty'));return;}
 const n=tree.nodes[selected];
 if(!Array.from(document.querySelectorAll('.node')).some(b=>b.dataset.node===selected)){
  const notice=el('div',undefined,'selection-notice');notice.append(el('span','当前详情节点不在图中：可能被搜索、折叠或聚焦隐藏。'));
  const reveal=el('button','在图中显示');reveal.onclick=()=>selectNode(selected,true);notice.append(reveal);panel.append(notice);
 }
 panel.append(badge(n.status),el('h2',n.question));
 const actions=el('div',undefined,'detail-actions');
 const locate=el('button','定位此节点');locate.onclick=()=>selectNode(n.id,true);
 const focus=el('button','聚焦此分支');focus.onclick=()=>{setPanel(null);graphZoom=1;focusRoot=n.id;collapsed.delete(n.id);$('search').value='';render();saveLocation();centerNode(n.id);};
 const share=el('button','复制节点链接');share.onclick=()=>copyText(location.href,share);
 actions.append(locate,focus,share);
 if(n.parent&&tree.nodes[n.parent]){const back=el('button','↑ 返回父节点');back.title=tree.nodes[n.parent].question;back.onclick=()=>selectNode(n.parent,true);actions.append(back);}
 panel.append(actions);
 const latest=(n.results||[]).at(-1);
 panel.append(el('h3','最新结论'));
 if(latest)panel.append(fields(latest,['summary','at','evidence','conditions','limitations','unknowns','uncovered']));
 else panel.append(el('p','尚未记录结果。可继续查看问题范围和会话位置。','hint'));
 const sessions=Object.values(tree.sessions).filter(s=>s.node===n.id);
 panel.append(el('h3','会话位置 · '+sessions.length));
 if(!sessions.length)panel.append(el('p','没有会话停留在此节点。','hint'));
 for(const session of sessions){
  const box=el('div',undefined,'card');box.append(badge(session.status),el('p',session.label||session.id));
  if(tree.nodes[session.boundary]){const link=el('button','工作范围：'+tree.nodes[session.boundary].question);link.onclick=()=>selectNode(session.boundary,true);box.append(link);}
  const copy=el('button','复制会话 ID');copy.onclick=()=>copyText(session.id,copy);box.append(copy);
  box.append(fields(session,['handoff']));panel.append(box);
 }
 panel.append(el('h3','问题范围'),fields(n,['scope','constraints','sources','parent_link','return_when','case','coverage','decision_effect','notes','activation_trigger','deferred_because','followup_reason']));
 for(const [key,title] of [['results','全部结果与证据'],['assessments','父层评估'],['updates','生命周期记录']]){
  const entries=n[key]||[],section=el('details');section.append(el('summary',title+' · '+entries.length));
  if(key==='assessments')section.append(el('p','父层评估记录这些局部结果如何影响上层问题，以及哪些结论不能推广。','hint'));
  for(const entry of [...entries].reverse()){const box=el('div',undefined,'card');box.append(fields(entry,Object.keys(entry)));section.append(box);}panel.append(section);
 }
 const events=[...(tree.events||[])].reverse(),history=el('details');history.append(el('summary','探索树历史 · '+events.length));
 const eventNames={start:'开始探索',enter:'进入分支',plan:'计划分支',return:'返回结果',return_:'返回结果',finish:'结束探索',attach:'加入会话',revise:'更新问题',abandon:'放弃分支',restore:'恢复分支',handoff:'交接会话'};
 let shown=0;const more=el('button','再显示 20 条');
 function showEvents(){
  more.remove();
  for(const event of events.slice(shown,shown+20)){
   const card=el('div',undefined,'event');const session=tree.sessions[event.session];
   card.append(el('div',dateText(event.at)+' · '+(eventNames[event.action]||event.action),'event-title'));
   if(session)card.append(el('p','会话：'+(session.label||session.id),'hint'));
   const nodeId=event.node||event.detail?.entered_node||event.detail?.planned_node||event.detail?.node;
   if(tree.nodes[nodeId]){const link=el('button',tree.nodes[nodeId].question);link.onclick=()=>selectNode(nodeId,true);card.append(link);}
   if(event.detail?.reason)card.append(el('p',event.detail.reason));
   const raw=el('details');raw.append(el('summary','原始事件'),el('pre',JSON.stringify(event,null,2)));card.append(raw);history.append(card);
  }
  shown+=20;if(shown<events.length)history.append(more);
 }
 more.onclick=showEvents;showEvents();panel.append(history);
 const raw=el('details');raw.append(el('summary','节点原始数据'),el('pre',JSON.stringify(n,null,2)));panel.append(raw);
}
async function loadTree(project,id,keepSelection=false,requestedNode=null,requestedFocus=null){
 const ticket=++generation;const previous=requestedNode||(keepSelection?selected:null);
 const same=activeProject===project&&activeTree===id;
 if(!same){collapsed.clear();focusRoot=null;graphZoom=1;$('search').value='';}expanded.add(project);
 activeProject=project;activeTree=id;tree=null;selected=null;renderSidebar();render();$('message').textContent='正在读取…';
 try{const data=await api('tree',{project,tree:id});if(ticket!==generation)return;tree=data;selected=previous&&data.nodes[previous]?previous:null;
  if(requestedFocus&&data.nodes[requestedFocus])focusRoot=requestedFocus;
  if(!same&&Object.keys(data.nodes).length>20)for(const n of Object.values(data.nodes))if(n.parent===data.root)collapsed.add(n.id);
  if(selected){let n=data.nodes[selected];const seen=new Set();while(n&&!seen.has(n.id)){seen.add(n.id);collapsed.delete(n.id);n=data.nodes[n.parent];}}
  render();saveLocation();$('message').textContent=previous&&!selected?'链接中的节点不存在，已显示探索树。':'';centerNode(selected||data.root);
 }catch(e){if(ticket===generation){tree=null;render();$('message').textContent=e.message;}}
}
function applyFilters(){
 const project=catalog.find(p=>p.id===activeProject);
 if(project&&!availableTrees(project).some(t=>t.id===activeTree)){++generation;clearTree();saveLocation();$('message').textContent='当前探索树已被左侧筛选隐藏。';}
 renderSidebar();
}
async function refresh(){
 const ticket=++refreshGeneration;++generation;$('message').textContent='正在读取…';
 try{
  const projects=await api('projects');
  const loaded=await Promise.all(projects.map(async p=>{try{return {...p,trees:await api('trees',{project:p.id})};}catch(e){return {...p,trees:[],error:e.message};}}));
  if(ticket!==refreshGeneration)return;catalog=loaded;
  if(!expanded.size&&catalog.length)expanded.add(catalog[0].id);
  const project=catalog.find(p=>p.id===activeProject);
  if(project&&availableTrees(project).some(t=>t.id===activeTree)){renderSidebar();await loadTree(activeProject,activeTree,true);}
  else{clearTree();renderSidebar();$('message').textContent='';await restoreLocation();}
 }catch(e){if(ticket===refreshGeneration)$('message').textContent=e.message;}
}
async function restoreLocation(){
 const params=new URLSearchParams(location.hash.slice(1)),project=params.get('project'),id=params.get('tree'),node=params.get('node'),focus=params.get('focus');
 if(!project||!id){if(activeTree){++generation;clearTree();renderSidebar();}return;}
 if(project===activeProject&&id===activeTree&&tree){
  if(node!==selected||focus!==focusRoot){
   selected=node&&tree.nodes[node]?node:null;focusRoot=focus&&tree.nodes[focus]?focus:null;
   let n=tree.nodes[selected];const seen=new Set();while(n&&!seen.has(n.id)){seen.add(n.id);collapsed.delete(n.id);n=tree.nodes[n.parent];}
   $('search').value='';graphZoom=1;setPanel(null);render();centerNode(selected||focusRoot||tree.root);
  }
  return;
 }
 if(!catalog.some(p=>p.id===project)){clearTree();renderSidebar();$('message').textContent='链接中的项目不存在。';return;}
 $('filter').value='';$('hide-ended').checked=false;
 await loadTree(project,id,false,node,focus);
}
window.addEventListener('hashchange',()=>{if(catalog.length)restoreLocation();});
function setPanel(kind){
 const content=document.querySelector('.content');content.classList.remove('map-expanded','detail-expanded');
 if(kind)content.classList.add(kind+'-expanded');
 $('expand-map').textContent=kind==='map'?'恢复分区':'扩大图区';
 $('expand-detail').textContent=kind==='detail'?'恢复分区':'扩大详情';
}
function togglePanel(kind){setPanel(document.querySelector('.content').classList.contains(kind+'-expanded')?null:kind);}
$('expand-map').onclick=()=>togglePanel('map');$('expand-detail').onclick=()=>togglePanel('detail');
$('show-all').onclick=showAll;
// Drag blank canvas space to scroll; leave node clicks and native touch scrolling intact.
const canvas=$('outline');
let pan=null;
function stopPan(){
 if(!pan)return;
 const pointerId=pan.id;pan=null;canvas.classList.remove('panning');
 if(canvas.hasPointerCapture(pointerId))canvas.releasePointerCapture(pointerId);
}
canvas.addEventListener('pointerdown',event=>{
 if(event.pointerType==='touch'||!event.isPrimary||event.button!==0||event.target.closest('button'))return;
 // Do not intercept the native scrollbars.
 const bounds=canvas.getBoundingClientRect();
 if(event.clientX>=bounds.left+canvas.clientWidth||event.clientY>=bounds.top+canvas.clientHeight)return;
 pan={id:event.pointerId,x:event.clientX,y:event.clientY,left:canvas.scrollLeft,top:canvas.scrollTop};
 canvas.setPointerCapture(event.pointerId);canvas.classList.add('panning');
 canvas.focus({preventScroll:true});event.preventDefault();
});
canvas.addEventListener('pointermove',event=>{
 if(!pan||pan.id!==event.pointerId)return;
 if(!(event.buttons&1)){stopPan();return;}
 canvas.scrollLeft=pan.left-(event.clientX-pan.x);
 canvas.scrollTop=pan.top-(event.clientY-pan.y);
});
for(const type of ['pointerup','pointercancel','lostpointercapture']){
 canvas.addEventListener(type,event=>{if(pan?.id===event.pointerId)stopPan();});
}
window.addEventListener('blur',stopPan);
$('fit').onclick=fitGraph;$('zoom-out').onclick=()=>setZoom(graphZoom/1.2);$('zoom-in').onclick=()=>setZoom(graphZoom*1.2);$('zoom-reset').onclick=()=>setZoom(1);
$('filter').oninput=applyFilters;$('hide-ended').onchange=applyFilters;$('search').oninput=()=>{graphZoom=1;render();const match=Object.values(tree?.nodes||{}).find(n=>[n.question,n.id,n.status].join(' ').toLowerCase().includes($('search').value.trim().toLowerCase()));centerNode(match?.id);};$('refresh').onclick=refresh;render();refresh();
