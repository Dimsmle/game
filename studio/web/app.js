/* Character Studio v0.7: runtime scheduler + renderer capabilities + diagnostics. */
"use strict";
const $=id=>document.getElementById(id);
const api=async(path,data)=>{
  const req=data===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)};
  const resp=await fetch(path,req);
  const ct=resp.headers.get("Content-Type")||"";
  if(!resp.ok){
    let msg="HTTP "+resp.status;
    try{ const j=await resp.json(); msg=j.error||msg; }catch{}
    throw Error(msg);
  }
  return ct.includes("application/json")?resp.json():resp;
};
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt=n=>Number(n||0).toLocaleString("zh-CN");
const fname=p=>String(p||"").split("/").pop();
const fileURL=rel=>"/file/"+String(rel).split("/").map(encodeURIComponent).join("/");
const imgURL=ref=>{
 const text=String(ref||"");
 if(text.startsWith("generated:"))return "/generated/"+text.split(":")[1]+".png";
 if(text.startsWith("background:"))return "/background/"+text.split(":")[1]+".png";
 return fileURL(text);
};
const clamp=(v,min,max)=>Math.min(max,Math.max(min,v));
let settings={},manifest={layers:[],scenes:{day:"",night:""},events:[]};
let activeRoleName="";
let verifiedSceneImage=null;
let characterMirror=false;
const roleDisplayName=()=>activeRoleName||settings.role_name||"角色";
let files=[],activeKind="images",atlasRef="",atlasImg=new Image(),crop=null,zoom=.5,rects=[];
let selectedLayer="",mood="neutral",action="idle",scene="day",sceneSince=0;
let gameBackdrop=null;
let gameMode=new URLSearchParams(location.search).get("mode")!=="studio";
document.body.classList.toggle("game-mode",gameMode);
let backgroundItems=[],selectedBgRef="",previewBackgroundRef="",lastAutoSceneSlot="";
let timelineCatalog=[],timelineGroup="face",activeExpression=null,expressionRequest=0;
let nodSequence=null,nodRuntimeToken=null,nodMouthUntil=0;
let textMouthUntil=0;
function mouthOpen(t=performance.now()){
 return playing?volume>.018:(t<textMouthUntil&&Math.floor(t/110)%2===0);
}
const sequenceRenderer=new FrameSequenceRenderer(ref=>new Promise((resolve,reject)=>{
 const image=new Image();image.onload=()=>resolve(image);
 image.onerror=()=>reject(Error("动作帧加载失败"));image.src=fileURL(ref);
}),{onEnd:sequence=>{
 activeExpression={label:sequence.expression,refs:sequence.settled_refs};
 if(nodRuntimeToken!==null)runtimeEvent("motion_ended",{token:nodRuntimeToken});
 nodRuntimeToken=null;
 $("nodStatus").textContent="点头播放完成，已恢复同一表情。";
}});
let behaviorCatalog={entries:[],emotions:[],action_tags:[]};
let memoryItems=[];
let runtimeState={phase:"idle",emotion:"neutral",action_tag:"idle",queue_length:0,cooldowns:{},scene_lock:{active:false}};
let runtimeActionToken=0;
let booting=true;
let imageCache=new Map(),busy=false,queue=[],playing=false,volume=.15,audioSource=null,audioContext=null,analyser=null,fft=null;
let currentAudio=null,recording=false,recorder=null,recorded=[],recordingStream=null;
let speechGeneration=0,speechFetch=null,speechQueue=Promise.resolve(),systemSpeechFinish=null;
const chatStream=new ChatStream((...args)=>fetch(...args));
let atlasDrag=null,stageDrag=false,toastTimer=null,assetSearchTimer=null;
const stage=$("stage"),ctx=stage.getContext("2d");
const W=stage.width,H=stage.height;
const moodLabels={
 neutral:"平静",happy:"开心",gentle:"温柔",shy:"害羞",
 sleepy:"困倦",surprised:"惊讶",sad:"悲伤",angry:"生气",
 worried:"不安",thinking:"思考",crying:"哭泣",
 playful:"俏皮",confident:"自信",grateful:"感激",
 serious:"认真",embarrassed:"尴尬",flustered:"慌张",annoyed:"无语/嫌弃",
 pouting:"鼓脸",moved:"感动",shocked:"大受打击",excited:"兴奋",
 happy_cry:"喜极而泣",dazed:"晕乎乎",wink:"眨眼笑",affectionate:"亲昵"
};
function toast(msg){
  const node=$("toast");node.textContent=msg;node.classList.remove("hidden");
  clearTimeout(toastTimer);toastTimer=setTimeout(()=>node.classList.add("hidden"),5000);
}
function setStatus(msg){$("chatStatus").textContent=msg;}
function setEngine(){
  const demo=settings.llm_mode==="demo";
  $("engineBadge").textContent=demo?"离线演示 · 未连 AI":"LLM · 已配置接口";
  $("engineBadge").style.color=demo?"#b9cae3":"#8fe2c6";
}
function chooseWork(id){
  document.querySelectorAll("#workTabs button").forEach(b=>b.classList.toggle("active",b.dataset.work===id));
  ["expressions","backgrounds","atlas","layers","events","scene","system"].forEach(x=>$(x+"Panel").classList.toggle("hidden",x!==id));
}
document.querySelectorAll("#workTabs button").forEach(b=>b.onclick=()=>chooseWork(b.dataset.work));
function chooseFileKind(kind){
 activeKind=kind;
 document.querySelectorAll("#fileTabs button").forEach(b=>b.classList.toggle("active",b.dataset.kind===kind));
 renderFiles();
}
document.querySelectorAll("#fileTabs button").forEach(b=>b.onclick=()=>chooseFileKind(b.dataset.kind));
function renderFiles(){
 const term=$("assetSearch").value.trim().toLowerCase();
 const relevant=files.filter(f=>activeKind==="images"?[".png",".webp",".jpg",".jpeg",".gif"].includes(f.ext):f.ext===".json");
 const filtered=relevant.filter(f=>f.path.toLowerCase().includes(term));
 const list=$("fileList");
 if(!filtered.length){list.innerHTML=`<div class="empty">${files.length?"没有符合条件的文件":"请先选择 PsbDecompile 的导出目录"}</div>`;return;}
 list.innerHTML=filtered.slice(0,230).map(f=>
 `<button class="file-item ${atlasRef===f.path?"active":""}" data-file="${esc(f.path)}">
 <span class="file-icon">${f.ext===".json"?"{}":"▧"}</span>
 <span class="file-meta"><strong title="${esc(f.path)}">${esc(fname(f.path))}</strong>
 <small title="${esc(f.path)}">${esc(f.path)} · ${(f.size/1024/1024).toFixed(1)} MB</small></span></button>`).join("")+
 (filtered.length>230?`<div class="empty">还有 ${fmt(filtered.length-230)} 个文件，请搜索缩小范围。</div>`:"");
 list.querySelectorAll("[data-file]").forEach(b=>b.addEventListener("click",()=>{
   const path=b.dataset.file;
   if(path.toLowerCase().endsWith(".json")){
      $("jsonSelect").value=path;chooseWork("atlas");inspectJSON();
   }else selectAtlas(path);
 }));
}
async function refreshAssets(){
 try{
  const a=await api("/api/assets");
  files=a.items;
  $("fileCount").textContent=fmt(files.length);
  $("imageCount").textContent=fmt(files.filter(x=>[".png",".webp",".jpg",".jpeg",".gif"].includes(x.ext)).length);
  $("jsonCount").textContent=fmt(files.filter(x=>x.ext===".json").length);
  $("rootHint").textContent=settings.assets_dir||"未选择素材目录";
  const options=files.filter(f=>f.ext===".json").map(f=>`<option value="${esc(f.path)}">${esc(fname(f.path))}</option>`).join("");
  $("jsonSelect").innerHTML=`<option value="">选择结构 JSON 进行检查</option>`+options;
  renderFiles();
  if(!atlasRef){
    const first=files.find(f=>f.ext===".png"&&/kan|shi|tou|say|let|fg/i.test(f.path))||
                files.find(f=>f.ext===".png");
    if(first)await selectAtlas(first.path);
  }
 }catch(e){toast("读取素材失败："+e.message);}
}
function selectAtlas(file){
 return new Promise((resolve)=>{
  atlasRef=file;
  atlasImg=new Image();
  $("atlasLabel").textContent=fname(file);
  $("selectedImageName").textContent=file;
  $("atlasInner").hidden=true;
  atlasImg.onload=()=>{
    $("atlasImage").src=atlasImg.src;
    $("atlasInner").hidden=false;
    $("atlasViewport").querySelector(".atlas-empty")?.remove();
    crop={x:0,y:0,w:atlasImg.naturalWidth,h:atlasImg.naturalHeight};
    renderAtlasZoom();
    $("atlasViewport").scrollTop=0;$("atlasViewport").scrollLeft=0;
    renderFiles();resolve(true);
  };
  atlasImg.onerror=()=>{toast("无法加载图像："+file);resolve(false);};
  atlasImg.src=imgURL(file);
 });
}
function renderAtlasZoom(){
 if(!atlasImg.naturalWidth)return;
 zoom=Number($("atlasZoom").value)||0.5;
 const w=atlasImg.naturalWidth*zoom,h=atlasImg.naturalHeight*zoom;
 const inner=$("atlasInner");
 inner.style.width=w+"px";inner.style.height=h+"px";
 $("atlasImage").style.width=w+"px";$("atlasImage").style.height=h+"px";
 drawCrop();
}
function drawCrop(){
 if(!crop)return;
 const b=$("cropBox");
 b.style.left=crop.x*zoom+"px";b.style.top=crop.y*zoom+"px";
 b.style.width=crop.w*zoom+"px";b.style.height=crop.h*zoom+"px";
 $("cropInfo").textContent=`x:${Math.round(crop.x)}  y:${Math.round(crop.y)}  w:${Math.round(crop.w)}  h:${Math.round(crop.h)} · 图片 ${atlasImg.naturalWidth}×${atlasImg.naturalHeight}`;
}
function setCrop(c){
 if(!atlasImg.naturalWidth)return;
 const x=clamp(Number(c.x)||0,0,atlasImg.naturalWidth-1);
 const y=clamp(Number(c.y)||0,0,atlasImg.naturalHeight-1);
 crop={x,y,w:clamp(Number(c.w)||1,1,atlasImg.naturalWidth-x),h:clamp(Number(c.h)||1,1,atlasImg.naturalHeight-y)};
 drawCrop();
}
$("atlasZoom").oninput=renderAtlasZoom;
$("fullCrop").onclick=()=>setCrop({x:0,y:0,w:atlasImg.naturalWidth,h:atlasImg.naturalHeight});
const coords=e=>{
 const b=$("atlasInner").getBoundingClientRect();
 return {x:clamp((e.clientX-b.left)/zoom,0,atlasImg.naturalWidth),
         y:clamp((e.clientY-b.top)/zoom,0,atlasImg.naturalHeight)};
};
$("atlasInner").addEventListener("pointerdown",e=>{
 if(e.button!==0 || !atlasImg.naturalWidth)return;
 atlasDrag=coords(e);
 $("atlasInner").setPointerCapture(e.pointerId);
 setCrop({x:atlasDrag.x,y:atlasDrag.y,w:1,h:1});
});
$("atlasInner").addEventListener("pointermove",e=>{
 if(!atlasDrag)return;
 const pos=coords(e);
 setCrop({x:Math.min(pos.x,atlasDrag.x),y:Math.min(pos.y,atlasDrag.y),
          w:Math.max(Math.abs(pos.x-atlasDrag.x),1),h:Math.max(Math.abs(pos.y-atlasDrag.y),1)});
});
$("atlasInner").addEventListener("pointerup",()=>{atlasDrag=null;});
$("atlasInner").addEventListener("pointercancel",()=>{atlasDrag=null;});

