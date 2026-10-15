/* Reviewed media/scene coordinator. UI never invents effects or asset paths. */
(function(root){
 'use strict';
 const geometry=typeof module!=='undefined'&&module.exports?require('./touch_geometry.js'):root.CharacterTouchGeometry;
 class GameplayStage {
  static toLocal({clientX,clientY,rect,canvasWidth,canvasHeight,layer,mirror=false}){
   const fit=Math.max(rect.width/canvasWidth,rect.height/canvasHeight);
   const width=layer.crop.w*layer.scale,height=layer.crop.h*layer.scale;
   const cropRect={left:rect.left+(rect.width-canvasWidth*fit)/2+(canvasWidth/2+layer.x-width/2)*fit,
    top:rect.top+(rect.height-canvasHeight*fit)/2+(canvasHeight/2+layer.y-height/2)*fit,width:width*fit,height:height*fit};
   const matrix=geometry.imageMatrixFromLayout({rect:cropRect,sourceWidth:layer.crop.w,sourceHeight:layer.crop.h,fit:'fill',flipX:mirror});
   const point=geometry.normalizedPointer(matrix,clientX,clientY,{rect});
   if(!point)return null;
   return {x:(layer.crop.x+point.x*layer.crop.w)/740,y:(layer.crop.y+point.y*layer.crop.h)/1250};
  }
  constructor({request,preload,applyScene,onOffer=()=>{},playMedia=async()=>{},onCG=async()=>{},onCGStatus=()=>{}}){Object.assign(this,{request,preload,applyScene,onOffer,playMedia,onCG,onCGStatus});this.generation=0;this.completed=new Set();this.inflight=new Set();}
  cancel(){++this.generation;this.onOffer(null);}
  async restore(){
   const generation=this.generation,result=await this.request('/api/game/scene/current');
   const loaded=result.scene?[await this.preload(result.scene)]:[];
   if(generation===this.generation)await this.applyScene(result.scene,loaded);
   if(generation===this.generation){const active=await this.request('/api/game/events/active');if(generation===this.generation)this.onOffer(active.event);}
  }
  async complete(turn){
   if(!turn?.turn_id||this.completed.has(turn.turn_id)||this.inflight.has(turn.turn_id))return;
   const generation=this.generation;this.inflight.add(turn.turn_id);
   try{const value=await this.request('/api/game/turn/complete',{turn_id:turn.turn_id,displayed:true,tts_finished:true});
    if(generation!==this.generation)return;if(value.cg_action)await this.onCG(value.cg_action);
    if(generation!==this.generation)return;this.completed.add(turn.turn_id);this.onOffer(value.event);this.onCGStatus(turn.cg_diagnostic);
   }finally{this.inflight.delete(turn.turn_id);}
  }
  async transition(kind,payload){
   const generation=++this.generation;
   const prepared=kind==='prepared'?payload:await this.request('/api/game/'+(kind==='scene'?'scene':'event')+'/prepare',payload);
   const loaded=await Promise.all([prepared.scene,prepared.media].filter(Boolean).map(asset=>this.preload(asset)));
   if(generation!==this.generation)return null;
   const key='choice_'+(typeof crypto!=='undefined'&&crypto.randomUUID?crypto.randomUUID().replaceAll('-',''):Date.now()+'_'+Math.random().toString(36).slice(2));
   const body={prepare_token:prepared.prepare_token,loaded:true,idempotency_key:key};
   // A lost response retries the same preparation and idempotency capability.
   let result;
   try{result=await this.request('/api/game/commit',body);}
   catch(error){if(generation!==this.generation)throw error;result=await this.request('/api/game/commit',body);}
   if(generation!==this.generation)return null;
   if(result.scene)await this.applyScene(result.scene,loaded);
   this.onOffer(null);
   if(result.media)await this.playMedia(result.media,loaded);
   return result;
  }
 }
 if(typeof module!=='undefined'&&module.exports)module.exports=GameplayStage;else root.GameplayStage=GameplayStage;
})(typeof window==='undefined'?globalThis:window);
