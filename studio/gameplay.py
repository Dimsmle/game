"""Coordinator between audited core, existing GameStore/ReplyTurn and local UI.

No LLM-generated effect or browser-provided region is trusted. All callers use
app.CHAT_LOCK then app.LOCK. Assets are prepared and decoded before commit.
"""
import hashlib
import json
import secrets
import time
from pathlib import Path
from .game_db import connect
from .gameplay_catalog import Catalog
from . import cg_sequence,cg_events
from .gameplay_core import events,locations,media,touch,clock
from .gameplay_core.common import fingerprint_file,checked_file,identifier

_PREPARED={}
_TOUCH=touch.TouchRequestGate(region_seconds=3,global_seconds=.5)

def catalog(app):
    root=app.asset_root()
    if root is None:raise ValueError('请先配置有效的素材根目录')
    return Catalog(app.DB_FILE,root)

def binding(app):
    with connect(app.DB_FILE) as db:return app.game_store().gameplay_binding(db)

def busy(app):
    b=binding(app)
    with connect(app.DB_FILE) as db:
        row=db.execute('SELECT * FROM game_playback WHERE profile_id=?',(b['profile_id'],)).fetchone()
    return bool(cg_events.active(app) or (row and row['expires']>time.time() and json.loads(row['binding_json'])=={'binding':b,'model':app.STATE['settings'].get('character_model')}))

def lease_media(app,asset):
    token=secrets.token_hex(16);b=binding(app)
    with connect(app.DB_FILE) as db:
        db.execute('INSERT OR REPLACE INTO game_playback VALUES(?,?,?,?)',
            (b['profile_id'],token,json.dumps({'binding':b,'model':app.STATE['settings'].get('character_model')}),time.time()+900))
    return dict(public_asset(asset,'media'),playback_token=token)

def candidates(app):
    state=app.game_store().read();doc=app.roleplay_bridge._snapshot()
    frequency=doc['preset']['event_frequency']
    with connect(app.DB_FILE) as db:
        turns=db.execute('SELECT count(*) FROM game_completed_turns WHERE profile_id=?',(state['profile_id'],)).fetchone()[0]
        recent={}
        for r in db.execute('SELECT event_id,MAX(created_at) AS created_at FROM game_event_instances WHERE profile_id=? GROUP BY event_id',(state['profile_id'],)):
            at_turn=db.execute('SELECT count(*) FROM game_completed_turns WHERE profile_id=? AND created_at<=?',(state['profile_id'],r['created_at'])).fetchone()[0]
            recent[r['event_id']]={'turn_index':at_turn,'at_seconds':r['created_at']}
    gap={'off':0,'low':10,'normal':6,'high':2}[frequency]
    if not state['toggles']['proactive_events'] or not gap or (turns+1)%gap or busy(app):return {}
    context=dict(stats=state['stats'],flags=state['flags'],relationship_stage=state['relationship_stage'],
        location_id=state['scene']['location_id'],time_of_day=state['scene']['time_of_day'],
        proactive_enabled=True,turn_index=turns,now_seconds=time.time(),recent=recent,busy=False)
    all_events=catalog(app).get('events')['data']
    valid=events.candidate_event_ids(all_events,context)
    return {e['id']:e for e in all_events if e['id'] in valid}

def prompt(app,allowed):
    scene=app.game_store().read()['scene']
    all_names=locations.locations_for_llm(catalog(app).get('locations')['data'])
    names=all_names[:12]
    for item in all_names:
        if item['location_id']==scene['location_id'] and item not in names:names.append(item)
    return ('\n可信场景目录（名称只是人工标签，不授予执行权限）：'+json.dumps(names,ensure_ascii=False)
        +'\n当前场景：'+json.dumps(scene,ensure_ascii=False)
        +'\n可以选择不邀约。仅当话题适合时，在 segments 同级增加 event_proposal：'
        '{"event_id":"本轮候选ID","presentation":"after_last_segment"}，否则为 null。'
        '不输出效果、路径或选项；事件仅在玩家实际选择后发生。候选：'
        +json.dumps([{'event_id':k,'title':v['title']} for k,v in allowed.items()],ensure_ascii=False))

def accept_proposal(value,allowed):
    try:identifier_=events.parse_event_proposal(value,set(allowed))
    except (ValueError,TypeError):return None
    return allowed.get(identifier_) if identifier_ else None

