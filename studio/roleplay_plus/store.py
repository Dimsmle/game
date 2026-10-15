"""SQLite-backed roleplay, state, and controlled event updates.

All new tables use rp_* names, so ongoing Codex game-state migrations are not
overwritten. This module never mutates existing messages/memories/settings.
"""
from __future__ import annotations

from contextlib import contextmanager, closing
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import sqlite3
import threading
import uuid

from . import domain

def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def dumps(value):
    return json.dumps(value,ensure_ascii=False,separators=(",",":"),sort_keys=True)

def obj(row,col="doc"):
    return json.loads(row[col]) if row else None

EVENTS={
    "take_break":{"title":"一起休息一会儿","description":"稍作休息，慢慢恢复精神。",
                  "effects":{"mood":3,"energy":8},"milestone":None},
    "share_hobby":{"title":"聊聊彼此的爱好","description":"分享一件最近喜欢的事。",
                   "effects":{"affection":1,"trust":1,"mood":2},"milestone":None},
    "keep_promise":{"title":"兑现小小的约定","description":"一起完成早已商量好的小约定。",
                    "effects":{"affection":2,"trust":3,"mood":3},"milestone":"promise_kept"},
}

class RoleplayStore:
    def __init__(self, db_path):
        self.path=Path(db_path)
        self._guard=threading.RLock()

    @contextmanager
    def connect(self,write=False):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        conn=sqlite3.connect(str(self.path),timeout=5,isolation_level=None)
        conn.row_factory=sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            if write:conn.execute("BEGIN IMMEDIATE")
            yield conn
            if write:conn.commit()
        except Exception:
            if write:conn.rollback()
            raise
        finally:conn.close()

    def initialize(self,settings=None):
        settings=settings or {}
        with self._guard:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            backup=None
            if self.path.exists() and self.path.stat().st_size:
                with self.connect() as db:
                    existing={r[0] for r in db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'")}
                if "rp_meta" not in existing and existing:
                    folder=self.path.parent/"roleplay_backups"
                    folder.mkdir(parents=True,exist_ok=True)
                    name=datetime.now().strftime("%Y%m%d_%H%M%S")
                    path=folder/f"before_roleplay_{name}.sqlite3"
                    n=1
                    while path.exists():
                        path=folder/f"before_roleplay_{name}_{n}.sqlite3";n+=1
                    with closing(sqlite3.connect(str(self.path))) as src,closing(sqlite3.connect(str(path))) as dst:
                        src.backup(dst)
                    backup=str(path)
            # DDL and seeds must roll back together; executescript commits early.
            with self.connect(write=True) as db:
                schema="""
                    CREATE TABLE IF NOT EXISTS rp_meta(
                      key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS rp_cards(
                      id TEXT PRIMARY KEY, revision INTEGER NOT NULL, doc TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS rp_personas(
                      id TEXT PRIMARY KEY, revision INTEGER NOT NULL, doc TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS rp_presets(
                      id TEXT PRIMARY KEY, revision INTEGER NOT NULL, builtin INTEGER NOT NULL DEFAULT 0, doc TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS rp_lore(
                      id TEXT NOT NULL, card_id TEXT NOT NULL, revision INTEGER NOT NULL,
                      doc TEXT NOT NULL, PRIMARY KEY(id,card_id));
                    CREATE TABLE IF NOT EXISTS rp_bindings(
                      profile_id TEXT PRIMARY KEY, card_id TEXT NOT NULL,
                      persona_id TEXT, preset_id TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS rp_state(
                      profile_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, doc TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS rp_events(
                      instance_id TEXT PRIMARY KEY, profile_id TEXT NOT NULL,
                      event_id TEXT NOT NULL, status TEXT NOT NULL, choice_id TEXT,
                      result_json TEXT, created_at TEXT NOT NULL, resolved_at TEXT);
                    CREATE TABLE IF NOT EXISTS rp_choices(
                      idempotency_key TEXT PRIMARY KEY, instance_id TEXT NOT NULL UNIQUE,
                      result_json TEXT NOT NULL, created_at TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS rp_journal(
                      id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id TEXT NOT NULL,
                      event_id TEXT NOT NULL, choice_id TEXT NOT NULL,
                      payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
                """
                for statement in schema.split(';'):
                    if statement.strip():db.execute(statement)
                if db.execute("SELECT value FROM rp_meta WHERE key='epoch'").fetchone() is None:
                    db.execute("INSERT INTO rp_meta(key,value) VALUES('epoch','0')")
                if db.execute("SELECT id FROM rp_cards WHERE id='legacy_character'").fetchone() is None:
                    initial=domain.initial_card(settings)
                    db.execute("INSERT INTO rp_cards(id,revision,doc) VALUES(?,1,?)",
                               (initial["card_id"],dumps(initial)))
                for built in domain.builtin_presets():
                    db.execute("INSERT OR IGNORE INTO rp_presets VALUES(?,1,1,?)",
                               (built["preset_id"],dumps(built)))
                db.execute("INSERT OR IGNORE INTO rp_personas VALUES('default_player',1,?)",
                           (dumps(domain.persona({"persona_id":"default_player","name":"玩家",
                                                   "description":"","share_with_llm":False})),))
                db.execute("INSERT OR IGNORE INTO rp_bindings VALUES('default','legacy_character',NULL,'immersive_galgame')")
                db.execute("INSERT OR IGNORE INTO rp_state VALUES('default',0,?)",
                           (dumps(domain.new_state()),))
            return {"ok":True,"backup":backup}

    def _epoch(self,db):
        db.execute("UPDATE rp_meta SET value=CAST(value AS INTEGER)+1 WHERE key='epoch'")

    def epoch(self):
        with self.connect() as db:
            row=db.execute("SELECT value FROM rp_meta WHERE key='epoch'").fetchone()
            return int(row[0]) if row else 0

    def _revision_write(self,db,table,key,id_value,doc,expected_revision=None):
        prev=db.execute(f"SELECT revision FROM {table} WHERE {key}=?",(id_value,)).fetchone()
        if prev:
            if expected_revision is None or (not domain._is_int(expected_revision)) or expected_revision!=prev[0]:
                raise ValueError("数据已更新，请刷新后再保存（revision 不匹配）")
            revision=prev[0]+1
            db.execute(f"UPDATE {table} SET revision=?, doc=? WHERE {key}=?",
                       (revision,dumps(doc),id_value))
        else:
            if expected_revision not in (None,0):
                raise ValueError("新数据的 revision 必须为 0")
            revision=1
            db.execute(f"INSERT INTO {table}({key},revision,doc) VALUES(?,?,?)",
                       (id_value,revision,dumps(doc)))
        self._epoch(db)
        return revision

    def _item(self,table,key,value):
        with self.connect() as db:
            row=db.execute(f"SELECT doc,revision FROM {table} WHERE {key}=?",(value,)).fetchone()
        if not row:raise ValueError("找不到对应条目")
        return {"revision":row["revision"],"data":obj(row)}

    def list_cards(self):
        with self.connect() as db:
            rows=db.execute("SELECT id,revision,doc FROM rp_cards ORDER BY id").fetchall()
        return [{"id":r["id"],"name":obj(r)["name"],"revision":r["revision"]} for r in rows]

    def get_card(self,card_id):
        return self._item("rp_cards","id",domain.ident(card_id,"角色卡 ID"))

    def save_card(self,value,expected_revision=None):
        doc=domain.card(value)
        with self.connect(write=True) as db:
            revision=self._revision_write(db,"rp_cards","id",doc["card_id"],doc,expected_revision)
        return {"id":doc["card_id"],"revision":revision,"data":doc}

    def list_personas(self):
        with self.connect() as db:
            rows=db.execute("SELECT id,revision,doc FROM rp_personas ORDER BY id").fetchall()
        return [{"id":r["id"],"name":obj(r)["name"],"revision":r["revision"]} for r in rows]

    def get_persona(self,persona_id):
        return self._item("rp_personas","id",domain.ident(persona_id,"玩家 ID"))

    def save_persona(self,value,expected_revision=None):
        doc=domain.persona(value)
        with self.connect(write=True) as db:
            revision=self._revision_write(db,"rp_personas","id",doc["persona_id"],doc,expected_revision)
        return {"id":doc["persona_id"],"revision":revision,"data":doc}

    def list_presets(self):
        with self.connect() as db:
            rows=db.execute("SELECT id,revision,builtin,doc FROM rp_presets ORDER BY builtin DESC,id").fetchall()
        return [{"id":r["id"],"name":obj(r)["name"],"builtin":bool(r["builtin"]),
                 "revision":r["revision"]} for r in rows]

    def get_preset(self,preset_id):
        return self._item("rp_presets","id",domain.ident(preset_id,"预设 ID"))

    def save_preset(self,value,expected_revision=None):
        doc=domain.preset(value)
        with self.connect(write=True) as db:
            row=db.execute("SELECT builtin FROM rp_presets WHERE id=?",(doc["preset_id"],)).fetchone()
            if row and row["builtin"]:
                raise ValueError("内置预设不可覆盖，请复制为新的 preset_id")
            revision=self._revision_write(db,"rp_presets","id",doc["preset_id"],doc,expected_revision)
        return {"id":doc["preset_id"],"revision":revision,"data":doc}

    def ensure_profile(self,profile_id):
        """Create only roleplay binding for an existing main-game profile.

        Never writes main GameStore tables or resets existing roleplay settings.
        A profile ID must come from the authoritative GameStore session, not
        from arbitrary incoming browser data.
        """
        domain.profile_ident(profile_id)
        with self.connect(write=True) as db:
            existing=db.execute("SELECT 1 FROM rp_bindings WHERE profile_id=?",(profile_id,)).fetchone()
            if not existing:
                db.execute("INSERT INTO rp_bindings VALUES(?,?,?,?)",
                           (profile_id,"legacy_character",None,"immersive_galgame"))
                self._epoch(db)
            # This row is inert in P1 authority mode. The real relationship
            # values are ALWAYS projected from GameStore, never from rp_state.
            db.execute("INSERT OR IGNORE INTO rp_state VALUES(?,?,?)",
                       (profile_id,0,dumps(domain.new_state())))
        return self.binding(profile_id)

    def binding(self,profile_id="default"):
        domain.profile_ident(profile_id)
        with self.connect() as db:
            row=db.execute("SELECT * FROM rp_bindings WHERE profile_id=?",(profile_id,)).fetchone()
        if not row:raise ValueError("存档不存在")
        return dict(row)

    def select(self,card_id=None,persona_id=None,preset_id=None,profile_id="default"):
        domain.profile_ident(profile_id)
        with self.connect(write=True) as db:
            row=db.execute("SELECT * FROM rp_bindings WHERE profile_id=?",(profile_id,)).fetchone()
            if not row:raise ValueError("存档不存在")
            updated={"card_id":row["card_id"],"persona_id":row["persona_id"],"preset_id":row["preset_id"]}
            for label,val,table in (("card_id",card_id,"rp_cards"),
                                    ("persona_id",persona_id,"rp_personas"),
                                    ("preset_id",preset_id,"rp_presets")):
                if val is None:continue
                if label=="persona_id" and val=="":
                    updated[label]=None;continue
                domain.ident(val,label)
                if db.execute(f"SELECT 1 FROM {table} WHERE id=?",(val,)).fetchone() is None:
                    raise ValueError(f"找不到 {label}={val}")
                updated[label]=val
            db.execute("UPDATE rp_bindings SET card_id=?,persona_id=?,preset_id=? WHERE profile_id=?",
                       (updated["card_id"],updated["persona_id"],updated["preset_id"],profile_id))
            self._epoch(db)
        return self.binding(profile_id)

    def list_lore(self,card_id):
        domain.ident(card_id,"角色卡 ID")
        with self.connect() as db:
            rows=db.execute("SELECT id,revision,doc FROM rp_lore WHERE card_id=? ORDER BY id",
                            (card_id,)).fetchall()
        return [{"revision":r["revision"],"data":obj(r)} for r in rows]

    def save_lore(self,card_id,value,expected_revision=None):
        domain.ident(card_id,"角色卡 ID")
        doc=domain.lore(value)
        with self.connect(write=True) as db:
            if not db.execute("SELECT 1 FROM rp_cards WHERE id=?",(card_id,)).fetchone():
                raise ValueError("角色卡不存在")
            row=db.execute("SELECT revision FROM rp_lore WHERE id=? AND card_id=?",
                           (doc["entry_id"],card_id)).fetchone()
            if row:
                if expected_revision is None or not domain._is_int(expected_revision) or expected_revision!=row[0]:
                    raise ValueError("世界书已被其他编辑覆盖，请刷新")
                rev=row[0]+1
                db.execute("UPDATE rp_lore SET revision=?,doc=? WHERE id=? AND card_id=?",
                           (rev,dumps(doc),doc["entry_id"],card_id))
            else:
                if expected_revision not in (None,0):raise ValueError("新世界书 revision 应为 0")
                rev=1
                db.execute("INSERT INTO rp_lore VALUES(?,?,?,?)",
                           (doc["entry_id"],card_id,rev,dumps(doc)))
            self._epoch(db)
        return {"revision":rev,"data":doc}

    def delete_lore(self,card_id,entry_id,expected_revision):
        domain.ident(card_id,"角色卡 ID");domain.ident(entry_id,"世界书 ID")
        with self.connect(write=True) as db:
            row=db.execute("SELECT revision FROM rp_lore WHERE id=? AND card_id=?",
                           (entry_id,card_id)).fetchone()
            if not row or not domain._is_int(expected_revision) or row[0]!=expected_revision:
                raise ValueError("世界书版本不一致，请刷新")
            db.execute("DELETE FROM rp_lore WHERE id=? AND card_id=?",(entry_id,card_id))
            self._epoch(db)
        return {"ok":True}

    def game_state(self,profile_id="default"):
        domain.profile_ident(profile_id)
        with self.connect() as db:
            row=db.execute("SELECT revision,doc FROM rp_state WHERE profile_id=?",
                           (profile_id,)).fetchone()
        if not row:raise ValueError("游戏状态不存在")
        return {"profile_id":profile_id,"revision":row["revision"],"state":obj(row)}

    def _set_state(self,db,state,profile_id="default"):
        row=db.execute("SELECT revision FROM rp_state WHERE profile_id=?",(profile_id,)).fetchone()
        if not row:raise ValueError("游戏状态不存在")
        clean=domain.validate_state(state)
        new_rev=row[0]+1
        db.execute("UPDATE rp_state SET revision=?,doc=? WHERE profile_id=?",
                   (new_rev,dumps(clean),profile_id))
        self._epoch(db)
        return {"profile_id":profile_id,"revision":new_rev,"state":clean}

    def sync_verified_location(self,location_id,verified_location_ids,profile_id="default"):
        """Python-only hook for *completed* real scene transitions.

        Never expose this as a generic client POST route. The caller must pass
        IDs from its already reviewed LocationCatalog, not model-generated text.
        """
        domain.profile_ident(profile_id)
        domain.ident(location_id,"地点 ID")
        if not isinstance(verified_location_ids,(set,frozenset,tuple,list)):
            raise ValueError("地点白名单必须由本地注册表提供")
        allowed={domain.ident(v,"登记地点") for v in verified_location_ids}
        if location_id not in allowed:
            raise ValueError("地点没有通过本地背景注册表验证")
        with self.connect(write=True) as db:
            row=db.execute("SELECT doc FROM rp_state WHERE profile_id=?",(profile_id,)).fetchone()
            state=domain.validate_state(obj(row))
            if state["location_id"]==location_id:
                revision=db.execute("SELECT revision FROM rp_state WHERE profile_id=?",
                                    (profile_id,)).fetchone()[0]
                return {"profile_id":profile_id,"revision":revision,"state":state}
            state["location_id"]=location_id
            return self._set_state(db,state,profile_id)

    def list_events(self):
        return [{"event_id":event_id,"title":conf["title"],"description":conf["description"]}
                for event_id,conf in EVENTS.items()]

    def offer_event(self,event_id,profile_id="default"):
        """Explicitly offer a vetted event. No stat or scene change here."""
        domain.profile_ident(profile_id)
        if event_id not in EVENTS:raise ValueError("未登记的事件不能发起")
        with self.connect(write=True) as db:
            if not db.execute("SELECT 1 FROM rp_bindings WHERE profile_id=?",(profile_id,)).fetchone():
                raise ValueError("存档不存在")
            active=db.execute("SELECT instance_id,created_at FROM rp_events WHERE profile_id=? AND status='offered'",
                              (profile_id,)).fetchone()
            if active:
                raise ValueError("已有一个待选择事件，请先接受或拒绝")
            latest=db.execute("SELECT created_at FROM rp_events WHERE profile_id=? AND event_id=? ORDER BY created_at DESC LIMIT 1",
                              (profile_id,event_id)).fetchone()
            if latest and (datetime.now(timezone.utc)-datetime.fromisoformat(latest[0])).total_seconds()<30:
                raise ValueError("该事件刚发生过，请稍后再试")
            instance_id='e_'+uuid.uuid4().hex
            db.execute("INSERT INTO rp_events(instance_id,profile_id,event_id,status,created_at) VALUES(?,?,?,'offered',?)",
                       (instance_id,profile_id,event_id,utcnow()))
        return {"instance_id":instance_id,"event_id":event_id,"status":"offered",
                "title":EVENTS[event_id]["title"],
                "choices":[{"id":"accept","label":"好呀"},{"id":"decline","label":"暂时不用"}]}

    def active_event(self,profile_id="default"):
        with self.connect() as db:
            row=db.execute("SELECT instance_id,event_id,created_at FROM rp_events WHERE profile_id=? AND status='offered'",
                           (profile_id,)).fetchone()
        if not row:return None
        if (datetime.now(timezone.utc)-datetime.fromisoformat(row["created_at"])).total_seconds()>900:
            return {"instance_id":row["instance_id"],"event_id":row["event_id"],"status":"expired"}
        return {"instance_id":row["instance_id"],"event_id":row["event_id"],
                "status":"offered","title":EVENTS[row["event_id"]]["title"],
                "choices":[{"id":"accept","label":"好呀"},{"id":"decline","label":"暂时不用"}]}

    def choose_event(self,instance_id,choice_id,idempotency_key):
        domain.ident(instance_id,"事件实例 ID")
        domain.ident(idempotency_key,"请求去重 ID")
        if choice_id not in ("accept","decline"):raise ValueError("事件选项不存在")
        with self.connect(write=True) as db:
            existing=db.execute("SELECT instance_id,result_json FROM rp_choices WHERE idempotency_key=?",
                                (idempotency_key,)).fetchone()
            if existing:
                if existing["instance_id"]!=instance_id:raise ValueError("同一去重 ID 不能用于两个事件")
                return json.loads(existing["result_json"])
            row=db.execute("SELECT * FROM rp_events WHERE instance_id=?",(instance_id,)).fetchone()
            if not row:raise ValueError("事件实例不存在")
            if row["status"]!="offered":raise ValueError("事件已经处理，不得重复应用")
            if (datetime.now(timezone.utc)-datetime.fromisoformat(row["created_at"])).total_seconds()>900:
                db.execute("UPDATE rp_events SET status='expired' WHERE instance_id=?",(instance_id,))
                raise ValueError("事件已过期，请重新触发")
            state_row=db.execute("SELECT doc,revision FROM rp_state WHERE profile_id=?",(row["profile_id"],)).fetchone()
            state=domain.validate_state(obj(state_row))
            effects={}
            if choice_id=="accept":
                conf=EVENTS[row["event_id"]]
                for key,delta in conf["effects"].items():
                    if key not in domain.STAT_BOUNDS or not isinstance(delta,int) or abs(delta)>10:
                        raise RuntimeError("事件配置异常")
                    lo,hi=domain.STAT_BOUNDS[key]
                    old=state[key];state[key]=max(lo,min(hi,old+delta))
                    effects[key]=state[key]-old
                milestone=conf.get("milestone")
                if milestone and milestone not in state["milestones"]:
                    state["milestones"].append(milestone)
                # Advancement requires actually completed milestones, not only affinity.
                if state["affection"]>=45 and state["trust"]>=35 and milestone:
                    state["relationship_stage"]="familiar"
            state_result=self._set_state(db,state,row["profile_id"]) if effects else {
                "profile_id":row["profile_id"],"revision":state_row["revision"],"state":state}
            result={"instance_id":instance_id,"event_id":row["event_id"],
                    "choice_id":choice_id,"effects":effects,
                    "game_state":state_result}
            now=utcnow()
            db.execute("UPDATE rp_events SET status='resolved',choice_id=?,result_json=?,resolved_at=? WHERE instance_id=?",
                       (choice_id,dumps(result),now,instance_id))
            db.execute("INSERT INTO rp_choices VALUES(?,?,?,?)",
                       (idempotency_key,instance_id,dumps(result),now))
            db.execute("INSERT INTO rp_journal(profile_id,event_id,choice_id,payload_json,created_at) VALUES(?,?,?,?,?)",
                       (row["profile_id"],row["event_id"],choice_id,dumps(effects),now))
            self._epoch(db)
            return result

    def journal(self,profile_id="default",limit=30):
        limit=domain.bounded_int(limit,1,100,"日志条数")
        with self.connect() as db:
            rows=db.execute("""SELECT event_id,choice_id,payload_json,created_at
                               FROM rp_journal WHERE profile_id=?
                               ORDER BY id DESC LIMIT ?""",(profile_id,limit)).fetchall()
        return [{"event_id":r["event_id"],"choice_id":r["choice_id"],
                 "effects":json.loads(r["payload_json"]),"at":r["created_at"]}
                for r in reversed(rows)]

    def snapshot(self,profile_id="default"):
        """Read data used by prompt. All returned objects are copies (JSON decoded)."""
        domain.profile_ident(profile_id)
        with self.connect() as db:
            db.execute('BEGIN')
            binding=db.execute('SELECT * FROM rp_bindings WHERE profile_id=?',(profile_id,)).fetchone()
            if not binding:raise ValueError('存档不存在')
            card=db.execute('SELECT * FROM rp_cards WHERE id=?',(binding['card_id'],)).fetchone()
            preset=db.execute('SELECT * FROM rp_presets WHERE id=?',(binding['preset_id'],)).fetchone()
            persona=db.execute('SELECT * FROM rp_personas WHERE id=?',(binding['persona_id'],)).fetchone()
            state=db.execute('SELECT * FROM rp_state WHERE profile_id=?',(profile_id,)).fetchone()
            entries=db.execute('SELECT doc FROM rp_lore WHERE card_id=? ORDER BY id',(binding['card_id'],)).fetchall()
            journal=db.execute('SELECT event_id,choice_id FROM rp_journal WHERE profile_id=? ORDER BY id DESC LIMIT 12',(profile_id,)).fetchall()
            epoch=int(db.execute("SELECT value FROM rp_meta WHERE key='epoch'").fetchone()[0])
            return {"binding":dict(binding),"card":obj(card),"card_revision":card['revision'],
                    "preset":obj(preset),"preset_revision":preset['revision'],"persona":obj(persona),
                    "state":obj(state),"state_revision":state['revision'],"lore":[obj(r) for r in entries],
                    "journal":[dict(r) for r in reversed(journal)],"epoch":epoch}
