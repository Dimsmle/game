const assert=require('node:assert/strict');
const GameplayStage=require('../studio/web/gameplay_stage.js');
(async()=>{
 const layer={x:0,y:0,scale:1,crop:{x:0,y:0,w:740,h:1250}};
 for(const size of [1,.5]){
  const args={clientX:800*size,clientY:450*size,rect:{left:0,top:0,width:1600*size,height:900*size},canvasWidth:1600,canvasHeight:900,layer};
  assert.deepEqual(GameplayStage.toLocal(args),{x:.5,y:.5});
 }
 const args={clientX:615,clientY:450,rect:{left:0,top:0,width:1600,height:900},canvasWidth:1600,canvasHeight:900,layer};
 assert.equal(GameplayStage.toLocal(args).x,.25);assert.equal(GameplayStage.toLocal({...args,mirror:true}).x,.75);
 let requests=[],offered=[],applied=0,release;
 const asset={asset_id:'bg',url:'/safe/bg'};
 const request=async(path,body)=>{
  requests.push({path,body});
  if(path.endsWith('/complete'))return {event:{instance_id:'offer'}};
  if(path.endsWith('/prepare'))return {prepare_token:'token',scene:asset,media:null};
  if(path.endsWith('/commit'))return {scene:asset};
  return {};
 };
 const player=new GameplayStage({request,preload:async x=>({asset_id:x.asset_id}),applyScene:async()=>{applied++;},onOffer:e=>offered.push(e)});
 await player.complete({turn_id:'one'});await player.complete({turn_id:'one'});
 assert.equal(requests.filter(x=>x.path.endsWith('/complete')).length,1);
 await player.transition('scene',{location_id:'one'});assert.equal(applied,1);
 const failed=new GameplayStage({request,preload:async()=>{throw Error('decode failed');},applyScene:()=>assert.fail('bad scene')});
 const count=requests.filter(x=>x.path.endsWith('/commit')).length;
 await assert.rejects(failed.transition('scene',{}),/decode/);
 assert.equal(requests.filter(x=>x.path.endsWith('/commit')).length,count);
 const stale=new GameplayStage({request,preload:async()=>await new Promise(r=>release=r),applyScene:()=>assert.fail('stale scene')});
 const pending=stale.transition('scene',{});await new Promise(setImmediate);stale.cancel();release({});await pending;
 assert.equal(requests.filter(x=>x.path.endsWith('/commit')).length,count);
 let attempts=0,bodies=[];
 const retry=new GameplayStage({request:async(path,body)=>{
  if(path.endsWith('/prepare'))return {prepare_token:'retry'};
  bodies.push(body);if(++attempts===1)throw Error('lost response');return {};
 },preload:async()=>{},applyScene:async()=>{}});
 await retry.transition('scene',{});assert.deepEqual(bodies[0],bodies[1]);
 console.log('GameplayStage: preload-before-commit, stale cancellation, idempotent ACK/retry, scaling/mirroring passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
