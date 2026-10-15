"""Reviewed local catalogs. No gameplay stats, credentials or inferred approvals.

The registry lives in the existing database. Clients see opaque IDs; every file
read rechecks containment and SHA256. Reviews are explicit local user actions.
"""
from copy import deepcopy
import json
from pathlib import Path
import threading
from .game_db import connect,backup_database
from .gameplay_core import locations,media,touch,events
from . import cg_sequence
from .gameplay_core.common import checked_file,fingerprint_file,identifier,stable_asset_id,safe_candidates,VALID_IMAGE_EXTENSIONS

EMPTY_LOC={'schema':1,'families':{},'unmatched':[],'warnings':[],'total_matched':0}
EMPTY_MEDIA={'schema':1,'assets':[],'count':0}
_MIGRATION=threading.RLock()


def initialize(path):
    # Separate catalog schema version, not a competing GameState/user_version.
    with _MIGRATION,connect(path) as db:
        if db.execute("SELECT name FROM sqlite_master WHERE name='game_catalog'").fetchone():return
        backup_database(path)
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS game_catalog(key TEXT PRIMARY KEY,revision INTEGER NOT NULL,doc TEXT NOT NULL)')
        db.execute("INSERT OR IGNORE INTO game_catalog VALUES('locations',0,?)",(json.dumps(EMPTY_LOC),))
        db.execute("INSERT OR IGNORE INTO game_catalog VALUES('media',0,?)",(json.dumps(EMPTY_MEDIA),))
        db.execute("INSERT OR IGNORE INTO game_catalog VALUES('touch',0,'{}')")
        starters=[]
        for name,title,delta in (('take_break','一起休息一会儿',{'energy':3}),('share_hobby','聊聊最近的爱好',{'trust':1}),('encouragement','互相说句鼓励的话',{'mood':2})):
            starters.append(events.validate_event({'id':name,'title':title,'type':'invitation','enabled':True,
                'triggers':['chat'],'conditions':{},'cooldown':{'turns':5,'seconds':300},
                'choices':[{'id':'accept','label':'好呀','effect':{'stats':delta}},
                           {'id':'decline','label':'这次先不用','effect':{}}]},verified_locations=set(),verified_media=set()))
        db.execute("INSERT OR IGNORE INTO game_catalog VALUES('events',0,?)",(json.dumps(starters,ensure_ascii=False),))
        db.execute('CREATE TABLE game_event_instances(instance_id TEXT PRIMARY KEY,profile_id TEXT NOT NULL,turn_id TEXT NOT NULL UNIQUE,event_id TEXT NOT NULL,status TEXT NOT NULL,binding_json TEXT NOT NULL,definition_json TEXT NOT NULL,result_json TEXT,created_at REAL NOT NULL)')
        db.execute("CREATE UNIQUE INDEX gameplay_pending ON game_event_instances(profile_id) WHERE status='presented'")
        db.execute('CREATE TABLE game_event_choices(instance_id TEXT PRIMARY KEY,choice_id TEXT NOT NULL,idempotency_key TEXT NOT NULL UNIQUE,result_json TEXT NOT NULL)')
        db.execute('CREATE TABLE game_unlocks(profile_id TEXT NOT NULL,asset_id TEXT NOT NULL,PRIMARY KEY(profile_id,asset_id))')
        db.execute('CREATE TABLE game_playback(profile_id TEXT PRIMARY KEY,token TEXT NOT NULL,binding_json TEXT NOT NULL,expires REAL NOT NULL)')
        db.execute('CREATE TABLE game_completed_turns(turn_id TEXT PRIMARY KEY,profile_id TEXT NOT NULL,binding_json TEXT NOT NULL,created_at REAL NOT NULL)')
        db.commit()


