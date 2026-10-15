"use strict";
const assert=require("node:assert/strict");
const {FrameSequenceRenderer}=require("../studio/web/frame_sequence.js");
const makeClip=(id="clip")=>({id,fps:24,duration_seconds:2,frames:Array.from({length:49},(_,i)=>({
 refs:{normal:`${id}/${i}/normal`,blink:`${id}/${i}/blink`,talk:`${id}/${i}/talk`}
}))});
(async()=>{
 let now=0,finished=null;
 const player=new FrameSequenceRenderer(async ref=>({ref}),{clock:()=>now,onEnd:clip=>{finished=clip.id;}});
 await player.play(makeClip());
 assert.equal(player.update({talk:true}).ref,"clip/0/talk");
 now=1000/24;
 assert.equal(player.update({blink:true}).ref,"clip/1/blink");
 for(let i=2;i<48;i++){
  now=i*1000/24;player.update();await new Promise(resolve=>setImmediate(resolve));
  assert.ok(player.cache.size<=15,"decoded frame cache must stay bounded");
 }
 now=2000;assert.equal(player.update(),null);assert.equal(finished,"clip");
 assert.equal(player.cache.size,0);
 let release;
 const slow=new FrameSequenceRenderer(()=>new Promise(resolve=>{release=resolve;}));
 // Resolve all pending loads after stop to reproduce an interrupted preload.
 const releases=[];
 slow.loadImage=()=>new Promise(resolve=>releases.push(resolve));
 const pending=slow.play(makeClip("old"));
 await Promise.resolve();slow.stop();releases.forEach(resolve=>resolve({ref:"old"}));
 assert.equal(await pending,false);assert.equal(slow.clip,null);
 console.log("FrameSequenceRenderer: clock, mouth/blink, bounded cache, completion and cancellation passed");
})().catch(error=>{console.error(error);process.exitCode=1;});
