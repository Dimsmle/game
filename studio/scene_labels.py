"""User-supplied visual location table (2026-10-15), not verified original canon."""
import hashlib
import json
from pathlib import Path
from .game_db import connect,backup_database

NAMES=dict(zip(
    '01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 30 31 32 33 34 35 36 37 38 40 81 82 99'.split(),
    '鸟居街口 河岸商街 海面 沿海公路 海边 防波堤 校门 教室 校园走廊 观景台 咖啡厅 水族外馆 水族内馆 日式中庭 露天温泉 餐厨 榻米卧室 书房 双床客房 单床客房 床幔客房 小卧室 空客房 庭院 露台餐厅 神社前院 挂轴客房 河畔 参道商街 古镇街道 竹林小径 寺旁参道 神社广场 山间商街 榻米客房 客房走廊 礼品店 餐馆卡座 山谷窗景 天空'.split()))
NAMES={'bg'+k:v for k,v in NAMES.items()}
# Existing schema tags retained; UI labels explicitly describe these four slots.
TIMES={'a':'morning','b':'day','c':'evening','d':'night'}

def install(app):
    """One-shot, backed-up labeling. Later edits and rescans are not overwritten."""
    from .gameplay import catalog
    cat=catalog(app);root=cat.root
    if not any((root/base/'image/bg').is_dir() for base in ('assets','assets_pfs_002','assets_pfs_main')):return False
    marker=hashlib.sha256(str(root).encode()).hexdigest()
    with connect(app.DB_FILE) as db:
        row=db.execute("SELECT doc FROM game_catalog WHERE key='scene_labels_v1'").fetchone()
    if row and json.loads(row[0]).get('root')==marker:return False
    backup_database(app.DB_FILE)
    doc=cat.scan('locations');data=doc['data']
    for family,items in data['families'].items():
        if family not in NAMES:continue
        # The first suffix letter is composition, the second is the time slot.
        ordered=sorted(items,key=lambda x:(x['suffix'][0]!='a',Path(x['relative_path']).stem.startswith('zbg'),x['suffix'],x['relative_path']))
        for item in items:
            slot=TIMES.get(item['suffix'][1],'unknown')
            item.update(verified=True,location_id=family,location_name=NAMES[family],time_of_day=slot,
                        allow_automatic=slot!='unknown',default=item is ordered[0])
    cat._save('locations',data,doc['revision'])
    with connect(app.DB_FILE) as db:db.execute("INSERT OR REPLACE INTO game_catalog VALUES('scene_labels_v1',0,?)",(json.dumps({'root':marker}),))
    return True

def prompt(app):
    from .gameplay import catalog
    from .gameplay_core.locations import locations_for_llm
    allowed=[x for x in locations_for_llm(catalog(app).get('locations')['data']) if x['location_id']!='bg99']
    return ('\n地点导演：仅在玩家明确提出去某地点、角色接受时，返回顶层 scene_proposal={"location_id":"合法地点ID"}；'
            '否则null。回忆、否定、假设不是出行。不改时间，不虚构地点。程序将展示玩家确认选项，确认后才换背景。合法地点：'
            +json.dumps([{'location_id':x['location_id'],'name':x['display_name']} for x in allowed],ensure_ascii=False))

def proposal(app,value):
    from .gameplay import catalog
    from .gameplay_core.locations import locations_for_llm
    if not isinstance(value,dict) or set(value)!={'location_id'}:return None
    loc=value['location_id']
    if not isinstance(loc,str) or loc=='bg99' or loc==app.game_store().read()['scene']['location_id']:return None
    item=next((x for x in locations_for_llm(catalog(app).get('locations')['data']) if x['location_id']==loc),None)
    if not item:return None
    from .gameplay_core.events import validate_event
    return validate_event({'id':'travel_'+loc,'title':'前往'+item['display_name'],'type':'invitation','enabled':True,
        'triggers':['chat'],'conditions':{},'cooldown':{'turns':0,'seconds':0},
        'choices':[{'id':'accept','label':'出发','effect':{'location_id':loc}},
                   {'id':'decline','label':'留在这里','effect':{}}]},verified_locations={loc},verified_media=set())