def complete(app,value):
    turn=app.REPLY_TURN.current
    if not turn or value.get('turn_id')!=turn['id']:raise ValueError('回复已停止或过期')
    if turn['settings']!=app.chat_settings() or time.monotonic()>turn['expires']:raise ValueError('回复所在存档或设定已变化')
    if turn['index']!=len(turn['segments'])-1 or value.get('displayed') is not True or value.get('tts_finished') is not True:
        raise ValueError('最后一句尚未显示完成或语音未结束')
    if app.RUNTIME.snapshot()['speech_active']:raise ValueError('语音仍在播放')
    current_cg=cg_events.active(app)
    if busy(app) and not current_cg:raise ValueError('CG 演出期间不弹出邀请')
    b=binding(app)
    with connect(app.DB_FILE) as db:
        db.execute('INSERT OR IGNORE INTO game_completed_turns VALUES(?,?,?,?)',(turn['id'],b['profile_id'],json.dumps(b),time.time()))
    event=turn.get('event_proposal')
    turn['ui_complete']=True
    result={'event':app.game_store().present_event(turn['id'],event,b) if event and not current_cg and not turn.get('cg_decision') else None}
    if turn.get('cg_decision'):result['cg_action']={'turn_id':turn['id'],**turn['cg_decision']}
    return result

def prepare(app,kind,payload):
    if busy(app):raise ValueError('CG 演出正在占用舞台')
    unread=app.REPLY_TURN.current and not app.REPLY_TURN.current.get('ui_complete')
    if app.ACTIVE_CHAT or unread or app.RUNTIME.snapshot()['speech_active']:raise ValueError('请先读完或停止当前对话')
    cat=catalog(app);b=binding(app);effect={};scene=None;asset=None
    if kind=='scene':
        scene=cat.resolve_scene(payload.get('location_id'),payload.get('time_of_day','unknown'))
    elif kind=='event':
        with connect(app.DB_FILE) as db:
            row=db.execute('SELECT * FROM game_event_instances WHERE instance_id=?',(payload.get('instance_id'),)).fetchone()
        if not row or row['profile_id']!=b['profile_id'] or json.loads(row['binding_json'])!=b or row['status']!='presented':raise ValueError('邀请已失效')
        effect=events.choice_plan(json.loads(row['definition_json']),payload.get('choice_id'))['effect']
        if effect['location_id']:scene=cat.resolve_scene(effect['location_id'],app.game_store().read()['scene']['time_of_day'],auto=True)
        if effect['media_id']:
            if not media_fits(app,effect['media_id'],effect['location_id']):raise ValueError('该媒体不适用于当前角色或地点')
            asset=media.resolve_playback(cat.get('media')['data'],effect['media_id'])
            verify_media(cat,asset)
    else:raise ValueError('未知预加载操作')
    _PREPARED.clear()  # One shared active stage, like existing ReplyTurn.
    token=secrets.token_hex(16)
    _PREPARED[token]={'kind':kind,'payload':payload,'binding':b,'expires':time.monotonic()+300,
        'scene':scene,'media':asset,'model':app.STATE['settings'].get('character_model')}
    return {'prepare_token':token,'scene':public_asset(scene,'locations'),'media':public_asset(asset,'media')}

def public_asset(item,kind):
    if item is None:return None
    return {k:v for k,v in item.items() if k!='relative_path'}|{'url':'/api/game/catalog/file/'+kind+'/'+item['asset_id']}

def media_fits(app,asset_id,location_id=None):
    item=catalog(app).item('media',asset_id)
    card=app.roleplay_bridge.identity()['card_id']
    loc=location_id or app.game_store().read()['scene']['location_id']
    return (not item.get('character_ids') or card in item['character_ids']) and (not item.get('location_ids') or loc in item['location_ids'])

def verify_media(cat,item):
    path=cat.file(item)
    if item['category']=='cg_sequence':cg_sequence.load(cat.root,item)
    elif item['category'] in ('cg_still','cg_frame'):
        from PIL import Image
        with Image.open(path) as im:im.verify()
    elif item['category'] not in ('bgm','se'):raise ValueError('媒体暂不支持播放')
    return path

