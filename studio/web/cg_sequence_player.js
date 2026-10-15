/* Manual CG scene steps. No autoplay timing inferred from dialogue/script lines. */
(function(root){
 'use strict';
 async function prepareSequence(doc,load){
  if(!doc||doc.manual_advance!==true||!Array.isArray(doc.frames)||!Array.isArray(doc.steps)||!doc.frames.length||doc.frames.length>32||!doc.steps.length||doc.steps.length>100)throw Error('CG演出清单无效');
  let pixels=0;
  for(const frame of doc.frames){
   if(!Number.isInteger(frame.width)||!Number.isInteger(frame.height)||frame.width<=0||frame.height<=0||frame.width*frame.height>16000000||!/^\/api\/game\/cg\/frame\/[A-Za-z0-9_-]+\/\d+$/.test(frame.url))throw Error('CG图片清单无效');
   pixels+=frame.width*frame.height;
  }
  if(pixels>80000000)throw Error('CG预加载像素总量超限');
  for(const step of doc.steps)if(!Number.isInteger(step.frame_index)||!doc.frames[step.frame_index]||!Number.isInteger(step.transition_ms)||step.transition_ms<0||step.transition_ms>15000)throw Error('CG步骤无效');
  const images=await Promise.all(doc.frames.map(load));
  return {doc,images};
 }
 class SequencePlayer{
  constructor(prepared,display){this.prepared=prepared;this.display=display;this.index=-1;this.stopped=false;}
  show(index){
   if(this.stopped||!Number.isInteger(index)||index<0||index>=this.prepared.doc.steps.length)return false;
   const step=this.prepared.doc.steps[index],first=this.index<0;this.index=index;
   this.display({index,step,frame:this.prepared.doc.frames[step.frame_index],image:this.prepared.images[step.frame_index],transition_ms:first?0:step.transition_ms});
   return true;
  }
  next(){return this.show(this.index+1);}
  previous(){return this.show(this.index-1);}
  stop(){this.stopped=true;}
 }
 class LoopPlayer extends SequencePlayer{
  constructor(prepared,display,{loop=true,hold_ms=3000,schedule=(fn,ms)=>setTimeout(fn,ms),cancel=id=>clearTimeout(id)}={}){super(prepared,display);Object.assign(this,{loop,hold_ms,schedule,cancel});this.timer=null;}
  start(){if(this.stopped)return;this.show(0);this.queue();}
  queue(){this.timer=this.schedule(()=>{if(this.stopped)return;const next=this.index+1;if(next>=this.prepared.doc.steps.length){if(!this.loop)return;this.show(0);}else this.show(next);this.queue();},this.hold_ms+Math.min(this.prepared.doc.steps[this.index].transition_ms,600));}
  stop(){super.stop();if(this.timer!==null)this.cancel(this.timer);this.timer=null;}
 }
 function createStageView(container,prepared,options){
  container.replaceChildren();const doc=container.ownerDocument,layers=[doc.createElement('img'),doc.createElement('img')];let active=-1;
  for(const image of layers){image.alt='CG事件画面';image.className='cg-stage-image';container.append(image);}
  const player=new LoopPlayer(prepared,state=>{active=(active+1)%2;const image=layers[active];image.style.transition='none';image.style.opacity='0';image.src=state.image.src;layers.forEach((x,i)=>{x.style.zIndex=i===active?'2':'1';});void image.offsetWidth;image.style.transition=`opacity ${Math.min(state.transition_ms,600)}ms linear`;image.style.opacity='1';},options);
  player.start();return {destroy(){player.stop();container.replaceChildren();}};
 }
 function createView(container,prepared){
  const doc=container.ownerDocument,frame=doc.createElement('div'),controls=doc.createElement('div'),note=doc.createElement('p'),previous=doc.createElement('button'),next=doc.createElement('button'),label=doc.createElement('span');
  container.classList.add('cg-sequence-view');controls.className='cg-controls';note.className='cg-note';
  frame.style.cssText='position:relative;height:min(55vh,600px);width:100%;overflow:hidden;background:#06080d';
  const layers=[doc.createElement('img'),doc.createElement('img')];
  for(const layer of layers){layer.alt='合成后的完整CG';layer.style.cssText='position:absolute;inset:0;width:100%;height:100%;object-fit:contain;opacity:0';frame.append(layer);}
  previous.textContent='上一画面';next.textContent='下一画面';controls.append(previous,label,next);note.textContent='按脚本顺序手动推进；不是原作完整动画。镜头移动、旋转、音效和台词尚未还原。';
  container.replaceChildren(frame,controls,note);let active=-1;
  const player=new SequencePlayer(prepared,state=>{
   const old=active;active=(active+1)%2;
   const incoming=layers[active];incoming.style.transition='none';incoming.style.opacity='0';incoming.src=state.image.src;
   // Keep the old opaque image below the new layer: alpha does not dip to black.
   layers.forEach((layer,i)=>{layer.style.zIndex=i===active?'2':'1';});
   void incoming.offsetWidth;incoming.style.transition=`opacity ${state.transition_ms}ms linear`;incoming.style.opacity='1';
   if(old<0)layers[1-active].style.opacity='0';
   label.textContent=` ${state.index+1}/${prepared.doc.steps.length} · ${state.frame.name} · 脚本行 ${state.step.line} `;
   previous.disabled=state.index===0;next.disabled=state.index===prepared.doc.steps.length-1;
  });
  previous.onclick=()=>player.previous();next.onclick=()=>player.next();player.next();
  return {player,destroy(){player.stop();container.replaceChildren();}};
 }
 const api={prepareSequence,SequencePlayer,LoopPlayer,createView,createStageView};
 if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.CGSequence=api;
})(typeof window==='undefined'?globalThis:window);
