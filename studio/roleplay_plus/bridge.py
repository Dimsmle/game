"""Additive integration with Character Studio 0.11's existing Handler and LLM.

Small adapter: preserve Handler's own Origin check, auth expectations, and
ReplyTurn. This module deliberately doesn't import studio.app (circular import).
"""
from __future__ import annotations

from pathlib import Path
import os
import re
from urllib.parse import parse_qs, urlsplit
import threading
from .store import RoleplayStore
from .composer import PromptComposer,select_lore
from . import domain

_GUARD=threading.RLock()
_STORE=None
_MAIN_GAME=None  # P1 authoritative GameStore; None in standalone demo and older apps
_COMPOSER=PromptComposer()

def load_project_env(project_root):
    """Load *only* DEEPSEEK_API_KEY from the private project-root .env file.

    No third-party dependency, no arbitrary environment interpolation, no
    logging of values. An already-set Windows environment variable wins.
    """
    if os.environ.get("DEEPSEEK_API_KEY"):
        return False
    path=Path(project_root)/".env"
    if not path.is_file() or path.stat().st_size>8192:
        return False
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line=raw.strip()
        if not line or line.startswith("#"):continue
        if line.startswith("export "):line=line[7:].lstrip()
        key,sep,value=line.partition("=")
        if not sep or key.strip()!="DEEPSEEK_API_KEY":continue
        value=value.strip()
        if len(value)>=2 and value[0]==value[-1] and value[0] in ("'",'"'):
            value=value[1:-1]
        if not value or len(value)>512 or re.search(r"\s|[\x00-\x1f]",value):
            raise ValueError(".env 中 DeepSeek Key 格式无效，请检查（不会显示密钥）")
        os.environ.setdefault("DEEPSEEK_API_KEY",value)
        return True
    return False

def initialize(db_path,settings,use_existing_game_state=False):
    """Idempotent initialization, optionally following P1 GameStore authority."""
    global _STORE,_MAIN_GAME
    path=Path(db_path).resolve()
    with _GUARD:
        if _STORE is None or _STORE.path.resolve()!=path:
            store=RoleplayStore(path)
            store.initialize(settings)
            _STORE=store
        if use_existing_game_state:
            # Imported only inside an installed P1+ project. The game's own
            # GameStore is the ONLY source of relationship/state truth.
            from studio.game_db import GameStore
            _MAIN_GAME=GameStore(path)
            _active_profile()
        else:
            _MAIN_GAME=None
    return _STORE

def store():
    with _GUARD:
        if _STORE is None:
            raise RuntimeError("Roleplay Plus 尚未初始化")
        return _STORE

def _main_snapshot():
    if _MAIN_GAME is None:return None
    session,state=_MAIN_GAME.snapshot()
    if not isinstance(session,dict) or not isinstance(state,dict):
        raise RuntimeError("主游戏存档快照结构错误")
    return session,state

def _active_profile():
    main=_main_snapshot()
    if main is None:return "default"
    profile_id=domain.profile_ident(main[0].get("profile_id"))
    store().ensure_profile(profile_id)
    return profile_id

def _normalize_main_state(value):
    """Read-only projection of P1 authoritative GameState for Lorebook and HUD."""
    stats=value["stats"]
    state={k:domain.bounded_int(stats[k],*domain.STAT_BOUNDS[k],k)
           for k in domain.STAT_BOUNDS}
    state.update(relationship_stage=domain.choice(
        value["relationship_stage"],domain.STAGES,"关系阶段"),
        location_id=("" if value["scene"]["location_id"]=="unknown"
                     else domain.ident(value["scene"]["location_id"],"地点 ID")),
        flags=dict(value["flags"]),milestones=list(value.get("milestones",[])))
    return state

def _snapshot():
    main=_main_snapshot()
    if main is None:
        profile_id="default"
    else:
        session,state=main
        profile_id=domain.profile_ident(session["profile_id"])
        store().ensure_profile(profile_id)
    snap=store().snapshot(profile_id)
    if main is not None:
        # Bind the roleplay card to the SAME snapshot, including ABA generation.
        # The game app verifies this session again before any reply is committed.
        snap["state"]=_normalize_main_state(state)
        snap["state_revision"]=state["revision"]
        snap["main_generation"]=session["generation"]
        snap["profile_id"]=profile_id
        snap["journal"]=[]  # Demo rp_* events are never official P1 story facts.
        current_session=_main_snapshot()[0]
        if current_session != session:
            raise RuntimeError("存档切换中，请重新发送")
    return snap

