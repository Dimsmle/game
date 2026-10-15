# -*- coding: utf-8 -*-
"""Dialogue -> semantic tags -> locally registered E-mote presets.

The LLM is NOT allowed to choose a file path, arbitrary model ID, or execute
model-provided instructions. Real E-mote mesh/physics playback is NOT provided.
This module intentionally separates behavior decisions from their renderers.
"""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import re
from typing import Any

EMOTION_TO_PRESETS = {
    "neutral": ("普通Ａ",),
    "happy": ("笑顔Ａ","微笑みＡ"),
    "gentle": ("微笑みＡ","普通Ａ"),
    "shy": ("照れＡ","困り笑いＡ"),
    "sleepy": ("目下閉じＡ","うっとりＡ"),
    "surprised": ("驚きＡ","きょとんＡ"),
    "sad": ("悲しみＡ","不安Ａ"),
    "angry": ("怒りＡ",),
    "worried": ("不安Ａ","悲しみＡ"),
    "thinking": ("考えるＡ","真剣Ａ"),
    "crying": ("泣くＡ","悲しみＡ"),
    "playful": ("イタズラ笑みＡ","笑顔Ａ"),
    "confident": ("得意げＡ","微笑みＡ"),
    "grateful": ("笑顔Ａ","微笑みＡ"),
    "serious": ("真剣Ａ","普通Ａ"),
    "embarrassed": ("焦りＡ","照れＡ"),
    "flustered": ("慌てるＡ","焦りＡ"),
    "annoyed": ("ジト目Ａ","もーＡ"),
    "pouting": ("ほっぺぷくーＡ","もーＡ"),
    "moved": ("感激Ａ","嬉し泣きＡ"),
    "shocked": ("ガーンＡ","驚きＡ"),
    "excited": ("＞ワ＜Ａ","笑顔Ａ"),
    "happy_cry": ("嬉し泣きＡ","笑顔Ａ"),
    "dazed": ("目がぐるぐるＡ","きょとんＡ"),
    "wink": ("ウインク笑みＡ","笑顔Ａ"),
    "affectionate": ("うっとりＡ","微笑みＡ"),
}
ACTION_TAGS = (
    "idle","nod","agree","disagree","wave","greet","thank","tilt_head",
    "curious","surprise","think","smile","laugh","shy","comfort",
    "approach","walk","celebrate","playful","sparkle","talk","sleep",
    "reaction","gesture","shake_head","affectionate",
)
DEFAULT_MOTION_TAGS = {
    "待機": ["idle"],
    "おさんぽ": ["walk"],
    "はい": ["agree","nod"],
    "うんうん": ["nod","agree"],
    "いいえ": ["disagree","shake_head"],
    "ありがとう": ["thank"],
    "首かしげ": ["tilt_head","curious"],
    "ん？": ["curious","reaction"],
    "反応": ["reaction"],
    "びっくり": ["surprise","reaction"],
    "思考": ["think"],
    "上目遣い": ["shy"],
    "あまえる": ["affectionate"],
    "にっこり": ["smile"],
    "あざとい": ["playful"],
    "うん強": ["nod","agree"],
    "元気": ["celebrate"],
    "近づく": ["approach"],
    "仕草": ["gesture"],
    "キラキラ": ["sparkle"],
}
# Old v0.2-v0.5 action identifiers are accepted as semantic compatibility aliases.
ACTION_ALIASES = {"happy":"smile", "sleepy":"sleep","surprised":"surprise",
                  "thinking":"think","sad":"comfort","angry":"reaction"}
ACTION_FALLBACKS = {
    "greet": ("greet","wave","reaction"),
    "wave": ("wave",),   # Do not silently label an unrelated gesture 'wave'.
    "comfort": ("comfort","affectionate"),
    "laugh": ("laugh","smile"),
    "talk": ("talk","reaction"),
    "sleep": ("sleep","idle"),
}
RENDER_CAPABILITY="static_emote_frame_preview"
ID_PATTERN=re.compile(r"^(?:kan|tou|say|shi|let)_\d{1,3}$")
TAG_PATTERN=re.compile(r"^[a-z][a-z0-9_]{0,30}$")

