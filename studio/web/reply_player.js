/* Ordered sentence playback. Late expression/speech completions cannot revive a stopped turn. */
(function(root){
 "use strict";
 class ReplyPlayer {
  constructor({prepare,show,speak=async()=>{},stopSpeech=async()=>{},onState=()=>{}}){
   Object.assign(this,{prepare,show,speak,stopSpeech,onState});this.generation=0;this.stop();
  }
  stop(){++this.generation;this.turn=null;this.index=-1;this.loading=false;this.error=null;this.current=null;this.speaking=false;this.emit();}
  snapshot(){return {turn:this.turn,index:this.index,current:this.current,loading:this.loading,speaking:this.speaking,error:this.error,
   count:this.turn?.segments?.length||0,hasNext:!!this.turn&&this.index<this.turn.segments.length-1};}
  emit(){this.onState(this.snapshot());}
  async start(turn){
   this.stop();
   if(!turn?.turn_id||!Array.isArray(turn.segments)||!turn.segments.length)throw Error('逐句回复协议无效');
   this.turn=turn;return this._show(0);
  }
  async next(){
   if(this.loading||!this.turn)return false;
   if(this.error&&!this.error.voice)return this._show(this.error.index);
   if(this.index>=this.turn.segments.length-1)return false;
   return this._show(this.index+1);
  }
  async _show(index){
   const generation=++this.generation,current=()=>generation===this.generation&&!!this.turn;
   const turn=this.turn;
   this.loading=true;this.speaking=false;this.error=null;this.emit();
   try{
    await this.stopSpeech();if(!current())return false;
    const value=await this.prepare(turn,index,current);if(!current())return false;
    this.index=index;this.current=value;this.loading=false;this.show(value,index,turn.segments.length);this.emit();
    this.speaking=true;this.emit();
    // Do not block next/new input on the duration of a voice clip.
    Promise.resolve(this.speak(value.speech)).then(voice=>{
     if(!current())return;this.speaking=false;
     if(voice?.error)this.error={message:voice.error,voice:true,index};
     this.emit();
    }).catch(error=>{if(current()){this.speaking=false;this.error={message:error.message,voice:true,index};this.emit();}});
    return true;
   }catch(error){
    if(!current())return false;
    this.loading=false;this.error={message:error.message,index};this.emit();return false;
   }
  }
 }
 if(typeof module!=='undefined'&&module.exports)module.exports=ReplyPlayer;else root.ReplyPlayer=ReplyPlayer;
})(typeof window==='undefined'?globalThis:window);
