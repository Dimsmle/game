/* Game presentation: silent authored dialogue, expression tags and modal choices. */
"use strict";
(function(){
 const el=id=>document.getElementById(id);
 const bridge=window.GameBridge;
 let scenarios=[],selectedStory=null,currentNode=null,textTimer=null,shown=0,typingText="";
 let warmGeneration=0,ready=false,chatMode=false,chatGeneration=0,chatBusy=false;
 let revealStream=false,textKind='dialogue';
 function paintText(text){
  const node=el('gameText');node.classList.toggle('is-narration',textKind==='narration');
  if(!ReplyPlayer.textParts){node.textContent=text;return;}
  node.replaceChildren(...ReplyPlayer.textParts(text).map(part=>{const span=document.createElement('span');span.textContent=part.text;if(part.action)span.className='dialogue-action';return span;}));
 }
 const gameplayEnabled=typeof GameplayStage!=='undefined';
 let gameplayController=null,closeGameplayMedia=null,cgEventController=null;
 const picker=el("gamePicker"),menu=el("gameMenu"),choice=el("gameChoice");
 const request=async(path,data)=>{
  const response=await fetch(path,data===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});
  const value=await response.json();if(!response.ok)throw Error(value.error||"无法准备这段对话");return value;
 };
 function showDialog(dialog){if(!dialog.open)dialog.showModal();}
 function closeDialogs(){for(const dialog of [picker,menu,choice])if(dialog.open)dialog.close();}
 function setBusy(value){
  // Keep the previous face visible; preparation must not cover the stage.
  el("gameLoading").classList.remove("visible");
  el("gameDialogue").setAttribute("aria-busy",String(value));
  if(value){clearInterval(textTimer);bridge.textSpeech(false);}
 }
 function showText(full){
  clearInterval(textTimer);typingText=full;shown=0;el("gameText").textContent="";
  textTimer=setInterval(()=>{
   shown=Math.min(full.length,shown+1);paintText(full.slice(0,shown));
   bridge.textSpeech(textKind!=='narration'&&shown<full.length);
   if(shown===full.length){clearInterval(textTimer);maybeCompleteTurn();}
  },27);
 }
 function finishText(){clearInterval(textTimer);bridge.textSpeech(false);shown=typingText.length;paintText(typingText);maybeCompleteTurn();}
 function streamText(preview,kind='dialogue'){
  textKind=kind;el('gameSpeaker').textContent=kind==='narration'?'旁白':bridge.speaker;
  if(!preview.startsWith(typingText)){shown=0;el("gameText").textContent="";}
  typingText=preview;
  if(revealStream){finishText();return;}
  clearInterval(textTimer);
  textTimer=setInterval(()=>{
   if(shown<typingText.length){shown++;paintText(typingText.slice(0,shown));bridge.textSpeech(textKind!=='narration');}
   else {clearInterval(textTimer);bridge.textSpeech(false);}
  },27);
 }
 function setOptions(container,options){
  container.replaceChildren();
  for(const item of options){
   const button=document.createElement("button");button.type="button";
   const title=document.createElement("strong");title.textContent=item.title;button.append(title);
   if(item.description){const description=document.createElement("span");description.textContent=item.description;button.append(description);}
   button.onclick=item.action;container.append(button);
  }
 }
 const director=new DialoguePlayer({
  async prepare(node,isCurrent){
   if(currentNode?.scene!==node.scene){
    el("gameCurtain").classList.add("fading");
   }
   await bridge.apply(node.behavior,isCurrent);
   if(!isCurrent())return;
   bridge.location(node.scene);el("gamePlace").textContent=node.place;
   el("gameCurtain").classList.remove("fading");
  },
  onState(state){
   setBusy(state.loading);el("gameNext").disabled=state.loading;
   if(state.error){
    el("gameCurtain").classList.remove("fading");el("gameText").textContent=state.error.message;
    el("gameHint").textContent="画面准备失败，可重试或打开设置";el("gameNext").textContent="重试 ↻";return;
   }
   if(state.loading||!state.current)return;
   if(state.current!==currentNode){
    currentNode=state.current;
    el("gameSpeaker").textContent=bridge.speaker;
    el("gameEmotion").textContent=bridge.emotionLabel(currentNode.emotion);
    el("gameHint").textContent="无语音 · 点击对话框或按空格继续";
    el("gameNext").textContent=currentNode.choices?.length?"回应 ▷":currentNode.next?"继续 ▷":"结束这一段 ▷";
    textKind='dialogue';showText(currentNode.text);
   }
   if(state.choosing){
    finishText();
    setOptions(el("gameChoiceOptions"),currentNode.choices.map((item,index)=>({title:item.text,action:()=>{
     choice.close();director.choose(index);
    }})));
    showDialog(choice);
   }
  }
 });
 const replyPlayer=new ReplyPlayer({
  async prepare(turn,index,isCurrent){
   if(turn.segments[index].kind!=='narration')await bridge.prepareSegment(turn.segments[index]);
   if(!isCurrent())return null;
   const value=await bridge.activateSegment(turn.turn_id,index);
   if(isCurrent()&&value.kind!=='narration')await bridge.applyChat(value,isCurrent);
   return value;
  },
  show(value,index,count){
   textKind=value.kind||'dialogue';el("gameSpeaker").textContent=textKind==='narration'?'旁白':bridge.speaker;
   el("gameEmotion").textContent=bridge.emotionLabel(value.emotion);
   const alreadyVisible=index===0&&el("gameText").textContent===value.speech;
   if(alreadyVisible){typingText=value.speech;finishText();}else showText(value.speech);
   el("gameHint").textContent=(value.source==="demo"?"离线演示 · ":"")+`${index+1}/${count} · 每句话独立表情`;
  },
  speak:text=>bridge.speak(text),stopSpeech:()=>bridge.stopSpeech(),
  onState(state){
   if(!chatMode)return;
   setBusy(state.loading);el("gameNext").hidden=!state.turn;
   el("gameNext").disabled=state.loading||(!state.hasNext&&!state.speaking&&!state.error);
   el("gameNext").textContent=state.error&&!state.error.voice?"重试这一句 ↻":!state.hasNext&&(state.speaking||state.error?.voice)?"跳过语音 ▷":state.hasNext?"下一句 ▷":"本轮已读完";
   if(state.error)el("gameHint").textContent=(state.error.voice?"语音暂不可用 · ":"本句准备失败 · ")+state.error.message;
   maybeCompleteTurn();
  }
 });
 function maybeCompleteTurn(){
  if(!gameplayController||!chatMode||shown<typingText.length)return;
  const state=replyPlayer.snapshot();
  if(!state.turn||state.loading||state.hasNext||state.speaking||!state.voiceSettled)return;
  gameplayController.complete(state.turn).catch(error=>{el('gameHint').textContent=error.message;});
 }
 async function advance(){
  if(chatMode){
   if(chatBusy&&!replyPlayer.turn){revealStream=true;finishText();return;}
   if(replyPlayer.loading)return;
   if((!replyPlayer.error||replyPlayer.error.voice)&&shown<typingText.length){finishText();return;}
   if(!replyPlayer.snapshot().hasNext&&(replyPlayer.speaking||replyPlayer.error?.voice)){await replyPlayer.skipVoice();return;}
   await replyPlayer.next();return;
  }
  if(director.loading)return;
  if(director.error){await director.retry();return;}
  if(shown<typingText.length){finishText();return;}
  if(!currentNode)return openStories();
  if(!currentNode.next&&!currentNode.choices?.length){
   el("gameHint").textContent="这一段结束了 · 可以体验另一种回应";
   return openStories();
  }
  await director.advance();
 }
 async function startStory(id){
  const generation=++warmGeneration;
  replyPlayer.stop();
  chatMode=false;el("gameChatForm").hidden=true;el("gameNext").hidden=false;
  ++chatGeneration;await bridge.cancelChat();
  if(generation!==warmGeneration)return;
  closeDialogs();director.stop();currentNode=null;clearInterval(textTimer);finishText();setBusy(true);
  selectedStory=id;
  try{
   await bridge.stopSpeech();
   if(generation!==warmGeneration)return;
   const scene=await request("/api/demo_scene",{id});
   if(generation!==warmGeneration)return;
   el("gameSceneTitle").textContent=scene.title;
   await director.start(scene);
   // Warm future facial states after the opening line, without changing the screen.
   const labels=new Set();
   for(const node of scene.nodes){
    if(generation!==warmGeneration)break;
    const label=node.behavior.expression?.label;
    if(label&&!labels.has(label)){labels.add(label);await bridge.warm(node.behavior);}
   }
  }catch(error){
   if(generation!==warmGeneration)return;
   setBusy(false);el("gameText").textContent=error.message;
   el("gameHint").textContent="请在设置中选择完整角色后重试";
   el("gameNext").disabled=false;
  }
 }
 async function openStories(){
  const generation=++warmGeneration;
  menu.close();choice.close();
  el("gamePickerEyebrow").textContent="无声的小片段";
  el("gamePickerTitle").textContent="今天，从哪一段开始？";
  el("gamePickerNote").textContent="每句话都有对应表情；点击继续，在选项处决定如何回应。";
  try{
   if(!scenarios.length)scenarios=(await request("/api/demo_scenes")).scenes;
   if(generation!==warmGeneration)return;
   setOptions(el("gamePickerOptions"),[
    {title:"自由聊天",description:bridge.demo?"输入“演示逐句表情”体验切换，或在设置里连接 DeepSeek。":"和她说说今天的事。",action:openChat},
    ...scenarios.map(item=>({title:item.title,description:item.description,action:()=>startStory(item.id)}))]);
   showDialog(picker);
  }catch(error){el("gameText").textContent=error.message;}
 }
 async function openLocations(){
  ++warmGeneration;
  menu.close();el("gamePickerEyebrow").textContent="让画面换一种心情";
  if(gameplayController){
   await stopChat();
   try{
    const result=await request('/api/game/locations');
    el('gamePickerTitle').textContent='场景地点';el('gamePickerNote').textContent=result.items.length?'选择地点后进入对应背景。':'请先在「场景与CG事件」给背景填写地点名称。';
    setOptions(el('gamePickerOptions'),result.items.flatMap(item=>item.times.map(period=>({title:item.display_name+' · '+({morning:'早晨',day:'白天',evening:'傍晚',night:'夜间',unknown:'未标时段'}[period]||period),action:async()=>{
     try{await gameplayController.transition('scene',{location_id:item.location_id,time_of_day:period});picker.close();el('gamePlace').textContent=item.display_name;}
     catch(error){el('gamePickerNote').textContent=error.message;}
    }}))));showDialog(picker);
   }catch(error){el('gameHint').textContent=error.message;}
   return;
  }
  el("gamePickerTitle").textContent="切换场景";
  el("gamePickerNote").textContent="已绑定的背景会直接显示；未绑定时使用程序内置的氛围场景。";
  const options=bridge.scenes();
  if(!options.some(item=>item.id==="evening"))options.splice(1,0,{id:"evening",title:"傍晚"});
  setOptions(el("gamePickerOptions"),options.map(item=>({title:item.title,action:()=>{
   picker.close();bridge.location(item.id);el("gamePlace").textContent=item.title;
  }})));
  showDialog(picker);
 }
 async function openOutfits(){
  const generation=++warmGeneration;
  menu.close();el("gamePickerEyebrow").textContent="选择本机已有的角色造型";
  el("gamePickerTitle").textContent="角色造型";
  el("gamePickerNote").textContent="造型名称来自本机登记；切换后重新开始当前片段。";
  setOptions(el("gamePickerOptions"),[{title:"正在读取…",action:()=>{}}]);showDialog(picker);
  try{
   const models=await bridge.models();
   if(generation!==warmGeneration)return;
   setOptions(el("gamePickerOptions"),models.map(model=>({title:model.label,action:async()=>{
    const generation=++warmGeneration;
    await stopChat();
    if(generation!==warmGeneration)return;
    picker.close();director.stop();setBusy(true);
    try{cgEventController?.cancel();await bridge.changeModel(model.name);if(generation!==warmGeneration)return;if(chatMode)await openChat();else await startStory(selectedStory||"promise");}
    catch(error){if(generation===warmGeneration){setBusy(false);el("gameText").textContent=error.message;}}
   }})));
  }catch(error){el("gamePickerNote").textContent=error.message;}
 }
 function changeMode(game){
  cgEventController?.cancel();
  replyPlayer.stop();
  ++chatGeneration;bridge.cancelChat();bridge.stopSpeech();chatMode=false;el("gameChatForm").hidden=true;el("gameNext").hidden=false;
  closeDialogs();director.stop();++warmGeneration;clearInterval(textTimer);currentNode=null;
  bridge.mode(game);setBusy(false);
  if(game&&ready)openChat();
 }
 el("gameNext").onclick=event=>{event.stopPropagation();advance();};
 el("gameDialogue").onclick=()=>advance();
 el("gameSettings").onclick=()=>showDialog(menu);
 async function stopChat(){
  if(closeGameplayMedia)await closeGameplayMedia();
  gameplayController?.cancel();
  replyPlayer.stop();setBusy(false);el("gameNext").hidden=chatMode;
  clearInterval(textTimer);
  bridge.textSpeech(false);
  ++chatGeneration;chatBusy=false;el("gameChatSend").disabled=false;
  await Promise.all([bridge.cancelChat(),bridge.stopSpeech()]);
 }
 async function openChat(){
  const generation=++warmGeneration;
  closeDialogs();director.stop();currentNode=null;clearInterval(textTimer);
  await stopChat();if(generation!==warmGeneration)return;chatMode=true;setBusy(false);
  el("gameChatForm").hidden=false;el("gameNext").hidden=true;
  el("gameSceneTitle").textContent="和她聊一会儿";el("gameSpeaker").textContent=bridge.speaker;
  el("gamePlace").textContent=bridge.demo?"逐句表情 · 离线演示":"逐句表情 · 自由聊天";
  el("gameEmotion").textContent="";el("gameText").textContent="我在这里。想聊些什么？";
  el("gameHint").textContent=bridge.demo?"离线演示 · 输入“演示逐句表情”体验切换":"回复文字由你配置的 API 生成；情绪和动作在本地校验";
  el("gameChatInput").focus();
  if(gameplayController)gameplayController.restore().catch(error=>{el('gameHint').textContent=error.message;});
  cgEventController?.sync().catch(error=>{el('gameHint').textContent=error.message;});
 }
 el("gameChat").onclick=openChat;
 el("gameChatForm").onclick=event=>event.stopPropagation();
 el("gameChatStop").onclick=async()=>{await stopChat();el("gameHint").textContent="已停止 · 可以继续输入";};
 el("gameChatForm").onsubmit=async event=>{
  event.preventDefault();const text=el("gameChatInput").value.trim();if(!text||chatBusy)return;
  chatBusy=true;const generation=++chatGeneration;
  revealStream=false;typingText="";shown=0;
  replyPlayer.stop();clearInterval(textTimer);el("gameNext").hidden=true;
  el("gameChatSend").disabled=true;
  await Promise.all([bridge.cancelChat(),bridge.stopSpeech()]);
  if(generation!==chatGeneration||!chatMode)return;
  const current=()=>generation===chatGeneration&&chatMode;
  el("gameChatSend").disabled=true;el("gameChatInput").value="";
  el("gameText").textContent="…";el("gameEmotion").textContent="";
  el("gameHint").textContent="你："+text;
  try{
   const result=await bridge.chat(text,(preview,kind)=>{if(current())streamText(preview,kind);});
   if(!result||!current())return;
   await replyPlayer.start(result);
  }catch(error){if(current()){clearInterval(textTimer);bridge.textSpeech(false);el("gameText").textContent=error.message;el("gameHint").textContent="文字聊天可继续；请检查连接设置后重试";el("gameChatInput").value=text;}}
  finally{if(current()){chatBusy=false;el("gameChatSend").disabled=false;el("gameChatInput").focus();}}
 };
 el("closeGameMenu").onclick=()=>menu.close();
 el("closeGamePicker").onclick=()=>picker.close();
 el("gameStories").onclick=openStories;el("gameScenes").onclick=openLocations;el("gameOutfits").onclick=openOutfits;
 el("gameShowEmotion").onchange=()=>{el("gameEmotion").hidden=!el("gameShowEmotion").checked;};
 el("gameConnections").onclick=()=>{menu.close();bridge.connections();};
 el("gameWorkbench").onclick=()=>changeMode(false);
 el("enterGame").onclick=()=>changeMode(true);
 choice.addEventListener("cancel",event=>event.preventDefault());
 document.addEventListener("keydown",event=>{
  if(event.target.closest?.('input,textarea,select,button,summary,#gameStatePanel'))return;
  if(!document.body.classList.contains("game-mode")||picker.open||menu.open||choice.open||
     !el("settingsOverlay").classList.contains("hidden"))return;
  if(event.code==="Space"||event.code==="Enter"){event.preventDefault();advance();}
  if(event.code==="Escape")showDialog(menu);
 });
 window.gameExperience={
  cancelPending:stopChat,
  get active(){return document.body.classList.contains("game-mode")&&(!!director.scene||chatMode);},
  ready(){
   if(ready)return;ready=true;setBusy(false);el("gameNext").disabled=false;
   if(document.body.classList.contains("game-mode"))openChat();
  }
 };
 if(gameplayEnabled){
  const offer=document.createElement('dialog');offer.className='game-modal';
  const title=document.createElement('h2'),options=document.createElement('div'),dismiss=document.createElement('button');dismiss.textContent='这次先不用';
  offer.append(title,options,dismiss);document.body.append(offer);
  let offeredInstance=null;
  dismiss.onclick=async()=>{try{if(offeredInstance)await request('/api/game/event/dismiss',{instance_id:offeredInstance});offer.close();}catch(error){el('gameHint').textContent=error.message;}};
  offer.addEventListener('cancel',event=>{event.preventDefault();dismiss.click();});
  const mediaDialog=document.createElement('dialog');mediaDialog.className='game-modal';
  const mediaImage=document.createElement('img'),audio=document.createElement('audio'),mediaClose=document.createElement('button');mediaImage.style.maxWidth='100%';audio.controls=true;mediaClose.textContent='继续／关闭演出';mediaDialog.append(mediaImage,audio,mediaClose);document.body.append(mediaDialog);
  const sequenceContainer=document.createElement('div');mediaDialog.prepend(sequenceContainer);let sequenceView=null;
  mediaClose.className='cg-close';
  mediaDialog.style.width='min(1120px,calc(100% - 40px))';
  const mediaCache=new Map();
  const preload=async asset=>{
   if(mediaCache.has(asset.url))return mediaCache.get(asset.url);
   let result;
   if(asset.category==='cg_sequence'){
    const doc=await request(asset.url);
    const sequence=await CGSequence.prepareSequence(doc,async frame=>{const image=new Image();image.src=frame.url;await image.decode();return image;});
    result={asset_id:asset.asset_id,sequence};
   }else if(['bgm','se'].includes(asset.category)){
    const sound=new Audio();sound.preload='auto';sound.src=asset.url;
    await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('音频加载超时')),15000);sound.oncanplaythrough=()=>{clearTimeout(timer);resolve();};sound.onerror=()=>{clearTimeout(timer);reject(Error('音频无法解码'));};sound.load();});
    result={asset_id:asset.asset_id,audio:sound};
   }else{const image=new Image();image.src=asset.url;await image.decode();result={asset_id:asset.asset_id,image};}
   mediaCache.set(asset.url,result);while(mediaCache.size>24)mediaCache.delete(mediaCache.keys().next().value);return result;
  };
  const cgOverlay=document.createElement('div');cgOverlay.className='cg-stage-overlay';cgOverlay.hidden=true;el('gameExperience').prepend(cgOverlay);let cgView=null;
  cgEventController=new CGEventStage({request,preload,
   show(session,loaded){cgView?.destroy();cgOverlay.hidden=false;cgView=CGSequence.createStageView(cgOverlay,loaded.sequence,{loop:session.loop,hold_ms:session.hold_ms});el('gameSceneTitle').textContent=session.title;},
   hide(){cgView?.destroy();cgView=null;cgOverlay.hidden=true;el('gameSceneTitle').textContent='和她聊一会儿';}});
  gameplayController=new GameplayStage({request,preload,applyScene:bridge.applyVerifiedScene,
   onCG:command=>cgEventController.act(command),
   onCGStatus(info){if(info?.keyword_matched_ids?.length&&info.status!=='accepted')el('gameHint').textContent=info.status==='model_null'?'关键词已匹配；AI本轮未决定进入CG（可继续描述要进行的活动）':'AI事件决定无效，未执行CG；详见本机日志。';},
   onOffer(event){offeredInstance=event?.instance_id||null;if(!event){offer.close();return;}title.textContent=event.title;options.replaceChildren();
    for(const option of event.choices){const button=document.createElement('button');button.textContent=option.label;button.onclick=async()=>{button.disabled=true;try{await gameplayController.transition('event',{instance_id:event.instance_id,choice_id:option.id});}catch(error){el('gameHint').textContent=error.message;button.disabled=false;}};options.append(button);}
    if(!offer.open)offer.showModal();
   },
   async playMedia(asset,loaded){
    const token=asset.playback_token;
    await bridge.stopSpeech();sequenceView?.destroy();sequenceView=null;
    const isSequence=asset.category==='cg_sequence',isAudio=['bgm','se'].includes(asset.category);
    sequenceContainer.hidden=!isSequence;mediaImage.hidden=isSequence||isAudio;audio.hidden=!isAudio;
    if(isSequence){const prepared=loaded.find(x=>x.asset_id===asset.asset_id)?.sequence;if(!prepared)throw Error('CG演出尚未预加载');sequenceView=CGSequence.createView(sequenceContainer,prepared);}
    else if(isAudio){audio.src=asset.url;audio.play().catch(()=>{el('gameHint').textContent='点击音频播放按钮继续';});}else mediaImage.src=asset.url;
    if(!mediaDialog.open)mediaDialog.showModal();
    await new Promise(resolve=>{const close=async()=>{closeGameplayMedia=null;audio.pause();sequenceView?.destroy();sequenceView=null;mediaDialog.close();try{await request('/api/game/media/end',{token});}finally{resolve();}};closeGameplayMedia=close;mediaClose.onclick=close;mediaDialog.oncancel=event=>{event.preventDefault();close();};});
   }});
  const link=document.createElement('a');link.href='/gameplay/';link.textContent='场景与CG事件';link.className='btn';menu.append(link);
  const exitCG=document.createElement('button');exitCG.textContent='结束当前CG事件';exitCG.onclick=async()=>{try{await stopChat();await cgEventController.exit();menu.close();}catch(error){el('gameHint').textContent=error.message;}};menu.append(exitCG);
  setInterval(()=>{if(document.body.classList.contains('game-mode'))cgEventController.sync().catch(error=>{el('gameHint').textContent=error.message;});},4000);
  const mirrorLabel=document.createElement('label'),mirrorToggle=document.createElement('input');mirrorToggle.type='checkbox';mirrorToggle.onchange=()=>bridge.mirror(mirrorToggle.checked);mirrorLabel.append(mirrorToggle,document.createTextNode('水平镜像角色'));menu.append(mirrorLabel);
  const unlock=document.createElement('button');unlock.textContent='解除地点锁（允许已标记时间变体）';unlock.onclick=async()=>{try{await request('/api/game/scene/unlock',{});el('gameHint').textContent='已解除地点锁';}catch(error){el('gameHint').textContent=error.message;}};menu.append(unlock);
  setInterval(async()=>{if(!chatMode||chatBusy||menu.open||picker.open||offer.open||mediaDialog.open)return;try{const result=await request('/api/game/scene/auto',{});if(result.prepared)await gameplayController.transition('prepared',result.prepared);}catch(error){el('gameHint').textContent=error.message;}},20000);
  const gallery=document.createElement('button');gallery.textContent='已解锁媒体图鉴';gallery.onclick=async()=>{
   try{await stopChat();const result=await request('/api/game/gallery');setOptions(el('gamePickerOptions'),result.items.map(item=>({title:item.title,action:async()=>{try{const lease=await request('/api/game/media/begin',{asset_id:item.asset_id});const loaded=await preload(lease.media);await gameplayController.playMedia(lease.media,[loaded]);}catch(error){el('gamePickerNote').textContent=error.message;}}})));el('gamePickerTitle').textContent='已解锁媒体';el('gamePickerNote').textContent=result.items.length?'只有本存档事件解锁的素材可复播。':'尚无解锁媒体。';menu.close();showDialog(picker);}catch(error){el('gameHint').textContent=error.message;}
  };menu.append(gallery);
  el('stage').addEventListener('click',async event=>{
   if(cgEventController?.session||!chatMode||chatBusy||offer.open||mediaDialog.open||menu.open||picker.open||!el('settingsOverlay').classList.contains('hidden'))return;
   const point=bridge.touchCoordinates(event);if(!point)return;
   try{const result=await request('/api/game/touch',{...point,request_id:'t_'+crypto.randomUUID().replaceAll('-',''),gesture:'tap'});if(result.text){el('gameChatInput').value=result.text;el('gameChatForm').requestSubmit();}}
   catch(error){el('gameHint').textContent=error.message;}
  });
 }
 const hud=typeof GameStateHUD==='undefined'?null:new GameStateHUD({
  request,beforeSwitch:async()=>{cgEventController?.cancel();await stopChat();},
  async onSwitch(){await bridge.profileChanged();await openChat();},
  render(value){
   if(value.error){el('gameStateStatus').textContent=value.error;return;}
   const state=value.state;
   const stages={acquaintance:'初识',familiar:'渐渐熟悉',close:'亲近',intimate:'很亲近',committed:'稳定亲密'};
   const mood=state.stats.mood>25?'愉快':state.stats.mood< -25?'低落':'平和';
   el('gameStateSummary').textContent=`${stages[state.relationship_stage]||state.relationship_stage} · 心情${mood}`;
   el('gameStateValues').textContent=`好感 ${state.stats.affection} · 信任 ${state.stats.trust}\n心情 ${state.stats.mood} · 精力 ${state.stats.energy}\n地点：${state.scene.location_id==='unknown'?'尚未登记':state.scene.location_id} · 存档版本 ${state.revision}`;
   const select=el('gameProfileSelect');select.replaceChildren();
   for(const profile of value.profiles){const option=document.createElement('option');option.value=profile.id;option.textContent=profile.display_name;select.append(option);}
   select.value=state.profile_id;
  }
 });
 if(hud){
  el('gameProfileSelect').onchange=async()=>{
   const select=el('gameProfileSelect');select.disabled=true;
   try{await hud.select(select.value);}catch(error){el('gameStateStatus').textContent=error.message;await hud.refresh();}
   finally{select.disabled=false;}
  };
  el('gameProfileCreate').onclick=async()=>{
   const button=el('gameProfileCreate');button.disabled=true;
   try{
    const id='p_'+crypto.randomUUID().replaceAll('-','');
    await request('/api/game/profile',{action:'create',id,display_name:el('gameProfileName').value.trim()});
    await hud.select(id);el('gameProfileName').value='';
   }catch(error){el('gameStateStatus').textContent=error.message;}
   finally{button.disabled=false;}
  };
  el('gameBackup').onclick=async()=>{
   const button=el('gameBackup');button.disabled=true;
   try{await request('/api/game/backup',{});el('gameStateStatus').textContent='已备份到本机用户数据的 backups 目录（包含全部存档的私人聊天）。';}
   catch(error){el('gameStateStatus').textContent=error.message;}
   finally{button.disabled=false;}
  };
  el('gameShowState').onchange=()=>{el('gameStatePanel').hidden=!el('gameShowState').checked;};
  hud.refresh();
  setInterval(()=>{if(!document.hidden&&document.body.classList.contains('game-mode')&&!el('gameStatePanel').hidden)hud.refresh();},10000);
 }
 if(bridge.ready)window.gameExperience.ready();
})();