def default_library():
    return {"version":1,"models":{}}

def load_library(path):
    path=Path(path)
    try:
        data=json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data,dict) or data.get("version")!=1 or not isinstance(data.get("models"),dict):
            return default_library()
        return data
    except (FileNotFoundError,ValueError,OSError,UnicodeError):
        return default_library()

def validated_tags(values):
    if not isinstance(values,list) or len(values)>16:
        raise ValueError("标签必须是长度不超过 16 的数组")
    result=[]
    for tag in values:
        if not isinstance(tag,str) or not TAG_PATTERN.fullmatch(tag):
            raise ValueError("动作标签只允许小写英文、数字和下划线")
        if tag not in ACTION_TAGS:
            raise ValueError("未知动作标签："+tag)
        if tag not in result:result.append(tag)
    return result

def annotate_motion(library,model_name,label,tags,catalog,sample_time=0):
    if not isinstance(model_name,str) or not ID_PATTERN.fullmatch(model_name):
        raise ValueError("不支持的角色模型编号")
    valid={item["label"]:item for item in catalog if item.get("type")=="motion"}
    if label not in valid:
        raise ValueError("必须选择当前模型实际包含的动作时间轴")
    checked=validated_tags(tags)
    if (not isinstance(sample_time,(float,int)) or isinstance(sample_time,bool)
        or not 0<=float(sample_time)<=min(600,valid[label].get("duration",0))):
        raise ValueError("采样帧超出实际动作范围")
    clean=dict(library)
    models=dict(clean.get("models",{}))
    existing=dict(models.get(model_name,{}))
    bindings=dict(existing.get("motion_tags",{}))
    bindings[label]={"tags":checked,"sample_time":float(sample_time)}
    existing["motion_tags"]=bindings
    models[model_name]=existing
    clean["models"]=models
    return clean

def annotate_expression(library,model_name,emotion,label,catalog):
    if model_name is None or not ID_PATTERN.fullmatch(str(model_name)):
        raise ValueError("模型编号无效")
    if emotion not in EMOTION_TO_PRESETS:
        raise ValueError("未知情绪标签")
    labels={x["label"] for x in catalog if x.get("type")=="face"}
    if label not in labels:
        raise ValueError("面部预设不存在于当前模型")
    clean=dict(library)
    models=dict(clean.get("models",{}))
    existing=dict(models.get(model_name,{}))
    overrides=dict(existing.get("expression_map",{}))
    overrides[emotion]=label
    existing["expression_map"]=overrides
    models[model_name]=existing
    clean["models"]=models
    return clean

def motion_catalog(model,model_name,library):
    custom=library.get("models",{}).get(model_name,{})
    custom_tags=custom.get("motion_tags",{})
    items=[]
    for original in model.expression_catalog():
        item=dict(original)
        if item["type"]=="motion":
            custom_record=custom_tags.get(item["label"])
            raw_tags=custom_record.get("tags") if isinstance(custom_record,dict) else None
            tags=raw_tags if isinstance(raw_tags,list) else DEFAULT_MOTION_TAGS.get(item["label"],[])
            item["tags"]=[x for x in tags if isinstance(x,str) and x in ACTION_TAGS]
            item["tag_source"]="manual" if isinstance(custom_record,dict) else ("seed" if item["label"] in DEFAULT_MOTION_TAGS else "unlabeled")
            time=custom_record.get("sample_time") if isinstance(custom_record,dict) else None
            if not isinstance(time,(float,int)) or time<0 or time>item["duration"]:
                time=round(min(600,item["duration"])*0.5,1)
            item["sample_time"]=time
            item["playback"]="sample_only"
        else:
            item["tags"]=[]
            item["playback"]="sample_only"
        item["id"]=f"{model_name}:preset:{item['index']}"
        items.append(item)
    return items

