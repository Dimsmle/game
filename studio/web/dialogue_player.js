/* Branching dialogue director. Pixels, text animation and UI live in adapters. */
"use strict";
(function(root){
 class DialoguePlayer {
  constructor({prepare=async()=>{},onState=()=>{}}={}){
   this.prepare=prepare;this.onState=onState;this.generation=0;this.stop();
  }
  stop(){this.generation++;this.scene=null;this.current=null;this.loading=false;this.choosing=false;this.error=null;}
  async start(scene){
   this.stop();
   if(!scene||!Array.isArray(scene.nodes)||!scene.nodes.length)throw Error("对话内容无效");
   this.scene=scene;this.nodes=new Map(scene.nodes.map(node=>[node.id,node]));
   if(this.nodes.size!==scene.nodes.length||!this.nodes.has(scene.start))throw Error("对话节点无效");
   for(const node of scene.nodes){
    const targets=[node.next,...(node.choices||[]).map(choice=>choice.next)].filter(Boolean);
    if(targets.some(target=>!this.nodes.has(target)))throw Error("对话分支不存在");
   }
   return this._show(scene.start);
  }
  snapshot(){return {scene:this.scene,current:this.current,loading:this.loading,choosing:this.choosing,error:this.error};}
  emit(){this.onState(this.snapshot());}
  async _show(id){
   const generation=++this.generation;
   this.loading=true;this.choosing=false;this.error=null;this.emit();
   const node=this.nodes.get(id);
   try{
    await this.prepare(node,()=>generation===this.generation);
    if(generation!==this.generation)return false;
    this.current=node;this.loading=false;this.emit();return true;
   }catch(error){
    if(generation!==this.generation)return false;
    this.loading=false;this.error={message:error.message,retry:id};this.emit();return false;
   }
  }
  async advance(){
   if(this.loading||!this.current)return false;
   if(this.error)return this._show(this.error.retry);
   if(this.current.choices?.length){this.choosing=true;this.emit();return false;}
   if(this.current.next)return this._show(this.current.next);
   this.emit();return false;
  }
  async choose(index){
   if(!this.choosing||this.loading||!Number.isInteger(index))return false;
   const choice=this.current?.choices?.[index];
   if(!choice)throw Error("请选择当前显示的选项");
   this.choosing=false;return this._show(choice.next);
  }
  retry(){return this.error?this._show(this.error.retry):Promise.resolve(false);}
 }
 if(typeof module!=="undefined"&&module.exports)module.exports={DialoguePlayer};
 else root.DialoguePlayer=DialoguePlayer;
})(typeof window!=="undefined"?window:globalThis);