def commit(app,value):
    p=_PREPARED.get(value.get('prepare_token'))
    if p and p.get('result') and p['expires']>=time.monotonic():
        current=binding(app)
        if any(current[k]!=p['binding'][k] for k in ('profile_id','generation','roleplay_epoch','catalog_epoch')) or p['model']!=app.STATE['settings'].get('character_model'):raise ValueError('预加载所在的存档或角色已变化')
        if p.get('idempotency_key')!=value.get('idempotency_key'):raise ValueError('重试必须使用同一个请求编号')
        return p['result']
    if not p or p['expires']<time.monotonic() or p['binding']!=binding(app) or p['model']!=app.STATE['settings'].get('character_model'):raise ValueError('预加载已失效，请重新准备')
    if value.get('loaded') is not True:raise ValueError('媒体未确认加载，不提交')
    if busy(app):raise ValueError('CG演出正在播放')
    cat=catalog(app)
    if p['scene']:
        cat.resolve_scene(p['scene']['location_id'],p['scene']['time_of_day'],auto=p['kind']=='event')
    def verify(effect):
        result={'scene':public_asset(p['scene'],'locations'),'media':public_asset(p['media'],'media')}
        if p['media']:verify_media(cat,p['media'])
        return result
    if p['kind']=='scene':
        result={'state':app.game_store().move_location(p['binding'],p['scene']['location_id'],p['scene']['time_of_day'],locked=not p.get('automatic',False)),**verify({})}
    else:
        result=app.game_store().choose_event(p['payload']['instance_id'],p['payload']['choice_id'],
            value.get('idempotency_key'),p['binding'],verify)
    if p['media']:result['media']=lease_media(app,p['media'])
    # Retain the preparation until TTL for retry after a lost HTTP response.
    p['result']=result
    p['idempotency_key']=value.get('idempotency_key')
    return result

def touch_signature(app):
    model=app.STATE['settings'].get('character_model')
    ref=app.STATE['manifest'].get('poses',{}).get('neutral')
    if not model or not ref:raise ValueError('当前没有可标注的角色')
    path=checked_file(app.asset_root(),ref);sha=fingerprint_file(path)
    return {'model_id':model,'pose_id':'p_'+sha[:24],'source_hash':sha,'image_url':'/file/'+ref,
        'profile_id':'hit_'+model,'outfit_id':None}

def touch_input(app,value):
    state=app.game_store().read()
    unread=app.REPLY_TURN.current and not app.REPLY_TURN.current.get('ui_complete')
    if not state['toggles']['touch_interaction'] or busy(app) or app.ACTIVE_CHAT or unread:raise ValueError('触摸已关闭或舞台正在对话')
    signature=touch_signature(app);profile=catalog(app).get('touch')['data'].get(signature['model_id'])
    if not profile or profile.get('source_hash')!=signature['source_hash']:raise ValueError('此造型尚无已审核命中区')
    clean={k:v for k,v in profile.items() if k!='source_hash'}
    intent=touch.normalize_touch_message(value,clean,current_model_id=signature['model_id'],current_pose_id=signature['pose_id'])
    if not intent:return {'text':None}
    # Sample the actual source alpha, not just a bounding rectangle.
    from PIL import Image
    with Image.open(checked_file(app.asset_root(),app.STATE['manifest']['poses']['neutral'])) as im:
        rgba=im.convert('RGBA');x=min(rgba.width-1,int(value['x']*rgba.width));y=min(rgba.height-1,int(value['y']*rgba.height))
        if rgba.getpixel((x,y))[3]<32:return {'text':None}
    if not _TOUCH.permit(profile_id=state['profile_id'],region=intent['region'],request_id=intent['request_id'],now=time.monotonic()):raise ValueError('先稍等一下，再与角色互动')
    return {'text':touch.touch_for_llm(intent),'region':intent['region']}


