"""P3 deterministic event schema, eligibility, and untrusted AI proposal validation.

This module NEVER changes the authoritative GameStore or approves a player
choice on the model's behalf. Codex owns the transactional EventCommitService.
"""
from __future__ import annotations
from copy import deepcopy
from .common import bounded_text, identifier, require_keys, strict_integer

TRIGGERS=frozenset({"chat","time","location","touch","manual"})
EVENT_TYPES=frozenset({"ambient","invitation","relationship","place",
                       "calendar","special_cg","callback"})
STAGES=("acquaintance","familiar","close","intimate","committed")
STAT_RANGES={"affection":(0,100),"trust":(0,100),"mood":(-100,100),"energy":(0,100)}
# Mirrored ONLY as an early validation cap; actual authorization is GameStore.
SINGLE_DELTA_LIMIT={"affection":5,"trust":5,"mood":20,"energy":20}
TIMES=frozenset({"unknown","morning","day","evening","night"})
EFFECT_KEYS={"stats","milestone","set_flags","location_id","media_id"}

def _ids(value: object, *, max_items=25, label="标识列表") -> list[str]:
    if not isinstance(value,list) or len(value)>max_items:
        raise ValueError(f"{label} 无效")
    ids=[identifier(x,label) for x in value]
    if len(ids)!=len(set(ids)):
        raise ValueError(f"{label} 重复")
    return ids

def validate_effect(raw: object, *, verified_locations: set[str],
                    verified_media: set[str]) -> dict:
    """Validate a REVIEWED LOCAL outcome, never a model-generated outcome."""
    value=require_keys(raw,EFFECT_KEYS,label="事件效果")
    stats=value.get("stats",{})
    if not isinstance(stats,dict) or set(stats)-set(STAT_RANGES):
        raise ValueError("属性效果包含未允许字段")
    for name,delta in stats.items():
        limit=SINGLE_DELTA_LIMIT[name]
        strict_integer(delta,-limit,limit,f"{name} 增量")
    milestone=value.get("milestone")
    if milestone is not None and milestone not in ("introduced","shared_activity",
                                 "mutual_commitment","lasting_bond"):
        raise ValueError("未知里程碑")
    flags=value.get("set_flags",{})
    if not isinstance(flags,dict) or len(flags)>20:
        raise ValueError("flag 更新无效")
    for key,flag in flags.items():
        identifier(key,"flag")
        if type(flag) not in (bool,int) or (type(flag) is int and abs(flag)>1_000_000):
            raise ValueError("flag 值无效")
    location=value.get("location_id")
    if location is not None and (identifier(location,"事件地点") not in verified_locations):
        raise ValueError("事件目标地点尚未审核")
    media=value.get("media_id")
    if media is not None and (identifier(media,"事件媒体") not in verified_media):
        raise ValueError("事件媒体尚未审核或不可播放")
    return {"stats":dict(stats),"milestone":milestone,"set_flags":dict(flags),
            "location_id":location,"media_id":media}

def validate_event(raw: object, *, verified_locations: set[str],
                   verified_media: set[str]) -> dict:
    allowed={"id","title","type","triggers","conditions","cooldown",
             "required_media_ids","choices","enabled","one_shot_flag"}
    value=require_keys(raw,allowed,
        {"id","title","type","triggers","conditions","cooldown","choices",
         "enabled"},label="事件定义")
    event_id=identifier(value["id"],"事件 ID")
    title=bounded_text(value["title"],limit=120,label="事件标题")
    typ=value["type"]
    if typ not in EVENT_TYPES:raise ValueError("事件类型无效")
    triggers=_ids(value["triggers"],max_items=5,label="触发方式")
    if not triggers or not set(triggers)<=TRIGGERS:
        raise ValueError("存在未知事件触发方式")
    conditions=require_keys(value["conditions"],
        {"affection_min","trust_min","mood_min","energy_min","location_any",
         "time_any","required_flags","forbidden_flags","stage_any"},label="事件条件")
    for name in ("affection_min","trust_min","energy_min"):
        if name in conditions:strict_integer(conditions[name],0,100,name)
    if "mood_min" in conditions:
        strict_integer(conditions["mood_min"],-100,100,"最低心情")
    for name in ("required_flags","forbidden_flags"):
        if name in conditions:_ids(conditions[name],label=name)
    if set(conditions.get("required_flags",[]))&set(conditions.get("forbidden_flags",[])):
        raise ValueError("同一 flag 不可同时为必须与禁止")
    for loc in _ids(conditions.get("location_any",[]),label="可用地点"):
        if loc not in verified_locations:raise ValueError("事件条件包含未审核地点")
    if conditions.get("time_any"):
        if not isinstance(conditions["time_any"],list) or not set(conditions["time_any"])<=TIMES:
            raise ValueError("时间条件不合法")
    if conditions.get("stage_any"):
        if not isinstance(conditions["stage_any"],list) or not set(conditions["stage_any"])<=set(STAGES):
            raise ValueError("关系条件不合法")
    cooldown=require_keys(value["cooldown"],{"turns","seconds"},
                          {"turns","seconds"},label="事件冷却")
    strict_integer(cooldown["turns"],0,1000,"冷却回合")
    strict_integer(cooldown["seconds"],0,86400*30,"冷却秒数")
    required_media=_ids(value.get("required_media_ids",[]),label="必需媒体")
    if set(required_media)-verified_media:
        raise ValueError("事件必需媒体未经审核")
    if type(value["enabled"]) is not bool:
        raise ValueError("事件启用状态必须是布尔值")
    one_shot=value.get("one_shot_flag")
    if one_shot is not None:identifier(one_shot,"只运行一次标记")
    choices=value["choices"]
    if not isinstance(choices,list) or not 1<=len(choices)<=3:
        raise ValueError("事件必须含 1–3 个有效选项")
    clean_choices=[];choice_ids=set()
    for item in choices:
        selected=require_keys(item,{"id","label","effect"},
                              {"id","label","effect"},label="事件选项")
        cid=identifier(selected["id"],"选项 ID")
        if cid in choice_ids:raise ValueError("选项 ID 重复")
        choice_ids.add(cid)
        clean_choices.append({
            "id":cid,"label":bounded_text(selected["label"],limit=120,label="选项标题"),
            "effect":validate_effect(selected["effect"],verified_locations=verified_locations,
                                     verified_media=verified_media)})
    return {"id":event_id,"title":title,"type":typ,
            "triggers":triggers,"conditions":deepcopy(conditions),
            "cooldown":dict(cooldown),"required_media_ids":required_media,
            "choices":clean_choices,"enabled":value["enabled"],
            "one_shot_flag":one_shot}

