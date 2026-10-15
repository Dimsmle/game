/* Game presentation: silent authored dialogue, expression tags and modal choices. */
"use strict";
(function(){
 const el=id=>document.getElementById(id);
 const bridge=window.GameBridge;
 let scenarios=[],selectedStory=null,currentNode=null,textTimer=null,shown=0,typingText="";
 let warmGeneration=0,ready=false,chatMode=false,chatGeneration=0,chatBusy=false;
 let revealStream=false;
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
   shown=Math.min(full.length,shown+1);el("gameText").textContent=full.slice(0,shown);
   bridge.textSpeech(shown<full.length);
   if(shown===full.length)clearInterval(textTimer);
  },27);
 }
 function finishText(){clearInterval(textTimer);bridge.textSpeech(false);shown=typingText.length;el("gameText").textContent=typingText;}
 function streamText(preview){
  if(!preview.startsWith(typingText)){shown=0;el("gameText").textContent="";}
  typingText=preview;
  if(revealStream){finishText();return;}
  clearInterval(textTimer);
  textTimer=setInterval(()=>{
   if(shown<typingText.length){shown++;el("gameText").textContent=typingText.slice(0,shown);bridge.textSpeech(true);}
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
    showText(currentNode.text);
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
   await bridge.prepareSegment(turn.segments[index]);
   if(!isCurrent())return null;
   const value=await bridge.activateSegment(turn.turn_id,index);
   if(isCurrent())await bridge.applyChat(value,isCurrent);
   return value;
  },
  show(value,index,count){
   el("gameSpeaker").textContent=bridge.speaker;
   el("gameEmotion").textContent=bridge.emotionLabel(value.emotion);
   const alreadyVisible=index===0&&el("gameText").textContent===value.speech;
   if(alreadyVisible){typingText=value.speech;finishText();}else showText(value.speech);
   el("gameHint").textContent=(value.source==="demo"?"离线演示 · ":"")+`${index+1}/${count} · 每句话独立表情`;
  },
  speak:text=>bridge.speak(text),stopSpeech:()=>bridge.stopSpeech(),
  onState(state){
   if(!chatMode)return;
   setBusy(state.loading);el("gameNext").hidden=!state.turn;
   el("gameNext").disabled=state.loading||(!state.hasNext&&(!state.error||state.error.voice));
   el("gameNext").textContent=state.error&&!state.error.voice?"重试这一句 ↻":state.hasNext?"下一句 ▷":"本轮已读完";
   if(state.error)el("gameHint").textContent=(state.error.voice?"语音暂不可用 · ":"本句准备失败 · ")+state.error.message;
  }
 });
 async function advance(){
  if(chatMode){
   if(chatBusy&&!replyPlayer.turn){revealStream=true;finishText();return;}
   if(replyPlayer.loading)return;
   if((!replyPlayer.error||replyPlayer.error.voice)&&shown<typingText.length){finishText();return;}
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
 function openLocations(){
  ++warmGeneration;
  menu.close();el("gamePickerEyebrow").textContent="让画面换一种心情";
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
    try{await bridge.changeModel(model.name);if(generation!==warmGeneration)return;if(chatMode)await openChat();else await startStory(selectedStory||"promise");}
    catch(error){if(generation===warmGeneration){setBusy(false);el("gameText").textContent=error.message;}}
   }})));
  }catch(error){el("gamePickerNote").textContent=error.message;}
 }
 function changeMode(game){
  replyPlayer.stop();
  ++chatGeneration;bridge.cancelChat();bridge.stopSpeech();chatMode=false;el("gameChatForm").hidden=true;el("gameNext").hidden=false;
  closeDialogs();director.stop();++warmGeneration;clearInterval(textTimer);currentNode=null;
  bridge.mode(game);setBusy(false);
  if(game&&ready)openStories();
 }
 el("gameNext").onclick=event=>{event.stopPropagation();advance();};
 el("gameDialogue").onclick=()=>advance();
 el("gameSettings").onclick=()=>showDialog(menu);
 async function stopChat(){
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
   const result=await bridge.chat(text,preview=>{if(current())streamText(preview);});
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
  if(chatMode&&event.target.matches("input,textarea"))return;
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
   if(document.body.classList.contains("game-mode"))openStories();
  }
 };
 if(bridge.ready)window.gameExperience.ready();
})();