function layerById(){return manifest.layers.find(x=>x.id===selectedLayer);}
function saveManifest(){
 return api("/api/manifest",manifest).then(r=>{manifest=r.manifest;return r;})
   .catch(e=>{toast("配置未保存："+e.message);throw e;});
}
$("addLayer").onclick=async()=>{
 if(!atlasRef||!crop)return toast("请先选中图片和图集范围");
 const id="layer_"+Date.now();
 let slot=$("layerSlot").value;
 manifest.layers.push({id,name:slot+" · "+fname(atlasRef),file:atlasRef,slot,crop:{...crop},
                       x:0,y:0,z:manifest.layers.length*10,scale:clamp(350/crop.h,.12,3),visible:true});
 selectedLayer=id;
 try{await saveManifest();renderLayers();chooseWork("layers");toast("图层已加入舞台，可拖动定位");}
 catch{manifest.layers.pop();}
};
function renderLayers(){
 const list=$("layerList");
 if(!manifest.layers.length){list.innerHTML=`<div class="empty">没有图层。请在“图集”页添加主体立绘，之后可补充眼睛和嘴型。</div>`;}
 else list.innerHTML=[...manifest.layers].sort((a,b)=>b.z-a.z).map(x=>`
 <div class="layer-entry ${selectedLayer===x.id?"active":""}">
 <input type="checkbox" data-visible="${esc(x.id)}" ${x.visible?"checked":""} style="width:auto" title="显示图层">
 <button data-select-layer="${esc(x.id)}" title="${esc(x.file)}">${esc(x.name)} <span class="muted">(${esc(x.slot)})</span></button>
 <button class="remove" title="移除" data-remove="${esc(x.id)}">×</button></div>`).join("");
 list.querySelectorAll("[data-select-layer]").forEach(b=>b.onclick=()=>{selectedLayer=b.dataset.selectLayer;renderLayers();});
 list.querySelectorAll("[data-remove]").forEach(b=>b.onclick=async()=>{
   manifest.layers=manifest.layers.filter(x=>x.id!==b.dataset.remove);
   if(selectedLayer===b.dataset.remove)selectedLayer="";
   await saveManifest();renderLayers();
 });
 list.querySelectorAll("[data-visible]").forEach(el=>el.onchange=async()=>{
  const l=manifest.layers.find(x=>x.id===el.dataset.visible);if(l){l.visible=el.checked;await saveManifest();}
 });
 renderProperties();
 $("stageHint").classList.toggle("hidden",manifest.layers.length>0);
}
function renderProperties(){
 const el=$("layerProps"),layer=layerById();
 if(!layer){el.innerHTML=`<div class="empty">点击一个图层进行调整。</div>`;return;}
 const slotOptions=["base","overlay","eyes_open","eyes_closed","mouth_open","mouth_closed","happy"];
 el.innerHTML=`<label class="wide">名称<input data-prop="name" value="${esc(layer.name)}"></label>
 <label>X 位置<input data-prop="x" type="number" value="${layer.x}" step="5"></label>
 <label>Y 位置<input data-prop="y" type="number" value="${layer.y}" step="5"></label>
 <label>缩放<input data-prop="scale" type="number" value="${layer.scale}" step="0.05" min="0.01"></label>
 <label>层级 Z<input data-prop="z" type="number" value="${layer.z}" step="1"></label>
 <label class="wide">图层类别<select data-prop="slot">${slotOptions.map(x=>`<option value="${x}" ${x===layer.slot?"selected":""}>${x}</option>`).join("")}</select></label>`;
 el.querySelectorAll("[data-prop]").forEach(inp=>inp.addEventListener("change",()=>{
   const k=inp.dataset.prop;
   const v=["x","y","scale","z"].includes(k)?Number(inp.value):inp.value;
   if(Number.isFinite(v)||typeof v==="string"){layer[k]=v;renderLayers();}
 }));
}
$("saveLayers").onclick=async()=>{await saveManifest();toast("图层和舞台配置已保存");};

function paintBackground(t){
 const grad=ctx.createLinearGradient(0,0,0,H);
 const night=gameMode&&gameBackdrop?gameBackdrop==="night":scene.includes("night")||scene==="night";
 const evening=gameMode&&gameBackdrop==="evening";
 grad.addColorStop(0,night?"#18233e":evening?"#ae7786":gameMode?"#97b5c3":"#7ca7cd");
 grad.addColorStop(1,night?"#45425d":evening?"#edd1bb":gameMode?"#eee1cc":"#dee4e0");
 ctx.fillStyle=grad;ctx.fillRect(0,0,W,H);
 if(!manifest.scenes[gameMode&&gameBackdrop?gameBackdrop:scene]){
  ctx.globalAlpha=night?.65:.4;
  ctx.fillStyle=night?"#1b2b4a":"#c3d3d9";
  ctx.fillRect(0,H*.64,W,H*.36);
  ctx.fillStyle=night?"#566585":"#d5e8f0";
  ctx.fillRect(W*.68,H*.12,W*.19,H*.48);
  ctx.fillStyle=night?"#112744":"#9bc4de";
  ctx.fillRect(W*.70,H*.14,W*.15,H*.43);
  ctx.globalAlpha=1;
 }
}
function resourceImage(ref){
 if(!ref)return null;
 if(imageCache.has(ref))return imageCache.get(ref);
 const obj=new Image();
 obj.onload=()=>{obj._ready=true;};
 obj.onerror=()=>{obj._failed=true;};
 obj.src=imgURL(ref);
 imageCache.set(ref,obj);
 return obj;
}
function drawBackgroundImage(img){
 const mode=manifest.background_fit==="contain"?"contain":"cover";
 const factor=(mode==="contain"?Math.min:Math.max)(W/img.width,H/img.height);
 const iw=img.width*factor,ih=img.height*factor;
 ctx.drawImage(img,(W-iw)/2,(H-ih)/2,iw,ih);
}
function placeholder(t){
 ctx.save();ctx.translate(W/2,H*.64);const s=1+Math.sin(t/770)*.006;ctx.scale(s,s);
 ctx.fillStyle="#425d7d99";ctx.beginPath();ctx.ellipse(0,110,145,178,0,0,Math.PI*2);ctx.fill();
 ctx.fillStyle="#2d3f58bb";ctx.beginPath();ctx.ellipse(0,-35,82,109,0,0,Math.PI*2);ctx.fill();
 ctx.fillStyle="#6882a5cc";ctx.beginPath();ctx.ellipse(0,-55,60,73,0,0,Math.PI*2);ctx.fill();
 ctx.restore();
 ctx.fillStyle="#cedef1";ctx.font="14px system-ui";ctx.textAlign="center";ctx.fillText("演示占位图 · 尚未导入游戏角色立绘",W/2,H-25);
}
function layerVisible(l,t){
 if(!l.visible)return false;
 const blink=(t%4200)<130;
 if(l.slot==="eyes_open")return !blink;
 if(l.slot==="eyes_closed")return blink;
 if(l.slot==="mouth_open")return mouthOpen();
 if(l.slot==="mouth_closed")return !mouthOpen();
 if(l.slot==="happy")return mood==="happy";
 return true;
}
function drawStage(t){
 const sequenceImage=sequenceRenderer.update({
   talk:mouthOpen(t)||t<nodMouthUntil,blink:(t%4200)<155});
 paintBackground(t);
 const activeBackground=gameMode&&gameBackdrop?manifest.scenes[gameBackdrop]:(previewBackgroundRef||manifest.scenes[scene]);
 const bg=activeBackground?resourceImage(activeBackground):null;
 if(gameMode&&verifiedSceneImage)drawBackgroundImage(verifiedSceneImage);
 else if(bg&&bg._ready)drawBackgroundImage(bg);
 const layers=[...manifest.layers].sort((a,b)=>a.z-b.z);
 if(layers.length===0)placeholder(t);
 const sway=Math.sin(t/1150)*3;
 const bob=action==="sleep"?Math.sin(t/1200)*1.5:Math.sin(t/680)*3;
 const wave=action==="wave"?Math.sin(t/210)*.024:0;
 const nod=action==="nod"?Math.sin(t/180)*8:0;
 for(const layer of layers){
  if(!layerVisible(layer,t))continue;
  // Real PSB JSON-derived static expressions generated at startup.
  const isAuto=(["__auto_emote_character","__auto_emote_kan"].includes(layer.id) && manifest.poses);
  const isBlink=(t%4200)<155;
  const expressionRefs=(isAuto && activeExpression) ? activeExpression.refs : null;
  const poseRef=isAuto
    ? (expressionRefs
       ? (mouthOpen(t) ? expressionRefs.talk :
          isBlink ? expressionRefs.blink : expressionRefs.normal)
       : (mouthOpen(t) && manifest.poses.talk
         ? manifest.poses.talk
         : isBlink && manifest.poses.blink
             ? manifest.poses.blink
             : (manifest.poses[mood]||manifest.poses.neutral||layer.file)))
    : layer.file;
  const fromSequence=isAuto&&sequenceImage;
  const im=fromSequence||resourceImage(poseRef);
  if(!im||(!fromSequence&&!im._ready))continue;
  let r=layer.crop;
  const ratio=isAuto?im.width/740:1;
  if(isAuto)r={x:r.x*ratio,y:r.y*ratio,w:r.w*ratio,h:r.h*ratio};
  const sw=clamp(r.w,1,im.width-r.x),sh=clamp(r.h,1,im.height-r.y);
  if(sw<=0||sh<=0)continue;
  ctx.save();
  ctx.translate(W/2+layer.x+(isAuto?0:sway),H/2+layer.y+(isAuto?0:bob+nod));
  ctx.rotate(isAuto?0:wave);
  ctx.scale(layer.scale*(isAuto&&characterMirror?-1:1),layer.scale);
  ctx.drawImage(im,r.x,r.y,sw,sh,-sw/ratio/2,-sh/ratio/2,sw/ratio,sh/ratio);
  if(selectedLayer===layer.id){
   ctx.strokeStyle="#8eebc7";ctx.lineWidth=1.7/layer.scale;
   ctx.setLineDash([7/layer.scale,5/layer.scale]);
   ctx.strokeRect(-sw/2,-sh/2,sw,sh);
  }
  ctx.restore();
 }
 // bottom info strip
 if(!gameMode){
  ctx.fillStyle="#0c1a30bb";ctx.fillRect(12,H-56,275,36);
  ctx.font="12px system-ui";ctx.textAlign="left";ctx.fillStyle="#e4eefc";
  ctx.fillText(roleDisplayName()+" · "+moodLabels[mood]+" · "+scene,24,H-33);
 }
 if(playing&&analyser&&fft){
  analyser.getByteTimeDomainData(fft);
  let sum=0;
  for(let i=0;i<fft.length;i++){let v=(fft[i]-128)/128;sum+=v*v;}
  volume=Math.sqrt(sum/fft.length);
 }
 requestAnimationFrame(drawStage);
}
requestAnimationFrame(drawStage);
$("focusStage").onclick=()=>{
 const focused=document.querySelector(".middle").classList.toggle("stage-focus");
 $("focusStage").textContent=focused?"恢复对话布局":"放大舞台";
};
function canvasLocation(e){
 const b=stage.getBoundingClientRect(),scale=Math.min(b.width/W,b.height/H);
 const ox=(b.width-W*scale)/2,oy=(b.height-H*scale)/2;
 return {x:(e.clientX-b.left-ox)/scale-W/2,
         y:(e.clientY-b.top-oy)/scale-H/2};
}
stage.onpointerdown=e=>{if(!layerById())return;stageDrag=true;stage.setPointerCapture(e.pointerId);};
stage.onpointermove=e=>{
 if(!stageDrag)return;
 const l=layerById();if(!l)return;
 const p=canvasLocation(e);
 l.x=Math.round(p.x);l.y=Math.round(p.y);
 // Do not rerender the whole properties form while dragging.
 const x=$("layerProps").querySelector('[data-prop="x"]');
 const y=$("layerProps").querySelector('[data-prop="y"]');
 if(x)x.value=l.x;if(y)y.value=l.y;
};
stage.onpointerup=async()=>{if(!stageDrag)return;stageDrag=false;try{await saveManifest();}catch{}};
stage.onpointercancel=()=>{stageDrag=false;};

