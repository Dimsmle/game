const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const elements=new Map(),timers=new Map();let clock=0,preview,resolveChat;
const mouth=[];
function el(id){
 if(!elements.has(id))elements.set(id,{textContent:'',value:'',hidden:false,disabled:false,open:false,
  classList:{add(){},remove(){},toggle(){},contains(){return false;}},setAttribute(){},
  addEventListener(){},replaceChildren(){},close(){this.open=false;},showModal(){this.open=true;},focus(){}});
 return elements.get(id);
}
class Director {constructor(opts){this.opts=opts;}stop(){} }
class Reply {
 constructor(opts){this.opts=opts;this.turn=null;this.loading=false;}
 stop(){this.turn=null;}
 async start(turn){this.turn=turn;this.opts.show(turn.segments[0],0,turn.segments.length);}
 async next(){}
}
const bridge={ready:false,speaker:'她',demo:false,textSpeech:value=>mouth.push(value),
 cancelChat:async()=>{},stopSpeech:async()=>mouth.push(false),
 chat:async(text,onText)=>{preview=onText;return await new Promise(resolve=>resolveChat=resolve);},emotionLabel:x=>x};
const document={getElementById:el,addEventListener(){},body:{classList:{contains(){return true;}}}};
const context={window:{GameBridge:bridge},document,DialoguePlayer:Director,ReplyPlayer:Reply,
 setInterval:fn=>{timers.set(++clock,fn);return clock;},clearInterval:id=>timers.delete(id),console};
vm.runInNewContext(fs.readFileSync('studio/web/game.js','utf8'),context);
const tick=n=>{for(let i=0;i<n;i++)for(const fn of [...timers.values()])fn();};
(async()=>{
 context.window.gameExperience.ready();await new Promise(setImmediate);
 assert.equal(el('gameChatForm').hidden,false);assert.equal(el('gamePicker').open,false);
 el('gameChatInput').value='你好';
 const pending=el('gameChatForm').onsubmit({preventDefault(){}});
 await new Promise(setImmediate);
 preview('你好，这是流式文字。');tick(2);
 assert.equal(el('gameText').textContent,'你好');assert.ok(mouth.includes(true));
 await el('gameDialogue').onclick();
 assert.equal(el('gameText').textContent,'你好，这是流式文字。');assert.equal(mouth.at(-1),false);
 preview('你好，这是流式文字。后续收到。');
 assert.equal(el('gameText').textContent,'你好，这是流式文字。后续收到。');
 resolveChat({turn_id:'turn',segments:[{speech:'你好，这是流式文字。后续收到。',emotion:'happy'}]});
 await pending;
 assert.equal(el('gameText').textContent,'你好，这是流式文字。后续收到。');
 await el('gameChatStop').onclick();tick(50);assert.equal(mouth.at(-1),false);
 assert.equal(timers.size,0);
 console.log('Game text: incremental stream, click reveal, later chunks, silent mouth and stop passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
