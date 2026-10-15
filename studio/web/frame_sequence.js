/* Clock-driven transparent sequence player. No network or DOM dependencies. */
"use strict";
(function(root){
 class FrameSequenceRenderer {
  constructor(loadImage,{clock=()=>performance.now(),onEnd=()=>{}}={}){
   this.loadImage=loadImage;this.clock=clock;this.onEnd=onEnd;
   this.serial=0;this.clip=null;this.cache=new Map();this.lastImage=null;
  }
  stop(){this.serial++;this.clip=null;this.cache.clear();this.lastImage=null;}
  _load(ref){
   if(this.cache.has(ref))return this.cache.get(ref).promise;
   const generation=this.serial;
   const entry={image:null,promise:null};
   entry.promise=Promise.resolve().then(()=>this.loadImage(ref)).then(image=>{
    if(generation===this.serial)entry.image=image;
    return image;
   });
   // Prevent unhandled background preload errors; play() still sees its own error.
   entry.promise.catch(()=>{});this.cache.set(ref,entry);return entry.promise;
  }
  async play(sequence){
   this.stop();const serial=this.serial;
   if(!sequence||!Array.isArray(sequence.frames)||sequence.frames.length<2||
      !(sequence.fps>=24&&sequence.fps<=30)||!(sequence.duration_seconds>0))
    throw Error("动作序列格式无效");
   await Promise.all(sequence.frames.slice(0,3).flatMap(f=>
    ["normal","blink","talk"].map(state=>this._load(f.refs[state]))));
   if(serial!==this.serial)return false;
   this.clip=sequence;this.started=this.clock();return true;
  }
  update({talk=false,blink=false}={}){
   if(!this.clip)return null;
   const sequence=this.clip;
   const seconds=Math.max(0,(this.clock()-this.started)/1000);
   if(seconds>=sequence.duration_seconds){
    this.stop();this.onEnd(sequence);return null;
   }
   const index=Math.min(sequence.frames.length-1,Math.floor(seconds*sequence.fps));
   const state=talk?"talk":blink?"blink":"normal";
   const wanted=new Set();
   // Keep at most 5*3 decoded frames (~20 MB at 444x750), including previous frame.
   for(let i=Math.max(0,index-1);i<=Math.min(sequence.frames.length-1,index+3);i++){
    for(const ref of Object.values(sequence.frames[i].refs)){
     wanted.add(ref);this._load(ref);
    }
   }
   for(const ref of this.cache.keys())if(!wanted.has(ref))this.cache.delete(ref);
   const image=this.cache.get(sequence.frames[index].refs[state])?.image;
   if(image)this.lastImage=image;
   return this.lastImage;
  }
 }
 if(typeof module!=="undefined"&&module.exports)module.exports={FrameSequenceRenderer};
 else root.FrameSequenceRenderer=FrameSequenceRenderer;
})(typeof window!=="undefined"?window:globalThis);
