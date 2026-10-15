"use strict";
const assert=require("node:assert/strict");
const {DialoguePlayer}=require("../studio/web/dialogue_player.js");
const scene={start:"hello",nodes:[{id:"hello",next:"choice"},
 {id:"choice",choices:[{text:"A",next:"a"},{text:"B",next:"b"}]},{id:"a"},{id:"b"}]};
(async()=>{
 const prepared=[];
 const director=new DialoguePlayer({prepare:async node=>{prepared.push(node.id);}});
 await director.start(scene);assert.equal(director.current.id,"hello");
 await director.advance();assert.equal(director.current.id,"choice");
 await director.advance();assert.equal(director.choosing,true);
 await assert.rejects(()=>director.choose(10),/选项/);
 await director.choose(1);assert.equal(director.current.id,"b");
 assert.deepEqual(prepared,["hello","choice","b"]);
 let release;
 const slow=new DialoguePlayer({prepare:()=>new Promise(resolve=>{release=resolve;})});
 const pending=slow.start(scene);slow.stop();release();
 assert.equal(await pending,false);assert.equal(slow.current,null);
 await assert.rejects(()=>director.start({start:"x",nodes:[{id:"x",next:"missing"}]}),/分支/);
 let fails=true;
 const retry=new DialoguePlayer({prepare:async()=>{if(fails)throw Error("load failed");}});
 await retry.start(scene);assert.equal(retry.error.message,"load failed");
 fails=false;await retry.retry();assert.equal(retry.current.id,"hello");
 console.log("DialoguePlayer: branch selection, stale-load cancellation and retry passed");
})().catch(error=>{console.error(error);process.exitCode=1;});
