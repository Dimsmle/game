# -*- coding: utf-8 -*-
"""Character Studio v0.7 — Python stdlib backend.
- Local-only file preview, editable sprite layers, persistent SQLite chat
- OpenAI-compatible chat, GPT-SoVITS api_v2, optional local Whisper, image API with cache
- NO PSB animation decoding, game archive extraction, or arbitrary code execution
"""
from __future__ import annotations
import argparse
import base64
from datetime import datetime
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

from studio import backgrounds, behavior, runtime as behavior_runtime, renderers, diagnostics, model_meta
from studio import replies
os.environ["DEEPSEEK_API_KEY"] = "sk-9f8b53701a73428cb6bc1631ea11ba56"
ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
DATA = ROOT / "data"
GEN = DATA / "generated"
# Avoid writing into the executable install directory during import.
# main_desktop.py redirects DATA to %LOCALAPPDATA% on Windows.
SETTINGS_FILE = DATA / "settings.json"
MANIFEST_FILE = DATA / "manifest.json"
DB_FILE = DATA / "history.sqlite3"
MAX_BODY = 24 * 1024 * 1024
APP_VERSION="0.11.0"

DEFAULT_SETTINGS = {
    "assets_dir":"",
    "llm_mode":"deepseek",
    "llm_url":"https://api.deepseek.com/v1/chat/completions",
    "llm_model":"deepseek-v4-flash",
    "role_name":"角色",
    "character_model":"",
    "persona":"温柔、自然地交谈，简短回答；在用户需要时主动关心",
    "tts_enabled":False,
    "tts_provider":"gpt_sovits",
    "qwen_model_dir":"",
    "stt_enabled":False,
    "auto_scene":False,
    "memory_enabled_for_llm":True,
    "tts_url":"http://127.0.0.1:9880/tts",
    "tts_text_lang":"zh",
    "tts_ref_audio":"",
    "tts_prompt_text":"",
    "tts_prompt_lang":"ja",
    "asr_model_path":"",
    "asr_language":"auto",
    "image_url":"",
    "image_model":"",
}
DEFAULT_MANIFEST = {
    "layers":[],
    "poses":{},
    "background_fit":"cover",
    "scenes":{"day":"","night":""},
    "events":[
        {"id":"evening","time":"18:30","scene":"night","message":"天色慢慢暗了。"},
        {"id":"morning","time":"08:00","scene":"day","message":"早上好，新的一天开始了。"}
    ]
}
IMG_EXT={".png",".jpg",".jpeg",".webp",".gif"}
ASSET_EXT=IMG_EXT | {".json",".psb",".ogg",".wav"}
FILE_EXT=IMG_EXT | {".json"}
# Semantic behavior tags are validated by studio.behavior; these are only
# legacy stage CSS action identifiers kept for older frontends.
ALLOWED_ACTIONS={"idle","nod","wave","happy","talk","sleep"}
ALLOWED_EMOTIONS=set(behavior.EMOTION_TO_PRESETS)
LOCK=threading.RLock()
LOG_LOCK=threading.RLock()
ASR_LOCK=threading.RLock()
ASR_MODEL=None
STATE={}
RUNTIME=behavior_runtime.BehaviorRuntime()
BEHAVIOR_CACHE={"key":None,"value":None}
PLAN_RENDER_ADAPTER=None
CHAT_LOCK=threading.RLock()
ACTIVE_CHAT=None
LLM_METRICS={}
REPLY_TURN=replies.ReplyTurn()

def app_log(event,detail=""):
    """Append a bounded local diagnostic line without request bodies or secrets."""
    try:
        text=str(detail).replace("\r"," ").replace("\n"," ").replace("\t"," ")[:900]
        event=re.sub(r"[^a-zA-Z0-9_.:-]","_",str(event))[:50] or "event"
        folder=DATA/"logs";folder.mkdir(parents=True,exist_ok=True)
        path=folder/"app.log"
        with LOG_LOCK:
            if path.exists() and path.stat().st_size>1024*1024:
                older=folder/"app.log.1"
                try:older.unlink(missing_ok=True)
                except OSError:pass
                try:path.replace(older)
                except OSError:pass
            with path.open("a",encoding="utf-8") as stream:
                stream.write(f"{datetime.now().isoformat(timespec='seconds')} [{event}] {text}\n")
    except OSError:
        pass

def log_tail(max_lines=120):
    try:
        path=DATA/"logs"/"app.log"
        if not path.is_file():return []
        # Log file is bounded to ~1 MB; reading it whole is safe and avoids seek encoding issues.
        lines=path.read_text(encoding="utf-8",errors="replace").splitlines()
        return lines[-max(1,min(300,int(max_lines))):]
    except OSError:
        return []

def read_json(path, default):
    try:
        obj=json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return obj if isinstance(obj,dict) else dict(default)
    except (FileNotFoundError, json.JSONDecodeError, UnicodeError, OSError):
        return dict(default)

def atomic_json(path, obj):
    p=Path(path)
    temp=p.with_name(p.name+".tmp")
    temp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
    temp.replace(p)

def behavior_file():
    return DATA/"animation_tags.json"

def backup_behavior_file():
    source=behavior_file()
    if not source.is_file():
        return None
    backup_dir=DATA/"backups"
    backup_dir.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
    target=backup_dir/f"animation_tags_{stamp}.json"
    # Avoid overwriting if imported twice in one second.
    counter=1
    while target.exists():
        target=backup_dir/f"animation_tags_{stamp}_{counter}.json";counter+=1
    shutil.copy2(source,target)
    # Keep only the newest 12 tag backups.
    backups=sorted(backup_dir.glob("animation_tags_*.json"),
                   key=lambda path:path.stat().st_mtime,reverse=True)
    for old in backups[12:]:
        try:old.unlink()
        except OSError:pass
    return target

def runtime_event(event,obj=None):
    if event=="motion_started":
        return RUNTIME.motion_started((obj or {}).get("token"),(obj or {}).get("duration",0))
    if event=="motion_ended":
        return RUNTIME.motion_ended((obj or {}).get("token"))
    obj=obj or {}
    if event=="speech_start":
        return RUNTIME.speech_start()
    if event=="speech_end":
        return RUNTIME.speech_end()
    if event=="cancel":
        return RUNTIME.cancel(str(obj.get("reason","user")),keep_speech=obj.get("keep_speech") is True)
    if event=="scene_lock":
        scene=str(obj.get("scene",""))
        if scene not in STATE.get("manifest",{}).get("scenes",{}):
            raise ValueError("要锁定的场景不存在")
        return RUNTIME.lock_scene(scene,obj.get("duration_seconds",1800))
    if event=="scene_unlock":
        return RUNTIME.unlock_scene()
    raise ValueError("未知运行时事件")

