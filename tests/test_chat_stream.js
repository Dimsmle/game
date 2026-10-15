const assert=require('node:assert/strict');
const {ReadableStream}=require('node:stream/web');
const ChatStream=require('../studio/web/chat_stream.js');
const encoder=new TextEncoder();
const response=events=>({ok:true,body:new ReadableStream({start(c){
 const raw=events.map(e=>JSON.stringify(e)+'\n').join('');const bytes=encoder.encode(raw);
 // Split inside multibyte UTF-8 and JSON tokens.
 for(let i=0;i<bytes.length;i+=5)c.enqueue(bytes.slice(i,i+5));c.close();
}})});
(async()=>{
 let seen=[];
 const chat=new ChatStream(async()=>response([{type:'text',text:'你好'},{type:'final',result:{speech:'你好',emotion:'happy'}}]));
 assert.equal((await chat.send('hi',text=>seen.push(text))).emotion,'happy');assert.deepEqual(seen,['你好']);
 const broken=new ChatStream(async()=>response([{type:'text',text:'未完'}]));
 await assert.rejects(()=>broken.send('hi',()=>{}),/未完成/);
 const failure=new ChatStream(async()=>response([{type:'error',error:'没有密钥'}]));
 await assert.rejects(()=>failure.send('hi',()=>{}),/没有密钥/);
 let release;
 const slow=new ChatStream(async path=>path.includes('cancel')?{}:await new Promise(resolve=>release=resolve));
 const pending=slow.send('old',()=>assert.fail('stale text'));
 await new Promise(resolve=>setImmediate(resolve));await slow.cancel();
 release(response([{type:'text',text:'旧回复'},{type:'final',result:{speech:'旧'}}]));
 assert.equal(await pending,null);
 const concurrent=new ChatStream(async()=>response([{type:'final',result:{speech:'latest'}}]));
 const [old,latest]=await Promise.all([concurrent.send('old',()=>assert.fail()),concurrent.send('new',()=>{})]);
 assert.equal(old,null);assert.equal(latest.speech,'latest');
 const paths=[];
 const completed=new ChatStream(async(path)=>{
  paths.push(path);return path==='/api/chat_stream'?response([{type:'final',result:{turn_id:'completed_turn',speech:'hi'}}]):{};
 });
 await completed.send('hi',()=>{});await completed.cancel();
 assert.ok(paths.includes('/api/chat_turn_cancel'));assert.equal(completed.turnId,null);
 console.log('ChatStream: UTF-8 chunks, final-only behavior, errors and stale cancellation passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