function setMood(next){
 mood=next in moodLabels?next:"neutral";$("moodChip").textContent=moodLabels[mood];
}
function setAction(next){
 action=["idle","happy","nod","wave","talk","sleep"].includes(next)?next:"idle";
 sceneSince=performance.now();
 document.querySelectorAll(".stage-toolbar [data-action]").forEach(b=>b.classList.toggle("active",b.dataset.action===action));
 // Keep the LLM's face emotion independent from the body gesture.
 // For example 'worried + talk' must not silently become 'happy'.
}
document.querySelectorAll(".stage-toolbar [data-action]").forEach(b=>b.onclick=()=>{
 const value=b.dataset.action;
 const auto=manifest.layers.some(layer=>["__auto_emote_character","__auto_emote_kan"].includes(layer.id));
 if(auto&&value==="nod")return previewNod(activeExpression?.label||emotionTimeline[mood]||"普通Ａ");
 if(auto&&value==="happy"){setMood("happy");return applyMoodTimeline("happy");}
 if(auto&&value==="sleep"){setMood("sleepy");return applyMoodTimeline("sleepy");}
 if(auto&&value==="wave")return toast("当前只实现了点头连续预览；轻摆动作尚未验收。");
 if(value==="idle")$("stopNod").click();
 setAction(value);
});
document.querySelectorAll(".stage-toolbar [data-emotion]").forEach(b=>b.onclick=async()=>{
  setMood(b.dataset.emotion);
  setAction("idle");
  await applyMoodTimeline(b.dataset.emotion);
});
function renderRuntimeSummary(){
 if(!$("runtimeSummary"))return;
 const lock=runtimeState.scene_lock||{};
 const cooldowns=Object.entries(runtimeState.cooldowns||{})
    .map(([tag,sec])=>`${tag}:${sec}s`).join(", ")||"无";
 $("runtimeSummary").textContent=[
   `phase=${runtimeState.phase||"idle"} · revision=${runtimeState.revision??0}`,
   `emotion=${runtimeState.emotion||"neutral"} · action=${runtimeState.action_tag||"idle"}`,
   `speech=${runtimeState.speech_active?"playing":"off"} · queue=${runtimeState.queue_length||0}`,
   `cooldown=${cooldowns}`,
   `scene lock=${lock.active?(lock.scene+" · "+lock.remaining+"s"):"off"}`
 ].join("\n");
}
async function runtimeEvent(event,extra={}){
 try{
  const result=await api("/api/runtime_event",{event,...extra});
  runtimeState=result.runtime||runtimeState;
  renderRuntimeSummary();
  return runtimeState;
 }catch(error){
  console.warn("runtime event failed",event,error);
  return runtimeState;
 }
}
async function refreshRuntimeState(){
 if(booting||window.gameExperience?.active)return;
 try{
  const next=await api("/api/runtime");
  const previousToken=runtimeActionToken;
  if(Number(next.action_token||0)<previousToken)return;
  runtimeState=next;
  runtimeActionToken=Number(next.action_token||0);
  renderRuntimeSummary();
  // A queued body reaction may start after the original chat request completed.
  // Apply it exactly once when the backend action token advances.
  if(runtimeActionToken>previousToken && next.active_behavior){
    setMood(next.active_behavior.emotion||runtimeState.emotion||"neutral");
    await applyBehaviorPlan(next.active_behavior);
  }
 }catch(error){console.warn("runtime refresh failed",error);}
}
function renderRendererCapabilities(result){
 const current=result?.current||{};
 const sequence=(result?.available_or_planned||[]).find(x=>x.renderer_id==="cpu_mesh_sequence_preview");
 const flags=[
  ["表情",current.expressions],["连续动作",current.continuous_motion],
  ["网格变形",current.mesh_deformation],["遮罩",current.masks],
  ["物理",current.physics],["透明背景",current.transparent_background]
 ];
 $("rendererCapabilities").textContent=[
   `${current.display_name||"未知后端"} (${current.renderer_id||""})`,
   flags.map(([name,ok])=>`${name}:${ok?"✓":"—"}`).join(" · "),
   `口型：${current.lip_sync||"none"}`,
   ...((current.notes||[]).map(x=>"• "+x)),
   ...(sequence?["另有可用实验后端："+sequence.display_name,...sequence.notes]:[])
 ].join("\n");
}
async function loadModelMetadata(){
 try{
  const data=await api("/api/model_metadata"),record=data.record||{};
  $("modelDisplayName").value=record.display_name||"";
  $("modelOutfitTag").value=record.outfit||"";
  $("modelPoseFamily").value=record.pose_family||"";
  $("modelVerified").checked=!!record.verified;
  $("modelMetaNotes").value=record.notes||"";
  $("modelMetadataStatus").textContent=data.current
    ? `当前：${data.current}${record.verified?" · 已人工确认":" · 尚未确认"}`
    : "尚未选择模型";
 }catch(error){$("modelMetadataStatus").textContent="读取失败："+error.message;}
}
function renderMemories(){
 const list=$("memoryList");
 if(!memoryItems.length){
   list.innerHTML='<div class="muted small">还没有长期记忆。只保存你明确希望角色记住的内容。</div>';
   return;
 }
 list.innerHTML=memoryItems.map(item=>`
   <div class="memory-item ${item.enabled?"":"disabled"}">
     <label><input type="checkbox" data-memory-toggle="${item.id}" ${item.enabled?"checked":""}>
       <span>${esc(item.content)}</span></label>
     <button class="mini-btn danger" data-memory-delete="${item.id}">删除</button>
   </div>`).join("");
 list.querySelectorAll("[data-memory-toggle]").forEach(input=>input.onchange=async()=>{
   try{
     const result=await api("/api/memory",{action:"toggle",id:Number(input.dataset.memoryToggle),enabled:input.checked});
     memoryItems=result.items||[];renderMemories();
   }catch(error){toast(error.message);input.checked=!input.checked;}
 });
 list.querySelectorAll("[data-memory-delete]").forEach(button=>button.onclick=async()=>{
   if(!confirm("删除这条本机长期记忆？"))return;
   try{
     const result=await api("/api/memory",{action:"delete",id:Number(button.dataset.memoryDelete)});
     memoryItems=result.items||[];renderMemories();
   }catch(error){toast(error.message);}
 });
}
async function refreshMemories(){
 try{
   const result=await api("/api/memories");
   memoryItems=result.items||[];renderMemories();
 }catch(error){$("memoryList").textContent="读取记忆失败："+error.message;}
}
$("addMemory").onclick=async()=>{
 const content=$("memoryInput").value.trim();
 if(!content)return toast("请输入要明确保存的记忆");
 try{
   const result=await api("/api/memory",{action:"add",content});
   memoryItems=result.items||[];$("memoryInput").value="";renderMemories();
   toast("已保存到本机长期记忆");
 }catch(error){toast(error.message);}
};

