'use strict';
(()=>{
 const $=id=>document.getElementById(id);
 const api=async(path,body)=>{const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const x=await r.json();if(!r.ok)throw Error(x.error||'请求失败');return x;};
 let snapshot,items=[],revision=0,selected=null,page=0,eventRevision=0,touchRevision=0,signature=null,polygons=[],points=[],image=null;
 const roleLabel=document.createElement('label'),roleInput=document.createElement('input');roleInput.id='media-roles';roleInput.placeholder='角色卡ID，逗号分隔；留空表示通用素材';roleLabel.textContent='媒体适用角色卡';roleLabel.append(roleInput);$('review').insertBefore(roleLabel,$('save-review'));
 let activeCardId='legacy_character';
 const importCG=document.createElement('button');importCG.textContent='导入 ev_shi_c04 海边CG';$('scan').after(importCG);
 const sequencePanel=document.createElement('div');$('preview').after(sequencePanel);let sequenceView=null,reviewGeneration=0;
 const report=error=>{$('status').textContent=error instanceof Error?error.message:String(error);};
 const run=fn=>async()=>{try{await fn();}catch(error){report(error);}};
 let cgRules=[],cgRevision=0;
 const split=value=>value.split(/[,，\n]/).map(x=>x.trim()).filter(Boolean);
 function editCG(rule){for(const [key,id] of Object.entries({id:'cg-id',title:'cg-title',group:'cg-group',model_prefix:'cg-model',hold_ms:'cg-hold'}))$(id).value=rule[key];$('cg-scenes').value=rule.scenes.join(', ');$('cg-keywords').value=rule.keywords.join(', ');$('cg-enabled').checked=rule.enabled;$('cg-loop').checked=rule.loop;}
 async function loadCG(){const doc=await api('/api/game/catalog?kind=cg_rules');cgRules=doc.data;cgRevision=doc.revision;$('cg-rule-list').replaceChildren();for(const rule of cgRules){const button=document.createElement('button');button.textContent=rule.title+' · '+rule.id;button.onclick=()=>editCG(rule);$('cg-rule-list').append(button);}if(cgRules.length)editCG(cgRules[0]);}
 $('cg-new').onclick=()=>editCG({id:'',title:'',group:'',model_prefix:'shi',scenes:[],keywords:[],enabled:true,loop:true,hold_ms:3000});
 $('cg-save').onclick=run(async()=>{const row={id:$('cg-id').value.trim(),title:$('cg-title').value.trim(),group:$('cg-group').value.trim(),model_prefix:$('cg-model').value.trim(),scenes:split($('cg-scenes').value),keywords:split($('cg-keywords').value),enabled:$('cg-enabled').checked,loop:$('cg-loop').checked,hold_ms:Number($('cg-hold').value)};const definitions=cgRules.filter(x=>x.id!==row.id);definitions.push(row);await api('/api/game/catalog/cg_rules',{definitions,revision:cgRevision});await loadCG();const media=await api('/api/game/catalog?kind=media');await api('/api/game/catalog/cg',{group:row.group,revision:media.revision});report('CG规则与素材已保存，无需审核。角色与场景匹配后，AI根据对话决定进入或结束。');});
 run(loadCG)();
 async function settings(){snapshot=await api('/api/game/interaction');$('current').textContent=`存档 ${snapshot.binding.profile_id} · 版本 ${snapshot.binding.revision} · 地点 ${snapshot.state.scene.location_id}`;for(const key of ['proactive_events','touch_interaction'])$(key==='proactive_events'?'proactive':'touch-on').checked=snapshot.state.toggles[key];$('clock').value=snapshot.state.clock_mode;$('game-hour').value=snapshot.state.flags.clock_game_hour??12;}
 async function load(){const x=await api('/api/game/catalog?kind='+$('kind').value);items=x.items;revision=x.revision;page=0;render();}
 function render(){const search=$('filter').value.trim().toLowerCase();const all=items.filter(x=>(x.filename+' '+(x.family||'')+' '+(x.location_name||'')).toLowerCase().includes(search));const max=Math.max(0,Math.ceil(all.length/24)-1);page=Math.min(page,max);$('counts').textContent=`${all.length} 项 · 第${page+1}/${max+1}页 · ${items.filter(x=>x.verified).length}项已标记`;$('items').replaceChildren();for(const item of all.slice(page*24,page*24+24)){const button=document.createElement('button');button.className='preset-card';button.textContent=[item.filename,item.family||item.extension,item.verified?'已标记':'未标记',item.location_name||item.title||'',item.time_of_day||''].join(' · ');button.onclick=()=>review(item);$('items').append(button);}}
 function review(item){
  const generation=++reviewGeneration;sequenceView?.destroy();sequenceView=null;sequencePanel.replaceChildren();
  selected=item;$('review').hidden=false;$('review-name').textContent=item.filename+' · '+item.asset_id;
  $('automatic').checked=!!(item.allow_automatic||item.safe_for_auto);$('default').checked=!!item.default;
  $('title').value=item.location_name||item.title||'';$('location-id').value=item.location_id||'';$('time').value=item.time_of_day||'unknown';
  $('category').value=item.category==='unknown'?'cg_still':item.category||'cg_still';
  roleInput.value=(item.character_ids??[activeCardId]).join(', ');
  const background=$('kind').value==='locations';roleLabel.hidden=background;$('category').closest('label').hidden=background;
  for(const key of ['location-id','time','default'])$(key).closest('label').hidden=!background;
  const audio=['.ogg','.mp3','.wav'].includes(item.extension),sequence=item.extension==='.cgseq';$('preview').hidden=audio||sequence||item.extension==='.psb';$('preview-audio').hidden=!audio;
  $('preview-audio').pause();$('preview-audio').removeAttribute('src');
  if(audio)$('preview-audio').src=item.preview_url;else if(sequence){
   $('category').value='cg_sequence';run(async()=>{const doc=await api(item.sequence_url);const prepared=await CGSequence.prepareSequence(doc,async frame=>{const image=new Image();image.src=frame.url;await image.decode();return image;});if(generation===reviewGeneration)sequenceView=CGSequence.createView(sequencePanel,prepared);})();
  }else if(item.extension!=='.psb')$('preview').src=item.preview_url;
  $('review').scrollIntoView({behavior:'smooth'});
 }
 $('kind').onchange=run(load);$('reload').onclick=run(load);$('filter').oninput=()=>{page=0;render();};$('previous').onclick=()=>{page=Math.max(0,page-1);render();};$('next').onclick=()=>{page++;render();};
 $('scan').onclick=run(async()=>{report('正在只读扫描并计算哈希，原素材不会改动…');await api('/api/game/catalog/scan',{kind:$('kind').value});await load();report('扫描完成；新素材可以直接配置用途。');});
 importCG.onclick=run(async()=>{report('正在安全解析IPT并合成完整画面；不执行原脚本、无需人工审核…');$('kind').value='media';await load();await api('/api/game/catalog/cg',{group:'ev_shi_c04',revision});await load();const item=items.find(x=>x.extension==='.cgseq'&&x.group==='ev_shi_c04');if(item)review(item);report('样例已导入。可以逐步预览；填写CG事件规则后由对话触发。舞台设置中另有不解锁的测试预览。');});
 $('save-review').onclick=run(async()=>{if(!selected)throw Error('请先选择素材');const kind=$('kind').value;const review={asset_id:selected.asset_id,file_hash:selected.file_hash};if(kind==='locations')Object.assign(review,{location_id:$('location-id').value.trim(),location_name:$('title').value,time_of_day:$('time').value,allow_automatic:$('automatic').checked,default:$('default').checked});else Object.assign(review,{category:$('category').value,title:$('title').value,safe_for_auto:$('automatic').checked,character_ids:roleInput.value.split(/[,，]/).map(x=>x.trim()).filter(Boolean)});await api('/api/game/catalog/configure',{kind,revision,review});await load();$('review').hidden=true;report('标签已保存。');});
 $('save-settings').onclick=run(async()=>{await api('/api/game/interaction',{binding:snapshot.binding,settings:{proactive_events:$('proactive').checked,touch_interaction:$('touch-on').checked,clock_mode:$('clock').value,game_hour:Number($('game-hour').value)}});await settings();report('当前存档互动设置已保存。');});
 $('save-events').onclick=run(async()=>{const r=await api('/api/game/catalog/events',{definitions:JSON.parse($('events').value),revision:eventRevision});eventRevision=r.revision;report('事件规则校验并保存成功。');});
 const canvas=$('touch-canvas'),ctx=canvas.getContext('2d');
 function draw(){ctx.clearRect(0,0,canvas.width,canvas.height);if(image)ctx.drawImage(image,0,0,canvas.width,canvas.height);for(const row of [...polygons,{name:$('region').value,polygon:points}]){if(!row.polygon.length)continue;ctx.beginPath();row.polygon.forEach(([x,y],i)=>i?ctx.lineTo(x*canvas.width,y*canvas.height):ctx.moveTo(x*canvas.width,y*canvas.height));ctx.closePath();ctx.fillStyle='#72c9a642';ctx.strokeStyle='#b1ffe7';ctx.fill();ctx.stroke();const [x,y]=row.polygon[0];ctx.fillStyle='white';ctx.fillText(row.name,x*canvas.width,y*canvas.height);}$('regions').textContent=JSON.stringify(polygons,null,2);}
 $('load-touch').onclick=run(async()=>{signature=await api('/api/game/touch/profile');const old=await api('/api/game/catalog?kind=touch');touchRevision=old.revision;const existing=old.data[signature.model_id];polygons=existing?.source_hash===signature.source_hash?existing.regions:[];points=[];image=new Image();image.src=signature.image_url;await image.decode();canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;$('touch-description').textContent=signature.model_id+' · '+signature.pose_id+'；换造型或源图变化后必须重新核对';draw();});
 canvas.onclick=event=>{if(!image||points.length>=20)return;const r=canvas.getBoundingClientRect();points.push([(event.clientX-r.left)/r.width,(event.clientY-r.top)/r.height]);draw();};
 $('region-clear').onclick=()=>{points=[];draw();};$('touch-clear').onclick=()=>{points=[];polygons=[];draw();};
 $('region-done').onclick=run(async()=>{if(points.length<3)throw Error('至少点击三个顶点');const name=$('region').value;polygons=polygons.filter(p=>p.name!==name);polygons.push({name,polygon:points,z:polygons.length,enabled:true});points=[];draw();});
 $('save-touch').onclick=run(async()=>{if(!signature)throw Error('请先读取当前造型');const {model_id,pose_id,profile_id,outfit_id}=signature;const r=await api('/api/game/catalog/touch',{profile:{model_id,pose_id,profile_id,outfit_id,verified:true,regions:polygons},revision:touchRevision,confirm:true});touchRevision=r.revision;report('已保存命中区。请返回舞台并在本存档启用触摸。');});
 run(async()=>{activeCardId=(await api('/api/roleplay/status')).binding.card_id;roleInput.value=activeCardId;await settings();await load();const e=await api('/api/game/catalog?kind=events');eventRevision=e.revision;$('events').value=JSON.stringify(e.data,null,2);$('diary').textContent=JSON.stringify((await api('/api/game/diary')).items,null,2);})();// no external assets or libraries
})();