def eligibility(event: dict, context: dict, *, trigger="chat") -> tuple[bool,list[str]]:
    """A pure eligibility check. Never applies effects or changes scenes."""
    reasons=[]
    if trigger not in event["triggers"]:reasons.append("trigger")
    if not event["enabled"]:reasons.append("disabled")
    if context.get("busy",False):reasons.append("busy")
    if context.get("proactive_enabled") is False and trigger!="manual":
        reasons.append("proactive_off")
    flags=context.get("flags",{})
    cond=event["conditions"]
    if event.get("one_shot_flag") and flags.get(event["one_shot_flag"]):
        reasons.append("already_completed")
    for attr in ("affection","trust","mood","energy"):
        minimum=cond.get(f"{attr}_min")
        if minimum is not None and context["stats"].get(attr,-999)<minimum:
            reasons.append("low_"+attr)
    if cond.get("location_any") and context.get("location_id") not in cond["location_any"]:
        reasons.append("location")
    if cond.get("time_any") and context.get("time_of_day") not in cond["time_any"]:
        reasons.append("time")
    if cond.get("stage_any") and context.get("relationship_stage") not in cond["stage_any"]:
        reasons.append("relationship_stage")
    if any(not flags.get(key) for key in cond.get("required_flags",[])):
        reasons.append("required_flags")
    if any(bool(flags.get(key)) for key in cond.get("forbidden_flags",[])):
        reasons.append("forbidden_flags")
    recent=context.get("recent",{}).get(event["id"])
    if recent:
        turn_gap=context.get("turn_index",0)-recent.get("turn_index",0)
        time_gap=context.get("now_seconds",0)-recent.get("at_seconds",0)
        if turn_gap<event["cooldown"]["turns"]:reasons.append("turn_cooldown")
        if time_gap<event["cooldown"]["seconds"]:reasons.append("time_cooldown")
    if context.get("pending_event_id"):reasons.append("another_event_pending")
    return not reasons,reasons

def candidate_event_ids(events: list[dict], context: dict, *, trigger="chat",
                        limit=8) -> list[str]:
    if type(limit) is not int or not 0<=limit<=20:raise ValueError("候选数量超限")
    return [event["id"] for event in events if eligibility(event,context,trigger=trigger)[0]][:limit]

def parse_event_proposal(raw: object, allowed_event_ids: set[str]) -> str | None:
    """LLM may choose ONE eligible ID; it cannot provide choices or effects."""
    if raw is None:return None
    proposal=require_keys(raw,{"event_id","presentation"},
                          {"event_id","presentation"},label="LLM 事件提议")
    event_id=identifier(proposal["event_id"],"AI 提议事件")
    if proposal["presentation"]!="after_last_segment":
        raise ValueError("只能在最后一句真正展示完成后提交事件")
    if event_id not in allowed_event_ids:
        raise ValueError("AI 事件不在此轮合法候选名单")
    return event_id

def parse_director_envelope(raw: object, allowed_event_ids: set[str]) -> dict:
    """Verify the envelope; the existing studio.replies handles segment semantics.

    This intentionally leaves the original segment validator authoritative.
    """
    value=require_keys(raw,{"segments","event_proposal"},{"segments"},
                       label="模型 JSON")
    segments=value["segments"]
    if not isinstance(segments,list) or not 1<=len(segments)<=6:
        raise ValueError("台词仍应是 1–6 段")
    # P1's actual renderer/behavior sanitizer remains responsible for tags.
    for segment in segments:
        if not isinstance(segment,dict) or not isinstance(segment.get("speech"),str):
            raise ValueError("每段必须包含 speech")
    event=parse_event_proposal(value.get("event_proposal"),allowed_event_ids)
    return {"segments":deepcopy(segments),"event_id":event}

def choice_plan(event: dict, choice_id: str) -> dict:
    """Return a *proposal* for Codex's authoritative SQL transaction."""
    identifier(choice_id,"玩家选项")
    for item in event["choices"]:
        if item["id"]==choice_id:
            return {"event_id":event["id"],"choice_id":choice_id,
                    "effect":deepcopy(item["effect"])}
    raise ValueError("不存在该选项，未发生任何游戏状态修改")