async function refreshSystemPanel(){
 await refreshRuntimeState();
 try{renderRendererCapabilities(await api("/api/renderer_capabilities"));}
 catch(error){$("rendererCapabilities").textContent="读取失败："+error.message;}
 await loadModelMetadata();
 await refreshMemories();
 await refreshLogs();
}
function setScene(next,source="system"){
 if(!next)return false;
 const lock=runtimeState.scene_lock||{};
 if(source!=="manual" && lock.active && lock.scene && next!==lock.scene){
   console.info(`scene change blocked by manual lock: ${source} -> ${next}`);
   return false;
 }
 scene=next;
 previewBackgroundRef="";
 $("sceneChip").textContent=next;
 if([...$("stageSceneSelect").options].some(x=>x.value===next)){
   $("stageSceneSelect").value=next;
 }
 if(source==="manual"){
   runtimeEvent("scene_lock",{scene:next,duration_seconds:1800});
 }
 return true;
}
$("stageSceneSelect").onchange=e=>setScene(e.target.value,"manual");
$("dayBtn").onclick=()=>setScene("day","manual");
$("nightBtn").onclick=()=>setScene("night","manual");
$("exportFrame").onclick=()=>{
  stage.toBlob(blob=>{
    if(!blob)return toast("舞台无法导出 PNG");
    const link=document.createElement("a");
    const url=URL.createObjectURL(blob);
    link.href=url;link.download="character_scene_"+new Date().toISOString().replace(/[:.]/g,"-")+".png";
    document.body.append(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1500);
    toast("已导出当前合成画面 PNG");
  },"image/png");
};
async function bindBackground(key){
 if(!atlasRef)return toast("先在左侧选择一张背景图片");
 manifest.scenes[key]=atlasRef;
 try{await saveManifest();setScene(key,"manual");renderSceneBindings();toast(`已把 ${fname(atlasRef)} 绑定为 ${key} 场景`);}
 catch(e){toast(e.message);}
}
$("setDay").onclick=()=>bindBackground("day");
$("setNight").onclick=()=>bindBackground("night");
function renderSceneBindings(){
 const el=$("sceneBindings");
 el.innerHTML=Object.entries(manifest.scenes).map(([k,v])=>`<div style="padding:4px 0">
 <strong>${esc(k)}</strong>：${esc(v?fname(v):"未绑定")}</div>`).join("");
 $("eventScene").innerHTML=Object.keys(manifest.scenes).map(k=>`<option value="${esc(k)}">${esc(k)}</option>`).join("");
 const keys=Object.keys(manifest.scenes);
 $("stageSceneSelect").innerHTML=keys.map(k=>`<option value="${esc(k)}">${esc(k)}</option>`).join("");
 if(keys.includes(scene))$("stageSceneSelect").value=scene;
 $("backgroundFit").value=manifest.background_fit||"cover";
}
function renderBackgroundLibrary(){
 const term=$("backgroundSearch").value.trim().toLowerCase();
 const matching=backgroundItems.filter(x=>
   (x.name+" "+x.ref+" "+x.folder+" "+x.category).toLowerCase().includes(term));
 const count=$("backgroundCount");
 count.textContent=`找到 ${backgroundItems.length} 张本机背景 · 当前显示 ${Math.min(90,matching.length)} 张`;
 const gallery=$("backgroundGallery");
 if(!matching.length){
   gallery.innerHTML=`<div class="empty">还没有识别到背景。可点击「从电脑导入背景图片」，或将原版背景放到 assets/bg / image/bg 文件夹。</div>`;
   return;
 }
 gallery.innerHTML=matching.slice(0,90).map(item=>`
 <button type="button" class="background-card ${selectedBgRef===item.ref?"selected":""}"
         data-background-ref="${esc(item.ref)}" title="${esc(item.ref)}">
   <img loading="lazy" src="${esc(imgURL(item.ref))}" alt="${esc(item.name)}">
   <span class="background-card-title">${esc(item.name)}</span>
   <span class="background-card-sub">${esc(item.category)} · ${item.source==="imported"?"本机导入":"游戏素材"}</span>
 </button>`).join("");
 gallery.querySelectorAll("[data-background-ref]").forEach(el=>el.onclick=()=>{
   const ref=el.dataset.backgroundRef;
   const item=backgroundItems.find(x=>x.ref===ref);
   selectedBgRef=ref;
   previewBackgroundRef=ref;
   $("selectedBackground").textContent=item
       ? `${item.name} · ${item.source==="imported"?"本机图库":"解包素材"} · ${item.ref}`
       : ref;
   renderBackgroundLibrary();
 });
}
async function refreshBackgroundLibrary(force=false){
 try{
  $("backgroundCount").textContent="正在读取背景目录...";
  const result=await api("/api/backgrounds"+(force?"?refresh=1":""));
  backgroundItems=result.items||[];
  if(selectedBgRef&&!backgroundItems.some(x=>x.ref===selectedBgRef)){
    selectedBgRef="";previewBackgroundRef="";
    $("selectedBackground").textContent="尚未选中背景";
  }
  renderBackgroundLibrary();
 }catch(error){
  $("backgroundCount").textContent="加载背景失败："+error.message;
  toast(error.message);
 }
}
$("backgroundSearch").oninput=renderBackgroundLibrary;
$("rescanBackgrounds").onclick=()=>refreshBackgroundLibrary(true);
$("openBackgroundLibrary").onclick=()=>{
  chooseWork("backgrounds");refreshBackgroundLibrary();
};
$("importBackgrounds").onclick=()=>$("backgroundUpload").click();
$("backgroundUpload").onchange=async()=>{
 const inputs=[...$("backgroundUpload").files].slice(0,30);
 if(!inputs.length)return;
 const button=$("importBackgrounds");
 button.disabled=true;
 let imported=0,first="",errors=[];
 try{
  for(const file of inputs){
   if(file.size>22*1024*1024){errors.push(file.name+": 超过22MB");continue;}
   try{
    const resp=await fetch("/api/background_import?name="+encodeURIComponent(file.name),{
       method:"POST",headers:{"Content-Type":file.type||"application/octet-stream"},body:file
    });
    const data=await resp.json();
    if(!resp.ok)throw Error(data.error||"导入失败");
    imported++;first=first||data.item.ref;
   }catch(error){errors.push(file.name+": "+error.message);}
  }
  await refreshBackgroundLibrary(true);
  if(first){
   selectedBgRef=first;previewBackgroundRef=first;
   const item=backgroundItems.find(x=>x.ref===first);
   $("selectedBackground").textContent=item?item.name:first;
   renderBackgroundLibrary();
  }
  toast(`导入成功 ${imported} 张${errors.length?"；失败："+errors.slice(0,2).join(" / "):""}`);
 }finally{
  button.disabled=false;
  $("backgroundUpload").value="";
 }
};
async function assignBackground(key,ref=selectedBgRef){
 if(!ref)return toast("请先从背景图库选一张图片");
 if(!/^[a-z][a-z0-9_]{0,35}$/.test(key))return toast("场景代号只能为小写英文字母、数字、下划线");
 manifest.scenes[key]=ref;
 try{
  await saveManifest();
  setScene(key,"manual");renderSceneBindings();renderEvents();
  toast(`已保存 ${key} 场景 · ${fname(ref)}`);
 }catch(error){toast("背景绑定失败："+error.message);}
}
$("bgAssignDay").onclick=()=>assignBackground("day");
$("bgAssignEvening").onclick=()=>assignBackground("evening");
$("bgAssignNight").onclick=()=>assignBackground("night");
$("bgAssignNamed").onclick=()=>assignBackground($("backgroundSceneKey").value.trim());
$("backgroundFit").onchange=async()=>{
 manifest.background_fit=$("backgroundFit").value;
 try{await saveManifest();toast("背景显示方式已保存");}
 catch(error){toast(error.message);}
};
function localSceneSlot(date=new Date()){
 const hours=date.getHours()+date.getMinutes()/60;
 return hours<7||hours>=19?"night":hours>=17?"evening":"day";
}
function applyAutoScene(force=false){
 if(window.gameExperience?.active)return;
 if(!settings.auto_scene)return;
 if(runtimeState.scene_lock?.active)return;
 const slot=localSceneSlot();
 if(force||slot!==lastAutoSceneSlot){
   const next=slot==="evening"&&!manifest.scenes.evening?"day":slot;
   lastAutoSceneSlot=slot;
   setScene(next,"auto");
 }
}
$("backgroundAutoTime").onchange=async()=>{
 const enabled=$("backgroundAutoTime").checked;
 try{
  const result=await api("/api/settings",{auto_scene:enabled});
  settings=result.settings;
  lastAutoSceneSlot="";
  if(enabled)applyAutoScene(true);
  toast(enabled?"已启用按时间自动切换背景":"已关闭自动切换背景");
 }catch(error){
  $("backgroundAutoTime").checked=!enabled;
  toast(error.message);
 }
};
setInterval(()=>applyAutoScene(),60000);

