/* Provisional text never contains executable behavior. */
(function(root){
 "use strict";
 class ChatStream {
  constructor(fetcher){this.fetch=fetcher;this.generation=0;this.pending=null;this.turnId=null;}
  async cancel(){
   ++this.generation;const pending=this.pending,turnId=this.turnId;this.pending=null;this.turnId=null;
   pending?.controller.abort();
   await Promise.all([
    pending?this.fetch('/api/chat_cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:pending.id})}).catch(()=>{}):null,
    turnId?this.fetch('/api/chat_turn_cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({turn_id:turnId})}).catch(()=>{}):null
   ]);
  }
  async send(text,onText){
   const stopping=this.cancel(),generation=this.generation;
   await stopping;if(generation!==this.generation)return null;
   const controller=new AbortController(),id='chat_'+Date.now()+'_'+Math.random().toString(36).slice(2);
   const pending={controller,id};this.pending=pending;
   const timer=setTimeout(()=>controller.abort(),100000);let reader;
   try{
    const response=await this.fetch('/api/chat_stream',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text,id}),signal:controller.signal});
    if(!response.ok)throw Error((await response.json()).error||'对话接口失败');
    reader=response.body.getReader();const decoder=new TextDecoder();let buffer='',result=null;
    while(true){
     const {done,value}=await reader.read();buffer+=decoder.decode(value||new Uint8Array(),{stream:!done});
     if(generation!==this.generation)return null;
     const lines=buffer.split('\n');buffer=lines.pop();
     for(const line of lines){
      if(!line.trim())continue;const event=JSON.parse(line);
      if(event.type==='text')onText(event.text,event.kind==='narration'?'narration':'dialogue');
      else if(event.type==='final'){result=event.result;this.turnId=result.turn_id||null;}
      else if(event.type==='cancelled')return null;
      else if(event.type==='error')throw Error(event.error);
     }
     if(done)break;
    }
    if(!result)throw Error('回复未完成，请重试；本轮没有执行行为');
    return result;
   }catch(error){
    if(generation!==this.generation)return null;
    if(error.name==='AbortError')throw Error('对话等待超时，已停止等待，可重新发送');
    throw error;
   }finally{
    clearTimeout(timer);if(reader){try{await reader.cancel();}catch{}}
    if(this.pending===pending)this.pending=null;
   }
  }
 }
 if(typeof module!=='undefined'&&module.exports)module.exports=ChatStream;else root.ChatStream=ChatStream;
})(typeof window==='undefined'?globalThis:window);
