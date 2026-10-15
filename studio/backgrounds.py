# -*- coding: utf-8 -*-
"""Background library for locally extracted VN backgrounds and user-imported images.

No game data ships with the app. Discovery uses the user's chosen asset root,
imports stay in the writable application-data folder, and all URLs are local.
"""
from __future__ import annotations

import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import threading
import time

VALID_EXT={".png",".jpg",".jpeg",".webp"}
LOCK=threading.RLock()
CACHE={"root":None,"time":0.0,"items":[]}
BLOCK_FOLDERS={"character_exports","voice","voices","bgm","se","sound",
               "sounds","audio","music","fonts","__pycache__"}
BAD_HINTS=("tex#","tex-texture","thumbnail","thumbs","sprite","chara")
GOOD_FOLDER_HINTS=("bg","background","背景","scene","scenery","location")
GOOD_NAME_HINTS=("bg","background","scene","backdrop","背景","教室","寝室",
                 "部屋","校舎","廊下","公園","夜景","昼","夜","夕","朝",
                 "room","classroom","garden","street","park","school",
                 "home","living","bedroom","city")
SCENE_WORDS={
    "night":("night","nighttime","night_","_night","夜","深夜","月"),
    "evening":("evening","sunset","dusk","夕","黄昏","傍晚"),
    "morning":("morning","dawn","sunrise","朝","早晨"),
}
MAX_SCAN=250000

def folder(data_dir):
    p=Path(data_dir)/"backgrounds"
    p.mkdir(parents=True,exist_ok=True)
    return p

def background_file(data_dir,ref):
    if not isinstance(ref,str) or not re.fullmatch(r"background:[0-9a-f]{64}",ref):
        return None
    p=Path(data_dir)/"backgrounds"/(ref.split(":",1)[1]+".png")
    return p if p.is_file() else None

def category(path):
    text=str(path).casefold().replace("\\","/")
    for key,hints in SCENE_WORDS.items():
        if any(h in text for h in hints):
            return key
    return "day"

def _is_candidate(relative:Path):
    if relative.suffix.casefold() not in VALID_EXT:
        return False
    names=[x.casefold() for x in relative.parts]
    if any(name in BLOCK_FOLDERS for name in names[:-1]):
        return False
    if any(re.fullmatch(r"(kan|tou|shi|say|let)_\d+_decompiled",name) for name in names[:-1]):
        return False
    stem=relative.stem.casefold()
    if any(token in stem for token in BAD_HINTS):
        return False
    return (any(name in GOOD_FOLDER_HINTS for name in names[:-1])
            or any(stem.startswith(token) for token in ("bg","scene","background"))
            or any(h in stem for h in GOOD_NAME_HINTS if len(h)>2))

def _scan_root(root):
    if root is None or not Path(root).is_dir():
        return []
    root=Path(root).resolve()
    items=[]
    visited=0
    for parent,dirs,files in os.walk(root,followlinks=False):
        parent=Path(parent)
        dirs[:]=sorted(x for x in dirs if not (parent/x).is_symlink()
                       and x.casefold() not in BLOCK_FOLDERS
                       and not re.fullmatch(
                           r"(?:kan|tou|shi|say|let)_\d+_decompiled",x.casefold()))
        for filename in sorted(files):
            visited+=1
            if visited>MAX_SCAN:break
            full=parent/filename
            try:
                rel=full.relative_to(root)
                if full.is_symlink() or not _is_candidate(rel):
                    continue
                if full.stat().st_size>40*1024*1024:
                    continue
            except OSError:
                continue
            items.append({
                "ref":rel.as_posix(),
                "name":rel.stem,
                "category":category(rel),
                "source":"assets",
                "folder":rel.parent.as_posix(),
            })
        if visited>MAX_SCAN:break
    # Background directories first; filenames then provide deterministic order.
    items.sort(key=lambda item:(
        0 if item["folder"].casefold().split("/")[-1] in GOOD_FOLDER_HINTS else 1,
        item["ref"].casefold()))
    return items[:600]

def discover(root, data_dir, force=False):
    """Cache potentially large recursive walks for 90 seconds, not imported metadata."""
    key=str(Path(root).resolve()) if root and Path(root).is_dir() else ""
    with LOCK:
        if force or CACHE["root"]!=key or time.monotonic()-CACHE["time"]>90:
            CACHE["items"]=_scan_root(key or None)
            CACHE["root"]=key
            CACHE["time"]=time.monotonic()
        originals=list(CACHE["items"])
    user_dir=folder(data_dir)
    manifest_path=user_dir/"catalog.json"
    try:
        names=json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(names,dict):names={}
    except (FileNotFoundError,UnicodeError,ValueError,OSError):
        names={}
    imported=[]
    for f in sorted(user_dir.glob("*.png")):
        if not re.fullmatch(r"[0-9a-f]{64}\.png",f.name) or f.is_symlink():
            continue
        ref="background:"+f.stem
        info=names.get(f.stem,{})
        if not isinstance(info,dict):info={}
        imported.append({
            "ref":ref,"name":str(info.get("name",f.stem[:12]))[:100],
            "category":category(str(info.get("name",""))),
            "source":"imported","folder":"本机背景图库"
        })
    return imported+originals

def import_image(data_dir, blob, original_name="local_background"):
    """Validate and normalize user-selected background using Pillow.

    Returns a fixed-content reference; never trusts a request-provided path.
    """
    if not isinstance(blob,bytes) or not 100<len(blob)<=22*1024*1024:
        raise ValueError("背景图片需为 100B–22MB")
    try:
        from PIL import Image,ImageOps,UnidentifiedImageError
    except ImportError as exc:
        raise RuntimeError("请安装 Pillow：pip install -r requirements.txt") from exc
    try:
        with Image.open(BytesIO(blob)) as raw:
            if raw.format not in ("PNG","JPEG","WEBP"):
                raise ValueError("仅支持 PNG、JPG、WEBP")
            w,h=raw.size
            if not (128<=w<=12000 and 128<=h<=12000 and w*h<=32_000_000):
                raise ValueError("背景图片尺寸超出 128–12000 像素及 3200 万像素限制")
            raw.load()
            oriented=ImageOps.exif_transpose(raw)
            im=oriented.convert("RGB")
    except (OSError,ValueError,Image.DecompressionBombError) as exc:
        raise ValueError("图片数据损坏或不符合要求："+str(exc)[:170]) from exc
    # Limit large image memory usage, preserve aspect ratio and strip metadata.
    im.thumbnail((2560,1600),Image.Resampling.LANCZOS)
    output=BytesIO()
    im.save(output,format="PNG",optimize=True)
    normalized=output.getvalue()
    digest=hashlib.sha256(normalized).hexdigest()
    lib=folder(data_dir)
    target=lib/(digest+".png")
    with LOCK:
        if not target.exists():
            target.write_bytes(normalized)
        mpath=lib/"catalog.json"
        try:
            meta=json.loads(mpath.read_text(encoding="utf-8"))
            if not isinstance(meta,dict):meta={}
        except (OSError,ValueError,UnicodeError):meta={}
        # Make name display-only, not a filesystem path.
        clean=Path(str(original_name).replace("\\","/")).name[:100]
        meta[digest]={"name":clean or "我的背景"}
        tmp=mpath.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
        tmp.replace(mpath)
    CACHE["time"]=0
    return {
        "ref":"background:"+digest,"name":meta[digest]["name"],
        "category":category(meta[digest]["name"]),
        "width":im.width,"height":im.height,
        "source":"imported",
    }