function renderEvents(){
 $("eventList").innerHTML=(manifest.events||[]).map(x=>`<div class="event-entry">
 <div><strong>${esc(x.time)} · ${esc(x.scene)}</strong><p>${esc(x.message||"切换场景")}</p></div>
 <button class="mini-btn danger" data-remove-event="${esc(x.id)}">删除</button></div>`).join("");
 $("eventList").querySelectorAll("[data-remove-event]").forEach(b=>b.onclick=async()=>{
  manifest.events=manifest.events.filter(x=>x.id!==b.dataset.removeEvent);
  await saveManifest();renderEvents();
 });
}
$("addEvent").onclick=async()=>{
 const time=$("eventTime").value, key=$("eventScene").value;
 manifest.events.push({id:"event_"+Date.now(),time,scene:key,message:$("eventMessage").value});
 try{await saveManifest();renderEvents();toast("定时事件已保存");}
 catch{manifest.events.pop();}
};
function checkEvents(){
 if(window.gameExperience?.active)return;
 const now=new Date(),date=[now.getFullYear(),String(now.getMonth()+1).padStart(2,"0"),String(now.getDate()).padStart(2,"0")].join("-");
 const minutes=now.getHours()*60+now.getMinutes();
 for(const event of manifest.events||[]){
  const parts=event.time.split(":").map(Number),trigger=parts[0]*60+parts[1];
  const id="character_event_"+event.id;
  if(minutes>=trigger&&minutes-trigger<=8&&localStorage.getItem(id)!==date){
    localStorage.setItem(id,date);
    if(busy||playing)queue.push(event);
    else executeEvent(event);
  }
 }
}
function executeEvent(event){
 const changed=setScene(event.scene,"event");
 if(event.message){
   appendBubble(event.message,"assistant",changed?"定时事件":"定时事件 · 场景被手动锁定");
 }
}
setInterval(()=>{checkEvents();if(!busy&&!playing&&queue.length)executeEvent(queue.shift());},15000);

function appendBubble(text,who="assistant",label){
 const box=document.createElement("div");
 box.className="bubble "+(who==="user"?"user":"assistant");
 const title=document.createElement("span");
 title.className="who";title.textContent=label||(who==="user"?"你":roleDisplayName());
 box.append(title,document.createTextNode(text));
 $("chatMessages").append(box);
 $("chatMessages").scrollTop=$("chatMessages").scrollHeight;
}
function speak(text){
 const generation=speechGeneration;
 speechQueue=speechQueue.catch(()=>{}).then(()=>generation===speechGeneration?speakNow(text,generation):null);
 return speechQueue;
}
async function speakNow(text,generation){
 if(!settings.tts_enabled)return;
 if(settings.tts_provider==="system"){
  if(!window.speechSynthesis)return {error:"当前窗口不支持系统语音；文字聊天继续"};
  const voice=speechSynthesis.getVoices().find(v=>v.localService&&v.lang.startsWith(settings.tts_text_lang));
  if(!voice)return {error:"没有可用的本地系统语音；文字聊天继续"};
  const utterance=new SpeechSynthesisUtterance(text);utterance.voice=voice;
  await runtimeEvent("speech_start");
  if(generation!==speechGeneration){await runtimeEvent("speech_end");return;}
  playing=true;volume=.2;
  await new Promise(resolve=>{
   let done=false;
   const finish=()=>{if(done)return;done=true;systemSpeechFinish=null;playing=false;volume=0;runtimeEvent("speech_end").finally(resolve);};
   systemSpeechFinish=finish;utterance.onend=finish;utterance.onerror=finish;speechSynthesis.speak(utterance);
  });
  return;
 }
 setStatus("正在合成角色语音...");
 try{
  speechFetch=new AbortController();
  const r=await fetch("/api/tts",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text}),signal:speechFetch.signal});
  if(!r.ok){
   let msg="音频接口返回 HTTP "+r.status;
   try{msg=(await r.json()).error||msg;}catch{}
   throw Error(msg);
  }
  const audioBlob=await r.blob();
  if(generation!==speechGeneration)return;
  const url=URL.createObjectURL(audioBlob);
  if(currentAudio){
    const previousAudio=currentAudio;
    if(typeof previousAudio._characterFinish==="function")await previousAudio._characterFinish();
    previousAudio.pause();previousAudio.src="";
  }
  const audio=new Audio(url);currentAudio=audio;
  try{
    audioContext=audioContext||new (window.AudioContext||window.webkitAudioContext)();
    if(audioContext.state==="suspended")await audioContext.resume();
    analyser=audioContext.createAnalyser();analyser.fftSize=512;fft=new Uint8Array(analyser.frequencyBinCount);
    const node=audioContext.createMediaElementSource(audio);
    node.connect(analyser);analyser.connect(audioContext.destination);
  }catch(e){console.warn("无法开启音频幅度分析，仍继续播放：",e);}
  await runtimeEvent("speech_start");
  if(generation!==speechGeneration){URL.revokeObjectURL(url);if(currentAudio===audio)currentAudio=null;await runtimeEvent("speech_end");return;}
  playing=true;volume=.2;setAction("talk");
  await new Promise((resolve,reject)=>{
    let finished=false;
    const finish=async(error=null)=>{
      if(finished)return;
      finished=true;
      try{URL.revokeObjectURL(url);}catch{}
      playing=false;volume=0;setAction("idle");
      if(currentAudio===audio)currentAudio=null;
      await runtimeEvent("speech_end");
      if(error)reject(error); else resolve();
    };
    audio._characterFinish=()=>finish();
    audio.onended=()=>finish();
    audio.onerror=()=>finish(new Error("音频播放失败"));
    audio.play().catch(error=>finish(error));
  });
  setStatus("就绪");
 }catch(e){
  if(generation!==speechGeneration)return;
  playing=false;volume=0;
  setStatus("语音连接失败");toast(e.message);
  return {error:e.message};
 }
}
async function applyBehaviorPlan(plan){
 if(!plan||typeof plan!=="object")return null;
 const label=plan.expression?.label;
 const motion=plan.motion;
 const trace=[
   `情绪标签：${plan.emotion||"neutral"} · 强度 ${plan.intensity??0.5}`,
   `面部预设：${label||"(缺少对应预设)"}`,
   `动作标签：${plan.action_tag||"idle"}`,
   `动作匹配：${motion?motion.label+" → "+motion.tags.join(", "):"(无可用动作)"}`,
   `播放能力：${motion?.playback==="frame_sequence"?"已验收 CPU 网格连续点头":motion?"PSB 单帧静态采样，不是完整连续动画":"面部表情 / 待机"}`,
   `场景：${plan.scene||"(保持当前场景)"}`,
   `调度：${plan.runtime_decision||"accepted"} · phase=${plan.runtime?.phase||runtimeState.phase||"idle"}`,
   ...(plan.warnings||[])
 ];
 $("behaviorTrace").textContent=trace.join("\n");
 if(!label){
   activeExpression=null;
   return null;
 }
 const serial=++expressionRequest;
 stopNodPlayback();
 try{
   if(motion?.label==="うんうん"){
     let prepared={state:"missing"};
     try{prepared=await api("/api/motion_sequence",{expression:label,cached_only:true});}
     catch(error){console.warn("点头缓存不可用，使用表情预览",error.message);}
     if(serial!==expressionRequest)return null;
     if(prepared.state==="ready"&&prepared.sequence.reviewed){
       const clip=prepared.sequence;nodSequence=clip;
       if(await sequenceRenderer.play(clip)){
         if(serial!==expressionRequest){if(sequenceRenderer.clip===clip)sequenceRenderer.stop();return null;}
         nodRuntimeToken=plan.runtime?.action_token??runtimeActionToken;
         await runtimeEvent("motion_started",{token:nodRuntimeToken,duration:nodSequence.duration_seconds});
         $("expressionStatus").textContent=`${label} + 点头 · 已验收 CPU 帧序列`;
         return prepared;
       }
     }
   }
   // Overlay selected PSB action's BODY/HEAD/MOVE variables on the selected
   // expression's FACE controls. Never let a movement overwrite the facial emotion.
   const response=await api("/api/expression_apply",{
     label,time:0,
     motion_label:motion?.label||null,
     motion_time:motion?.sample_time||0
   });
   if(serial!==expressionRequest)return null;
   activeExpression=response;
   $("expressionStatus").textContent=motion
     ? `对话已选择 ${label} + ${motion.label}（单帧预览，非原生动画）`
     : `对话已选择 ${label}（目前为静态近似表情）`;
   return response;
 }catch(error){
   if(serial===expressionRequest){
     $("expressionStatus").textContent="表情或动作装入失败："+error.message;
   }
   return null;
 }
}
async function sendMessage(text){
 if(busy||booting)return;
 busy=true;$("sendBtn").disabled=true;$("chatInput").disabled=true;
 appendBubble(text,"user");
 setStatus("正在等待模型响应...");
 try{
  const data=await api("/api/chat",{text});
  appendBubble(data.speech,"assistant",data.source==="demo"?"演示回复":"角色");
  setMood(data.emotion);setAction(data.action);
  if(data.runtime){
    runtimeState=data.runtime;
    runtimeActionToken=Number(data.runtime.action_token||runtimeActionToken);
    renderRuntimeSummary();
  }
  if(data.scene)setScene(data.scene,"ai");
  const behaviorPromise=applyBehaviorPlan(data.behavior);
  setStatus(data.source==="demo"?"演示模式 · 行为标签已解析":"LLM 已决策 · 角色准备动作/语音");
  await Promise.all([behaviorPromise,speak(data.speech)]);
 }catch(e){
  appendBubble("模型调用失败："+e.message,"assistant","系统提示");
  setStatus("接口请求失败");toast(e.message);
 }finally{
  busy=false;$("sendBtn").disabled=false;$("chatInput").disabled=false;$("chatInput").focus();
 }
}
$("chatForm").addEventListener("submit",e=>{e.preventDefault();if(booting)return;const text=$("chatInput").value.trim();if(text){$("chatInput").value="";sendMessage(text);}});
$("clearHistory").onclick=async()=>{
 if(!confirm("确认清空本机保存的聊天记录？"))return;
 try{await api("/api/clear_history",{});$("chatMessages").replaceChildren();toast("聊天记录已清空");}
 catch(e){toast(e.message);}
};
async function toggleMic(){
 if(!settings.stt_enabled)return toast("语音识别已关闭，本阶段无需安装 Whisper");
 if(recording){
  recorder.stop();$("micBtn").classList.remove("recording");$("micBtn").textContent="🎙";recording=false;
  return;
 }
 if(!navigator.mediaDevices||!window.MediaRecorder){return toast("当前浏览器不支持本地麦克风录制");}
 try{
  recordingStream=await navigator.mediaDevices.getUserMedia({audio:true});
  let opt={};
  if(MediaRecorder.isTypeSupported("audio/webm;codecs=opus"))opt={mimeType:"audio/webm;codecs=opus"};
  recorder=new MediaRecorder(recordingStream,opt);recorded=[];
  recorder.ondataavailable=e=>{if(e.data.size)recorded.push(e.data);};
  recorder.onstop=async()=>{
   recordingStream?.getTracks().forEach(x=>x.stop());
   const blob=new Blob(recorded,{type:recorder.mimeType||"audio/webm"});
   setStatus("正在用本地 faster-whisper 识别...");
   try{
    const response=await fetch("/api/asr",{method:"POST",headers:{"Content-Type":blob.type},body:blob});
    const result=await response.json();
    if(!response.ok)throw Error(result.error||"识别失败");
    $("chatInput").value=result.text;
    setStatus("语音已转为文字，可以点击发送");
   }catch(e){setStatus("识别失败");toast(e.message);}
  };
  recorder.start();$("micBtn").classList.add("recording");$("micBtn").textContent="■";
  setStatus("正在录音；再次点击麦克风结束并识别");
  recording=true;
 }catch(e){toast("无法访问麦克风："+e.message);}
}
$("micBtn").onclick=toggleMic;