def _game_state():
    main=_main_snapshot()
    if main is None:return store().game_state()
    session,state=main
    return {"profile_id":session["profile_id"],"revision":state["revision"],
            "state":_normalize_main_state(state)}

def epoch():
    # Seed binding before taking the request epoch, including first chat in a new save.
    if _MAIN_GAME is not None:_active_profile()
    return store().epoch()

def identity():
    snap=store().snapshot(_active_profile())
    return {'name':snap['card']['name'],'card_id':snap['card']['card_id'],'epoch':snap['epoch']}

def sync_verified_location(location_id,verified_location_ids):
    """Call only after the app completed a verified scene transition."""
    if _MAIN_GAME is not None:
        raise ValueError("P1 主游戏地点由 GameStore/已审核场景流程管理，Roleplay 不允许另外修改")
    return store().sync_verified_location(location_id,verified_location_ids)

def extend_prompt(prompt,settings,user_text,history_items=None):
    """Actually influence DeepSeek prompt without altering JSON reply envelope.

    Call this after existing core/behavior/memory prompt construction, before
    constructing messages=[{role:system,...}].
    """
    snap=_snapshot()
    if "_roleplay_epoch" in settings and settings['_roleplay_epoch']!=snap['epoch']:
        raise RuntimeError("角色设定已变化，请重新发送")
    if _MAIN_GAME is not None and "_game_session" in settings:
        expected=settings["_game_session"]
        if (expected["profile_id"]!=snap["profile_id"]
                or expected.get("generation")!=snap.get("main_generation")):
            raise RuntimeError("角色存档已切换，请重试")
    # Existing v0.11 app.py embeds old settings.role_name/settings.persona.
    # After migration these are legacy fallback values, NOT the live character card.
    # Strip just the exact legacy identity fragment from both known chat routes,
    # keeping the untouched behavior schema, runtime hints and memory instructions.
    old_name=str(settings.get("role_name",""))[:100]
    old_persona=str(settings.get("persona",""))[:1000]
    for legacy in (
        "你的名字："+old_name+"；性格："+old_persona,
        "你的名字："+old_name+"。你的角色设定："+old_persona,
    ):
        if legacy in prompt:
            prompt=prompt.replace(legacy,"【当前人物以角色卡为准】",1)
    is_shared=settings.get("memory_enabled_for_llm",True) is True
    return _COMPOSER.compose(snap,user_text,history_items or [],
                             base_prompt=prompt,send_memories=is_shared)["prompt"]

def _get_param(query,key,default):
    value=query.get(key,[default])
    return value[0] if value else default

def try_get(handler,path,query):
    """Return True iff handled. Handler.reply wraps all data in existing headers."""
    if path in ("/roleplay","/roleplay/"):
        return _serve_file(handler,"index.html","text/html; charset=utf-8")
    static={"/roleplay/main.js":("main.js","text/javascript; charset=utf-8"),
            "/roleplay/style.css":("style.css","text/css; charset=utf-8"),
            "/roleplay/launcher.js":("launcher.js","text/javascript; charset=utf-8")}
    if path in static:
        return _serve_file(handler,*static[path])
    if not path.startswith("/api/roleplay/"):
        return False
    s=store()
    profile_id=_active_profile()
    binding=s.binding(profile_id)
    if path=="/api/roleplay/status":
        handler.reply(200,{"ok":True,"version":"0.14.1-integrated",
            "epoch":s.epoch(),"binding":binding,"session":(_main_snapshot()[0] if _MAIN_GAME else None),
            "authority_mode":("game_db" if _MAIN_GAME else "roleplay_demo"),
            "cards":s.list_cards(),"presets":s.list_presets(),
            "personas":s.list_personas(),
            "game_state":_game_state(),
            "events":[] if _MAIN_GAME else s.list_events(),
            "active_event":None if _MAIN_GAME else s.active_event(profile_id)})
    elif path=="/api/roleplay/card":
        handler.reply(200,s.get_card(_get_param(query,"id",binding["card_id"])))
    elif path=="/api/roleplay/persona":
        target=_get_param(query,"id",binding["persona_id"] or "default_player")
        handler.reply(200,s.get_persona(target))
    elif path=="/api/roleplay/preset":
        handler.reply(200,s.get_preset(_get_param(query,"id",binding["preset_id"])))
    elif path=="/api/roleplay/lore":
        handler.reply(200,{"items":s.list_lore(_get_param(query,"card_id",binding["card_id"]))})
    elif path=="/api/roleplay/game_state":
        handler.reply(200,_game_state())
    elif path=="/api/roleplay/events":
        handler.reply(200,{"events":[] if _MAIN_GAME else s.list_events(),
                           "active":None if _MAIN_GAME else s.active_event(profile_id)})
    elif path=="/api/roleplay/journal":
        handler.reply(200,{"items":[] if _MAIN_GAME else s.journal(profile_id)})
    elif path=="/api/roleplay/prompt_trace":
        handler.reply(200,{"trace":_COMPOSER.last_trace()})
    else:
        return False
    return True

