const assert=require('node:assert/strict');
const HUD=require('../studio/web/game_state_hud.js');
(async()=>{
 let selected='default',epoch=0,stops=0,changes=0,views=[];
 const request=async(path,body)=>{
  if(path==='/api/game/profile'){selected=body.id;epoch++;return {ok:true};}
  if(path==='/api/game/state')return {profile_id:selected};
  return {selected,generation:epoch,profiles:[{id:selected,display_name:'<script>text</script>'}]};
 };
 const hud=new HUD({request,render:v=>views.push(v),beforeSwitch:async()=>stops++,onSwitch:async()=>changes++});
 assert.equal(await hud.refresh(),true);assert.equal(changes,0);
 await hud.select('second');assert.equal(stops,1);assert.equal(changes,1);
 assert.equal(views.at(-1).state.profile_id,'second');
 epoch+=2;await hud.refresh();assert.equal(changes,2); // Other window switched away and back.
 let late=[];
 // Both asynchronous reads must settle to verify the generation guard.
 const gates=[];
 const guarded=new HUD({request:()=>new Promise(resolve=>gates.push(resolve)),render:v=>late.push(v)});
 const old=guarded.refresh();guarded.generation++;
 gates[0]({profile_id:'default'});gates[1]({selected:'default',generation:0,profiles:[]});
 assert.equal(await old,false);assert.deepEqual(late,[]);
 const errors=[];
 const failing=new HUD({request:async()=>{throw Error('offline');},render:v=>errors.push(v)});
 assert.equal(await failing.refresh(),false);assert.equal(errors[0].error,'offline');
 console.log('GameStateHUD: explicit profile switch, remote ABA isolation, stale response guard and recoverable error passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
