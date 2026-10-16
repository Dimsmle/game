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


def wardrobe(data,model):
    """Use reviewed metadata first, then the user's explicit shi-only ranges."""
    if not MODEL_PATTERN.fullmatch(model):raise ValueError('模型编号无效')
    code,number=model.split('_');number=int(number);item=data.get('models',{}).get(model,{})
    family=item.get('pose_family') if item.get('verified') else None
    outfit=item.get('outfit') if item.get('verified') else None
    if code=='shi' and (0<=number<=25 or 30<=number<=55):
        family=family or ('pose_a' if number<=25 else 'pose_b')
        outfit=outfit or f'outfit_{number if number<=25 else number-30:02}'
    return {'character':code,'pose_family':family or 'unclassified',
            'outfit':outfit or model,'outfit_label':item.get('outfit_name') or item.get('display_name') or (outfit.replace('outfit_','衣服 ') if outfit else model)}


def appearance(data,model):
    if not isinstance(model,str) or not MODEL_PATTERN.fullmatch(model):return None
    row=wardrobe(data,model);record=data.get('models',{}).get(model,{})
    name=record.get('outfit_name') or ''
    if not name:
        shared={entry['outfit_name'] for other,entry in data.get('models',{}).items() if entry.get('outfit_name')
                and wardrobe(data,other)['character']==row['character'] and wardrobe(data,other)['outfit']==row['outfit']}
        if len(shared)==1:name=shared.pop()
    return {'outfit_label':name or row['outfit_label'],'outfit_name':name,
            'pose':{'pose_a':'姿势A','pose_b':'姿势B'}.get(row['pose_family'],'已选姿势（未标注）')}

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
            "outfit_name":str(item.get('outfit_name','')).strip()[:80],
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
                    ("display_name","outfit_name","outfit","pose_family","verified","notes")
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
