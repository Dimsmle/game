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