def _serve_file(handler,filename,mime):
    path=Path(__file__).parent/"web"/filename
    if not path.is_file():raise RuntimeError("Roleplay 前端文件未安装")
    raw=path.read_bytes()
    if len(raw)>2*1024*1024:raise RuntimeError("前端文件过大")
    handler.reply(200,raw,mime)
    return True

def try_post(handler,path,value):
    """Called from current do_POST after its JSON parser and verify_origin()."""
    if not path.startswith("/api/roleplay/"):
        return False
    # The parent Handler already validates Origin. Additionally require
    # JSON content type so a cross-site simple HTML form cannot mutate state.
    headers=getattr(handler,"headers",None)
    if headers is not None:
        content_type=headers.get("Content-Type","").split(";",1)[0].strip().lower()
        if content_type!="application/json":
            raise ValueError("Roleplay API 只接受 application/json")
    if not isinstance(value,dict):raise ValueError("请求必须是对象")
    s=store()
    profile_id=_active_profile()
    binding=s.binding(profile_id)
    if path=="/api/roleplay/card/save":
        result=s.save_card(value.get("data"),value.get("expected_revision"))
    elif path=="/api/roleplay/persona/save":
        result=s.save_persona(value.get("data"),value.get("expected_revision"))
    elif path=="/api/roleplay/preset/save":
        result=s.save_preset(value.get("data"),value.get("expected_revision"))
    elif path=="/api/roleplay/select":
        if _MAIN_GAME and value.get('expected_session') is not None:
            if value['expected_session']!=_main_snapshot()[0]:
                raise ValueError('存档已切换，请刷新角色工作台后重试')
        result={"binding":s.select(value.get("card_id"),value.get("persona_id"),
                                   value.get("preset_id"),profile_id=profile_id),"epoch":s.epoch()}
    elif path=="/api/roleplay/lore/save":
        result=s.save_lore(value.get("card_id",binding["card_id"]),
                           value.get("data"),value.get("expected_revision"))
    elif path=="/api/roleplay/lore/delete":
        result=s.delete_lore(value.get("card_id",binding["card_id"]),
                             value.get("entry_id",""),value.get("expected_revision"))
    elif path=="/api/roleplay/lore/test":
        snapshot=_snapshot()
        selected,trace,used=select_lore(snapshot["lore"],snapshot["state"],
            value.get("text",""),value.get("history",[]),
            send_memories=value.get("share_memory",False) is True)
        result={"selected_ids":[x["entry_id"] for x in selected],
                "trace":trace,"tokens_estimate":used}
    elif path=="/api/roleplay/prompt_preview":
        if value.get("confirm") is not True:
            raise ValueError("预览 Prompt 需要明确确认")
        message=domain.text(value.get("text",""),"预览消息",1000,1)
        snap=_snapshot()
        # A local preview must never replace the trace of a provider request.
        composed=PromptComposer().compose(snap,message,base_prompt="",
            send_memories=value.get("send_memory") is True)
        # Never return API keys, local file paths or ChatGPT user's actual history.
        result={"addendum":composed["addendum"],"trace":composed["trace"],
                "note":"仅预览 Roleplay 扩展段落；基础行为协议与真实对话历史不在此预览中"}
    elif path=="/api/roleplay/event/offer":
        if _MAIN_GAME is not None:
            raise ValueError("P1 主游戏尚未开放事件提交，不能绕过现有 GameStore")
        result=s.offer_event(value.get("event_id",""),profile_id=profile_id)
    elif path=="/api/roleplay/event/choose":
        if _MAIN_GAME is not None:
            raise ValueError("P1 主游戏尚未开放事件提交，不能绕过现有 GameStore")
        result=s.choose_event(value.get("instance_id",""),
                              value.get("choice_id",""),
                              value.get("idempotency_key",""))
    else:
        return False
    handler.reply(200,result)
    return True
