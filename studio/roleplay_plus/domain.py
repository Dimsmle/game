"""Validated roleplay domain objects. No network, no third-party dependencies."""
from __future__ import annotations

import re
from copy import deepcopy

IDENT = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
MAIN_PROFILE_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
STAT_BOUNDS = {"affection": (0, 100), "trust": (0, 100),
               "mood": (-100, 100), "energy": (0, 100)}
STAGES = ("acquaintance", "familiar", "close", "intimate", "committed", "devoted")
STYLES = ("daily", "immersive_galgame", "literary", "romance_growth", "sandbox", "custom")
SCOPE = ("global", "character", "location", "story", "event", "player", "session")
ACTIVATION = ("always", "keyword", "game_state", "location")
FACT_CLASSES = ("canon", "fanon", "game_log", "personal_memory")

def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)

def text(value, name, max_len, min_len=0):
    if not isinstance(value, str) or len(value)>max_len or len(value.strip())<min_len:
        raise ValueError(f"{name} 不是有效文字，长度要求 {min_len}–{max_len}")
    if "\x00" in value:
        raise ValueError(f"{name} 含无效字符")
    return value.strip()

def ident(value, name="ID"):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise ValueError(f"{name} 只能使用小写字母、数字、_、- 且以字母开头")
    return value

def profile_ident(value):
    """Match Codex P1 GameStore profile identifiers without loosening card IDs."""
    if not isinstance(value,str) or not MAIN_PROFILE_ID.fullmatch(value):
        raise ValueError("主游戏存档 ID 不合法")
    return value

def choice(value, allowed, name):
    if value not in allowed:
        raise ValueError(f"{name} 不支持：{value!r}")
    return value

def bounded_int(value, low, high, name):
    if not _is_int(value) or not low <= value <= high:
        raise ValueError(f"{name} 只能是 {low}–{high} 的整数")
    return value

def str_list(value, name, max_items=20, max_chars=300):
    if not isinstance(value, list) or len(value)>max_items:
        raise ValueError(f"{name} 必须是最多 {max_items} 条的列表")
    return [text(x,f"{name}第{i+1}项",max_chars,1) for i,x in enumerate(value)]

def card(value):
    """Return a sanitized, complete character card; don't accept commands/paths."""
    if not isinstance(value,dict):
        raise ValueError("角色卡必须是对象")
    return {
        "card_id":ident(value.get("card_id",""),"角色卡 ID"),
        "name":text(value.get("name",""),"角色名称",80,1),
        "description":text(value.get("description",""),"人物介绍",12000),
        "traits":str_list(value.get("traits",[]),"性格",12,240),
        "values":str_list(value.get("values",[]),"性格原则",12,240),
        "speech_style":text(value.get("speech_style",""),"说话方式",2000),
        "motivations":str_list(value.get("motivations",[]),"角色目标",12,250),
        "likes":str_list(value.get("likes",[]),"喜好",24,140),
        "dislikes":str_list(value.get("dislikes",[]),"不喜欢",24,140),
        "canon_facts":str_list(value.get("canon_facts",[]),"核实的原作设定",40,500),
        "fanon_facts":str_list(value.get("fanon_facts",[]),"自创设定",40,500),
        "example_dialogues":examples(value.get("example_dialogues",[])),
        "source_note":text(value.get("source_note",""),"来源说明",500),
        "canon_verified":bool_field(value.get("canon_verified",False),"原作核实开关"),
    }

def examples(value):
    if not isinstance(value,list) or len(value)>16:
        raise ValueError("示例台词最多 16 组")
    output=[]
    for i,row in enumerate(value):
        if not isinstance(row,dict):
            raise ValueError(f"示例台词第 {i+1} 行无效")
        output.append({
            "user":text(row.get("user",""),"用户示例",250,1),
            "character":text(row.get("character",""),"角色示例",500,1)
        })
    return output

def persona(value):
    if not isinstance(value,dict):raise ValueError("玩家人设必须是对象")
    return {
        "persona_id":ident(value.get("persona_id",""),"玩家人设 ID"),
        "name":text(value.get("name",""),"玩家称呼",80,1),
        "description":text(value.get("description",""),"玩家身份介绍",1600),
        "share_with_llm":bool_field(value.get("share_with_llm",False),"云端共享开关"),
    }

def bool_field(value,name):
    if not isinstance(value,bool):raise ValueError(f"{name} 必须是 true/false")
    return value

def preset(value):
    if not isinstance(value,dict):raise ValueError("预设必须是对象")
    style=ident(value.get("preset_id",""),"预设 ID")
    return {
        "preset_id":style,
        "name":text(value.get("name",""),"预设名称",80,1),
        "description":text(value.get("description",""),"预设介绍",800),
        "response_length":choice(value.get("response_length"),("short","medium","long"),"回复长度"),
        "narration":choice(value.get("narration"),("none","low","medium","high"),"描写密度"),
        "initiative":choice(value.get("initiative"),("low","normal","high"),"主动程度"),
        "tone":choice(value.get("tone"),("natural","visual_novel","literary"),"文风"),
        "emotion":choice(value.get("emotion"),("restrained","natural","expressive"),"情绪表达"),
        "event_frequency":choice(value.get("event_frequency"),("off","low","normal","high"),"事件频率"),
        "custom_guidance":text(value.get("custom_guidance",""),"自定义创作要求",1800),
    }

