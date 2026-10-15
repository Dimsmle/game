/* Dialogue CG sessions are not modal: chat stays usable over the full stage. */
(function(root){
 'use strict';
 class CGEventStage{
  constructor({request,preload,show,hide}){Object.assign(this,{request,preload,show,hide});this.generation=0;this.session=null;this.syncing=false;}
  async sync(){
   if(this.syncing)return;this.syncing=true;const generation=this.generation;
   try{const result=await this.request('/api/game/cg/state'),session=result.active;
    if(generation!==this.generation)return;
    if(!session){this.session=null;this.hide();return;}
    if(this.session?.session_id===session.session_id)return;
    const loaded=await this.preload(session.media);
    if(generation!==this.generation)return;
    this.show(session,loaded);this.session=session;
   }finally{this.syncing=false;}
  }
  async act(command){
   const generation=++this.generation;
   const prepared=await this.request('/api/game/cg/prepare',{turn_id:command.turn_id});
   if(prepared.media)await this.preload(prepared.media);
   if(generation!==this.generation)return;
   const body={turn_id:command.turn_id,loaded:true};
   try{await this.request('/api/game/cg/apply',body);}catch(error){if(generation!==this.generation)throw error;await this.request('/api/game/cg/apply',body);}
   if(generation===this.generation)await this.sync();
  }
  async exit(){const session=this.session;++this.generation;if(session)await this.request('/api/game/cg/close',{session_id:session.session_id});this.session=null;this.hide();}
  cancel(){++this.generation;this.session=null;this.hide();}
 }
 if(typeof module!=='undefined'&&module.exports)module.exports=CGEventStage;else root.CGEventStage=CGEventStage;
})(typeof window==='undefined'?globalThis:window);
