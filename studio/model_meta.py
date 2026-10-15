# -*- coding: utf-8 -*-
"""Human-reviewed character model metadata.

PSB numeric suffixes are opaque. This file stores user-confirmed outfit/pose
family labels without guessing relationships from filenames.
"""
from __future__ import annotations
import json
from pathlib import Path
import re

CHARACTER_CODES=("kan","tou","say","shi","let")
MODEL_PATTERN=re.compile(r"^(?:kan|tou|say|shi|let)_\d{1,3}$")
SLUG_PATTERN=re.compile(r"^[a-z][a-z0-9_]{0,39}$")

def empty():
    return {"version":1,"models":{}}

def validate(data):
    if not isinstance(data,dict) or data.get("version")!=1:
        raise ValueError("模型元数据版本无效")
    models=data.get("models",{})
    if not isinstance(models,dict) or len(models)>300:
        raise ValueError("模型元数据数量无效")
    clean=empty()
    for model,item in models.items():
        if not isinstance(model,str) or not MODEL_PATTERN.fullmatch(model):
            raise ValueError("模型编号无效："+str(model))
        if not isinstance(item,dict):
            raise ValueError("模型元数据必须是对象")
        display=str(item.get("display_name","")).strip()[:80]
        outfit=str(item.get("outfit","")).strip()
        family=str(item.get("pose_family","")).strip()
        if outfit and not SLUG_PATTERN.fullmatch(outfit):
            raise ValueError("outfit 只能用小写英文/数字/下划线")
        if family and not SLUG_PATTERN.fullmatch(family):
            raise ValueError("pose_family 只能用小写英文/数字/下划线")
        clean["models"][model]={
            "display_name":display,
            "outfit":outfit,
            "pose_family":family,
            "verified":bool(item.get("verified",False)),
            "notes":str(item.get("notes","")).strip()[:500],
        }
    return clean

def load(path):
    path=Path(path)
    try:
        raw=json.loads(path.read_text(encoding="utf-8"))
        return validate(raw)
    except (FileNotFoundError,OSError,UnicodeError,ValueError,TypeError):
        return empty()

def update(data,model,patch):
    data=validate(data if isinstance(data,dict) else empty())
    if not MODEL_PATTERN.fullmatch(str(model)):
        raise ValueError("模型编号无效")
    if not isinstance(patch,dict):
        raise ValueError("模型元数据必须是对象")
    current=dict(data["models"].get(model,{}))
    current.update({k:patch[k] for k in
                    ("display_name","outfit","pose_family","verified","notes")
                    if k in patch})
    raw={"version":1,"models":{**data["models"],model:current}}
    return validate(raw)

def label_for(data,model):
    item=data.get("models",{}).get(model,{})
    parts=[model]
    if item.get("display_name"):parts.append(item["display_name"])
    if item.get("outfit"):parts.append("outfit="+item["outfit"])
    if item.get("pose_family"):parts.append("family="+item["pose_family"])
    if item.get("verified"):parts.append("✓已人工确认")
    return " · ".join(parts)