def lore(value):
    if not isinstance(value,dict):raise ValueError("世界书条目必须是对象")
    conditions=value.get("conditions",{})
    if not isinstance(conditions,dict):raise ValueError("世界书触发条件必须是对象")
    allowed_cond={"location_any","stage_any","flags_all","mood_min","mood_max","affection_min","trust_min"}
    if set(conditions)-allowed_cond:raise ValueError("世界书有未知条件")
    clean={}
    for key in ("location_any","flags_all"):
        if key in conditions:clean[key]=str_list(conditions[key],key,30,80)
    if "stage_any" in conditions:
        raw=str_list(conditions["stage_any"],"关系阶段",4,24)
        if any(x not in STAGES for x in raw):raise ValueError("未知关系阶段")
        clean["stage_any"]=raw
    for key in ("mood_min","mood_max","affection_min","trust_min"):
        if key in conditions:
            lo,hi=(-100,100) if key.startswith("mood") else (0,100)
            clean[key]=bounded_int(conditions[key],lo,hi,key)
    activation=choice(value.get("activation","keyword"),ACTIVATION,"世界书触发方式")
    keywords=str_list(value.get("keywords",[]),"关键词",30,100)
    if activation=="keyword" and not keywords:raise ValueError("关键词模式至少需要一个关键词")
    return {
        "entry_id":ident(value.get("entry_id",""),"世界书 ID"),
        "title":text(value.get("title",""),"条目标题",100,1),
        "content":text(value.get("content",""),"世界书内容",2500,1),
        "scope":choice(value.get("scope","character"),SCOPE,"作用范围"),
        "activation":activation,
        "keywords":keywords,
        "conditions":clean,
        "priority":bounded_int(value.get("priority",50),0,100,"优先级"),
        "fact_class":choice(value.get("fact_class","fanon"),FACT_CLASSES,"事实类型"),
        "verified":bool_field(value.get("verified",False),"核实状态"),
        "enabled":bool_field(value.get("enabled",True),"启用状态"),
        "source_note":text(value.get("source_note",""),"资料来源",300),
    }

def initial_card(settings):
    """Migrates old settings.persona as *character*, not player persona."""
    role=text(settings.get("role_name","角色") or "角色","角色名称",80,1)
    legacy=text(settings.get("persona",""),"旧人设",12000)
    return card({
        "card_id":"legacy_character","name":role,
        "description":legacy,
        "traits":["有自己的想法；随着相处逐渐建立熟悉感"],
        "values":["尊重玩家的明确选择；不假定未发生的游戏事件"],
        "speech_style":"自然中文交流，不反复重复相同套话。",
        "source_note":"由旧版 settings.role_name 和 settings.persona 迁移；不保证原作资料已验证。",
        "canon_verified":False,
    })

PRESETS = {
    "daily": ("自然日常","简短、轻松、少套话","short","low","low","natural","natural","low","保持普通日常聊天，不要每次都制造剧情。"),
    "immersive_galgame": ("沉浸 Galgame","对白为主，兼顾表情与少量氛围","medium","medium","normal","visual_novel","natural","normal","自然对话优先；有条件才提出少量活动邀请。"),
    "literary": ("剧情小说","适量心理与环境描写","long","high","normal","literary","expressive","normal","保持场景细节和语言变化，避免拖沓；对白与旁白明确区分。"),
    "romance_growth": ("情感养成","注重关系细节与慢速成长","medium","medium","normal","visual_novel","natural","low","依据已发生共同经历和当前关系发展，不强制亲密。"),
    "sandbox": ("开放世界","自由话题与探索","medium","low","high","natural","expressive","high","允许灵活延伸话题，不虚构已切换的场景或尚未发生的事件。"),
    "custom": ("完全自定义","用户自定","medium","medium","normal","natural","natural","normal",""),
}
def builtin_presets():
    return [preset(dict(zip(
        ("preset_id","name","description","response_length","narration","initiative","tone","emotion","event_frequency","custom_guidance"),
        (key, *vals)))) for key,vals in PRESETS.items()]

def new_state():
    return {"affection":25,"trust":30,"mood":15,"energy":80,
            "location_id":"","relationship_stage":"acquaintance",
            "flags":{},"milestones":[]}

def validate_state(value):
    if not isinstance(value,dict):raise ValueError("游戏状态必须是对象")
    stats={key:bounded_int(value.get(key),*bounds,key)
           for key,bounds in STAT_BOUNDS.items()}
    loc=value.get("location_id","")
    if loc:ident(loc,"地点 ID")
    milestones=str_list(value.get("milestones",[]),"关系里程碑",60,64)
    flags=value.get("flags",{})
    if not isinstance(flags,dict) or len(flags)>200:raise ValueError("flags 无效")
    clean_flags={}
    for key,v in flags.items():
        ident(key,"flag")
        clean_flags[key]=bool_field(v,"flag 值")
    stage=choice(value.get("relationship_stage","acquaintance"),STAGES,"关系阶段")
    return {**stats,"location_id":loc,"relationship_stage":stage,"flags":clean_flags,"milestones":milestones}