class Catalog:
    def __init__(self,path,root):self.path=Path(path);self.root=Path(root).resolve()

    def get(self,key):
        with connect(self.path) as db:
            row=db.execute('SELECT revision,doc FROM game_catalog WHERE key=?',(key,)).fetchone()
        if not row:raise ValueError('目录尚未初始化')
        return {'revision':row['revision'],'data':json.loads(row['doc'])}

    def epoch(self):
        with connect(self.path) as db:return sum(r[0] for r in db.execute('SELECT revision FROM game_catalog'))

    def _save(self,key,value,expected):
        if type(expected) is not int:raise ValueError('目录版本无效，请刷新')
        with connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT revision FROM game_catalog WHERE key=?',(key,)).fetchone()
            if not row or row[0]!=expected:raise ValueError('目录已经更新，请刷新重试')
            db.execute('UPDATE game_catalog SET revision=revision+1,doc=? WHERE key=?',
                       (json.dumps(value,ensure_ascii=False),key));db.commit()
        return {'revision':expected+1,'data':value}

    def scan(self,kind):
        previous=self.get(kind)
        # Root identity is checked on every use, so switching assets_dir cannot
        # reuse a review of a different relative file with coincidentally same name.
        if kind=='locations':
            scanned=locations.scan_backgrounds(self.root)
            # Unrecognized bg filenames must remain reviewable, without inventing
            # a numeric family or suffix meaning. Preserve approvals by hash/ID.
            known={x['relative_path'] for x in locations.flattened(scanned)}
            for relative,path in safe_candidates(self.root,VALID_IMAGE_EXTENSIONS,forbidden_folders=locations.NO_SCAN_FOLDERS):
                if relative in known:continue
                # Actual Amakano3 also has zbg*.jpg and other names in image/bg.
                # Discover those by directory, but do not infer their semantics.
                if not any(p.lower() in ('bg','background','backgrounds') for p in Path(relative).parts[:-1]) and not path.stem.lower().startswith(('bg','zbg')):continue
                sha=fingerprint_file(path)
                aid=stable_asset_id('bg',relative,sha);family='unclassified_'+aid[3:15]
                scanned['families'][family]=[dict(asset_id=aid,relative_path=relative,file_hash=sha,bytes=path.stat().st_size,
                    family=family,suffix='unmatched',verified=False,allow_automatic=False,time_of_day='unknown',location_id=None,location_name=None,default=False)]
            value=locations.migrate_unchanged_reviews(previous['data'],scanned)
        elif kind=='media':
            value=media.merge_unchanged_media(previous['data'],media.scan_media(self.root))
            # Generated bundles are intentionally excluded by the raw scanner.
            # Retain only explicitly imported, still-pinned sequences.
            for item in previous['data']['assets']:
                if item.get('extension')=='.cgseq':
                    try:cg_sequence.load(self.root,item)
                    except (OSError,ValueError,KeyError):continue
                    value['assets'].append(deepcopy(item))
            value['count']=len(value['assets'])
            old={x['asset_id']:x for x in previous['data']['assets'] if x['verified']}
            for x in value['assets']:
                if x['verified'] and x['asset_id'] in old:x['character_ids']=old[x['asset_id']].get('character_ids',[])
        else:raise ValueError('未知扫描类别')
        return self._save(kind,value,previous['revision'])

    def review(self,kind,review,expected):
        previous=self.get(kind)
        if type(expected) is not int or previous['revision']!=expected:raise ValueError('目录已变化，请刷新')
        item=self.item(kind,review.get('asset_id'))
        self.file(item)  # Reject a stale scan before accepting human approval.
        if kind=='locations':value=locations.apply_reviews(previous['data'],[review])
        elif kind=='media':
            if item.get('extension')=='.cgseq':cg_sequence.load(self.root,item)
            elif (self.root/Path(item['relative_path']).with_suffix('.ipt')).is_file():
                raise ValueError('这是差分小图，请先导入CG演出并审核合成结果，而非直接当作完整CG')
            roles=review.get('character_ids',[])
            if not isinstance(roles,list) or len(roles)>20:raise ValueError('适用角色卡列表无效')
            for role in roles:
                identifier(role)
                with connect(self.path) as db:
                    if not db.execute('SELECT 1 FROM rp_cards WHERE id=?',(role,)).fetchone():raise ValueError('适用角色卡不存在')
            value=media.review_media(previous['data'],[{k:v for k,v in review.items() if k!='character_ids'}])
            next(x for x in value['assets'] if x['asset_id']==review['asset_id'])['character_ids']=roles
        else:raise ValueError('未知审核类别')
        return self._save(kind,value,expected)

    def item(self,kind,asset_id):
        identifier(asset_id)
        doc=self.get(kind)['data']
        items=locations.flattened(doc) if kind=='locations' else doc['assets']
        for item in items:
            if item['asset_id']==asset_id:return item
        raise ValueError('素材ID不存在；请重新扫描')

    def file(self,item):
        try:path=checked_file(self.root,item['relative_path'])
        except (OSError,ValueError):raise ValueError('素材缺失或不在允许的目录内，请重新扫描') from None
        if fingerprint_file(path)!=item['file_hash']:raise ValueError('素材内容已变化，需要重新扫描审核')
        return path

    def public(self,kind):
        value=self.get(kind)
        if kind not in ('locations','media'):return value
        items=(locations.flattened(value['data']) if kind=='locations' else value['data']['assets'])
        # File paths and scan warnings (which also contain paths) stay server-side.
        safe=[]
        for item in items:
            entry={k:deepcopy(v) for k,v in item.items() if k!='relative_path'}
            entry['filename']=Path(item['relative_path']).name
            entry['preview_url']='/api/game/catalog/file/'+kind+'/'+item['asset_id']
            if item.get('extension')=='.cgseq':
                entry['sequence_url']=entry['preview_url']
                entry['preview_url']='/api/game/cg/frame/'+item['asset_id']+'/0'
            safe.append(entry)
        return {'revision':value['revision'],'items':safe,'count':len(safe)}

    def import_cg(self,group,expected):
        previous=self.get('media')
        if type(expected) is not int or previous['revision']!=expected:raise ValueError('媒体目录已改变，请刷新')
        item=cg_sequence.build(self.root,group)
        value=previous['data']
        # Reimporting unchanged data preserves explicit reviews. Changed inputs
        # get a new ID, with no transfer of approval or unlocks.
        if any(x['asset_id']==item['asset_id'] for x in value['assets']):return previous
        value['assets']=[x for x in value['assets'] if not (x.get('extension')=='.cgseq' and x.get('group')==group)]
        value['assets'].append(item);value['count']=len(value['assets'])
        return self._save('media',value,expected)

    def resolve_scene(self,location_id,time_of_day,auto=False):
        item=locations.resolve_background(self.get('locations')['data'],location_id,time_of_day,auto=auto)
        if not item:raise ValueError('地点没有匹配的已审核背景')
        path=self.file(item)
        from PIL import Image
        with Image.open(path) as image:image.verify()
        return {k:v for k,v in item.items() if k!='relative_path'}

    def save_hitbox(self,value,expected,signature):
        profile=touch.validate_hitbox_profile(value)
        if not profile['verified']:raise ValueError('命中区必须经玩家人工确认')
        if profile['model_id']!=signature['model_id'] or profile['pose_id']!=signature['pose_id']:
            raise ValueError('当前模型已改变，请重新标注')
        previous=self.get('touch');data=previous['data']
        data[profile['model_id']]=dict(profile,source_hash=signature['source_hash'])
        return self._save('touch',data,expected)

    def save_events(self,definitions,expected):
        if not isinstance(definitions,list) or len(definitions)>100:raise ValueError('事件定义必须为最多100项数组')
        locs={x['location_id'] for x in locations.flattened(self.get('locations')['data']) if x['verified']}
        assets=media.playable_ids(self.get('media')['data'])
        clean=[events.validate_event(x,verified_locations=locs,verified_media=assets) for x in definitions]
        for event in clean:
            declines=[x for x in event['choices'] if x['id']=='decline']
            if not declines or any(any(x['effect'].get(k) for k in ('stats','set_flags','milestone','location_id','media_id')) for x in declines):
                raise ValueError('每个事件必须提供无属性/场景/媒体副作用的 decline 选项')
        if len({x['id'] for x in clean})!=len(clean):raise ValueError('事件ID重复')
        return self._save('events',clean,expected)
