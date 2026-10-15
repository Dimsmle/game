const assert=require('node:assert/strict');
const CGEventStage=require('../studio/web/cg_event_stage.js');
(async()=>{
 let active=null,calls=[],shown=0,hidden=0;
 const request=async(path,body)=>{calls.push(path);if(path.endsWith('/state'))return {active};if(path.endsWith('/prepare'))return {media:{asset_id:'cg'}};if(path.endsWith('/apply')){active={session_id:'one',media:{asset_id:'cg'}};return {};}if(path.endsWith('/close')){active=null;return {};}};
 const stage=new CGEventStage({request,preload:async()=>({sequence:{}}),show:()=>shown++,hide:()=>hidden++});
 await stage.act({turn_id:'turn'});assert.equal(shown,1);assert(calls.indexOf('/api/game/cg/prepare')<calls.indexOf('/api/game/cg/apply'));
 await stage.sync();assert.equal(shown,1);await stage.exit();assert.equal(stage.session,null);assert(hidden);
 let committed=false;
 const bad=new CGEventStage({request:async path=>{if(path.endsWith('/apply'))committed=true;return {media:{}};},preload:async()=>{throw Error('decode');},show:()=>{},hide:()=>{}});
 await assert.rejects(bad.act({turn_id:'bad'}),/decode/);assert(!committed);
 console.log('CGEventStage: preload gate, nonmodal session sync, explicit exit, no duplicate views and decode rollback passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