def _choose_expression(emotion,catalog,custom):
    faces={item["label"] for item in catalog if item.get("type")=="face"}
    override=custom.get("expression_map",{}).get(emotion)
    if override in faces:
        return override
    for label in EMOTION_TO_PRESETS.get(emotion,EMOTION_TO_PRESETS["neutral"]):
        if label in faces:
            return label
    return "普通Ａ" if "普通Ａ" in faces else (next(iter(sorted(faces)),None))

def _choose_motion(action,catalog):
    if action in ("idle",):
        return None
    tags=ACTION_FALLBACKS.get(action,(action,))
    motions=[item for item in catalog if item.get("type")=="motion"]
    for tag in tags:
        hits=[item for item in motions if tag in item.get("tags",[])]
        if hits:
            # Explicit manual tags first; ordered timeline is tie-breaker.
            chosen=sorted(hits,key=lambda x:(0 if x["tag_source"]=="manual" else 1,x["index"]))[0]
            return {"id":chosen["id"],"label":chosen["label"],
                    "sample_time":chosen["sample_time"],
                    "tags":chosen["tags"],"playback":"sample_only",
                    "status":RENDER_CAPABILITY}
    return None


def validate_library_basic(data):
    """Validate an imported animation-tag library without trusting file paths.

    Imported mappings can mention models not currently installed; actual preset
    existence is checked again when a model is loaded/edited.
    """
    if not isinstance(data,dict) or data.get("version")!=1:
        raise ValueError("动作标签文件版本不支持")
    models=data.get("models",{})
    if not isinstance(models,dict) or len(models)>40:
        raise ValueError("动作标签模型数量无效")
    clean={"version":1,"models":{}}
    for model_name,record in models.items():
        if not isinstance(model_name,str) or not ID_PATTERN.fullmatch(model_name):
            raise ValueError("动作标签包含非法模型编号")
        if not isinstance(record,dict):
            raise ValueError("模型动作标签格式错误")
        motions=record.get("motion_tags",{})
        expressions=record.get("expression_map",{})
        if not isinstance(motions,dict) or len(motions)>260:
            raise ValueError("动作标签条目过多")
        if not isinstance(expressions,dict) or len(expressions)>60:
            raise ValueError("表情映射条目过多")
        clean_motions={}
        for label,item in motions.items():
            if not isinstance(label,str) or not 1<=len(label)<=120 or not isinstance(item,dict):
                raise ValueError("动作预设名称无效")
            tags=validated_tags(item.get("tags",[]))
            sample=item.get("sample_time",0)
            if (not isinstance(sample,(int,float)) or isinstance(sample,bool)
                or not 0<=float(sample)<=600):
                raise ValueError("动作采样时间必须在 0–600")
            clean_motions[label]={"tags":tags,"sample_time":round(float(sample),2)}
        clean_expr={}
        for emotion,label in expressions.items():
            if emotion not in EMOTION_TO_PRESETS:
                raise ValueError("未知情绪映射："+str(emotion))
            if not isinstance(label,str) or not 1<=len(label)<=120:
                raise ValueError("表情预设名称无效")
            clean_expr[emotion]=label
        clean["models"][model_name]={
            "motion_tags":clean_motions,
            "expression_map":clean_expr,
        }
    return clean

def merge_libraries(base,incoming):
    base=validate_library_basic(base if isinstance(base,dict) and base.get("version")==1 else default_library())
    incoming=validate_library_basic(incoming)
    merged={"version":1,"models":{}}
    all_models=set(base["models"])|set(incoming["models"])
    for model in sorted(all_models):
        left=base["models"].get(model,{})
        right=incoming["models"].get(model,{})
        merged["models"][model]={
            "motion_tags":{**left.get("motion_tags",{}),**right.get("motion_tags",{})},
            "expression_map":{**left.get("expression_map",{}),**right.get("expression_map",{})},
        }
    return merged

def _intensity(value):
    if not isinstance(value,(int,float)) or isinstance(value,bool):
        return 0.5
    return round(max(0.0,min(1.0,float(value))),2)

