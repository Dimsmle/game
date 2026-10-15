const assert=require('node:assert/strict');
const {prepareSequence,SequencePlayer}=require('../studio/web/cg_sequence_player.js');
(async()=>{
 const doc={manual_advance:true,frames:[{name:'base',width:1920,height:1080,url:'/api/game/cg/frame/cgseq_one/0'},{name:'diff',width:1920,height:1080,url:'/api/game/cg/frame/cgseq_one/1'}],
 steps:[{frame_index:0,transition_ms:7000},{frame_index:1,transition_ms:400},{frame_index:0,transition_ms:400}]};
 let loads=0,shown=[];
 const prepared=await prepareSequence(doc,async f=>{loads++;return {src:f.url};});assert.equal(loads,2);
 const player=new SequencePlayer(prepared,x=>shown.push(x));
 assert(player.next());assert.equal(shown[0].transition_ms,0);assert(player.next());assert.equal(shown[1].frame.name,'diff');assert.equal(shown[1].transition_ms,400);
 assert(player.next());assert.equal(shown[2].frame.name,'base');assert.equal(player.next(),false);
 assert(player.previous());assert.equal(player.index,1);player.stop();assert.equal(player.next(),false);
 await assert.rejects(prepareSequence({...doc,manual_advance:false},async()=>{}));
 await assert.rejects(prepareSequence({...doc,frames:[{...doc.frames[0],url:'file:///secret'}]},async()=>{}));
 await assert.rejects(prepareSequence({...doc,steps:[{frame_index:9,transition_ms:400}]},async()=>{}));
 await assert.rejects(prepareSequence(doc,async()=>{throw Error('decode failure');}),/decode failure/);
 console.log('CGSequence: preload, exact source order, manual advance, durations, cancellation and invalid manifests passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
