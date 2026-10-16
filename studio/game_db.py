"""Additive SQLite migration and transactional P1 profile store."""
from contextlib import contextmanager
from datetime import datetime,timedelta
import json
from pathlib import Path
import sqlite3
import threading
import uuid
from . import game_state as schema

VERSION=1
_migration_lock=threading.RLock()


@contextmanager
def connect(path):
    db=sqlite3.connect(path,timeout=5,isolation_level=None)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA busy_timeout=5000')
    try:yield db
    finally:
        if db.in_transaction:db.rollback()
        db.close()


def backup_database(path):
    path=Path(path)
    target=path.parent/'backups'/('history_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex+'.sqlite3')
    target.parent.mkdir(parents=True,exist_ok=True)
    with connect(path) as source:
        destination=sqlite3.connect(target)
        try:source.backup(destination)
        finally:destination.close()
    return target


def migrate(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with _migration_lock:
        existed=path.is_file() and path.stat().st_size>0
        with connect(path) as db:
            version=db.execute('PRAGMA user_version').fetchone()[0]
            if version>VERSION:raise ValueError('数据库来自较新版本，停止迁移以保护数据')
            if version==VERSION:return None
            backup=backup_database(path) if existed else None
            db.execute('BEGIN IMMEDIATE')
            if db.execute('PRAGMA user_version').fetchone()[0]==VERSION:
                db.rollback();return backup
            statements=[
                'CREATE TABLE game_profiles(id TEXT PRIMARY KEY,character_id TEXT NOT NULL,display_name TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)',
                'CREATE TABLE game_state(profile_id TEXT PRIMARY KEY REFERENCES game_profiles(id),revision INTEGER NOT NULL,schema_version INTEGER NOT NULL,state_json TEXT NOT NULL,updated_at TEXT NOT NULL)',
                'CREATE TABLE game_session(singleton INTEGER PRIMARY KEY CHECK(singleton=1),profile_id TEXT NOT NULL REFERENCES game_profiles(id),generation INTEGER NOT NULL DEFAULT 0)',
                'CREATE TABLE game_journal(id INTEGER PRIMARY KEY AUTOINCREMENT,profile_id TEXT NOT NULL REFERENCES game_profiles(id),event_id TEXT NOT NULL,kind TEXT NOT NULL,payload_json TEXT NOT NULL,idempotency_key TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(profile_id,idempotency_key))',
                # Future event schema only; P1 exposes no event execution route.
                'CREATE TABLE event_instances(instance_id TEXT PRIMARY KEY,profile_id TEXT NOT NULL REFERENCES game_profiles(id),event_id TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,result_json TEXT)',
                'CREATE UNIQUE INDEX one_active_event ON event_instances(profile_id) WHERE status IN (\'presented\',\'applying\')',
                'CREATE TABLE event_choices(instance_id TEXT PRIMARY KEY REFERENCES event_instances(instance_id),choice_id TEXT NOT NULL,idempotency_key TEXT NOT NULL UNIQUE,outcome_json TEXT NOT NULL,created_at TEXT NOT NULL)']
            for statement in statements:db.execute(statement)
            now=datetime.now().isoformat()
            db.execute('INSERT INTO game_profiles VALUES(?,?,?,?,?)',('default','legacy_character','原有存档',now,now))
            db.execute('INSERT INTO game_state VALUES(?,?,?,?,?)',('default',0,1,json.dumps(schema.new_state(),ensure_ascii=False),now))
            db.execute('INSERT INTO game_session VALUES(1,?,0)',('default',))
            for name,ddl in (
                ('messages','id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,role TEXT NOT NULL,content TEXT NOT NULL,source TEXT NOT NULL DEFAULT \'user\''),
                ('memories','id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,content TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1')):
                db.execute(f'CREATE TABLE IF NOT EXISTS {name}({ddl})')
                columns={row['name'] for row in db.execute(f'PRAGMA table_info({name})')}
                if 'profile_id' not in columns:db.execute(f"ALTER TABLE {name} ADD COLUMN profile_id TEXT NOT NULL DEFAULT 'default'")
                db.execute(f'CREATE INDEX {name}_profile ON {name}(profile_id,id)')
            db.execute(f'PRAGMA user_version={VERSION}')
            db.commit()
            return backup


class GameStore:
    def __init__(self,path):self.path=Path(path)

    @staticmethod
    def _state(db,profile_id):
        row=db.execute('SELECT * FROM game_state WHERE profile_id=?',(schema.identifier(profile_id),)).fetchone()
        if row is None:raise ValueError('存档不存在')
        value=schema.validate_state(json.loads(row['state_json']))
        if value['profile_id']!=profile_id or value['revision']!=row['revision']:raise ValueError('存档一致性检查失败')
        return value

    def session(self):
        with connect(self.path) as db:return dict(db.execute('SELECT profile_id,generation FROM game_session WHERE singleton=1').fetchone())

    def snapshot(self):
        with connect(self.path) as db:
            db.execute('BEGIN')
            session=dict(db.execute('SELECT profile_id,generation FROM game_session WHERE singleton=1').fetchone())
            return session,self._state(db,session['profile_id'])

    def read(self,profile_id=None):
        with connect(self.path) as db:
            if profile_id is None:profile_id=db.execute('SELECT profile_id FROM game_session WHERE singleton=1').fetchone()[0]
            return self._state(db,profile_id)

    def profiles(self):
        with connect(self.path) as db:
            return [dict(row) for row in db.execute('SELECT id,character_id,display_name FROM game_profiles ORDER BY created_at,id')]

    def create(self,profile_id,display_name,character_id='legacy_character'):
        schema.identifier(profile_id);schema.identifier(character_id)
        if not isinstance(display_name,str) or not 1<=len(display_name.strip())<=60:raise ValueError('存档名称需为 1–60 字')
        with connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT count(*) FROM game_profiles').fetchone()[0]>=30:raise ValueError('最多 30 个存档')
            if db.execute('SELECT 1 FROM game_profiles WHERE id=?',(profile_id,)).fetchone():raise ValueError('存档 ID 已存在')
            now=datetime.now().isoformat();state=schema.new_state(profile_id,character_id)
            db.execute('INSERT INTO game_profiles VALUES(?,?,?,?,?)',(profile_id,character_id,display_name.strip(),now,now))
            db.execute('INSERT INTO game_state VALUES(?,?,?,?,?)',(profile_id,0,1,json.dumps(state,ensure_ascii=False),now))
            db.commit();return state

    def select(self,profile_id):
        with connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE');value=self._state(db,profile_id)
            db.execute('UPDATE game_session SET generation=generation+1,profile_id=? WHERE singleton=1',(profile_id,))
            db.commit();return value

    def commit_effect(self,profile_id,expected_revision,event_id,idempotency_key,delta,*,milestone=None,now=None):
        """INTERNAL ONLY. Future EventCommitService supplies reviewed local rules.

        No HTTP endpoint or model JSON calls this method in P1.
        """
        schema.identifier(event_id);schema.identifier(idempotency_key);schema.integer(expected_revision,0,2**53-1)
        schema.validate_delta(delta,milestone)
        now=now or datetime.now();date=now.date().isoformat()
        request={'event_id':event_id,'delta':delta,'milestone':milestone}
        with connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT payload_json FROM game_journal WHERE profile_id=? AND idempotency_key=?',(profile_id,idempotency_key)).fetchone()
            if old:
                saved=json.loads(old[0])
                if saved['request']!=request:raise ValueError('重复提交编号不能用于不同效果')
                return saved['state']
            state=self._state(db,profile_id)
            if state['revision']!=expected_revision:raise ValueError('存档版本已变化，请重试')
            used={key:0 for key in schema.RANGES}
            for row in db.execute('SELECT payload_json FROM game_journal WHERE profile_id=? AND created_at>=? AND created_at<?',(profile_id,date,(now.date()+timedelta(days=1)).isoformat())):
                for key,amount in json.loads(row[0]).get('applied',{}).items():used[key]+=max(0,amount)
            value,applied=schema.apply_delta(state,delta,used,milestone)
            payload={'request':request,'applied':applied,'before':state['stats'],'state':value}
            db.execute('UPDATE game_state SET revision=?,state_json=?,updated_at=? WHERE profile_id=? AND revision=?',
                       (value['revision'],json.dumps(value,ensure_ascii=False),now.isoformat(),profile_id,expected_revision))
            db.execute('INSERT INTO game_journal(profile_id,event_id,kind,payload_json,idempotency_key,created_at) VALUES(?,?,?,?,?,?)',
                       (profile_id,event_id,'local_rule',json.dumps(payload,ensure_ascii=False),idempotency_key,now.isoformat()))
            db.commit();return value

    def gameplay_binding(self,db):
        session=dict(db.execute('SELECT profile_id,generation FROM game_session WHERE singleton=1').fetchone())
        state=self._state(db,session['profile_id'])
        epoch=int(db.execute("SELECT value FROM rp_meta WHERE key='epoch'").fetchone()[0])
        catalog=sum(r[0] for r in db.execute('SELECT revision FROM game_catalog'))
        return dict(session,revision=state['revision'],roleplay_epoch=epoch,catalog_epoch=catalog)

    def edit_stats(self,binding,stats):
        """Explicit player editor only; never reachable from a model intention."""
        if not isinstance(stats,dict) or set(stats)!=set(schema.RANGES):raise ValueError('需要完整的四项属性')
        for key,(low,high) in schema.RANGES.items():schema.integer(stats[key],low,high)
        backup_database(self.path)
        with connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            if self.gameplay_binding(db)!=binding:raise ValueError('存档已变化，请刷新属性')
            state=self._state(db,binding['profile_id']);before=dict(state['stats'])
            state['stats']=dict(stats);state['revision']+=1;schema.validate_state(state)
            now=datetime.now().isoformat()
            db.execute('UPDATE game_state SET revision=?,state_json=?,updated_at=? WHERE profile_id=?',(state['revision'],json.dumps(state),now,binding['profile_id']))
            db.execute('INSERT INTO game_journal(profile_id,event_id,kind,payload_json,idempotency_key,created_at) VALUES(?,?,?,?,?,?)',
                (binding['profile_id'],'player_stats_editor','manual_stats',json.dumps({'before':before,'after':stats}),uuid.uuid4().hex,now))
            db.commit();return state

    def move_location(self,binding,location_id,time_of_day,*,locked=True):
        """Reviewed coordinator only; not an arbitrary client state endpoint."""
        schema.identifier(location_id)
        if time_of_day not in ('unknown','morning','day','evening','night') or type(locked) is not bool:raise ValueError('场景状态无效')
        with connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            if self.gameplay_binding(db)!=binding:raise ValueError('场景准备已过期，请重试')
            state=self._state(db,binding['profile_id'])
            state['scene']={'location_id':location_id,'time_of_day':time_of_day,'lock':locked}
            state['revision']+=1;schema.validate_state(state)
            db.execute('UPDATE game_state SET revision=?,state_json=?,updated_at=? WHERE profile_id=?',
                (state['revision'],json.dumps(state,ensure_ascii=False),datetime.now().isoformat(),binding['profile_id']))
            db.commit();return state

    def present_event(self,turn_id,event,binding):
        """Only called after final sentence activation + display/TTS ACK."""
        schema.identifier(turn_id)
        with connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            if self.gameplay_binding(db)!=binding:raise ValueError('邀请所在的存档或设定已失效')
            row=db.execute('SELECT * FROM game_event_instances WHERE turn_id=?',(turn_id,)).fetchone()
            if row:
                if row['status']!='presented':raise ValueError('邀请已取消或结束')
                return self._public_event(row)
            instance='e_'+uuid.uuid4().hex
            import time
            db.execute('INSERT INTO game_event_instances VALUES(?,?,?,?,?,?,?,?,?)',
                (instance,binding['profile_id'],turn_id,event['id'],'presented',json.dumps(binding),json.dumps(event,ensure_ascii=False),None,time.time()))
            db.commit()
        return self.active_event()

    @staticmethod
    def _public_event(row):
        event=json.loads(row['definition_json'])
        return {'instance_id':row['instance_id'],'event_id':event['id'],'title':event['title'],
                'choices':[{'id':c['id'],'label':c['label']} for c in event['choices']]}

    def active_event(self):
        import time
        with connect(self.path) as db:
            binding=self.gameplay_binding(db)
            row=db.execute("SELECT * FROM game_event_instances WHERE profile_id=? AND status='presented'",(binding['profile_id'],)).fetchone()
            if not row or json.loads(row['binding_json'])!=binding or time.time()-row['created_at']>900:return None
            return self._public_event(row)

    def cancel_events(self,turn_id=None,instance_id=None):
        with connect(self.path) as db:
            sql="UPDATE game_event_instances SET status='cancelled' WHERE profile_id=(SELECT profile_id FROM game_session WHERE singleton=1) AND status='presented'"
            params=[]
            if turn_id is not None:sql+=' AND turn_id=?';params.append(schema.identifier(turn_id))
            if instance_id is not None:sql+=' AND instance_id=?';params.append(schema.identifier(instance_id))
            db.execute(sql,params)

    def choose_event(self,instance,choice,key,binding,verify_resources):
        """One authority/transaction for choice, daily caps, location, flags and diary."""
        from .gameplay_core import events
        import time
        schema.identifier(instance);schema.identifier(choice);schema.identifier(key)
        with connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM game_event_instances WHERE instance_id=?',(instance,)).fetchone()
            if not row or row['profile_id']!=binding['profile_id']:raise ValueError('邀请不属于当前存档')
            session=dict(db.execute('SELECT profile_id,generation FROM game_session WHERE singleton=1').fetchone())
            if any(binding[k]!=session[k] for k in ('profile_id','generation')):raise ValueError('档案已切换')
            old=db.execute('SELECT * FROM game_event_choices WHERE instance_id=? OR idempotency_key=?',(instance,key)).fetchone()
            if old:
                if old['instance_id']!=instance or old['choice_id']!=choice or old['idempotency_key']!=key:raise ValueError('重复提交编号或选项不一致')
                return json.loads(old['result_json'])
            if self.gameplay_binding(db)!=binding or json.loads(row['binding_json'])!=binding:raise ValueError('邀请版本已失效')
            if row['status']!='presented' or time.time()-row['created_at']>900:raise ValueError('邀请已结束或过期')
            event=json.loads(row['definition_json']);effect=events.choice_plan(event,choice)['effect']
            media_result=verify_resources(effect)
            state=self._state(db,binding['profile_id']);now=datetime.now();used={k:0 for k in schema.RANGES}
            for saved in db.execute('SELECT payload_json FROM game_journal WHERE profile_id=? AND created_at>=? AND created_at<?',
                    (binding['profile_id'],now.date().isoformat(),(now.date()+timedelta(days=1)).isoformat())):
                for k,amount in json.loads(saved[0]).get('applied',{}).items():used[k]+=max(0,amount)
            value,applied=schema.apply_delta(state,effect['stats'],used,effect.get('milestone'))
            value['flags'].update(effect['set_flags'])
            # Decline is guaranteed by the reviewed event schema/coordinator to have no effects.
            if choice!='decline' and event.get('one_shot_flag'):value['flags'][event['one_shot_flag']]=True
            if effect['location_id']:
                value['scene']={'location_id':effect['location_id'],'time_of_day':state['scene']['time_of_day'] if state['scene']['time_of_day']!='unknown' else 'morning','lock':True}
            schema.validate_state(value)
            result={'instance_id':instance,'event_id':event['id'],'choice_id':choice,'state':value,'applied':applied,**media_result}
            payload={'applied':applied,'state':value,'event_title':event['title'],'choice_id':choice,'choice_label':next(c['label'] for c in event['choices'] if c['id']==choice)}
            db.execute('UPDATE game_state SET revision=?,state_json=?,updated_at=? WHERE profile_id=?',
                (value['revision'],json.dumps(value,ensure_ascii=False),now.isoformat(),binding['profile_id']))
            db.execute('INSERT INTO game_journal(profile_id,event_id,kind,payload_json,idempotency_key,created_at) VALUES(?,?,?,?,?,?)',
                (binding['profile_id'],event['id'],'player_choice',json.dumps(payload,ensure_ascii=False),key,now.isoformat()))
            db.execute('INSERT INTO game_event_choices VALUES(?,?,?,?)',(instance,choice,key,json.dumps(result,ensure_ascii=False)))
            db.execute("UPDATE game_event_instances SET status='resolved',result_json=? WHERE instance_id=?",(json.dumps(result,ensure_ascii=False),instance))
            if effect['media_id']:db.execute('INSERT OR IGNORE INTO game_unlocks VALUES(?,?)',(binding['profile_id'],effect['media_id']))
            db.commit();return result

    def diary(self,limit=20):
        schema.integer(limit,1,100)
        with connect(self.path) as db:
            profile=db.execute('SELECT profile_id FROM game_session WHERE singleton=1').fetchone()[0]
            rows=db.execute("SELECT event_id,payload_json,created_at FROM game_journal WHERE profile_id=? AND kind='player_choice' ORDER BY id DESC LIMIT ?",(profile,limit)).fetchall()
            return [dict(event_id=r['event_id'],at=r['created_at'],**{k:v for k,v in json.loads(r['payload_json']).items() if k in ('choice_id','event_title','choice_label')}) for r in reversed(rows)]

    def interaction_settings(self,binding,value):
        if not isinstance(value,dict) or set(value)-{'proactive_events','touch_interaction','clock_mode','game_hour'} or not {'proactive_events','touch_interaction','clock_mode'}<=set(value):raise ValueError('互动设置字段无效')
        if any(type(value[k]) is not bool for k in ('proactive_events','touch_interaction')) or value['clock_mode'] not in ('manual','system','game','off'):raise ValueError('互动设置值无效')
        with connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            if self.gameplay_binding(db)!=binding:raise ValueError('存档已变化')
            state=self._state(db,binding['profile_id'])
            if 'game_hour' in value:state['flags']['clock_game_hour']=schema.integer(value['game_hour'],0,23)
            state['toggles']={k:value[k] for k in ('proactive_events','touch_interaction')};state['clock_mode']=value['clock_mode'];state['revision']+=1
            schema.validate_state(state)
            db.execute('UPDATE game_state SET revision=?,state_json=?,updated_at=? WHERE profile_id=?',(state['revision'],json.dumps(state),datetime.now().isoformat(),binding['profile_id']))
            db.commit();return state