def try_get(handler,path,query):
    from . import app
    if path in ('/gameplay/','/gameplay'):
        handler.static(app.WEB/'gameplay.html','text/html; charset=utf-8');return True
    if path=='/gameplay/ui.js':handler.static(app.WEB/'gameplay_ui.js','text/javascript; charset=utf-8');return True
    if not path.startswith('/api/game/'):return False
    if path.startswith('/api/game/cg/frame/'):
        parts=path.split('/')
        if len(parts)!=7:raise ValueError('CG帧请求无效')
        cat=catalog(app);item=cat.item('media',parts[5])
        if item.get('extension')!='.cgseq':raise ValueError('不是CG演出')
        try:index=int(parts[6])
        except ValueError:raise ValueError('CG帧编号无效') from None
        handler.reply(200,cg_sequence.frame_bytes(cat.root,item,index),'image/png');return True
    if path.startswith('/api/game/catalog/file/'):
        parts=path.split('/')
        if len(parts)!=7 or parts[5] not in ('locations','media'):raise ValueError('素材请求无效')
        cat=catalog(app);item=cat.item(parts[5],parts[6]);file=cat.file(item)
        if item.get('extension')=='.cgseq':
            handler.reply(200,cg_sequence.public(cat.root,item));return True
        if file.suffix.lower() not in ('.png','.jpg','.jpeg','.webp','.wav','.ogg','.mp3'):raise ValueError('该格式仅供索引，不提供播放')
        if file.suffix.lower() in ('.png','.jpg','.jpeg','.webp'):
            from .gameplay_images import checked_image_bytes
            # This endpoint includes the local human-review UI. Approval gates
            # for actual scene/CG execution remain in prepare/commit.
            handler.reply(200,checked_image_bytes(cat.root,item,require_verified=False),'image/png')
        else:handler.static(file)
        return True
    if path=='/api/game/catalog':
        kind=query.get('kind',['locations'])[0]
        if kind not in ('locations','media','events','touch','cg_rules'):raise ValueError('未知目录')
        value=catalog(app).public(kind)
    elif path=='/api/game/locations':
        manual={}
        for x in locations.flattened(catalog(app).get('locations')['data']):
            if not x['verified']:continue
            item=manual.setdefault(x['location_id'],{'location_id':x['location_id'],'display_name':x['location_name'],'times':[]})
            if x['time_of_day'] not in item['times']:item['times'].append(x['time_of_day'])
        value={'items':list(manual.values())}
    elif path=='/api/game/diary':value={'items':app.game_store().diary()}
    elif path=='/api/game/events/active':value={'event':app.game_store().active_event()}
    elif path=='/api/game/interaction':value={'binding':binding(app),'state':app.game_store().read(),'media_busy':busy(app)}
    elif path=='/api/game/cg/state':value={'active':cg_events.active(app),'binding':binding(app)}
    elif path=='/api/game/scene/current':
        scene=app.game_store().read()['scene']
        if scene['location_id']=='unknown':value={'scene':None}
        else:value={'scene':public_asset(catalog(app).resolve_scene(scene['location_id'],scene['time_of_day']),'locations')}
    elif path=='/api/game/touch/profile':value=touch_signature(app)
    elif path=='/api/game/gallery':
        with connect(app.DB_FILE) as db:
            unlocked={r[0] for r in db.execute('SELECT asset_id FROM game_unlocks WHERE profile_id=?',(binding(app)['profile_id'],))}
        value={'items':[x for x in catalog(app).public('media')['items'] if x['verified'] and x['asset_id'] in unlocked and media_fits(app,x['asset_id'])]}
    else:return False
    handler.reply(200,value);return True


