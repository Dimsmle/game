'use strict';
/* Roleplay Plus: no framework, external assets or untrusted HTML injection. */
const RP = (() => {
  const $ = id => document.getElementById(id);
  const fields = {
    character: ['id','name','description','traits','values','speech','likes','dislikes',
                'motivations','canon','fanon','examples','source','verified'],
    persona: ['id','name','description','share'],
    preset: ['id','name','description','length','narration','initiative','tone','emotion','frequency','guidance'],
    lore: ['id','title','content','keywords','activation','scope','priority','fact',
           'locations','affection','extra','enabled','verified','source']
  };
  let status = null, currentCard = null, currentPersona = null, currentPreset = null;
  let currentLore = null, pendingChoice = new Map(), toastTimer = null;

  function show(message, error=false) {
    const node=$('toast');
    node.textContent=String(message);
    node.className=error?'show error':'show';
    clearTimeout(toastTimer);
    toastTimer=setTimeout(()=>node.className='',3500);
  }
  async function confirmLocal(message) {
    // HTML dialog works consistently in WebView2 and automated in-app browsers.
    const dialog=document.createElement('dialog');dialog.className='rp-confirm';
    const text=document.createElement('p');text.textContent=message;
    const yes=document.createElement('button'),no=document.createElement('button');
    yes.textContent='确认';no.textContent='取消';no.className='secondary';
    dialog.append(text,no,yes);document.body.append(dialog);
    return await new Promise(resolve=>{
      const finish=value=>{dialog.close();dialog.remove();resolve(value);};
      yes.onclick=()=>finish(true);no.onclick=()=>finish(false);
      dialog.oncancel=event=>{event.preventDefault();finish(false);};dialog.showModal();
    });
  }
  async function api(path, obj) {
    const opt=obj===undefined ? {} : {
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(obj),
    };
    const response=await fetch(path,opt);
    let data;
    try { data=await response.json(); }
    catch { throw Error('后端没有返回有效 JSON'); }
    if (!response.ok) throw Error(data.error||`请求失败 ${response.status}`);
    return data;
  }
  const txt = id => $(id).value;
  const set = (id,v) => { $(id).value=String(v??''); };
  const check = id => $(id).checked;
  const setCheck = (id,v) => { $(id).checked=Boolean(v); };
  const lines = str => str.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
  const csv = str => str.split(/[,，]/).map(x=>x.trim()).filter(Boolean);
  const cell = (tag,text,className='') => {
    const node=document.createElement(tag);
    node.textContent=text==null?'':String(text);
    if (className) node.className=className;
    return node;
  };
  function appendTextRow(parent,title,subtitle,buttonLabel,onClick) {
    const row=cell('div','','list-row'),lhs=cell('div',''),
          h=cell('strong',title),small=cell('div',subtitle,'muted');
    lhs.append(h,small);row.append(lhs);
    if (buttonLabel) {
      const button=cell('button',buttonLabel,'secondary tiny');
      button.addEventListener('click',onClick);
      row.append(button);
    }
    parent.append(row);
    return row;
  }
  function options(id,items,selected,prop='id') {
    const sel=$(id);sel.replaceChildren();
    for (const x of items) {
      const opt=document.createElement('option');
      opt.value=x[prop];opt.textContent=x.name||x.title||x.id;
      sel.append(opt);
    }
    if (items.some(x=>x[prop]===selected)) sel.value=selected;
  }
  async function refresh() {
    status=await api('/api/roleplay/status');
    $('health').textContent='● 本地引擎已连接 · 数据已持久化';
    options('card-select',status.cards,status.binding.card_id);
    options('persona-select',status.personas,status.binding.persona_id||'default_player');
    options('preset-select',status.presets,status.binding.preset_id);
    renderStatus();
    renderPresets();
  }
  function renderStatus() {
    const state=status.game_state.state;
    const labels=[['affection','好感度',0,100],['trust','信任度',0,100],
                  ['mood','心情',-100,100],['energy','精力',0,100]];
    const grid=$('stats');grid.replaceChildren();
    for (const [key,label,lo,hi] of labels) {
      const box=cell('div','','stat'),top=cell('div',label,'label'),
            value=cell('strong',state[key]),progress=cell('div','','progress'),
            fill=cell('div','');
      fill.style.width=(Math.max(0,Math.min(1,(state[key]-lo)/(hi-lo)))*100)+'%';
      progress.append(fill);box.append(top,value,progress);grid.append(box);
    }
    const definitions=[['人物卡',status.binding.card_id],
      ['玩家身份',status.binding.persona_id||'不共享'],
      ['叙事预设',status.binding.preset_id],
      ['关系阶段',state.relationship_stage],
      ['当前地点',state.location_id||'尚未关联已验证地点'],
      ['角色属性版本',status.game_state.revision],
      ['活动配置版本',status.epoch]];
    const dl=$('binding-details');dl.replaceChildren();
    for (const [a,b] of definitions) dl.append(cell('dt',a),cell('dd',b));
    const choices=$('events');choices.replaceChildren();
    if (status.authority_mode==='game_db') {
      choices.append(cell('div','主项目 GameStore 是唯一属性权威。这里只禁用独立 RP 演示奖励；v0.15 开发中的真实邀请在角色舞台经玩家选择提交，素材和触摸请到「玩法与素材审核」配置。','muted'));
    }
    for (const item of status.events) appendTextRow(
      choices,item.title,item.description,'发起演示',()=>offerEvent(item.event_id));
    renderActive(status.active_event);
  }
  async function renderJournal() {
    const payload=await api('/api/roleplay/journal');
    const area=$('journal');area.replaceChildren();
    if (!payload.items.length) {area.textContent='还没有实际提交的事件';return;}
    for (const item of [...payload.items].reverse()) {
      appendTextRow(area,item.event_id,`${item.choice_id} · ${item.at}`,null,null);
    }
  }
  function renderActive(event) {
    const view=$('event-choice');view.replaceChildren();
    view.hidden=!event||event.status!=='offered';
    if (view.hidden) return;
    view.append(cell('strong',event.title),cell('div','在你做出选择前，角色属性不会发生变化。','muted'));
    for (const choice of event.choices) {
      const button=cell('button',choice.label);
      button.addEventListener('click',()=>chooseEvent(event.instance_id,choice.id));
      view.append(button);
    }
  }
  async function offerEvent(id) {
    try {
      const event=await api('/api/roleplay/event/offer',{event_id:id});
      renderActive(event);show('事件已提出，请自主选择；当前没有修改属性');
    } catch(e) {show(e.message,true);}
  }
  async function chooseEvent(instance,choice) {
    const target=instance+':'+choice;
    if (!pendingChoice.has(target)) {
      const rnd=(typeof crypto!=='undefined' && crypto.randomUUID) ?
        crypto.randomUUID().replace(/-/g,'') :
        (Date.now().toString(36)+Math.random().toString(36).slice(2));
      pendingChoice.set(target,'k_'+rnd);
    }
    try {
      const res=await api('/api/roleplay/event/choose',{
        instance_id:instance,choice_id:choice,idempotency_key:pendingChoice.get(target)
      });
      show(`已完成选择：${res.choice_id}。实际状态已保存在 SQLite。`);
      await refresh();await renderJournal();
    } catch(e) {show(e.message+'（重试仍使用同一个请求 ID）',true);}
  }
  async function loadCard(id) {
    try {
      currentCard=await api('/api/roleplay/card?id='+encodeURIComponent(id));
      const x=currentCard.data;
      set('card-id',x.card_id);set('card-name',x.name);
      set('card-description',x.description);set('card-speech',x.speech_style);
      for (const field of ['traits','values','likes','dislikes','motivations'])
        set('card-'+field,(x[field]||[]).join('\n'));
      set('card-canon',(x.canon_facts||[]).join('\n'));
      set('card-fanon',(x.fanon_facts||[]).join('\n'));
      set('card-examples',(x.example_dialogues||[]).map(a=>a.user+' | '+a.character).join('\n'));
      set('card-source',x.source_note);
      setCheck('card-verified',x.canon_verified);
      $('card-revision').textContent=`修订版：${currentCard.revision}`;
      $('card-id').readOnly=true;
    } catch(e) {show(e.message,true);}
  }
  function cardFromForm() {
    const examples=lines(txt('card-examples')).map(row=>{
      const index=row.indexOf('|');
      if (index<0)throw Error('说话示例必须使用“玩家台词 | 角色台词”格式');
      return {user:row.slice(0,index).trim(),character:row.slice(index+1).trim()};
    });
    return {
      card_id:txt('card-id').trim(),name:txt('card-name'),
      description:txt('card-description'),speech_style:txt('card-speech'),
      traits:lines(txt('card-traits')),values:lines(txt('card-values')),
      likes:lines(txt('card-likes')),dislikes:lines(txt('card-dislikes')),
      motivations:lines(txt('card-motivations')),
      canon_facts:lines(txt('card-canon')),fanon_facts:lines(txt('card-fanon')),
      example_dialogues:examples,source_note:txt('card-source'),
      canon_verified:check('card-verified')
    };
  }
  async function saveCard() {
    try {
      const result=await api('/api/roleplay/card/save',{
        data:cardFromForm(),expected_revision:currentCard?currentCard.revision:0
      });
      show('角色卡已保存；启用此卡后影响下一轮对话');
      await refresh();$('card-select').value=result.id;await loadCard(result.id);
    }catch(e){show(e.message,true);}
  }
  function newCard() {
    currentCard=null;
    for (const key of fields.character) {
      const el=$('card-'+key);
      if (el.type==='checkbox') el.checked=false;else el.value='';
    }
    set('card-id','new_character');set('card-name','新角色');
    $('card-id').readOnly=false;
    $('card-revision').textContent='新的角色卡';
  }
  async function loadPersona(id) {
    try {
      currentPersona=await api('/api/roleplay/persona?id='+encodeURIComponent(id));
      const x=currentPersona.data;
      set('persona-id',x.persona_id);set('persona-name',x.name);
      set('persona-description',x.description);
      setCheck('persona-share',x.share_with_llm);
      $('persona-id').readOnly=true;
      $('persona-revision').textContent=`修订版：${currentPersona.revision}`;
    }catch(e){show(e.message,true);}
  }
  async function savePersona() {
    try {
      const doc={persona_id:txt('persona-id').trim(),
        name:txt('persona-name'),description:txt('persona-description'),
        share_with_llm:check('persona-share')};
      const r=await api('/api/roleplay/persona/save',{
        data:doc,expected_revision:currentPersona?currentPersona.revision:0});
      await refresh();$('persona-select').value=r.id;await loadPersona(r.id);
      show('玩家人设已保存；未启用共享时不会进入 Prompt');
    }catch(e){show(e.message,true);}
  }
  function newPersona() {
    currentPersona=null;
    set('persona-id','new_player');set('persona-name','玩家');
    set('persona-description','');setCheck('persona-share',false);
    $('persona-id').readOnly=false;$('persona-revision').textContent='新的玩家身份';
  }
  function renderPresets() {
    const box=$('preset-cards');box.replaceChildren();
    for (const preset of status.presets) {
      const button=cell('button','','preset-card'+(status.binding.preset_id===preset.id?' active':''));
      button.append(cell('strong',preset.name),
        cell('span',(preset.builtin?'内置预设':'自定义预设')+' · 点击应用'));
      button.addEventListener('click',()=>selectBinding({preset_id:preset.id}));
      box.append(button);
    }
  }
  async function loadPreset(id) {
    try {
      currentPreset=await api('/api/roleplay/preset?id='+encodeURIComponent(id));
      const x=currentPreset.data;
      for (const [key,value] of [
        ['id',x.preset_id],['name',x.name],['description',x.description],
        ['length',x.response_length],['narration',x.narration],
        ['initiative',x.initiative],['tone',x.tone],['emotion',x.emotion],
        ['frequency',x.event_frequency],['guidance',x.custom_guidance]])
        set('preset-'+key,value);
      const builtin=status.presets.find(p=>p.id===id)?.builtin;
      $('preset-id').readOnly=true;
      $('preset-revision').textContent=builtin?
        `内置预设（版本 ${currentPreset.revision}），不能直接修改`:
        `修订版 ${currentPreset.revision}`;
    }catch(e){show(e.message,true);}
  }
  function copyPreset() {
    if (!currentPreset)return;
    const base=currentPreset.data.preset_id.replace(/_copy\d*$/,'');
    currentPreset=null;
    set('preset-id',(base+'_custom').slice(0,63));
    set('preset-name',txt('preset-name')+' · 我的版本');
    $('preset-id').readOnly=false;
    $('preset-revision').textContent='新的自定义预设';
    show('已复制当前值。修改后点击“保存自定义预设”。');
  }
  async function savePreset() {
    try {
      const data={
        preset_id:txt('preset-id').trim(),name:txt('preset-name'),
        description:txt('preset-description'),
        response_length:txt('preset-length'),narration:txt('preset-narration'),
        initiative:txt('preset-initiative'),tone:txt('preset-tone'),
        emotion:txt('preset-emotion'),event_frequency:txt('preset-frequency'),
        custom_guidance:txt('preset-guidance')};
      const r=await api('/api/roleplay/preset/save',{
        data,expected_revision:currentPreset?currentPreset.revision:0});
      await refresh();$('preset-select').value=r.id;await loadPreset(r.id);
      show('自定义叙事预设已保存');
    }catch(e){show(e.message,true);}
  }
  async function selectBinding(args) {
    try {
      await api('/api/roleplay/select',{...args,expected_session:status.session});
      await refresh();
      if(args.preset_id)await loadPreset(status.binding.preset_id);
      if(args.card_id){await loadCard(status.binding.card_id);newLore();await loadLore();}
      if(args.persona_id)await loadPersona(status.binding.persona_id);
      show('已应用设置；之后的 DeepSeek 对话将使用新的配置');
    }catch(e){show(e.message,true);}
  }
  async function loadLore() {
    try {
      const payload=await api('/api/roleplay/lore?card_id='+encodeURIComponent(status.binding.card_id));
      const box=$('lore-list');box.replaceChildren();
      if (!payload.items.length)box.append(cell('div','暂无条目','muted'));
      for (const item of payload.items) appendTextRow(
        box,item.data.title,
        `${item.data.entry_id} · ${item.data.activation} · ${item.data.enabled?'已启用':'关闭'}`,
        '编辑',()=>editLore(item));
    } catch(e){show(e.message,true);}
  }
  function editLore(item) {
    currentLore=item;
    const x=item.data;
    set('lore-id',x.entry_id);set('lore-title',x.title);set('lore-content',x.content);
    set('lore-keywords',x.keywords.join(', '));
    set('lore-activation',x.activation);set('lore-scope',x.scope);
    set('lore-priority',x.priority);set('lore-fact',x.fact_class);
    set('lore-locations',(x.conditions.location_any||[]).join(', '));
    set('lore-affection',x.conditions.affection_min??'');
    const extra={...x.conditions};delete extra.location_any;delete extra.affection_min;
    set('lore-extra',JSON.stringify(extra,null,2));
    setCheck('lore-enabled',x.enabled);setCheck('lore-verified',x.verified);
    set('lore-source',x.source_note);
    $('lore-id').readOnly=true;
    $('lore-revision').textContent=`修订版 ${item.revision}`;
  }
  function newLore() {
    currentLore=null;
    for (const key of fields.lore) {
      const el=$('lore-'+key);
      if (el.type==='checkbox')el.checked=key==='enabled';
      else el.value='';
    }
    set('lore-id','new_entry');set('lore-priority','50');
    set('lore-activation','keyword');set('lore-scope','character');
    set('lore-fact','fanon');$('lore-id').readOnly=false;
    $('lore-revision').textContent='新的世界书条目';
  }
  function loreFromForm() {
    const conditions=JSON.parse(txt('lore-extra').trim()||'{}');
    if(!conditions||typeof conditions!=='object'||Array.isArray(conditions))throw Error('其他条件必须是 JSON 对象');
    delete conditions.location_any;delete conditions.affection_min;
    if (csv(txt('lore-locations')).length)conditions.location_any=csv(txt('lore-locations'));
    if (txt('lore-affection')!=='') conditions.affection_min=Number(txt('lore-affection'));
    return {entry_id:txt('lore-id').trim(),title:txt('lore-title'),
      content:txt('lore-content'),keywords:csv(txt('lore-keywords')),
      activation:txt('lore-activation'),scope:txt('lore-scope'),
      priority:Number(txt('lore-priority')),fact_class:txt('lore-fact'),
      verified:check('lore-verified'),enabled:check('lore-enabled'),
      source_note:txt('lore-source'),conditions};
  }
  async function saveLore() {
    try {
      const r=await api('/api/roleplay/lore/save',{
        card_id:status.binding.card_id,data:loreFromForm(),
        expected_revision:currentLore?currentLore.revision:0});
      editLore(r);await loadLore();show('世界书已保存');
    }catch(e){show(e.message,true);}
  }
  async function deleteLore() {
    if (!currentLore)return show('没有可删除的条目',true);
    if (!await confirmLocal('确认删除世界书条目：'+currentLore.data.title+'？'))return;
    try {
      await api('/api/roleplay/lore/delete',{
        card_id:status.binding.card_id,entry_id:currentLore.data.entry_id,
        expected_revision:currentLore.revision});
      newLore();await loadLore();show('已删除');
    }catch(e){show(e.message,true);}
  }
  async function testLore() {
    try {
      const r=await api('/api/roleplay/lore/test',{text:txt('lore-query'),share_memory:false});
      $('lore-results').textContent=JSON.stringify(r,null,2);
    }catch(e){show(e.message,true);}
  }
  async function loadTrace() {
    try {
      const r=await api('/api/roleplay/prompt_trace');
      $('prompt-trace').textContent=r.trace?JSON.stringify(r.trace,null,2):'尚未进行 Roleplay 版对话；可先打开角色舞台聊一句。';
    }catch(e){show(e.message,true);}
  }
  async function previewPrompt() {
    const message=txt('prompt-query').trim();
    if (!message)return show('请输入测试话题',true);
    if (!await confirmLocal('将显示角色人设与世界书的本地预览文本。请确认当前屏幕不会被不相关人员看到。'))return;
    try {
      const r=await api('/api/roleplay/prompt_preview',{
        confirm:true,text:message,send_memory:false
      });
      $('prompt-output').textContent=r.addendum+'\n\n——诊断——\n'+JSON.stringify(r.trace,null,2);
    }catch(e){show(e.message,true);}
  }
  function bindUI() {
    for (const button of document.querySelectorAll('.nav')) {
      button.addEventListener('click',()=>{
        const tab=button.dataset.tab;
        document.querySelectorAll('.nav').forEach(x=>x.classList.toggle('active',x===button));
        document.querySelectorAll('.pane').forEach(x=>x.classList.toggle('active',x.id==='tab-'+tab));
        if (tab==='inspector')loadTrace();
        if (tab==='overview')renderJournal();
        if (tab==='lore')loadLore();
      });
    }
    $('card-select').addEventListener('change',e=>loadCard(e.target.value));
    $('card-new').addEventListener('click',newCard);
    $('card-save').addEventListener('click',saveCard);
    $('card-activate').addEventListener('click',()=>selectBinding({card_id:txt('card-select')}));
    $('persona-select').addEventListener('change',e=>loadPersona(e.target.value));
    $('persona-new').addEventListener('click',newPersona);
    $('persona-save').addEventListener('click',savePersona);
    $('persona-activate').addEventListener('click',()=>selectBinding({persona_id:txt('persona-select')}));
    $('persona-off').addEventListener('click',()=>selectBinding({persona_id:''}));
    $('preset-select').addEventListener('change',e=>loadPreset(e.target.value));
    $('preset-copy').addEventListener('click',copyPreset);
    $('preset-save').addEventListener('click',savePreset);
    $('preset-activate').addEventListener('click',()=>selectBinding({preset_id:txt('preset-select')}));
    $('lore-new').addEventListener('click',newLore);
    $('lore-save').addEventListener('click',saveLore);
    $('lore-delete').addEventListener('click',deleteLore);
    $('lore-test').addEventListener('click',testLore);
    $('trace-refresh').addEventListener('click',loadTrace);
    $('prompt-preview').addEventListener('click',previewPrompt);
  }
  async function init() {
    bindUI();
    try {
      await refresh();
      await Promise.all([
        loadCard(status.binding.card_id),
        loadPersona(status.binding.persona_id||'default_player'),
        loadPreset(status.binding.preset_id),
        loadLore(),renderJournal()
      ]);
    } catch (e) {
      $('health').textContent='● 后端不可用';
      show(e.message,true);
    }
  }
  document.addEventListener('DOMContentLoaded',init);
  return {refresh};
})();
