"""Read-only discovery, explicit review, and deterministic location resolution."""
from __future__ import annotations
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
import re

from .common import (VALID_IMAGE_EXTENSIONS, identifier, bounded_text, checked_file,
                     fingerprint_file, require_keys, safe_candidates, stable_asset_id)

BG_STEM=re.compile(r"^z?bg(?P<number>[0-9]{1,5})(?P<variant>[a-z]{2})$",re.IGNORECASE)
KNOWN_SUFFIXES=frozenset({"aa","ab","ac","af"})
TIME_TAGS=frozenset({"unknown","morning","day","evening","night"})
NO_SCAN_FOLDERS={"character_exports","voice","voices","bgm","se","audio","music",
                 "generated","__pycache__","characters"}

def parse_background(stem: str) -> tuple[str,str] | None:
    """Only numeric family identity is known. No suffix implies a time."""
    match=BG_STEM.fullmatch(stem)
    if not match:return None
    return "bg"+match.group("number"),match.group("variant").casefold()

def scan_backgrounds(root: str | Path, *, max_files=100_000) -> dict:
    groups=defaultdict(list);unknown=[];warnings=[]
    for relative,path in safe_candidates(root,VALID_IMAGE_EXTENSIONS,
            max_files=max_files,forbidden_folders=NO_SCAN_FOLDERS,
            on_skip=warnings.append):
        stem=path.stem
        parsed=parse_background(stem)
        if parsed is None:
            # Record files looking like background families, not every image.
            if stem.casefold().startswith("bg"):
                unknown.append({"relative_path":relative,"reason":"unmatched_filename"})
            continue
        family,variant=parsed
        sha=fingerprint_file(path)
        groups[family].append({
            "asset_id":stable_asset_id("bg",relative,sha),
            "relative_path":relative,
            "file_hash":sha,
            "bytes":path.stat().st_size,
            "family":family,
            "suffix":variant,
            "verified":False,
            "allow_automatic":False,
            "time_of_day":"unknown",
            "location_id":None,
            "location_name":None,
            "default":False,
        })
        if variant not in KNOWN_SUFFIXES:
            warnings.append({"relative_path":relative,"reason":"unknown_suffix",
                             "suffix":variant})
    for family,items in groups.items():
        seen=Counter(x["suffix"] for x in items)
        for suffix,amount in seen.items():
            if amount>1:
                warnings.append({"family":family,"suffix":suffix,
                                 "reason":"duplicate_family_variant","count":amount})
    return {"schema":1,
            "families":{key:sorted(groups[key],key=lambda x:(x["suffix"],x["relative_path"]))
                        for key in sorted(groups)},
            "unmatched":unknown,"warnings":warnings,
            "total_matched":sum(len(v) for v in groups.values())}

def flattened(catalog: dict) -> list[dict]:
    require_keys(catalog,{"schema","families","unmatched","warnings","total_matched"},
                 {"schema","families"})
    if catalog["schema"]!=1:raise ValueError("未知 LocationCatalog 版本")
    return [entry for items in catalog["families"].values() for entry in items]

def apply_reviews(catalog: dict, reviews: list[dict]) -> dict:
    """Human reviews tie stable IDs AND hashes to a concrete local scan.

    If the actual image changed since review, its ID changes and review cannot
    be carried over by guessing a filename.
    """
    result=deepcopy(catalog)
    index={a["asset_id"]:a for a in flattened(result)}
    if len(index)!=len(flattened(result)):
        raise ValueError("存在重复背景 asset_id")
    if not isinstance(reviews,list):raise ValueError("审核记录必须是数组")
    reviewed_in_batch = set()
    for review in reviews:
        require_keys(review,{"asset_id","file_hash","location_id","location_name",
                 "time_of_day","verified","allow_automatic","default"},
                 {"asset_id","file_hash","location_id","location_name","time_of_day","verified"},
                 "背景审核")
        if review["asset_id"] in reviewed_in_batch:
            raise ValueError("同一个素材在一次审核中重复出现")
        reviewed_in_batch.add(review["asset_id"])
        asset=index.get(review["asset_id"])
        if asset is None or review["file_hash"]!=asset["file_hash"]:
            raise ValueError("背景未在本次扫描中找到或内容已变化，需重新人工审核")
        if review["verified"] is not True:
            raise ValueError("自动应用的审核必须明确标记 verified=true")
        loc=identifier(review["location_id"],"地点 ID")
        name=bounded_text(review["location_name"],limit=100,label="地点名称")
        time=review["time_of_day"]
        if time not in TIME_TAGS:raise ValueError("时间标签无效")
        if review.get("allow_automatic",False) is True and time == "unknown":
            raise ValueError("未明确时间的背景不能用于自动时间切换")
        if type(review.get("allow_automatic",False)) is not bool or type(review.get("default",False)) is not bool:
            raise ValueError("自动使用及默认标记必须是布尔值")
        # A bgXX family cannot represent two locations at the same time.
        for another in result["families"][asset["family"]]:
            if another["verified"] and another["location_id"]!=loc:
                raise ValueError("同一背景家族已有不同地点审核，需人工拆分")
        asset.update(verified=True,location_id=loc,location_name=name,
                     time_of_day=time,allow_automatic=review.get("allow_automatic",False),
                     default=review.get("default",False))
    for items in result["families"].values():
        default_by_location=Counter(x["location_id"] for x in items
                                     if x["verified"] and x["default"])
        if any(count>1 for count in default_by_location.values()):
            raise ValueError("同一地点背景家族存在多个默认图片")
    return result

def migrate_unchanged_reviews(previous: dict, scanned: dict) -> dict:
    """Never transfer human approval to a changed binary (hash/id mismatch)."""
    old_index={x["asset_id"]:x for x in flattened(previous) if x["verified"]}
    result=deepcopy(scanned)
    for item in flattened(result):
        old=old_index.get(item["asset_id"])
        if old and item["file_hash"]==old["file_hash"]:
            for key in ("verified","location_id","location_name","time_of_day",
                        "allow_automatic","default"):
                item[key]=old[key]
    return result

def locations_for_llm(catalog: dict) -> list[dict]:
    """Only IDs, labels and reviewed time variants. Never a filesystem path."""
    found={}
    for item in flattened(catalog):
        if item["verified"] and item["allow_automatic"]:
            record=found.setdefault(item["location_id"],{
                "location_id":item["location_id"],"display_name":item["location_name"],
                "times":[]})
            if item["time_of_day"] not in record["times"]:
                record["times"].append(item["time_of_day"])
    return [found[key] for key in sorted(found)]

def resolve_background(catalog: dict, location_id: str, time_of_day: str,
                       *, auto=True) -> dict | None:
    loc=identifier(location_id,"地点")
    if time_of_day not in TIME_TAGS:raise ValueError("时间标签无效")
    matches=[item for item in flattened(catalog)
             if item["verified"] and item["location_id"]==loc
             and (item["allow_automatic"] or not auto)]
    if not matches:return None
    exact=[x for x in matches if x["time_of_day"]==time_of_day]
    pool=exact or [x for x in matches if x["default"]] or matches
    chosen=sorted(pool,key=lambda x:(not x["default"],x['suffix'][0]!='a',Path(x['relative_path']).stem.startswith('zbg'),x["asset_id"]))[0]
    return {key:chosen[key] for key in ("asset_id","file_hash","family","suffix",
                                      "location_id","location_name","time_of_day",
                                      "relative_path")}