async function inspectJSON(){
 const name=$("jsonSelect").value;if(!name)return toast("请选择 JSON 文件");
 $("jsonDiagnostics").textContent="正在分析结构...";
 try{
  const res=await api("/api/json_inspect?file="+encodeURIComponent(name));
  rects=res.rect_candidates;
  $("jsonDiagnostics").textContent=
    `${fname(name)}\n根类型：${res.root_type}\n顶层字段：${res.top_keys.slice(0,16).join(", ")||"(无)"}\n`+
    `检查节点：${fmt(res.nodes_visited)}；疑似矩形：${rects.length}\n`+
    `动画相关字段提示：${Object.entries(res.keyword_hits||{}).map(([k,v])=>k+"="+v).join(", ")||"无"}\n`+
    (res.truncated?"已达到安全扫描上限；":"")+res.note;
  const inbounds=rects.filter(r=>r.x>=0&&r.y>=0&&r.x+r.w<=atlasImg.naturalWidth&&r.y+r.h<=atlasImg.naturalHeight);
  $("rectList").innerHTML=inbounds.slice(0,70).map((r,i)=>
    `<button class="rect-item" data-rect="${i}">${esc(r.json_path)} · (${r.x},${r.y},${r.w},${r.h})</button>`).join("")+
    (inbounds.length===0?`<div class="muted small">没有发现当前图集范围内的标准矩形字段。可继续手动裁剪。</div>`:"");
  $("rectList").querySelectorAll("[data-rect]").forEach(b=>b.onclick=()=>{
    const r=inbounds[Number(b.dataset.rect)];
    setCrop(r);
    const viewport=$("atlasViewport");
    viewport.scrollLeft=Math.max(0,r.x*zoom-100);viewport.scrollTop=Math.max(0,r.y*zoom-50);
  });
 }catch(e){$("jsonDiagnostics").textContent="分析失败："+e.message;}
}
$("inspectJson").onclick=inspectJSON;
$("generateScene").onclick=async()=>{
 let sceneId=$("sceneId").value.trim(),prompt=$("scenePrompt").value.trim();
 if(!prompt)return toast("请输入绘图描述");
 const node=$("generateStatus");node.textContent="正在请求绘图 API 或查找缓存...";
 $("generateScene").disabled=true;
 try{
  const result=await api("/api/generate_scene",{scene:sceneId,prompt});
  manifest.scenes[sceneId]=result.ref;
  renderSceneBindings();setScene(sceneId);
  node.textContent=result.cached?"已复用本地缓存，不产生新的绘图请求。":"已生成并保存 PNG 到本地缓存。";
  toast(node.textContent);
 }catch(e){node.textContent="失败："+e.message;toast(e.message);}
 finally{$("generateScene").disabled=false;}
};
function fillSettings(){
 const mapping={
  cfgMode:"llm_mode",cfgLlmUrl:"llm_url",cfgLlmModel:"llm_model",cfgTtsProvider:"tts_provider",cfgQwenDir:"qwen_model_dir",
  cfgRoleName:"role_name",cfgPersona:"persona",cfgTtsUrl:"tts_url",
  cfgRefAudio:"tts_ref_audio",cfgTextLang:"tts_text_lang",
  cfgPromptText:"tts_prompt_text",cfgPromptLang:"tts_prompt_lang",
  cfgAsrPath:"asr_model_path",cfgAsrLang:"asr_language",
  cfgImageUrl:"image_url",cfgImageModel:"image_model",cfgAssetsDir:"assets_dir"};
 for(const [dom,key] of Object.entries(mapping))$(dom).value=settings[key]??"";
 $("cfgTts").checked=!!settings.tts_enabled;
 $("cfgStt").checked=!!settings.stt_enabled;
 $("cfgMemoryLLM").checked=settings.memory_enabled_for_llm!==false;
}
$("openSettings").onclick=()=>{fillSettings();$("settingsOverlay").classList.remove("hidden");};
$("cfgMode").onchange=()=>{if($("cfgMode").value==="deepseek"){$("cfgLlmUrl").value="https://api.deepseek.com";$("cfgLlmModel").value="deepseek-flash";}};
$("closeSettings").onclick=()=>$("settingsOverlay").classList.add("hidden");
$("settingsOverlay").addEventListener("click",e=>{if(e.target===$("settingsOverlay"))$("closeSettings").click();});
$("saveSettings").onclick=async()=>{
 const fields={
  cfgMode:"llm_mode",cfgLlmUrl:"llm_url",cfgLlmModel:"llm_model",cfgTtsProvider:"tts_provider",cfgQwenDir:"qwen_model_dir",
  cfgRoleName:"role_name",cfgPersona:"persona",cfgTtsUrl:"tts_url",
  cfgRefAudio:"tts_ref_audio",cfgTextLang:"tts_text_lang",
  cfgPromptText:"tts_prompt_text",cfgPromptLang:"tts_prompt_lang",
  cfgAsrPath:"asr_model_path",cfgAsrLang:"asr_language",
  cfgImageUrl:"image_url",cfgImageModel:"image_model",cfgAssetsDir:"assets_dir"};
 let obj={
  tts_enabled:$("cfgTts").checked,
  stt_enabled:$("cfgStt").checked,
  memory_enabled_for_llm:$("cfgMemoryLLM").checked
 };
 for(const [dom,key] of Object.entries(fields))obj[key]=$(dom).value.trim();
 try{
  const old=settings.assets_dir;
  await window.gameExperience?.cancelPending();
  await chatStream.cancel();await $("cancelRuntime").onclick();
  const result=await api("/api/settings",obj);settings=result.settings;
  $("settingsOverlay").classList.add("hidden");setEngine();toast("设置已保存");
  if(old!==settings.assets_dir){
    atlasRef="";imageCache.clear();
    await refreshAssets();await refreshBackgroundLibrary(true);
  }
 }catch(e){toast("保存失败："+e.message);}
};
$("refreshBtn").onclick=async()=>{
 await refreshAssets();await refreshBackgroundLibrary(true);
 toast("已刷新角色素材与背景图库");
};
const emotionTimeline={
  neutral:"普通Ａ",happy:"笑顔Ａ",gentle:"微笑みＡ",shy:"照れＡ",
  sleepy:"目下閉じＡ",surprised:"驚きＡ",sad:"悲しみＡ"
};
function selectedTimelineEntry(){
 return timelineCatalog.find(x=>x.label===$("expressionSelect").value);
}
function updateFrameSelector(){
 const item=selectedTimelineEntry();
 syncBehaviorTagsForSelectedMotion();
 const isMotion=item?.type==="motion";
 $("expressionFrameBox").classList.toggle("hidden",!isMotion);
 const max=Math.max(0,Math.round(item?.duration||0));
 $("expressionFrame").max=String(Math.min(max,600));
 $("expressionFrameMax").textContent=String(max);
 const sample=isMotion?String(Math.round(Math.min(max,600)/2)):"0";
 $("expressionFrame").value=sample;
 $("expressionFrameValue").textContent=sample;
}
function renderTimelineOptions(){
 const select=$("expressionSelect"),search=$("expressionSearch").value.trim().toLowerCase();
 const selected=select.value;
 const rows=timelineCatalog.filter(x=>x.type===timelineGroup
    &&x.label.toLowerCase().includes(search));
 select.replaceChildren();
 for(const p of rows){
  const option=document.createElement("option");
  option.value=p.label;
  option.textContent=p.label+(p.type==="motion"?" · "+Math.round(p.duration)+"f":"");
  select.append(option);
 }
 if(rows.some(x=>x.label===selected))select.value=selected;
 else if(rows.length)select.value=rows[0].label;
 updateFrameSelector();
}
$("expressionFaces").onclick=()=>{
 timelineGroup="face";$("expressionFaces").classList.add("active");
 $("expressionMotions").classList.remove("active");renderTimelineOptions();
};
$("expressionMotions").onclick=()=>{
 timelineGroup="motion";$("expressionMotions").classList.add("active");
 $("expressionFaces").classList.remove("active");renderTimelineOptions();
};
$("expressionSearch").oninput=renderTimelineOptions;
$("expressionSelect").onchange=updateFrameSelector;
$("expressionFrame").oninput=()=>
  $("expressionFrameValue").textContent=$("expressionFrame").value;