def init():
    global STATE
    DATA.mkdir(parents=True,exist_ok=True)
    GEN.mkdir(parents=True,exist_ok=True)
    settings=dict(DEFAULT_SETTINGS)
    settings.update(read_json(SETTINGS_FILE,{}))
    manifest=dict(DEFAULT_MANIFEST)
    manifest.update(read_json(MANIFEST_FILE,{}))
    STATE={"settings":settings,"manifest":manifest}
    RUNTIME.reset(settings.get("character_model",""))
    app_log("app.init",f"version={APP_VERSION} model={settings.get('character_model','') or '(none)'}")
    with connect_db() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'user')""")
        db.execute("""CREATE TABLE IF NOT EXISTS memories(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            content TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1)""")
        db.commit()
    return STATE

@contextmanager
def connect_db():
    con=sqlite3.connect(DB_FILE,timeout=5)
    con.row_factory=sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

def history(limit=30):
    with connect_db() as db:
        rows=db.execute("SELECT role,content,created_at,source FROM messages ORDER BY id DESC LIMIT ?",(limit,)).fetchall()
    return [dict(r) for r in reversed(rows)]

def add_history(role,text,source):
    with connect_db() as db:
        db.execute("INSERT INTO messages(created_at,role,content,source) VALUES(?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"),role,text[:3000],source))
        db.execute("DELETE FROM messages WHERE id NOT IN (SELECT id FROM messages ORDER BY id DESC LIMIT 200)")
        db.commit()

def memories(limit=80):
    limit=max(1,min(100,int(limit)))
    with connect_db() as db:
        rows=db.execute(
            "SELECT id,created_at,content,enabled FROM memories ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
    return [dict(row) for row in reversed(rows)]

def add_memory(content):
    if not isinstance(content,str):
        raise ValueError("记忆内容必须是文字")
    content=" ".join(content.strip().split())
    if not 1<=len(content)<=500:
        raise ValueError("单条长期记忆需为 1–500 字")
    with connect_db() as db:
        count=db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        if count>=100:
            raise ValueError("长期记忆已达到 100 条，请先整理或删除")
        cur=db.execute(
            "INSERT INTO memories(created_at,content,enabled) VALUES(?,?,1)",
            (datetime.now().isoformat(timespec="seconds"),content))
        db.commit()
        return int(cur.lastrowid)

def update_memory(memory_id,enabled=None):
    if not isinstance(memory_id,int) or isinstance(memory_id,bool) or memory_id<=0:
        raise ValueError("记忆 ID 无效")
    with connect_db() as db:
        if enabled is None:
            row=db.execute("SELECT id FROM memories WHERE id=?",(memory_id,)).fetchone()
            if not row:raise ValueError("记忆不存在")
        else:
            cur=db.execute("UPDATE memories SET enabled=? WHERE id=?",
                           (1 if enabled else 0,memory_id))
            if cur.rowcount!=1:raise ValueError("记忆不存在")
        db.commit()

def delete_memory(memory_id):
    if not isinstance(memory_id,int) or isinstance(memory_id,bool) or memory_id<=0:
        raise ValueError("记忆 ID 无效")
    with connect_db() as db:
        cur=db.execute("DELETE FROM memories WHERE id=?",(memory_id,))
        if cur.rowcount!=1:raise ValueError("记忆不存在")
        db.commit()

def memory_context(max_items=12,max_chars=1400):
    enabled=[x for x in memories(100) if x["enabled"]]
    selected=enabled[-max_items:]
    chunks=[];used=0
    for item in selected:
        text=item["content"]
        if used+len(text)>max_chars:break
        chunks.append("- "+text);used+=len(text)
    if not chunks:return ""
    return "用户明确保存的本机长期记忆（仅作为对话背景，不要虚构未记录事实）：\\n"+"\\n".join(chunks)

def asset_root():
    s=STATE["settings"].get("assets_dir","")
    if not s:
        return None
    p=Path(s).expanduser()
    return p.resolve() if p.is_dir() else None

def safe_file(relative, allowed=FILE_EXT):
    root=asset_root()
    if not root or not isinstance(relative,str) or not relative or len(relative)>1000:
        return None
    # Relative path only; symlinks cannot escape the selected tree.
    if relative.startswith(("/", "\\")) or re.match(r"^[a-zA-Z]:",relative):
        return None
    p=(root / relative).resolve()
    try:
        p.relative_to(root)
    except ValueError:
        return None
    if p.suffix.lower() not in allowed or not p.is_file():
        return None
    return p

def is_gen_ref(ref):
    if not isinstance(ref,str) or not re.fullmatch(r"generated:[0-9a-f]{64}",ref):
        return False
    return (GEN/(ref.split(":",1)[1]+".png")).is_file()

def valid_img(ref):
    if backgrounds.background_file(DATA,ref) is not None:
        return True
    return is_gen_ref(ref) or (isinstance(ref,str) and safe_file(ref,IMG_EXT) is not None)

def scan_assets():
    root=asset_root()
    result=[]
    if not root:
        return result
    # Scan decompiled images and their corresponding JSON, not PFS archives.
    for parent,dirs,files in os.walk(root,followlinks=False):
        if Path(parent)==root/"character_exports":
            dirs[:]=[d for d in dirs if d not in
                     {"sequences","expressions","diagnostics","motion_probes","mesh_poc"}]
        dirs[:]=sorted(
            [d for d in dirs if not (Path(parent)/d).is_symlink()],
            key=lambda name:(0 if name=="character_exports" else 1,name)
        )
        for name in sorted(files):
            p=Path(parent)/name
            if p.is_symlink() or p.suffix.lower() not in ASSET_EXT:
                continue
            try:
                size=p.stat().st_size
                rel=p.relative_to(root).as_posix()
            except OSError:
                continue
            result.append({"path":rel,"size":size,"ext":p.suffix.lower()})
            if len(result)>=6500:
                return result
    return result

def validate_layers(layers):
    if not isinstance(layers,list) or len(layers)>70:
        raise ValueError("图层列表无效，最多 70 层")
    checked=[]
    allowed_slots={"base","eyes_open","eyes_closed","mouth_open","mouth_closed","overlay","happy"}
    for idx,item in enumerate(layers):
        if not isinstance(item,dict) or not valid_img(item.get("file","")):
            raise ValueError(f"第 {idx+1} 层使用了不存在的图片路径")
        crop=item.get("crop",{})
        if not isinstance(crop,dict):
            raise ValueError("裁剪数据必须是对象")
        rect={}
        for key in ("x","y","w","h"):
            v=crop.get(key,0)
            if not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 or v>50000:
                raise ValueError("裁剪坐标无效")
            rect[key]=round(float(v),2)
        if rect["w"]<1 or rect["h"]<1:
            raise ValueError("裁剪宽度/高度不能小于 1")
        slot=item.get("slot","overlay")
        if slot not in allowed_slots:
            raise ValueError("未知图层类型")
        properties={}
        for k,limit in (("x",4000),("y",4000),("scale",10),("z",300)):
            v=item.get(k,1 if k=="scale" else 0)
            if not isinstance(v,(int,float)) or not math.isfinite(v) or abs(v)>limit:
                raise ValueError("图层参数无效")
            properties[k]=float(v)
        if properties["scale"]<=0.01:
            raise ValueError("图层缩放必须大于 0")
        checked.append({
            "id":str(item.get("id","layer"+str(idx)))[:80],
            "name":str(item.get("name","图层"))[:80],
            "file":item["file"],
            "slot":slot,"crop":rect,
            "visible":bool(item.get("visible",True)),**properties
        })
    return checked

def validate_manifest(obj):
    if not isinstance(obj,dict):
        raise ValueError("配置格式错误")
    layers=validate_layers(obj.get("layers",[]))
    scenes=obj.get("scenes",{})
    if not isinstance(scenes,dict):
        raise ValueError("场景配置错误")
    clean_scenes={}
    for k,v in scenes.items():
        if not isinstance(k,str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,35}",k):
            raise ValueError("场景代号无效")
        if v and not valid_img(v):
            raise ValueError("场景资源不存在："+str(v))
        clean_scenes[k]=v or ""
    if len(clean_scenes)>35:
        raise ValueError("场景过多")
    events=obj.get("events",[])
    if not isinstance(events,list) or len(events)>30:
        raise ValueError("定时事件数量无效")
    clean_events=[]
    for i,item in enumerate(events):
        if not isinstance(item,dict) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d",str(item.get("time",""))):
            raise ValueError("事件时间无效，请输入 HH:MM")
        scene=str(item.get("scene",""))
        if scene not in clean_scenes:
            raise ValueError("事件使用了不存在的场景代码")
        clean_events.append({"id":str(item.get("id","event"+str(i)))[:60],
           "time":item["time"],"scene":scene,"message":str(item.get("message",""))[:150]})
    raw_poses=obj.get("poses",{})
    if not isinstance(raw_poses,dict):
        raise ValueError("表情资源表必须是对象")
    clean_poses={}
    for key,value in raw_poses.items():
        if key not in ("neutral","happy","gentle","shy","sleepy","surprised","sad","blink","talk"):
            raise ValueError("未知表情键："+str(key))
        if value and not valid_img(value):
            raise ValueError("表情图片不存在："+str(value))
        clean_poses[key]=value or ""
    fit=obj.get("background_fit","cover")
    if fit not in ("cover","contain"):
        raise ValueError("背景适配方式只支持 cover 或 contain")
    return {"layers":layers,"scenes":clean_scenes,"events":clean_events,
            "poses":clean_poses,"background_fit":fit}

def validate_api_url(url):
    parsed=urllib.parse.urlparse(url)
    if parsed.scheme not in ("https","http") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("请输入有效 HTTP(S) API 地址")
    if parsed.scheme=="http" and parsed.hostname not in ("127.0.0.1","localhost","::1"):
        raise ValueError("非本机服务请使用 HTTPS")
    return url

def validate_settings(obj):
    if not isinstance(obj,dict):
        raise ValueError("设置数据无效")
    out=dict(STATE["settings"])
    for key in DEFAULT_SETTINGS:
        if key not in obj:
            continue
        v=obj[key]
        if key in ("tts_enabled","auto_scene","memory_enabled_for_llm","stt_enabled"):
            out[key]=bool(v)
        elif not isinstance(v,str) or len(v)>4000:
            raise ValueError("设置字段内容无效：" + key)
        else:
            out[key]=v
    if out["llm_mode"] not in ("demo","openai","deepseek"):
        raise ValueError("不支持的大模型模式")
    if out["tts_provider"] not in ("gpt_sovits","qwen3_tts","system"):
        raise ValueError("不支持的语音提供者")
    for key in ("llm_url","tts_url"):
        validate_api_url(out[key])
    if out["image_url"]:
        validate_api_url(out["image_url"])
    # No arbitrary HTTP credentials entered into settings; keys are environment variables.
    return out

def http_json(url,payload,key_env="",timeout=80):
    validate_api_url(url)
    data=json.dumps(payload,ensure_ascii=False).encode("utf-8")
    headers={"Content-Type":"application/json","Accept":"application/json"}
    if key_env and os.environ.get(key_env,""):
        headers["Authorization"]="Bearer "+os.environ[key_env]
    req=urllib.request.Request(url,data=data,headers=headers,method="POST")
    try:
        with urllib.request.urlopen(req,timeout=timeout) as response:
            raw=response.read(14*1024*1024)
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        msg=e.read(1000).decode("utf-8","replace")
        raise RuntimeError(f"API 返回 HTTP {e.code}: {msg[:250]}") from e
    except (urllib.error.URLError,TimeoutError) as e:
        raise RuntimeError("模型服务无法连接："+str(e.reason if hasattr(e,"reason") else e)) from e

def chat_url(base):
    u=base.rstrip("/")
    if u.endswith("/chat/completions"):
        return u
    return u+"/chat/completions"

def mock_reply(text):
    if "点头" in text:
        return {"speech":"嗯，我同意。这是点头与表情的离线演示。",
                "emotion":"happy","action_tag":"nod","scene":""}
    if any(w in text for w in ("晚安","睡觉","困了")):
        return {"speech":"晚安。这里是演示回答，尚未连接语言模型。","emotion":"sleepy","action":"sleep","scene":"night"}
    if any(w in text for w in ("开心","高兴","早上好","你好")):
        return {"speech":"你好呀！这是离线演示回复。你可以在设置里接入 DeepSeek。","emotion":"happy","action":"happy","scene":""}
    if "挥手" in text:
        return {"speech":"我试着向你挥挥手。这是画布模拟动作，不是游戏原生骨骼动画。","emotion":"gentle","action":"wave","scene":""}
    return {"speech":"我收到你的话了。这是演示模式，接入对话 API 后我才能自由回答。","emotion":"gentle","action":"nod","scene":""}

def current_behavior_context():
    """Return the active model timeline catalog with a small mtime-based cache.

    Large PsbDecompile JSON must not be reparsed for every chat turn. Cache
    invalidates when the model JSON or user animation-tags file changes.
    """
    model_name=str(STATE.get("settings",{}).get("character_model",""))
    tag_file=behavior_file()
    annotations=behavior.load_library(tag_file)
    root=asset_root()
    if root is None or not behavior.ID_PATTERN.fullmatch(model_name):
        return model_name,[],annotations
    path=root/(model_name+"_decompiled")/(model_name+".json")
    if not path.is_file():
        matches=sorted(root.glob("**/"+model_name+".json"))
        path=next((x for x in matches if x.is_file() and not x.is_symlink()),None)
    if path is None or not path.is_file():
        return model_name,[],annotations
    try:
        model_stamp=path.stat().st_mtime_ns
        tag_stamp=tag_file.stat().st_mtime_ns if tag_file.is_file() else 0
    except OSError:
        model_stamp=tag_stamp=0
    key=(str(path.resolve()),model_stamp,tag_stamp,model_name)
    with LOCK:
        if BEHAVIOR_CACHE["key"]==key and BEHAVIOR_CACHE["value"] is not None:
            cached=BEHAVIOR_CACHE["value"]
            return model_name,cached["catalog"],cached["annotations"]
    from emote_model import PoseModel
    model=PoseModel(path)
    catalog=behavior.motion_catalog(model,model_name,annotations)
    with LOCK:
        BEHAVIOR_CACHE["key"]=key
        BEHAVIOR_CACHE["value"]={"catalog":catalog,"annotations":annotations}
    return model_name,catalog,annotations

def planned_reply(value,activate=True):
    """Strict LLM response -> stage-compatible response + audited behavior plan."""
    scenes=[key for key,ref in STATE["manifest"].get("scenes",{}).items() if ref]
    clean=behavior.normalize_llm_reply(value,scenes)
    model_name,catalog,annotations=current_behavior_context()
    plan=behavior.resolve_behavior(clean,model_name,catalog,annotations,scenes)
    if callable(PLAN_RENDER_ADAPTER):
        plan=PLAN_RENDER_ADAPTER(plan,catalog)
    if activate:plan=RUNTIME.submit_plan(plan,source="ai")
    fallback_actions={"nod":"nod","agree":"nod","wave":"wave",
                      "greet":"wave","smile":"happy","laugh":"happy",
                      "talk":"talk","sleep":"sleep"}
    # Only drive legacy CSS body animation when the scheduler actually accepted
    # a motion; cooldown/queue suppression must not secretly animate anyway.
    legacy=(fallback_actions.get(clean["action_tag"],"idle")
            if plan.get("motion") else "idle")
    return {"speech":clean["speech"],"emotion":clean["emotion"],
            "action_tag":clean["action_tag"],"action":legacy,
            "intensity":clean["intensity"],"scene":clean["scene"],"voice_style":clean["voice_style"],
            "behavior":plan,"runtime":plan.get("runtime",RUNTIME.snapshot())}

def parse_reply(value):
    """Backwards-compatible entrypoint. Never trusts LLM-returned model paths."""
    return planned_reply(value)

def chat_response(user_text):
    with CHAT_LOCK:
        REPLY_TURN.clear()
        if ACTIVE_CHAT:ACTIVE_CHAT['cancel'].set()
    settings=STATE["settings"]
    if settings["llm_mode"]=="deepseek":
        result=None
        for event in stream_chat(user_text,"internal_"+str(time.monotonic_ns()),segmented=False):
            if event["type"]=="final":result=event["result"]
        if result is None:raise RuntimeError("本轮对话已取消")
        # Legacy workbench consumes a whole reply, not the new sentence player.
        first=activate_reply(result['turn_id'],0)
        result.update(behavior=first['behavior'],runtime=first['runtime'])
        return result
    if settings["llm_mode"]=="demo":
        output=planned_reply(mock_reply(user_text))
        origin="demo"
    else:
        if not settings["llm_model"].strip():
            raise ValueError("请先在设置中填写模型名称（与代理服务中的模型 ID 一致）")
        scenes=[k for k,v in STATE["manifest"]["scenes"].items() if v]
        mem_context=(memory_context()
                     if settings.get("memory_enabled_for_llm",True) else "")
        prompt=(
            "你是一个具有固定性格的本地虚拟角色。"
            "用中文自然对话，尽量用一至三句话。\n"
            +behavior.llm_instructions(scenes,RUNTIME.context_hint())
            +"你的名字："+settings["role_name"][:100]
            +"。你的角色设定："+settings["persona"][:1000]
            +(("\n"+mem_context) if mem_context else "")
        )
        conversation=[{"role":"system","content":prompt}]
        for item in history(12):
            if item["role"] in ("user","assistant"):
                conversation.append({"role":item["role"],"content":item["content"]})
        conversation.append({"role":"user","content":user_text})
        result=http_json(chat_url(settings["llm_url"]),
             {"model":settings["llm_model"],"messages":conversation,"temperature":0.65},
             "LLM_API_KEY",timeout=85)
        try:
            message=result["choices"][0]["message"]["content"]
            if not isinstance(message,str):
                raise ValueError("模型没有返回可解析的文字")
        except (KeyError,IndexError,TypeError) as e:
            raise RuntimeError("模型返回内容缺少 choices[0].message.content") from e
        output=planned_reply(message)
        origin="openai-compatible"
    add_history("user",user_text,"user")
    add_history("assistant",output["speech"],origin)
    output["source"]=origin
    return output

def cancel_chat(request_id):
    with CHAT_LOCK:
        if ACTIVE_CHAT and ACTIVE_CHAT["id"]==request_id:ACTIVE_CHAT["cancel"].set()


def activate_reply(token,index):
    with CHAT_LOCK,LOCK:
        def apply_segment(intent):
            turn=REPLY_TURN.current
            visible='\n'.join(item['speech'] for item in turn['segments'][:index+1])
            history_id=turn['history_id']
            with connect_db() as db:
                if history_id is None:
                    db.execute('INSERT INTO messages(created_at,role,content,source) VALUES(?,?,?,?)',
                        (datetime.now().isoformat(),'user',turn['user_text'],'user'))
                    cursor=db.execute('INSERT INTO messages(created_at,role,content,source) VALUES(?,?,?,?)',
                        (datetime.now().isoformat(),'assistant',visible,turn['source']))
                    history_id=cursor.lastrowid
                else:
                    updated=db.execute('UPDATE messages SET content=? WHERE id=? AND role=?',(visible,history_id,'assistant'))
                    if updated.rowcount!=1:raise ValueError('聊天记录已被清理，请开始新的对话')
                result=planned_reply(intent)
            turn['history_id']=history_id
            return result
        return REPLY_TURN.activate(token,index,STATE['settings'],apply_segment)


def stream_chat(user_text,request_id,segmented=True):
    """Preview text streams; only a completed, current JSON reply can act/commit."""
    global ACTIVE_CHAT,LLM_METRICS
    from .llm import OpenAICompatibleProvider,Cancelled,speech_prefix
    settings=dict(STATE["settings"]); began=time.monotonic(); first=None
    job={"id":request_id,"cancel":threading.Event()}
    with CHAT_LOCK:
        if ACTIVE_CHAT:ACTIVE_CHAT["cancel"].set()
        ACTIVE_CHAT=job
        REPLY_TURN.clear()
    try:
        if settings["llm_mode"]=="demo":
            intent=replies.demo_reply(user_text,mock_reply(user_text))
            raw=json.dumps(intent,ensure_ascii=False)
            yield {"type":"text","text":speech_prefix(raw)}
        else:
            if not settings["llm_model"].strip():raise ValueError("请填写模型 ID")
            validate_api_url(settings["llm_url"])
            scenes=[k for k,v in STATE["manifest"].get("scenes",{}).items() if v]
            prompt=("你是具有固定性格的虚拟角色。用中文自然交谈，回复一到三句。"
                +behavior.llm_instructions(scenes,RUNTIME.context_hint(),segmented=segmented)
                +(replies.instructions() if segmented else '\n请先输出 speech 字段。')
                +"你的名字："+settings["role_name"][:100]+"；性格："+settings["persona"][:1000])
            if settings.get("memory_enabled_for_llm",True):prompt+='\n'+memory_context()
            messages=[{"role":"system","content":prompt}]
            messages.extend(replies.history_message(x,segmented) for x in history(12) if x["role"] in ("user","assistant"))
            messages.append({"role":"user","content":user_text})
            raw="";visible=""
            for piece in OpenAICompatibleProvider(settings).stream(messages,job["cancel"]):
                raw+=piece
                if len(raw)>24000:raise RuntimeError("模型输出超过本轮限制")
                preview=speech_prefix(raw)
                if preview!=visible:
                    if first is None:first=round((time.monotonic()-began)*1000)
                    visible=preview;yield {"type":"text","text":preview}
        try:intent=replies.parse_reply(raw)
        except ValueError as exc:
            app_log('llm.invalid_json',json.dumps({'characters':len(raw),'position':getattr(exc,'pos',None),'empty':not bool(raw.strip())}))
            raise RuntimeError("模型未返回有效 JSON；没有执行行为或保存本轮，可重试") from None
        scenes=[k for k,v in STATE['manifest'].get('scenes',{}).items() if v]
        segments=replies.normalize_segments(intent,scenes)
        if not segmented:segments=[{**segments[0],'speech':'\n'.join(item['speech'] for item in segments)}]
        with CHAT_LOCK,LOCK:
            if job["cancel"].is_set() or ACTIVE_CHAT is not job:raise Cancelled("已停止本轮对话")
            if settings!=STATE["settings"]:raise Cancelled("配置或角色已变化，请重新发送")
            prepared_segments=[planned_reply(item,activate=False) for item in segments]
            result=dict(prepared_segments[0])
            result['speech']='\n'.join(item['speech'] for item in segments)
            origin='demo' if settings['llm_mode']=='demo' else settings['llm_mode']
            LLM_METRICS={'first_text_ms':first,'total_ms':round((time.monotonic()-began)*1000),'source':origin}
            app_log('llm.metrics',json.dumps(LLM_METRICS))
            result.update(source=origin,metrics=dict(LLM_METRICS))
            result.update(segments=prepared_segments,turn_id=REPLY_TURN.register(segments,settings,origin,user_text))
        yield {"type":"final","result":result}
    finally:
        job["cancel"].set()
        with CHAT_LOCK:
            if ACTIVE_CHAT is job:ACTIVE_CHAT=None


def synthesize_gpt(text):
    s=STATE["settings"]
    if not s["tts_enabled"]:
        raise ValueError("当前未开启语音")
    if not s["tts_ref_audio"].strip():
        raise ValueError("GPT-SoVITS api_v2 需要参考音频路径；请在设置中填写服务器可访问的 ref_audio_path")
    payload={
        "text":text[:900],
        "text_lang":s["tts_text_lang"],
        "ref_audio_path":s["tts_ref_audio"],
        "prompt_text":s["tts_prompt_text"],
        "prompt_lang":s["tts_prompt_lang"],
        "text_split_method":"cut5","media_type":"wav","streaming_mode":False,
    }
    u=validate_api_url(s["tts_url"])
    req=urllib.request.Request(u,data=json.dumps(payload,ensure_ascii=False).encode(),
        headers={"Content-Type":"application/json"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=130) as resp:
            if "audio" not in resp.headers.get("Content-Type",""):
                err=resp.read(500).decode("utf-8","replace")
                raise RuntimeError("语音服务未返回音频："+err[:200])
            audio=resp.read(16*1024*1024)
            if len(audio)<50:
                raise RuntimeError("语音返回内容过短")
            return audio
    except urllib.error.HTTPError as err:
        err.close()
        raise RuntimeError(f"语音接口 HTTP {err.code}，请检查本地 TTS 服务配置") from None
    except urllib.error.URLError as err:
        raise RuntimeError("无法连接语音服务："+str(err.reason)) from err

from .tts import TTSService
TTS_SERVICE=TTSService(synthesize_gpt)


def synthesize(text):
    if not isinstance(text,str) or not 1<=len(text.strip())<=900:raise ValueError("语音文本须为 1–900 字")
    audio=TTS_SERVICE.synthesize(text,dict(STATE["settings"]),DATA)
    app_log('tts.metrics',json.dumps(TTS_SERVICE.last_metrics))
    return audio


def asr_audio(blob):
    global ASR_MODEL
    if not STATE["settings"].get("stt_enabled",False):raise ValueError("语音识别已关闭，本阶段无需安装 Whisper")
    path=STATE["settings"].get("asr_model_path","").strip()
    if not path:
        raise ValueError("尚未配置本地 faster-whisper 模型路径（不会自动下载大型模型）")
    if not Path(path).is_dir():
        raise ValueError("ASR 模型目录不存在："+path)
    ffmpeg=shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("需要在 PATH 中安装 FFmpeg 以转换麦克风录音")
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("当前 Python 环境没有 faster-whisper（可用 pip install faster-whisper）") from exc
    with tempfile.TemporaryDirectory(prefix="character_asr_") as temp:
        inp=Path(temp)/"recording.webm"
        out=Path(temp)/"recording.wav"
        inp.write_bytes(blob)
        proc=subprocess.run([ffmpeg,"-hide_banner","-loglevel","error","-y",
            "-i",str(inp),"-ar","16000","-ac","1",str(out)],
            capture_output=True,timeout=45)
        if proc.returncode!=0:
            raise RuntimeError("FFmpeg 转换录音失败："+proc.stderr.decode("utf-8","replace")[:160])
        with ASR_LOCK:
            if ASR_MODEL is None or getattr(ASR_MODEL,"_custom_path",None)!=path:
                model=WhisperModel(path,device="auto",compute_type="auto")
                model._custom_path=path
                ASR_MODEL=model
            lang=STATE["settings"].get("asr_language","auto")
            segments,info=ASR_MODEL.transcribe(str(out),beam_size=3,
                 language=None if lang=="auto" else lang,vad_filter=True)
            text="".join(segment.text for segment in segments).strip()
        return text

def generate_scene(scene_id,prompt):
    config=STATE["settings"]
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,35}",scene_id):
        raise ValueError("请使用英文字母、数字或下划线作为场景代码")
    if not config["image_url"] or not config["image_model"]:
        raise ValueError("尚未配置兼容 /images/generations 的绘图 API 与模型")
    if not isinstance(prompt,str) or not 5<=len(prompt)<=1200:
        raise ValueError("请填写 5–1200 字的场景描述")
    digest=hashlib.sha256((config["image_model"]+"\n"+prompt).encode()).hexdigest()
    target=GEN/(digest+".png")
    cached=target.exists()
    if not cached:
        result=http_json(config["image_url"],{
           "model":config["image_model"],"prompt":prompt,
           "size":"1536x1024","response_format":"b64_json"}, "IMAGE_API_KEY",timeout=165)
        try:
            encoded=result["data"][0]["b64_json"]
            image=base64.b64decode(encoded,validate=True)
        except (KeyError,IndexError,TypeError,ValueError) as e:
            raise RuntimeError("绘图接口未返回 b64_json；当前适配器不支持 URL 模式") from e
        if not image.startswith(b"\x89PNG\r\n\x1a\n") or len(image)>14*1024*1024:
            raise RuntimeError("绘图结果不是合适的 PNG，未保存")
        target.write_bytes(image)
    ref="generated:"+digest
    with LOCK:
        m=dict(STATE["manifest"])
        m["scenes"]={**m["scenes"],scene_id:ref}
        STATE["manifest"]=validate_manifest(m)
        atomic_json(MANIFEST_FILE,STATE["manifest"])
    return {"scene":scene_id,"ref":ref,"cached":cached}

def inspect_json(rel):
    p=safe_file(rel,{".json"})
    if not p:
        raise ValueError("未找到 JSON 文件")
    if p.stat().st_size>28*1024*1024:
        raise ValueError("JSON 超过 28MB，建议上传较小的结构样本")
    try:
        obj=json.loads(p.read_text(encoding="utf-8-sig"))
    except (UnicodeError,json.JSONDecodeError) as e:
        raise ValueError("JSON 无法解析："+str(e)[:170]) from e
    counts={"dict":0,"list":0,"number":0,"string":0}
    rects=[]
    keyword_hits={k:0 for k in ("motion","mesh","bone","frame","timeline","texture","layer","part","vertex","draw")}
    node_limit=28000
    queue=[("$",obj,0)]
    seen=0
    while queue and seen<node_limit:
        path,value,depth=queue.pop()
        seen+=1
        if isinstance(value,dict):
            counts["dict"]+=1
            for raw_key in value:
                lower_key=str(raw_key).lower()
                for marker in keyword_hits:
                    if marker in lower_key:
                        keyword_hits[marker]+=1
            keys={str(k).lower():k for k in value.keys()}
            for candidate in (("x","y","w","h"),("left","top","width","height"),
                              ("srcx","srcy","srcwidth","srcheight")):
                if all(key in keys for key in candidate):
                    vals=[value[keys[k]] for k in candidate]
                    if all(isinstance(x,(int,float)) and math.isfinite(x) for x in vals):
                        x,y,w,h=vals
                        if 0<=x<=50000 and 0<=y<=50000 and 2<=w<=50000 and 2<=h<=50000:
                            if len(rects)<300:
                                rects.append({"json_path":path,"x":x,"y":y,"w":w,"h":h})
                    break
            if depth<14:
                for k,v in list(value.items())[:150]:
                    queue.append((path+"."+str(k),v,depth+1))
        elif isinstance(value,list):
            counts["list"]+=1
            if depth<14:
                for i,v in enumerate(value[:180]):
                    queue.append((path+"["+str(i)+"]",v,depth+1))
        elif isinstance(value,str):
            counts["string"]+=1
        elif isinstance(value,(int,float)):
            counts["number"]+=1
    return {"file":rel,"root_type":type(obj).__name__,
      "top_keys":list(obj.keys())[:90] if isinstance(obj,dict) else [],
      "counts":counts,"nodes_visited":seen,"truncated":bool(queue),
      "keyword_hits":{k:v for k,v in keyword_hits.items() if v},
      "rect_candidates":rects,
      "note":"疑似矩形只是启发式检测，并非已经解码 E-mote 网格或时间轴。"}

class Handler(BaseHTTPRequestHandler):
    protocol_version="HTTP/1.1"
    server_version="CharacterStudio/0.7"
    def log_message(self,fmt,*args):
        if "/api/health" not in self.path:
            message=fmt%args
            print("[%s]"%datetime.now().strftime("%H:%M:%S"),message)
            # Standard BaseHTTPRequestHandler format contains method/path/status only,
            # never JSON request bodies.
            app_log("http",message)
    def reply(self,status,content,content_type="application/json; charset=utf-8"):
        if isinstance(content,(dict,list)):
            content=json.dumps(content,ensure_ascii=False).encode("utf-8")
        if isinstance(content,str):
            content=content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type",content_type)
        self.send_header("Content-Length",str(len(content)))
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("X-Frame-Options","DENY")
        self.send_header("Cross-Origin-Resource-Policy","same-origin")
        self.send_header("Referrer-Policy","no-referrer")
        self.send_header("Cache-Control","no-store")
        self.send_header("Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; "
            "media-src 'self' blob:; connect-src 'self'; "
            "script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "font-src 'self' data:; object-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(content)
    def err(self,exc,code=400):
        self.reply(code,{"error":str(exc)[:550]})
    def static(self,p,kind=None):
        if not p or not p.is_file() or p.stat().st_size>70*1024*1024:
            return self.reply(404,{"error":"文件不存在或过大"})
        ctype=kind or mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        self.reply(200,p.read_bytes(),ctype)
    def do_GET(self):
        route=urllib.parse.urlsplit(self.path)
        path=route.path
        query=urllib.parse.parse_qs(route.query)
        try:
            if path=="/":
                return self.static(WEB/"index.html","text/html; charset=utf-8")
            if path in ("/style.css","/app.js","/frame_sequence.js","/dialogue_player.js","/chat_stream.js","/reply_player.js","/game.js","/game.css"):
                return self.static(WEB/path[1:])
            if path=="/api/demo_scenes":
                from . import dialogue
                return self.reply(200,{"scenes":dialogue.summaries()})
            if path=="/api/health":
                return self.reply(200,{"ok":True,"version":APP_VERSION,
                    "asset_root_selected":asset_root() is not None,
                    "runtime":RUNTIME.snapshot(),
                    "renderer":renderers.current_capabilities()})
            if path=="/api/runtime":
                return self.reply(200,RUNTIME.snapshot())
            if path=="/api/provider_status":
                return self.reply(200,{"deepseek_key_present":bool(os.environ.get("DEEPSEEK_API_KEY")),
                    "llm_metrics":LLM_METRICS,"tts_metrics":TTS_SERVICE.last_metrics,
                    "stt_enabled":STATE["settings"].get("stt_enabled",False)})
            if path=="/api/log_tail":
                return self.reply(200,{"lines":log_tail(120),
                    "path":str(DATA/"logs"/"app.log"),
                    "note":"日志不记录聊天请求正文或 API Key"})
            if path=="/api/renderer_capabilities":
                return self.reply(200,{"current":renderers.current_capabilities(),
                    "available_or_planned":renderers.all_capabilities()})
            if path=="/api/diagnostics":
                report=diagnostics.run(DATA,asset_root(),STATE["settings"],
                                       STATE["settings"].get("character_model",""))
                return self.reply(200,report)
            if path=="/api/behavior_export":
                library=behavior.load_library(behavior_file())
                return self.reply(200,behavior.validate_library_basic(library))
            if path=="/api/memories":
                return self.reply(200,{"items":memories(80),
                    "note":"长期记忆只在本机 SQLite 中保存；当前版本只支持用户手工确认写入"})
            if path=="/api/model_metadata":
                metadata=model_meta.load(DATA/"model_metadata.json")
                current=STATE["settings"].get("character_model","")
                return self.reply(200,{"current":current,
                    "record":metadata["models"].get(current,{}),
                    "library":metadata})
            if path=="/api/state":
                return self.reply(200,{"settings":STATE["settings"],
                   "manifest":STATE["manifest"],"history":history(30),
                   "memories":memories(80)})
            if path=="/api/assets":
                return self.reply(200,{"items":scan_assets(),"configured":asset_root() is not None})
            if path=="/api/behavior_catalog":
                model_name,catalog,library=current_behavior_context()
                return self.reply(200,{
                    "model":model_name,"entries":catalog,
                    "emotions":list(behavior.EMOTION_TO_PRESETS),
                    "action_tags":list(behavior.ACTION_TAGS),
                    "capability":"E-mote 时间轴静态采样；未实现原生连续动画",
                    "annotation_file":str(behavior_file())
                })
            if path=="/api/backgrounds":
                ref=asset_root()
                force=query.get("refresh",["0"])[0]=="1"
                items=backgrounds.discover(ref,DATA,force=force)
                return self.reply(200,{"items":items,"count":len(items),
                                      "source_root":str(ref or ""),
                                      "note":"原始背景素材保留在你的本地目录"})
            if path.startswith("/background/"):
                name=path[len("/background/"):]
                if re.fullmatch(r"[0-9a-f]{64}\.png",name):
                    f=backgrounds.background_file(DATA,"background:"+name[:-4])
                    if f:return self.static(f,"image/png")
                return self.reply(404,{"error":"背景不存在"})
            if path=="/api/json_inspect":
                return self.reply(200,inspect_json(query.get("file",[""])[0]))
            if path.startswith("/file/"):
                rel=urllib.parse.unquote(path[len("/file/"):])
                f=safe_file(rel,FILE_EXT)
                if f:
                    return self.static(f)
                return self.reply(404,{"error":"素材不存在"})
            if path.startswith("/generated/"):
                name=path.removeprefix("/generated/")
                if re.fullmatch(r"[0-9a-f]{64}\.png",name):
                    return self.static(GEN/name,"image/png")
                return self.reply(404,{"error":"生成素材不存在"})
            return self.reply(404,{"error":"未知路径"})
        except (ValueError,OSError) as e:
            return self.err(e)
    def recv(self):
        raw=self.headers.get("Content-Length","0")
        n=int(raw)
        if n<=0 or n>MAX_BODY:
            raise ValueError("请求体大小无效")
        return self.rfile.read(n)
    def verify_origin(self):
        orig=self.headers.get("Origin")
        expected=f"http://127.0.0.1:{self.server.server_port}"
        if orig and orig!=expected:
            raise ValueError("已拒绝来自其他站点的请求")
    def do_POST(self):
        try:
            self.verify_origin()
            path=urllib.parse.urlsplit(self.path).path
            raw=self.recv()
            if path=="/api/asr":
                result=asr_audio(raw)
                return self.reply(200,{"text":result})
            if path=="/api/background_import":
                request=urllib.parse.urlsplit(self.path)
                name=urllib.parse.parse_qs(request.query).get("name",["local_background"])[0]
                result=backgrounds.import_image(DATA,raw,name)
                return self.reply(200,{"ok":True,"item":result})
            if path=="/api/tts":
                obj=json.loads(raw)
                audio=synthesize(str(obj.get("text","")))
                return self.reply(200,audio,"audio/wav")
            obj=json.loads(raw)
            if not isinstance(obj,dict):
                raise ValueError("请求体必须是对象")
            if path=="/api/settings":
                with LOCK:
                    STATE["settings"]=validate_settings(obj)
                    atomic_json(SETTINGS_FILE,STATE["settings"])
                return self.reply(200,{"ok":True,"settings":STATE["settings"]})
            if path=="/api/demo_scene":
                from . import dialogue
                model,catalog,library=current_behavior_context()
                return self.reply(200,dialogue.compile_scene(obj.get("id"),model,catalog,library))
            if path=="/api/chat_cancel":
                cancel_chat(str(obj.get("id","")))
                return self.reply(200,{"ok":True})
            if path=="/api/chat_turn_cancel":
                with CHAT_LOCK:REPLY_TURN.cancel(obj.get('turn_id'))
                return self.reply(200,{'ok':True})
            if path=="/api/chat_segment":
                return self.reply(200,activate_reply(obj.get('turn_id'),obj.get('index')))
            if path=="/api/chat_stream":
                msg=obj.get("text","");request_id=obj.get("id","")
                if not isinstance(msg,str) or not 1<=len(msg.strip())<=1200:raise ValueError("请输入 1–1200 字")
                if not isinstance(request_id,str) or not re.fullmatch(r"[a-zA-Z0-9_-]{8,80}",request_id):raise ValueError("请求编号无效")
                return self.stream_reply(msg.strip(),request_id)
            if path=="/api/manifest":
                with LOCK:
                    STATE["manifest"]=validate_manifest(obj)
                    atomic_json(MANIFEST_FILE,STATE["manifest"])
                return self.reply(200,{"ok":True,"manifest":STATE["manifest"]})
            if path=="/api/memory":
                action=obj.get("action","")
                if action=="add":
                    memory_id=add_memory(obj.get("content",""))
                    return self.reply(200,{"ok":True,"id":memory_id,"items":memories(80)})
                if action=="toggle":
                    memory_id=obj.get("id")
                    update_memory(memory_id,bool(obj.get("enabled")))
                    return self.reply(200,{"ok":True,"items":memories(80)})
                if action=="delete":
                    delete_memory(obj.get("id"))
                    return self.reply(200,{"ok":True,"items":memories(80)})
                raise ValueError("未知记忆操作")
            if path=="/api/runtime_event":
                event=str(obj.get("event",""))
                return self.reply(200,{"ok":True,"runtime":runtime_event(event,obj)})
            if path=="/api/model_metadata":
                model=str(obj.get("model") or STATE["settings"].get("character_model",""))
                metadata=model_meta.load(DATA/"model_metadata.json")
                updated=model_meta.update(metadata,model,obj.get("record",{}))
                with LOCK:
                    atomic_json(DATA/"model_metadata.json",updated)
                return self.reply(200,{"ok":True,"model":model,
                    "record":updated["models"][model]})
            if path=="/api/behavior_import":
                incoming=behavior.validate_library_basic(obj.get("library"))
                mode=obj.get("mode","merge")
                if mode not in ("merge","replace"):
                    raise ValueError("导入模式只支持 merge 或 replace")
                current=behavior.load_library(behavior_file())
                updated=(behavior.merge_libraries(current,incoming)
                         if mode=="merge" else incoming)
                with LOCK:
                    backup=backup_behavior_file()
                    atomic_json(behavior_file(),updated)
                return self.reply(200,{"ok":True,"library":updated,
                    "backup":str(backup or "")})
            if path=="/api/behavior_tags":
                model_name,catalog,library=current_behavior_context()
                label=obj.get("label","")
                tags=obj.get("tags",[])
                if not catalog or not model_name:
                    raise ValueError("当前没有可供标注的角色模型")
                updated=behavior.annotate_motion(
                    library,model_name,label,tags,catalog,obj.get("sample_time",0))
                with LOCK:
                    atomic_json(behavior_file(),updated)
                return self.reply(200,{"ok":True,"model":model_name,
                    "label":label,"tags":tags})
            if path=="/api/behavior_expression":
                model_name,catalog,library=current_behavior_context()
                if not catalog:
                    raise ValueError("还没有可选择的表情模型")
                emotion=obj.get("emotion","")
                label=obj.get("label","")
                updated=behavior.annotate_expression(
                    library,model_name,emotion,label,catalog)
                with LOCK:
                    atomic_json(behavior_file(),updated)
                return self.reply(200,{"ok":True,"model":model_name,
                    "emotion":emotion,"label":label})
            if path=="/api/chat":
                msg=obj.get("text","")
                if not isinstance(msg,str) or not 1<=len(msg.strip())<=1200:
                    raise ValueError("请输入 1–1200 字的对话内容")
                return self.reply(200,chat_response(msg.strip()))
            if path=="/api/clear_history":
                with CHAT_LOCK:
                    REPLY_TURN.clear()
                    if ACTIVE_CHAT:ACTIVE_CHAT['cancel'].set()
                with connect_db() as db:
                    db.execute("DELETE FROM messages");db.commit()
                return self.reply(200,{"ok":True})
            if path=="/api/generate_scene":
                return self.reply(200,generate_scene(str(obj.get("scene","")),obj.get("prompt","")))
            return self.reply(404,{"error":"未知路径"})
        except (ValueError,RuntimeError,json.JSONDecodeError,OSError,TimeoutError) as e:
            self.err(e)
        except Exception as e:
            detail=f"{type(e).__name__}: {str(e)[:240]}"
            print("内部错误",detail)
            app_log("server.error",detail)
            self.err(RuntimeError("服务器内部错误（详见本机 app.log）"),500)

    def stream_reply(self,text,request_id):
        self.send_response(200)
        self.send_header('Content-Type','application/x-ndjson; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Connection','close');self.end_headers();self.close_connection=True
        def write(item):
            self.wfile.write((json.dumps(item,ensure_ascii=False)+'\n').encode());self.wfile.flush()
        iterator=stream_chat(text,request_id)
        try:
            try:
                for event in iterator:write(event)
            except Exception as exc:
                from .llm import Cancelled
                known=isinstance(exc,(ValueError,RuntimeError,OSError))
                if not known:app_log('llm.stream_error',type(exc).__name__)
                write({'type':'cancelled' if isinstance(exc,Cancelled) else 'error',
                    'error':str(exc)[:350] if known else '对话服务内部错误，请重试'})
        except (OSError,ConnectionError):cancel_chat(request_id)
        finally:iterator.close()


def pick_dir():
    try:
        import tkinter as tk
        from tkinter import filedialog
        ui=tk.Tk();ui.withdraw();ui.attributes("-topmost",True)
        selected=filedialog.askdirectory(title="选择 PsbDecompile 解出的 PNG/JSON 文件夹")
        ui.destroy()
        return selected
    except Exception as exc:
        print("无法打开目录选择窗口，可使用 --assets 指定路径：",exc)
        return ""

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--choose-assets",action="store_true",help="打开资源文件夹选择器")
    ap.add_argument("--assets",help="PsbDecompile 输出根目录")
    ap.add_argument("--no-browser",action="store_true",help="不自动打开浏览器")
    ap.add_argument("--port",type=int,default=8765)
    args=ap.parse_args()
    init()
    chosen=args.assets or (pick_dir() if args.choose_assets else "")
    if chosen and Path(chosen).is_dir():
        with LOCK:
            STATE["settings"]["assets_dir"]=str(Path(chosen).resolve())
            atomic_json(SETTINGS_FILE,STATE["settings"])
    # Start bound to loopback ONLY.
    try:
        server=ThreadingHTTPServer(("127.0.0.1",args.port),Handler)
    except OSError:
        server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    address=f"http://127.0.0.1:{server.server_port}/"
    print("="*52)
    print("Character Studio v0.7 · 本地兼容服务器")
    print("本地地址：",address)
    print("素材目录：",str(asset_root() or "未选择，可用选择素材脚本重新启动"))
    print("按 Ctrl+C 退出；只绑定 127.0.0.1，不暴露至局域网。")
    print("="*52)
    if not args.no_browser:
        webbrowser.open(address)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\n程序已退出。")
    finally:
        server.server_close()
if __name__=="__main__":
    main()
