const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map(),calls=[];
function node(id=''){
 const byId=[...nodes.values()].find(x=>x.id===id);if(byId)return byId;
 if(!nodes.has(id))nodes.set(id,{id,value:id==='kind'?'locations':'',hidden:false,checked:false,children:[],textContent:'',
  append(...x){this.children.push(...x);},after(){},insertBefore(){},replaceChildren(...x){this.children=x;},
  querySelector(){return node('cg-help');},closest(){return {hidden:false};},getContext(){return {};},scrollIntoView(){},pause(){},removeAttribute(){}});
 return nodes.get(id);
}
let rules=[{id:'shi_beach',group:'ev_shi_c04',title:'海边',model_prefix:'shi',scenes:['bg05'],keywords:['海边'],enabled:true,loop:true,hold_ms:3000},
 {id:'ev_shi_c08',group:'ev_shi_c08',title:'',model_prefix:'shi',scenes:[],keywords:[],enabled:false,loop:true,hold_ms:3000}];
async function fetch(path,opts){const body=opts?.body?JSON.parse(opts.body):undefined;calls.push({path,body});let doc={};
 if(path==='/api/roleplay/status')doc={binding:{card_id:'card'}};
 else if(path==='/api/game/interaction')doc={binding:{profile_id:'default',revision:1},state:{scene:{location_id:'bg05'},toggles:{},flags:{},clock_mode:'manual'}};
 else if(path==='/api/game/catalog?kind=cg_rules')doc={revision:2,data:rules};
 else if(path==='/api/game/catalog?kind=events')doc={revision:0,data:[]};
 else if(path==='/api/game/diary')doc={items:[]};
 else if(path.startsWith('/api/game/catalog?'))doc={revision:1,items:[]};
 else if(path==='/api/game/catalog/cg_rules')rules=body.definitions;
 return {ok:true,json:async()=>doc};
}
vm.runInNewContext(fs.readFileSync('studio/web/gameplay_ui.js','utf8'),{document:{getElementById:node,createElement:()=>node('generated_'+nodes.size),createTextNode:text=>({textContent:text})},fetch,console});
const settle=()=>new Promise(setImmediate);
(async()=>{
 await settle();assert.equal(node('cg-editor').hidden,true);
 node('kind').value='cg_rules';await node('kind').onchange();
 assert.equal(node('items').children.length,2);assert.match(node('counts').textContent,/2 项/);
 node('items').children[1].onclick();assert.equal(node('cg-title').value,'');assert.equal(node('cg-id').readOnly,true);
 node('cg-title').value='自定义名字';await node('cg-save').onclick();
 assert.equal(rules.find(x=>x.group==='ev_shi_c08').title,'自定义名字');
 assert.equal(calls.filter(x=>x.path==='/api/game/catalog/cg').length,0); // draft cannot import or enable
 assert.ok(![...nodes.values()].some(x=>x.id==='cg-any-location'));
 node('cg-scenes').value='';await node('cg-save').onclick();
 assert.deepEqual(rules.find(x=>x.group==='ev_shi_c08').scenes,[]);
 assert.ok(!('any_location' in rules.find(x=>x.group==='ev_shi_c08')));
 node('filter').value='c08';node('filter').oninput();assert.equal(node('items').children.length,1);
 await node('scan').onclick();assert.ok(calls.some(x=>x.path==='/api/game/catalog/cg_shi'));
 node('kind').value='locations';await node('kind').onchange();assert.equal(node('cg-editor').hidden,true);
 console.log('Gameplay UI: dropdown, CG draft list/editor, safe save, filter and shi scan passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
