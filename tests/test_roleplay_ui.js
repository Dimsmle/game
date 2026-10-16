const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const nodes=new Map();
function node(id=''){
 if(!nodes.has(id))nodes.set(id,{id,value:'',textContent:'',checked:false,readOnly:false,
  style:{},type:'text',children:[],classList:{toggle(){}},addEventListener(){},
  append(...items){this.children.push(...items);},after(...items){this.following=items;},replaceChildren(){this.children=[];}});
 return nodes.get(id);
}
const status={binding:{card_id:'actor',persona_id:null,preset_id:'daily'},session:{profile_id:'default',generation:1},
 cards:[{id:'actor',name:'角色'}],personas:[],presets:[{id:'daily',name:'自然日常',builtin:true}],
 game_state:{revision:0,state:{affection:25,trust:30,mood:15,energy:80}},events:[]};
const calls=[];
const context={document:{getElementById:node,createElement:tag=>({...node('template-'+tag),children:[]}),
 querySelectorAll:()=>[],addEventListener(){}},setTimeout:()=>1,clearTimeout(){},console,
 fetch:async(path,opt)=>{
  calls.push({path,body:opt?.body?JSON.parse(opt.body):null});
  let data={};
  if(path==='/api/roleplay/status')data=status;
  if(path.startsWith('/api/roleplay/preset?'))data={revision:1,data:{preset_id:'daily',name:'自然日常',response_length:'short'}};
  return {ok:true,json:async()=>data};
 }};
let source=fs.readFileSync('studio/roleplay_plus/web/main.js','utf8');
assert.equal(source.split('return {refresh};').length,2);
source=source.replace('return {refresh};','return {refresh,editLore,loreFromForm,newLore,selectBinding,installStats};');
vm.runInNewContext(source+'\nglobalThis.testRP=RP;',context);
(async()=>{
 const entry={revision:2,data:{entry_id:'school',title:'学校',content:'内容',keywords:['学校'],activation:'keyword',
  scope:'character',priority:50,fact_class:'fanon',verified:false,enabled:true,source_note:'',
  conditions:{affection_min:30,trust_min:55,stage_any:['familiar'],mood_min:0,flags_all:['met'],location_any:['school']}}};
 context.testRP.editLore(entry);
 node('lore-title').value='改标题';node('lore-affection').value='40';
 const output=context.testRP.loreFromForm();
 assert.equal(output.conditions.trust_min,55);assert.equal(output.conditions.affection_min,40);
 assert.equal(output.conditions.stage_any[0],'familiar');assert.equal(output.conditions.flags_all[0],'met');
 node('lore-locations').value='';node('lore-affection').value='';
 const noBasic=context.testRP.loreFromForm();
 assert.ok(!('location_any' in noBasic.conditions));assert.equal(noBasic.conditions.mood_min,0);
 node('lore-extra').value='[]';assert.throws(()=>context.testRP.loreFromForm(),/JSON/);
 context.testRP.newLore();assert.equal(node('lore-extra').value,'');
 await context.testRP.refresh();await context.testRP.selectBinding({preset_id:'daily'});
 assert.equal(node('preset-id').value,'daily');assert.equal(node('preset-name').value,'自然日常');
 const selection=calls.find(x=>x.path==='/api/roleplay/select');
 assert.equal(selection.body.expected_session.generation,1);
 assert.equal(selection.body.expected_session.profile_id,'default');
 context.testRP.installStats();
 const editor=node('stats').following[0];
 assert.equal(editor.children[0].textContent,'当前角色属性');
 assert.equal(editor.children.filter(x=>x.type==='number').length,0); // inputs live inside labels
 assert.equal(editor.children.filter(x=>x.children?.some(y=>y.type==='number')).length,4);
 assert.ok(!node('tab-character').children.includes(editor));
 console.log('Roleplay UI: overview stats editor, preset/editor sync, profile guard and lore conditions passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
