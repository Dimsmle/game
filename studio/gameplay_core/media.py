"""P4 local CG/audio/media review registry. Never uploads or renders source assets."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
from .common import (VALID_IMAGE_EXTENSIONS, bounded_text, identifier, require_keys,
                     safe_candidates, fingerprint_file, stable_asset_id)

EXTENSIONS=frozenset(VALID_IMAGE_EXTENSIONS|{".wav",".ogg",".mp3",".psb"})
IMAGE_KINDS=frozenset({"cg_still","cg_frame"})
AUDIO_KINDS=frozenset({"bgm","se"})
SUPPORTED_KINDS=IMAGE_KINDS|AUDIO_KINDS
# PSB is discovered for auditing but must NEVER be marked playable here.
PSB_SUFFIX=".psb"
BLOCKED_FOLDERS={"__pycache__","character_exports","generated","fonts"}

def scan_media(root: str | Path, *, max_files=100_000) -> dict:
    """All results begin PENDING review; filename heuristics are not approval."""
    files=[]
    warnings=[]
    for relative,path in safe_candidates(root,EXTENSIONS,max_files=max_files,
                                          forbidden_folders=BLOCKED_FOLDERS,
                                          on_skip=warnings.append):
        sha=fingerprint_file(path)
        ext=path.suffix.casefold()
        files.append({
            "asset_id":stable_asset_id("media",relative,sha),
            "relative_path":relative,
            "file_hash":sha,
            "extension":ext,
            "bytes":path.stat().st_size,
            "category":"unknown",
            "verified":False,
            "safe_for_auto":False,
            "title":"",
            "location_ids":[],
            "tags":[],
        })
    return {"schema":1,"assets":files,"count":len(files),
            "warnings":warnings}

def review_media(catalog: dict, reviews: list[dict]) -> dict:
    if not isinstance(catalog,dict) or catalog.get("schema")!=1:
        raise ValueError("媒体索引版本无效")
    result=deepcopy(catalog)
    index={item["asset_id"]:item for item in result["assets"]}
    if len(index)!=len(result["assets"]):
        raise ValueError("媒体 asset_id 冲突")
    if not isinstance(reviews,list):raise ValueError("审核记录不是数组")
    reviewed_in_batch=set()
    for raw in reviews:
        review=require_keys(raw,
            {"asset_id","file_hash","category","title","safe_for_auto",
             "location_ids","tags","verified"},
            {"asset_id","file_hash","category","title","verified"},
            label="媒体审核")
        if review["asset_id"] in reviewed_in_batch:
            raise ValueError("同一个媒体在一次审核中重复出现")
        reviewed_in_batch.add(review["asset_id"])
        item=index.get(review["asset_id"])
        if item is None or item["file_hash"]!=review["file_hash"]:
            raise ValueError("媒体素材修改或缺失，必须重新审查")
        if review["verified"] is not True:
            raise ValueError("审核记录必须由人工确认")
        kind=review["category"]
        if kind not in SUPPORTED_KINDS:
            raise ValueError("尚未支持该媒体播放种类")
        ext=item["extension"]
        if (kind in IMAGE_KINDS and ext not in VALID_IMAGE_EXTENSIONS or
            kind in AUDIO_KINDS and ext not in {".wav",".ogg",".mp3"} or
            ext==PSB_SUFFIX):
            raise ValueError("文件格式与媒体类型不符或原生 PSB 尚无播放能力")
        locations=review.get("location_ids",[])
        tags=review.get("tags",[])
        if not isinstance(locations,list) or len(locations)>40:
            raise ValueError("媒体地点标签无效")
        if not isinstance(tags,list) or len(tags)>20:
            raise ValueError("媒体类型标签无效")
        locations=[identifier(x,"媒体地点") for x in locations]
        tags=[bounded_text(x,limit=40,label="媒体标签") for x in tags]
        auto=review.get("safe_for_auto",False)
        if type(auto) is not bool:raise ValueError("自动播放开关不合法")
        item.update(category=kind,verified=True,safe_for_auto=auto,
                    title=bounded_text(review["title"],limit=150,label="媒体标题"),
                    location_ids=locations,tags=tags)
    return result

def merge_unchanged_media(old: dict, scanned: dict) -> dict:
    if old.get("schema")!=1 or scanned.get("schema")!=1:
        raise ValueError("媒体索引版本无效")
    result=deepcopy(scanned)
    valid={item["asset_id"]:item for item in old["assets"] if item["verified"]}
    for item in result["assets"]:
        previous=valid.get(item["asset_id"])
        if previous and item["file_hash"]==previous["file_hash"]:
            for key in ("category","title","verified","safe_for_auto",
                        "location_ids","tags"):
                item[key]=deepcopy(previous[key])
    return result

def playable_ids(catalog: dict, *, auto=True) -> set[str]:
    if not isinstance(catalog,dict) or catalog.get("schema")!=1:
        raise ValueError("媒体索引版本无效")
    return {x["asset_id"] for x in catalog["assets"]
            if x["verified"] and x["category"] in SUPPORTED_KINDS
            and (x["safe_for_auto"] or not auto)}

def resolve_playback(catalog: dict, asset_id: str, *, auto=True) -> dict:
    asset=identifier(asset_id,"媒体 ID")
    for item in catalog.get("assets",[]):
        if item["asset_id"]==asset:
            if asset not in playable_ids(catalog,auto=auto):
                raise ValueError("媒体未经审核或禁止自动播放")
            return {key:deepcopy(item[key]) for key in
                    ("asset_id","file_hash","relative_path","category","title")}
    raise ValueError("媒体不存在")

def media_summaries_for_ai(catalog: dict) -> list[dict]:
    """Metadata only. No relative or absolute paths, no file bytes."""
    return [{"asset_id":x["asset_id"],"title":x["title"],
             "category":x["category"],"tags":x["tags"]}
            for x in catalog.get("assets",[])
            if x["verified"] and x["safe_for_auto"]]
