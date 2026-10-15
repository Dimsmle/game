const assert=require('node:assert/strict');
const ReplyPlayer=require('../studio/web/reply_player.js');
const turn={turn_id:'turn_one',segments:[{speech:'真的吗',emotion:'surprised'},{speech:'有点害羞',emotion:'shy'},{speech:'很开心',emotion:'happy'}]};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 let applied=[],shown=[],stops=0,resolveVoice;
 const player=new ReplyPlayer({
  prepare:async(t,index)=>{applied.push(index);return t.segments[index];},
  show:line=>shown.push(line.emotion),speak:()=>new Promise(resolve=>resolveVoice=resolve),
  stopSpeech:async()=>{stops++;resolveVoice?.();},
 });
 await player.start(turn);assert.deepEqual(applied,[0]);assert.deepEqual(shown,['surprised']);
 assert.equal(player.speaking,true);
 assert.equal(player.snapshot().voiceSettled,false);
 await player.next();assert.deepEqual(applied,[0,1]);assert.deepEqual(shown,['surprised','shy']);
 player.stop();resolveVoice?.({error:'late error'});await tick();
 assert.equal(player.error,null);assert.equal(await player.next(),false);assert.equal(stops,2);
 let release;
 const stale=new ReplyPlayer({prepare:async()=>await new Promise(resolve=>release=resolve),show:()=>assert.fail('stale face')});
 const loading=stale.start(turn);await tick();assert.equal(await stale.next(),false);stale.stop();release(turn.segments[0]);
 assert.equal(await loading,false);
 let tries=0;
 const retry=new ReplyPlayer({prepare:async(t,index)=>{if(++tries===1)throw Error('image failed');return t.segments[index];},show:()=>{},speak:async()=>({error:'not installed'})});
 assert.equal(await retry.start(turn),false);assert.match(retry.error.message,/image failed/);
 assert.equal(await retry.next(),true);await tick();assert.equal(retry.index,0);assert.equal(retry.error.voice,true);
 await retry.next();await tick();assert.equal(retry.index,1); // voice error must not replay the previous sentence
 await retry.skipVoice();assert.equal(retry.snapshot().voiceSettled,true);assert.equal(retry.error,null);
 console.log('ReplyPlayer: ordered sentences, voice interruption, stale-load isolation, retry and optional TTS passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