function syncBehaviorTagsForSelectedMotion(){
 const selected=selectedTimelineEntry();
 const binding=behaviorCatalog.entries.find(x=>x.label===selected?.label
                              &&x.type==="motion");
 const input=$("behaviorTagInput");
 if(!binding){
   input.value="";
   input.disabled=true;
   $("saveBehaviorTags").disabled=true;
   $("behaviorTagStatus").textContent="先选「动作时间轴」中的真实动作";
   return;
 }
 input.disabled=false;
 $("saveBehaviorTags").disabled=false;
 input.value=(binding.tags||[]).join(", ");
 $("behaviorTagStatus").textContent=binding.tag_source==="manual"
   ?"当前为人工确认标签":"当前为建议标签，保存后将成为人工配置";
}
function fillBehaviorEmotionOptions(){
 const existing=$("behaviorEmotionSelect").value;
 $("behaviorEmotionSelect").replaceChildren();
 for(const code of behaviorCatalog.emotions){
   const option=document.createElement("option");
   option.value=code;option.textContent=`${moodLabels[code]||code} (${code})`;
   $("behaviorEmotionSelect").append(option);
 }
 if(behaviorCatalog.emotions.includes(existing)){
   $("behaviorEmotionSelect").value=existing;
 }
 const target=$("behaviorExpressionTarget");
 target.replaceChildren();
 for(const item of behaviorCatalog.entries.filter(x=>x.type==="face")){
   const option=document.createElement("option");
   option.value=item.label;option.textContent=item.label;
   target.append(option);
 }
}
async function refreshBehaviorCatalog(){
 try{
   behaviorCatalog=await api("/api/behavior_catalog");
   fillBehaviorEmotionOptions();
   syncBehaviorTagsForSelectedMotion();
 }catch(error){
   $("behaviorTagStatus").textContent="标签列表读取失败："+error.message;
 }
}
async function refreshTimelines(){
 const result=await api("/api/expression_catalog");
 timelineCatalog=result.presets||[];
 $("expressionCount").textContent=
  `${result.model} · ${result.faces} 套面部表情 · ${result.motions} 套动作预设`;
 renderTimelineOptions();
 await refreshBehaviorCatalog();
 return result;
}
$("saveBehaviorTags").onclick=async()=>{
 const selected=selectedTimelineEntry();
 if(!selected||selected.type!=="motion")return toast("请选择当前模型中的动作预设");
 const text=$("behaviorTagInput").value;
 const tags=text.split(",").map(x=>x.trim().toLowerCase()).filter(Boolean);
 try{
  const result=await api("/api/behavior_tags",{
     label:selected.label,tags,
     sample_time:Math.min(Number($("expressionFrame").value)||0,600)
  });
  await refreshBehaviorCatalog();
  $("behaviorTagStatus").textContent="已保存："+selected.label+" → "+result.tags.join(", ");
  toast("PSB 动作标签已写入本机配置");
 }catch(error){toast(error.message);$("behaviorTagStatus").textContent=error.message;}
};
$("saveEmotionBinding").onclick=async()=>{
 const emotion=$("behaviorEmotionSelect").value;
 const label=$("behaviorExpressionTarget").value;
 if(!label)return toast("还没有可用面部预设");
 try{
   await api("/api/behavior_expression",{emotion,label});
   toast(`${emotion} 已绑定到 ${label}`);
 }catch(error){toast("保存情绪映射失败："+error.message);}
};
async function applyTimeline(label,frame=0){
 if(!timelineCatalog.some(x=>x.label===label)){
   return null;
 }
 const serial=++expressionRequest;
 stopNodPlayback();
 const stat=$("expressionStatus");
 stat.textContent=`正在计算 ${label}，第 ${frame} 帧的角色表情和嘴型...`;
 try{
  await cancelBodyForManual();
  if(serial!==expressionRequest)return null;
  const result=await api("/api/expression_apply",{label,time:frame});
  if(serial!==expressionRequest)return null; // fast-click races must not reset the newer pose
  activeExpression=result;
  stat.textContent=`${label} · 第 ${frame} 帧已加载；`
   +(result.type==="motion"?"动作静态采样，非连续原版动画。":"闭眼与说话均保留此表情的其他参数。");
  toast("已应用 E-mote "+label);
  return result;
 }catch(error){
  if(serial===expressionRequest){
   stat.textContent="生成失败："+error.message;toast(error.message);
  }
  return null;
 }
}
async function applyMoodTimeline(emotion){
 const label=emotionTimeline[emotion]||"普通Ａ";
 return applyTimeline(label,0);
}
$("applyExpression").onclick=async()=>{
 const item=selectedTimelineEntry();
 if(!item)return toast("请先选一个表情");
 return applyTimeline(item.label,item.type==="motion"
  ? Number($("expressionFrame").value):0);
};
$("sampleExpressionFrame").onclick=()=>{
 const item=selectedTimelineEntry();
 if(item)return applyTimeline(item.label,Number($("expressionFrame").value));
};
$("reloadExpressionList").onclick=async()=>{
 try{await refreshTimelines();toast("已重新读取实际角色预设");}
 catch(error){toast(error.message);}
};

function stopNodPlayback(){
 sequenceRenderer.stop();
 if(nodRuntimeToken!==null)runtimeEvent("motion_ended",{token:nodRuntimeToken});
 nodRuntimeToken=null;
}
async function cancelBodyForManual(){
 const state=await runtimeEvent("cancel",{reason:"manual_preview",keep_speech:true});
 runtimeActionToken=Number(state.action_token||runtimeActionToken);
}
async function previewNod(expressionOverride=null){
 const selected=selectedTimelineEntry();
 const expression=expressionOverride||(selected?.type==="face"?selected.label:activeExpression?.label||"普通Ａ");
 const serial=++expressionRequest;
 stopNodPlayback();nodSequence=null;
 $("reviewNod").disabled=true;$("reviewNod").checked=false;
 const button=$("previewNod");button.disabled=true;
 try{
  await cancelBodyForManual();
  if(serial!==expressionRequest)return;
  let job=await api("/api/motion_sequence",{expression});
  while(job.state==="rendering"){
   $("nodStatus").textContent=`正在生成真实网格帧 ${Math.round(job.progress*100)}% · 可以停止等待`;
   await new Promise(resolve=>setTimeout(resolve,700));
   if(serial!==expressionRequest)return;
   job=await api("/api/motion_sequence",{expression,cached_only:true});
  }
  if(serial!==expressionRequest)return;
  if(job.state!=="ready")throw Error(job.error||"动作没有生成有效画面");
  const clip=job.sequence;nodSequence=clip;
  const started=await sequenceRenderer.play(clip);
  if(serial!==expressionRequest){if(started&&sequenceRenderer.clip===clip)sequenceRenderer.stop();return;}
  $("reviewNod").disabled=false;$("reviewNod").checked=nodSequence.reviewed;
  $("nodStatus").textContent=`${nodSequence.frame_count} 帧 · ${nodSequence.distinct_visual_frames} 个不同画面 · 24 FPS · ${nodSequence.expression}`;
 }catch(error){$("nodStatus").textContent="点头预览失败："+error.message;}
 finally{button.disabled=false;}
}
$("previewNod").onclick=()=>previewNod();
$("stopNod").onclick=()=>{
 ++expressionRequest;stopNodPlayback();
 if(nodSequence)activeExpression={label:nodSequence.expression,refs:nodSequence.settled_refs};
 $("nodStatus").textContent="已停止，保持当前面部表情。";
};
$("testNodMouth").onclick=()=>{nodMouthUntil=performance.now()+2000;};
$("reviewNod").onchange=async()=>{
 if(!nodSequence)return;
 try{
  const result=await api("/api/motion_review",{expression:nodSequence.expression,
    id:nodSequence.id,reviewed:$("reviewNod").checked,cached_only:true});
  nodSequence=result.sequence;
  $("nodStatus").textContent=nodSequence.reviewed?"当前表情的点头已允许用于对话。":"已取消对话使用，仍可手动预览。";
 }catch(error){$("reviewNod").checked=false;toast(error.message);}
};
async function refreshCharacterModels(){
  const combo=$("characterModelSelect"),status=$("characterModelStatus");
  try{
    const result=await api("/api/character_models");
    const prev=combo.value;
    combo.replaceChildren();
    for(const model of result.models){
      const option=document.createElement("option");
      option.value=model.name;
      option.textContent=model.label;
      option.disabled=!model.available;
      combo.append(option);
    }
    const match=[...combo.options].find(x=>x.value===(prev||result.selected) && !x.disabled)
       || [...combo.options].find(x=>x.value===result.selected && !x.disabled)
       || [...combo.options].find(x=>!x.disabled);
    if(match){combo.value=match.value;}
    else {
      const option=document.createElement("option");
      option.value="";option.textContent="没有完整的角色模型解包";
      combo.append(option);combo.value="";
    }
    status.textContent=`已找到 ${result.models.length} 套模型，服装类型需实际预览。`;
    $("applyCharacterModel").disabled=!match;
  }catch(err){
    status.textContent="查询造型失败："+err.message;
    $("applyCharacterModel").disabled=true;
  }
}
$("applyCharacterModel").onclick=async()=>{
  const model=$("characterModelSelect").value;
  if(!model)return toast("请先解出目标角色模型的 JSON 和纹理");
  const button=$("applyCharacterModel"),status=$("characterModelStatus");
  button.disabled=true;status.textContent="正在计算所选模型的角色部件和表情，请稍候...";
  try{
    const result=await api("/api/character_model",{name:model});
    manifest=result.manifest;
    settings.character_model=result.selected;
    imageCache.clear();
    atlasRef="";
    selectedLayer="";
    renderLayers();
    renderEvents();renderSceneBindings();
    setMood("neutral");setAction("idle");
    activeExpression=null;
    await refreshAssets();
    await refreshTimelines();
    await applyTimeline("普通Ａ",0);
    await refreshSystemPanel();
    status.textContent=`已加载 ${result.selected}。请看人物服装是否符合需要。`;
    toast(result.message);
  }catch(error){
    status.textContent="加载失败："+error.message;
    toast(error.message);
  }finally{
    button.disabled=false;
  }
};
$("cancelRuntime").onclick=async()=>{
 ++speechGeneration;speechFetch?.abort();speechFetch=null;
 if(window.speechSynthesis)speechSynthesis.cancel();
 if(systemSpeechFinish)systemSpeechFinish();
 ++expressionRequest;stopNodPlayback();
 if(currentAudio){
   const audio=currentAudio;
   if(typeof audio._characterFinish==="function")await audio._characterFinish();
   audio.pause();audio.src="";currentAudio=null;
 }
 playing=false;volume=0;setAction("idle");
 await runtimeEvent("cancel",{reason:"manual_stop"});
 toast("已停止当前角色运行状态");
};
$("unlockScene").onclick=async()=>{
 await runtimeEvent("scene_unlock");
 toast("已解除手动场景锁");
 if(settings.auto_scene)applyAutoScene(true);
};
$("saveModelMetadata").onclick=async()=>{
 const model=settings.character_model||$("characterModelSelect").value;
 if(!model)return toast("请先加载角色模型");
 try{
  const result=await api("/api/model_metadata",{model,record:{
    display_name:$("modelDisplayName").value.trim(),
    outfit:$("modelOutfitTag").value.trim().toLowerCase(),
    pose_family:$("modelPoseFamily").value.trim().toLowerCase(),
    verified:$("modelVerified").checked,
    notes:$("modelMetaNotes").value.trim()
  }});
  $("modelMetadataStatus").textContent=`${model} 元数据已保存${result.record.verified?" · 已人工确认":""}`;
  await refreshCharacterModels();
  toast("模型服装/动作家族元数据已保存");
 }catch(error){toast("保存模型元数据失败："+error.message);}
};
$("exportBehaviorConfig").onclick=async()=>{
 try{
  const data=await api("/api/behavior_export");
  const blob=new Blob([JSON.stringify(data,null,2)],{type:"application/json"});
  const url=URL.createObjectURL(blob),a=document.createElement("a");
  a.href=url;a.download="CharacterStudio_animation_tags.json";
  document.body.append(a);a.click();a.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
  $("behaviorConfigStatus").textContent="已导出标签 JSON；不包含游戏素材或聊天记录。";
 }catch(error){toast(error.message);}
};
$("importBehaviorConfig").onclick=()=>$("behaviorImportFile").click();
$("behaviorImportFile").onchange=async()=>{
 const file=$("behaviorImportFile").files[0];
 if(!file)return;
 try{
  if(file.size>1024*1024)throw Error("标签 JSON 不能超过 1MB");
  const parsed=JSON.parse(await file.text());
  const result=await api("/api/behavior_import",{library:parsed,mode:"merge"});
  $("behaviorConfigStatus").textContent="导入完成；旧配置已自动备份。"+(result.backup?` 备份：${result.backup}`:"");
  await refreshBehaviorCatalog();
  toast("动作标签已合并");
 }catch(error){toast("导入失败："+error.message);}
 finally{$("behaviorImportFile").value="";}
};
async function refreshLogs(){
 try{
  const result=await api("/api/log_tail");
  $("runtimeLogs").textContent=(result.lines||[]).join("\n")||"当前还没有运行日志。";
 }catch(error){$("runtimeLogs").textContent="读取日志失败："+error.message;}
}
$("refreshLogs").onclick=refreshLogs;
$("runDiagnostics").onclick=async()=>{
 const box=$("diagnosticsPanel");box.textContent="正在检查本机环境...";
 try{
  const report=await api("/api/diagnostics");
  box.textContent=report.items.map(item=>
    `[${item.severity.toUpperCase()}] ${item.label}: ${item.detail}`).join("\n")
    +`\n\nerrors=${report.errors} warnings=${report.warnings}\n${report.note}`;
  await refreshLogs();
 }catch(error){box.textContent="诊断失败："+error.message;}
};
setInterval(refreshRuntimeState,5000);