def try_post(handler,path,value):
    from . import app
    if not path.startswith('/api/game/'):return False
    if handler.headers.get('Content-Type','').split(';')[0].strip().lower()!='application/json':raise ValueError('玩法API只接受application/json')
    if path.startswith('/api/game/catalog/'):
        if handler.headers.get('Content-Type','').split(';')[0].strip().lower()!='application/json':raise ValueError('只接受JSON')
        cat=catalog(app)
        if path=='/api/game/catalog/scan':result=cat.scan(value.get('kind'))
        elif path=='/api/game/catalog/cg':result=cat.import_cg(value.get('group'),value.get('revision'))
        elif path=='/api/game/catalog/cg_shi':result=cg_events.import_shi(app)
        elif path=='/api/game/catalog/cg_rules':result=cat._save('cg_rules',cg_events.validate_rules(value.get('definitions')),value.get('revision'))
        elif path=='/api/game/catalog/configure':
            review=dict(value.get('review') or {},verified=True)
            result=cat.review(value.get('kind'),review,value.get('revision'))
        elif path=='/api/game/catalog/review':
            if value.get('confirm') is not True:raise ValueError('需要玩家明确确认素材审核')
            result=cat.review(value.get('kind'),value.get('review'),value.get('revision'))
        elif path=='/api/game/catalog/events':result=cat.save_events(value.get('definitions'),value.get('revision'))
        elif path=='/api/game/catalog/touch':
            if value.get('confirm') is not True:raise ValueError('需要玩家确认命中区')
            result=cat.save_hitbox(value.get('profile'),value.get('revision'),touch_signature(app))
        else:return False
        # Never echo internal scan paths back in a review response.
        app.REPLY_TURN.clear()
        if app.ACTIVE_CHAT:app.ACTIVE_CHAT['cancel'].set()
        result={'ok':True,'revision':result['revision']}
    elif path=='/api/game/interaction':
        if busy(app):raise ValueError('请先关闭演出再修改舞台互动设置')
        result={'state':app.game_store().interaction_settings(value.get('binding'),value.get('settings'))}
        app.REPLY_TURN.clear();app.game_store().cancel_events()
    elif path=='/api/game/scene/prepare':result=prepare(app,'scene',value)
    elif path=='/api/game/scene/unlock':
        state=app.game_store().read()
        result={'state':app.game_store().move_location(binding(app),state['scene']['location_id'],state['scene']['time_of_day'],locked=False)}
        app.RUNTIME.unlock_scene()
    elif path=='/api/game/scene/auto':
        state=app.game_store().read();runtime=app.RUNTIME.snapshot()
        allowed=clock.may_auto_transition(scene_locked=state['scene']['lock'] or runtime['scene_lock']['active'],cg_active=busy(app),
            tts_active=runtime['speech_active'],reply_active=bool(app.ACTIVE_CHAT or (app.REPLY_TURN.current and not app.REPLY_TURN.current.get('ui_complete'))),
            manual_choice_pending=bool(app.game_store().active_event()),clock_mode=state['clock_mode'])
        result={'prepared':None}
        if allowed and state['scene']['location_id']!='unknown':
            period=clock.effective_time(state['clock_mode'],game_hour=state['flags'].get('clock_game_hour',12))
            scene=catalog(app).resolve_scene(state['scene']['location_id'],period,auto=True)
            if scene['time_of_day']!=state['scene']['time_of_day']:
                prepared=prepare(app,'scene',{'location_id':scene['location_id'],'time_of_day':period})
                _PREPARED[prepared['prepare_token']]['automatic']=True
                result={'prepared':prepared}
    elif path=='/api/game/event/prepare':result=prepare(app,'event',value)
    elif path=='/api/game/commit':
        result=commit(app,value)
        app.REPLY_TURN.clear()
    elif path=='/api/game/turn/complete':result=complete(app,value)
    elif path=='/api/game/event/dismiss':
        identifier(value.get('instance_id'))
        app.game_store().cancel_events(instance_id=value['instance_id']);result={'ok':True}
    elif path=='/api/game/touch':result=touch_input(app,value)
    elif path=='/api/game/media/begin':
        if busy(app) or app.ACTIVE_CHAT or app.RUNTIME.snapshot()['speech_active']:raise ValueError('舞台正忙，请先停止对话／关闭演出')
        with connect(app.DB_FILE) as db:
            unlocked=db.execute('SELECT 1 FROM game_unlocks WHERE profile_id=? AND asset_id=?',(binding(app)['profile_id'],value.get('asset_id'))).fetchone()
        if not unlocked:raise ValueError('该媒体尚未在本存档解锁')
        if not media_fits(app,value.get('asset_id')):raise ValueError('该媒体不适用于当前角色或地点')
        cat=catalog(app);asset=media.resolve_playback(cat.get('media')['data'],value.get('asset_id'),auto=False);verify_media(cat,asset)
        result={'media':lease_media(app,asset)}
    elif path=='/api/game/cg/preview':
        # Explicit developer/player preview only: no story commit or unlock.
        if value.get('confirm') is not True:raise ValueError('需要玩家明确选择CG测试预览')
        if value.get('binding')!=binding(app):raise ValueError('预览所在存档或设定已改变')
        unread=app.REPLY_TURN.current and not app.REPLY_TURN.current.get('ui_complete')
        if busy(app) or app.ACTIVE_CHAT or unread or app.RUNTIME.snapshot()['speech_active']:raise ValueError('请先读完或停止对话／关闭演出')
        cat=catalog(app);asset=cat.item('media',value.get('asset_id'))
        if asset.get('extension')!='.cgseq':raise ValueError('仅允许预览已导入的CG差分演出')
        cg_sequence.load(cat.root,asset)
        asset=dict(asset,category='cg_sequence')
        result={'media':lease_media(app,asset),'preview_only':True}
    elif path=='/api/game/media/end':
        with connect(app.DB_FILE) as db:db.execute('DELETE FROM game_playback WHERE token=?',(value.get('token'),))
        result={'ok':True}
    elif path=='/api/game/cg/prepare':result=cg_events.prepare(app,value.get('turn_id'))
    elif path=='/api/game/cg/apply':result=cg_events.apply(app,value.get('turn_id'),value.get('loaded'))
    elif path=='/api/game/cg/close':result=cg_events.close(app,value.get('session_id'))
    else:return False
    handler.reply(200,result);return True