def normalize_llm_reply(obj,valid_scenes):
    """Model text is untrusted. Only small semantic enums survive parsing."""
    if isinstance(obj,str):
        content=obj.strip()
        if content.startswith("```"):
            content=re.sub(r"^```(?:json)?\s*","",content,flags=re.I)
            content=re.sub(r"\s*```\s*$","",content)
        try:
            parsed=json.loads(content)
            if not isinstance(parsed,dict):parsed={"speech":obj}
        except (ValueError,TypeError):
            parsed={"speech":obj}
        obj=parsed
    if not isinstance(obj,dict):obj={"speech":str(obj)}
    speech=obj.get("speech",obj.get("reply",""))
    if not isinstance(speech,str):speech=""
    speech=speech[:900].strip() or "我在听，你可以再说一遍吗？"
    emotion=obj.get("emotion","neutral")
    emotion=emotion if isinstance(emotion,str) and emotion in EMOTION_TO_PRESETS else "neutral"
    action=obj.get("action_tag",obj.get("action","idle"))
    action=action if isinstance(action,str) else "idle"
    action=ACTION_ALIASES.get(action,action)
    action=action if action in ACTION_TAGS else "idle"
    scene=obj.get("scene","")
    scene=scene if isinstance(scene,str) and scene in valid_scenes else ""
    voice=obj.get("voice_style","normal")
    voice=voice if isinstance(voice,str) and voice in ("normal","soft","cheerful","calm","sad") else "normal"
    return {"speech":speech,"emotion":emotion,"action_tag":action,"voice_style":voice,
            "scene":scene,"intensity":_intensity(obj.get("intensity",obj.get("emotion_intensity",0.5)))}

def resolve_behavior(intent,model_name,catalog,library,valid_scenes):
    """Pure selection. Never executes an action; the renderer decides feasibility."""
    safe=normalize_llm_reply(intent,valid_scenes)
    custom=library.get("models",{}).get(model_name,{})
    expression=_choose_expression(safe["emotion"],catalog,custom)
    motion=_choose_motion(safe["action_tag"],catalog)
    warnings=[]
    if not expression:
        warnings.append("当前模型没有已登记的可用表情预设")
    if safe["action_tag"]!="idle" and motion is None:
        warnings.append("没有匹配该动作标签的 PSB 预设，保持当前表情；不伪造原版动作")
    elif motion:
        warnings.append("动作仅为时间轴单帧静态近似，不是原版 E-mote 连续动画")
    return {
        "emotion":safe["emotion"],"action_tag":safe["action_tag"],
        "intensity":safe["intensity"],"scene":safe["scene"],
        "expression":{"label":expression,"time":0} if expression else None,
        "motion":motion,"model":model_name,
        "playback_status":("preview_only" if motion else "expression_only"),
        "warnings":warnings,
    }

def llm_instructions(scene_ids,runtime_hint=''):
    emotions=", ".join(EMOTION_TO_PRESETS.keys())
    actions=", ".join(ACTION_TAGS)
    places=", ".join(scene_ids) if scene_ids else "(none)"
    return (
        "只输出一个有效 JSON 对象，不要 Markdown。必须有字段 "
        "speech（自然中文回复）, emotion, action_tag, scene, intensity, voice_style。\n"
        "voice_style 只能是 normal/soft/cheerful/calm/sad；不能指定声音文件。\n"
        "emotion（你推断回复时人物面部的情绪）必须取自："+emotions+"。\n"
        "action_tag（你推断应播放的动作语义）必须取自："+actions+"。\n"
        "scene 只能是空字符串或已登记场景："+places+"。\n"
        "intensity 是 0 到 1 的数值。请根据对话语境而不是机械关键词来选；"
        "没有合适动作则使用 idle。"
        "绝不要填写 PSB 预设名、文件路径、代码或外部 URL。"
        +(("\n"+str(runtime_hint)[:500]) if runtime_hint else "")
    )