async function start(){
 let ready=false;
 try{
  const state=await api("/api/state");
  activeRoleName=state.roleplay?.name||"";
  settings=state.settings;manifest=state.manifest;
  setEngine();renderLayers();renderEvents();renderSceneBindings();
  $("backgroundAutoTime").checked=!!settings.auto_scene;
  await refreshSystemPanel();
  (state.history||[]).forEach(x=>appendBubble(x.content,x.role,x.source==="demo"?"演示回复":null));
  if(!(state.history||[]).length)
    appendBubble("桌面版已启动。人物请选 kan_10 等完整模型；背景可在「背景」页从本机导入，并绑定白天、傍晚和夜晚场景。AI 默认是演示模式。","assistant","系统引导");
  await refreshAssets();
  await refreshCharacterModels();
  try{
    await refreshTimelines();
    await applyTimeline("普通Ａ",0);
  }catch(error){
    $("expressionStatus").textContent="尚未装入模型："+error.message;
  }
  await refreshBackgroundLibrary();
  if(settings.auto_scene)applyAutoScene(true);
  if(!settings.assets_dir)toast("请先选择 PsbDecompile 解出的 PNG/JSON 文件夹");
  checkEvents();
  ready=true;
 }catch(e){toast("初始化失败："+e.message);setStatus("启动失败");}
 finally{
  booting=!ready;
  $("chatInput").disabled=!ready;$("sendBtn").disabled=!ready;
  $("previewNod").disabled=!ready;
  if(ready)window.gameExperience?.ready();
 }
}

// Adapter used by the game presentation; all expressions still pass through
// the backend's semantic resolver and constrained local renderer API.
const gameExpressionCache=new Map();
function loadGameExpression(plan){
 const label=plan.expression?.label;
 if(!label)return Promise.reject(Error("当前造型缺少对应表情，请在设置中选择完整角色。"));
 const model=settings.character_model;
 const key=model+"\0"+label;
 if(gameExpressionCache.has(key))return gameExpressionCache.get(key);
 const promise=api("/api/expression_apply",{label,time:0}).then(async result=>{
  if(result.model!==model)throw Error("角色造型已更换，请重新开始这段对话。");
  await Promise.all(Object.values(result.refs).map(ref=>new Promise((resolve,reject)=>{
   const image=new Image();image.onload=()=>{image._ready=true;imageCache.set(ref,image);resolve();};
   image.onerror=()=>reject(Error("角色表情图片未能加载"));image.src=imgURL(ref);
  })));
  return result;
 }).catch(error=>{gameExpressionCache.delete(key);throw error;});
 gameExpressionCache.set(key,promise);return promise;
}
window.GameBridge={
 async profileChanged(){
  const state=await api('/api/state');
  activeRoleName=state.roleplay?.name||"";
  $("chatMessages").replaceChildren();
  for(const item of state.history||[])appendBubble(item.content,item.role,item.source==="demo"?"演示回复":null);
  await refreshSystemPanel();
 },
 get ready(){return !booting;},
 get model(){return settings.character_model;},
 get speaker(){const name=roleDisplayName();return name!=="角色"?name:"她";},
 emotionLabel:emotion=>moodLabels[emotion]||emotion,
 get demo(){return settings.llm_mode==="demo";},
 chat:(text,onText)=>chatStream.send(text,onText),
 activateSegment:(turnId,index)=>api('/api/chat_segment',{turn_id:turnId,index}),
 prepareSegment:segment=>loadGameExpression(segment.behavior),
 async cancelChat(){await chatStream.cancel();},
 speak,
 textSpeech(active){textMouthUntil=active?performance.now()+180:0;},
 async applyChat(result,isCurrent){
  if(!isCurrent())return;
  const rendered=await loadGameExpression(result.behavior);
  if(!isCurrent())return;
  ++expressionRequest;stopNodPlayback();activeExpression=rendered;
  setMood(result.emotion);setAction("idle");
  if(result.runtime){runtimeState=result.runtime;runtimeActionToken=Number(result.runtime.action_token||runtimeActionToken);}
  if(result.scene)setScene(result.scene,"ai");
  if(result.behavior.motion)await applyBehaviorPlan(result.behavior);
 },
 async apply(plan,isCurrent){
  const rendered=await loadGameExpression(plan);
  if(!isCurrent())return;
  ++expressionRequest;stopNodPlayback();selectedLayer="";
  activeExpression=rendered;setMood(plan.emotion);setAction("idle");
 },
 warm:plan=>loadGameExpression(plan).catch(()=>null),
 async stopSpeech(){textMouthUntil=0;await $("cancelRuntime").onclick();},
 async applyVerifiedScene(asset,loaded){
  if(!asset){verifiedSceneImage=null;return;}
  const item=loaded.find(x=>x.asset_id===asset.asset_id);
  if(!item?.image)throw Error('已审背景未预加载');
  verifiedSceneImage=item.image;
 },
 touchCoordinates(event){
  const layer=manifest.layers.find(x=>['__auto_emote_character','__auto_emote_kan'].includes(x.id));
  if(!layer||!layer.visible||activeExpression?.motion||nodRuntimeToken!==null)return null;
  return GameplayStage.toLocal({clientX:event.clientX,clientY:event.clientY,rect:stage.getBoundingClientRect(),canvasWidth:W,canvasHeight:H,layer,mirror:characterMirror});
 },
 mirror(value){characterMirror=!!value;},
 location(slot){
  verifiedSceneImage=null;
  gameBackdrop=slot;
  const available=Object.keys(manifest.scenes);
  const key=available.includes(slot)?slot:slot==="evening"&&available.includes("day")?"day":available[0];
  if(key)setScene(key,"manual");
 },
 scenes:()=>Object.keys(manifest.scenes).map(id=>({id,title:({day:"白天",evening:"傍晚",night:"夜晚"})[id]||id})),
 async models(){return (await api("/api/character_models")).models.filter(item=>item.available);},
 async changeModel(model){
  const result=await api("/api/character_model",{name:model});
  manifest=result.manifest;settings.character_model=result.selected;
  activeExpression=null;imageCache.clear();gameExpressionCache.clear();
  await refreshTimelines();renderLayers();
 },
 mode(game){
  gameMode=game;document.body.classList.toggle("game-mode",game);
  const url=new URL(location.href);url.searchParams.set("mode",game?"game":"studio");
  history.replaceState(null,"",url);selectedLayer="";
 },
 connections(){fillSettings();$("settingsOverlay").classList.remove("hidden");},
};
start();
