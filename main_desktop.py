# -*- coding: utf-8 -*-
"""Integrated CharacterLab desktop app:
1) Auto-compose actual local PSB JSON texture sprites into useful expression PNGs;
2) Register them as persistent character poses;
3) Start existing AI/voice/scene/chat controller in a native Windows WebView2 window.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import sys
import threading
import traceback
import webbrowser

from emote_model import find_model, PoseModel
from pose_renderer import AtlasRenderer
from motion_probe import export_motion_probe
from studio import app as studio
from studio import backgrounds, diagnostics, model_meta
from studio.frame_sequence import SequenceJobs, sequence_key, export_nod_sequence

DEFAULT_ROOT=Path(r"G:\开发游戏\Amakano3_AI")
POSE_KEYS={
    "neutral":"普通Ａ",
    "happy":"笑顔Ａ",
    "surprised":"驚きＡ",
    "sad":"悲しみＡ",
    "gentle":"微笑みＡ",
    "shy":"照れＡ",
    "sleepy":"目下閉じＡ",
}
RENDER_VERSION="5.4"
POSE_SIZE=(740,1250)
SEQUENCE_JOBS=SequenceJobs()


def adapt_sequence_behavior(plan,catalog):
    """Prefer a reviewed/renderable nod over a same-tag static timeline."""
    if plan.get("action_tag") not in ("nod","agree") or not plan.get("expression"):
        return plan
    candidate=next((item for item in catalog if item.get("label")=="うんうん"
                    and plan["action_tag"] in item.get("tags",[])),None)
    root=studio.asset_root()
    if candidate is None or root is None:return plan
    try:
        job=request_nod_sequence(root,plan["model"],plan["expression"]["label"],True)
    except (ValueError,OSError):return plan
    sequence=job.get("sequence",{})
    if job["state"]!="ready" or not sequence.get("reviewed"):return plan
    return {**plan,"motion":{
        "id":candidate["id"],"label":"うんうん","sample_time":0,
        "tags":candidate["tags"],"playback":"frame_sequence",
        "status":"reviewed_cpu_preview","duration_seconds":sequence["duration_seconds"],
    },"playback_status":"playable",
        "warnings":["已验收的实验 CPU Bezier 点头；不含完整 E-mote mask/physics"]}


def request_nod_sequence(root,model_name,expression,cached_only=False):
    entry=discover_model(Path(root),model_name)
    if entry is None or not entry["available"]:
        raise ValueError("当前角色素材不完整")
    model=PoseModel(entry["path"])
    faces={x["label"] for x in model.expression_catalog() if x["type"]=="face"}
    if not isinstance(expression,str) or expression not in faces:
        raise ValueError("请选择当前模型的面部表情")
    signature=pose_signature(entry["path"],entry["textures"],model.resx_path)
    key=sequence_key(model_name,expression,signature)
    def builder(progress):
        return export_nod_sequence(model,AtlasRenderer(model,entry["textures"]),
                                   root,key,expression,progress)
    result=SEQUENCE_JOBS.request(root,key,None if cached_only else builder)
    if result.get("sequence"):
        reviews=studio.read_json(studio.DATA/"sequence_reviews.json",{})
        reviewed=reviews.get(key) is True
        result["sequence"]["reviewed"]=reviewed
        result["sequence"]["playable"]=reviewed
    return result

def write_startup_error(exc):
    base=Path(os.getenv("LOCALAPPDATA") or Path.home())/"CharacterLab"/"logs"
    try:
        base.mkdir(parents=True,exist_ok=True)
        target=base/"startup_error.txt"
        target.write_text(
            f"CharacterStudio startup error: {type(exc).__name__}: {exc}\n\n"+
            traceback.format_exc(),
            encoding="utf-8")
        return target
    except OSError:
        return None

def select_folder():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root=tk.Tk();root.withdraw()
        root.attributes("-topmost",True)
        answer=filedialog.askdirectory(title="选择含角色 PSB 解包文件夹的游戏素材根目录")
        root.destroy()
        return Path(answer) if answer else None
    except Exception:
        return None

def setup_persistent_config():
    # Support editable Conda project and future read-only EXE install folders.
    if sys.platform=="win32" and os.getenv("LOCALAPPDATA"):
        data=Path(os.environ["LOCALAPPDATA"])/"CharacterLab"
        data.mkdir(parents=True,exist_ok=True)
        (data/"generated").mkdir(parents=True,exist_ok=True)
        studio.DATA=data
        studio.GEN=data/"generated"
        studio.SETTINGS_FILE=data/"settings.json"
        studio.MANIFEST_FILE=data/"manifest.json"
        studio.DB_FILE=data/"history.sqlite3"
    studio.init()

def pose_signature(modelpath, texture, resx):
    h=hashlib.sha256()
    h.update(RENDER_VERSION.encode())
    texture_paths=(list(texture.values()) if isinstance(texture,dict) else [texture])
    for file in (modelpath,resx,*texture_paths):
        file=Path(file)
        if file.is_file():
            stat=file.stat()
            h.update(str(file.resolve()).encode("utf-8"))
            h.update(str(stat.st_size).encode())
            h.update(str(stat.st_mtime_ns).encode())
    return h.hexdigest()

def discover_models(root):
    """Only list actually decompiled same-character models; never guess costumes from filenames."""
    root=Path(root).resolve()
    result={}
    metadata=model_meta.load(studio.DATA/"model_metadata.json")
    candidates=[]
    for code in model_meta.CHARACTER_CODES:
        candidates.extend(root.rglob(code+"_*.json"))
    for path in sorted(candidates):
        if path.name.endswith(".resx.json") or not model_meta.MODEL_PATTERN.fullmatch(path.stem):
            continue
        if not path.is_file() or path.is_symlink():
            continue
        name=path.stem
        if name in result:
            continue
        try:
            model=PoseModel(path)
            found,missing=model.find_texture_pages(root)
            total=len(model.texture_infos)
            count=len(found)
            human=model_meta.label_for(metadata,name)
            label=(human+f"（{count}/{total} 张纹理，已就绪）"
                   if not missing else
                   human+f"（{count}/{total} 张纹理，缺少：" +
                   "、".join(v["expected"] for v in missing.values())+"）")
            result[name]={
                "name":name,"path":path,"textures":found,
                "available":not missing,"total_pages":total,
                "loaded_pages":count,"missing":missing,"label":label,
            }
        except (ValueError,TypeError,KeyError,OSError) as exc:
            result[name]={
                "name":name,"path":path,"textures":{},"available":False,
                "total_pages":0,"loaded_pages":0,
                "missing":{},"label":name+"（JSON无法解析："+str(exc)[:70]+"）"
            }
    return dict(sorted(result.items(),key=lambda pair:int(pair[0].split("_")[1])))


def discover_model(root,model_name):
    """Load one exact model without reparsing every decompiled PSB in the asset tree."""
    root=Path(root).resolve()
    if not isinstance(model_name,str) or not model_meta.MODEL_PATTERN.fullmatch(model_name):
        return None
    metadata=model_meta.load(studio.DATA/"model_metadata.json")
    matches=sorted(root.glob("**/"+model_name+".json"))
    path=next((x for x in matches
               if x.is_file() and not x.is_symlink()
               and not x.name.endswith(".resx.json")),None)
    if path is None:
        return None
    try:
        model=PoseModel(path)
        found,missing=model.find_texture_pages(root)
        total=len(model.texture_infos);count=len(found)
        human=model_meta.label_for(metadata,model_name)
        label=(human+f"（{count}/{total} 张纹理，已就绪）"
               if not missing else human+f"（{count}/{total} 张纹理，缺少："+
               "、".join(v["expected"] for v in missing.values())+"）")
        return {"name":model_name,"path":path,"textures":found,
                "available":not missing,"total_pages":total,
                "loaded_pages":count,"missing":missing,"label":label}
    except (ValueError,TypeError,KeyError,OSError) as exc:
        return {"name":model_name,"path":path,"textures":{},"available":False,
                "total_pages":0,"loaded_pages":0,"missing":{},
                "label":model_name+"（JSON无法解析："+str(exc)[:70]+"）"}

def prepare_character(root, force=False, model_name="kan_0"):
    """Produce six approximate poses for any locally decompiled supported character model.
    Each model has its own cache; switching cannot overwrite another outfit's PNG.
    """
    root=Path(root).resolve()
    if not root.is_dir():
        raise FileNotFoundError("AI 素材目录不存在："+str(root))
    meta=discover_model(root,model_name)
    if meta is None:
        choices=", ".join(discover_models(root)) or "无"
        raise FileNotFoundError(f"找不到 {model_name}.json，已解出的可用模型：{choices}")
    if not meta["available"]:
        missing_names="、".join(
            x["expected"] for x in meta.get("missing",{}).values()
        )
        raise FileNotFoundError(
            f"{model_name} 的纹理不完整，现有 "
            f"{meta['loaded_pages']}/{meta['total_pages']} 张，"
            f"缺少：{missing_names}。请保留所有 tex#NNN-texture.png。"
        )
    modelpath=meta["path"]
    model=PoseModel(modelpath)
    texture=meta["textures"]
    cache=root/"character_exports"
    cache.mkdir(parents=True,exist_ok=True)
    flag=cache/f"_characterlab_render_cache_{model_name}.json"
    expected_sig=pose_signature(modelpath,texture,model.resx_path)
    output={key:cache/f"{model_name}_{key}.png" for key in
            (*POSE_KEYS.keys(),"blink","talk")}
    existing=False
    if flag.exists():
        try:
            old=json.loads(flag.read_text(encoding="utf-8"))
            existing=(old.get("signature")==expected_sig and
                      all(path.is_file() for path in output.values()))
        except (OSError,ValueError,TypeError):
            pass
    if force or not existing:
        renderer=AtlasRenderer(model,texture)
        available_labels=model.label_to_preset
        fallback=next((label for label in ("普通Ａ","普通Ｂ","普通Ｃ") if label in available_labels),next(iter(available_labels),None))
        if fallback is None:
            raise ValueError(f"{model_name} 不包含可读取的表情时间轴")
        for kind,label in POSE_KEYS.items():
            actual=next((label[:-1]+suffix for suffix in ('Ａ','Ｂ','Ｃ')
                         if label[:-1]+suffix in available_labels),fallback)
            renderer.render(actual,size=POSE_SIZE).save(output[kind])
        renderer.render(fallback,overrides=model.safe_blink_override(fallback),
                        size=POSE_SIZE).save(output["blink"])
        renderer.render(fallback,overrides={"face_talk":4},
                        size=POSE_SIZE).save(output["talk"])
        flag.write_text(json.dumps({
            "signature":expected_sig,"renderer":RENDER_VERSION,
            "model":modelpath.name,
            "available_presets":list(available_labels.keys())[:20],
            "sources":[str(p.relative_to(root)).replace("\\","/") for p in output.values()],
            "limitations":"Approximate static render. No clothing inference, mesh, or physics."
        },ensure_ascii=False,indent=2),encoding="utf-8")
        print(f"[{model_name}] 自动生成 {len(output)} 张基础角色状态图（静态近似）")
    else:
        print(f"[{model_name}] 已复用本地状态图缓存")
    return output,model


def prune_expression_cache(cache_dir,keep=(),max_files=360):
    """Bound generated expression-preview cache size.

    This folder is Character Studio's own disposable output; original game files
    are never deleted. Keep the files involved in the current response.
    """
    cache_dir=Path(cache_dir)
    keep={Path(x).resolve() for x in keep}
    try:
        candidates=[
            path for path in cache_dir.glob("*_*.png")
            if path.is_file() and not path.is_symlink()
        ]
        if len(candidates)<=max_files:
            return 0
        candidates.sort(key=lambda path:path.stat().st_mtime_ns)
        remove_count=len(candidates)-max_files
        removed=0
        for path in candidates:
            if removed>=remove_count:break
            try:
                if path.resolve() in keep:continue
                path.unlink()
                removed+=1
            except OSError:
                continue
        return removed
    except OSError:
        return 0

def render_expression_state(root,model_name,label,time=0,motion_label=None,motion_time=0):
    """Cache frame-specific expression PNG triplet, derived from the SAME preset.
    Never force the character into neutral state while talking or blinking.
    """
    root=Path(root).resolve()
    entry=discover_model(root,model_name)
    if entry is None or not entry["available"]:
        raise ValueError("当前模型未解包完整，不能生成表情")
    model=PoseModel(entry["path"])
    if not isinstance(label,str) or label not in model.label_to_preset:
        raise ValueError("表情名称不在当前模型的原始时间轴中")
    if not isinstance(time,(int,float)) or not 0<=float(time)<=600:
        raise ValueError("动作帧需要在 0–600 之间")
    time=round(float(time),2)
    catalog=model.expression_catalog()
    item=catalog[model.label_to_preset[label]]
    if time>max(0,item["duration"])+0.01:
        raise ValueError("动作帧超过当前预设的时间范围")
    movement={}
    if motion_label is not None:
        if not isinstance(motion_label,str) or motion_label not in model.label_to_preset:
            raise ValueError("动作预设不属于当前模型")
        motion_item=model.expression_catalog()[model.label_to_preset[motion_label]]
        if motion_item["type"]!="motion":
            raise ValueError("当前附加预设不是动作时间轴")
        if (not isinstance(motion_time,(int,float)) or isinstance(motion_time,bool)
            or not 0<=motion_time<=min(600,motion_item["duration"])):
            raise ValueError("动作采样时间超出范围")
        # Keep selected expression's face, mouth and tears unchanged. Sample only
        # non-face movement controls from a PSB motion into that expression.
        for key,value in model.preset_vars(motion_label,motion_time).items():
            if key.startswith(("move_","head_","body_","act_","arm_","hair_","quake_")):
                if isinstance(value,(int,float)):
                    movement[key]=value
    digest=hashlib.sha256(
        (model_name+"\0"+label+"\0"+str(time)+"\0"+
         str(motion_label)+"\0"+str(motion_time)).encode("utf-8")
    ).hexdigest()[:20]
    signature=pose_signature(entry["path"],entry["textures"],model.resx_path)[:12]
    prefix=f"{model_name}_expr_{digest}_{signature}"
    cache=root/"character_exports"/"expressions"
    cache.mkdir(parents=True,exist_ok=True)
    files={suffix:cache/f"{prefix}_{suffix}.png" for suffix in
           ("normal","blink","talk")}
    if not all(path.is_file() for path in files.values()):
        renderer=AtlasRenderer(model,entry["textures"])
        renderer.render(label,size=POSE_SIZE,time=time,
                        overrides=movement).save(files["normal"])
        renderer.render(label,size=POSE_SIZE,time=time,
                        overrides={**movement,**model.safe_blink_override(label)}).save(files["blink"])
        renderer.render(label,size=POSE_SIZE,time=time,
                        overrides={**movement,"face_talk":4}).save(files["talk"])
    # Refresh access recency so frequently used expressions survive pruning.
    for path in files.values():
        try:path.touch()
        except OSError:pass
    prune_expression_cache(cache,files.values(),max_files=360)
    return {
        "label":label,
        "model":model_name,
        "time":time,
        "motion_label":motion_label,
        "motion_time":motion_time,
        "motion_controls_applied":list(movement),
        "type":item["type"],
        "duration":item["duration"],
        "refs":{suffix:path.relative_to(root).as_posix()
                for suffix,path in files.items()},
        "limitations":"Static sampled sprites; original mesh blending, stencil and physics unavailable."
    }


def register_pose_assets(root,pose_files,model,model_name="kan_0"):
    root=Path(root).resolve()
    with studio.LOCK:
        studio.STATE["settings"]["assets_dir"]=str(root)
        studio.STATE["settings"]["character_model"]=model_name
        studio.RUNTIME.reset(model_name)
        studio.atomic_json(studio.SETTINGS_FILE,studio.STATE["settings"])
        man=dict(studio.STATE["manifest"])
        layer_id="__auto_emote_character"
        legacy_layer_ids={layer_id,"__auto_emote_kan"}
        neutral_file=pose_files["neutral"]
        neutral_ref=neutral_file.relative_to(root).as_posix()
        layer={
            "id":layer_id,
            "name":model_name+" E-mote 静态近似 · 服装取决于所选模型",
            "file":neutral_ref,"slot":"base",
            "crop":{"x":0,"y":0,"w":POSE_SIZE[0],"h":POSE_SIZE[1]},
            "x":0,"y":0,"z":0,"scale":0.39,"visible":True
        }
        layers=list(man.get("layers",[]))
        found=False
        for i,item in enumerate(layers):
            if item.get("id") in legacy_layer_ids:
                # Keep user's manually adjusted placement and scale.
                for key in ("x","y","z","scale","visible"):
                    if key in item:layer[key]=item[key]
                layers[i]=layer;found=True
                break
        if not found:
            layers.insert(0,layer)
        man["layers"]=layers
        man["poses"]={key:p.relative_to(root).as_posix()
                      for key,p in pose_files.items()}
        studio.STATE["manifest"]=studio.validate_manifest(man)
        studio.atomic_json(studio.MANIFEST_FILE,studio.STATE["manifest"])
    print(f"已把 {len(pose_files)} 张真实模型姿势与人物图层加入 AI Studio")

class StudioHandler(studio.Handler):
    """Constrained localhost costume selector; user-supplied names never become filesystem paths."""
    def do_GET(self):
        if self.path.split("?",1)[0]=="/api/expression_catalog":
            model_id=studio.STATE["settings"].get("character_model","")
            entry=discover_model(self.server.asset_root,model_id)
            if entry is None or not entry["available"]:
                return self.reply(404,{"error":"请先加载有效的角色模型"})
            model=PoseModel(entry["path"])
            catalog=model.expression_catalog()
            return self.reply(200,{
                "model":model_id,"presets":catalog,
                "faces":sum(item["type"]=="face" for item in catalog),
                "motions":sum(item["type"]=="motion" for item in catalog),
                "note":"动作采用指定帧的近似静态采样，不是原版运行时"
            })
        if self.path.split("?",1)[0]=="/api/character_models":
            root=self.server.asset_root
            found=discover_models(root)
            models=[{
                "name":v["name"],"label":v["label"],
                "available":v["available"],
                "total_pages":v["total_pages"],
                "loaded_pages":v["loaded_pages"],
                "file":v["path"].relative_to(root).as_posix()
            } for v in found.values()]
            return self.reply(200,{
                "models":models,
                "selected":studio.STATE["settings"].get("character_model",""),
                "note":"文件名无法判断有没有衣服，请切换后预览实际贴图。"
            })
        return super().do_GET()

    def do_POST(self):
        if self.path.split("?",1)[0] in ("/api/motion_sequence","/api/motion_review"):
            try:
                self.verify_origin()
                request=json.loads(self.recv())
                if not isinstance(request,dict):raise ValueError("请求体必须是对象")
                current=studio.STATE["settings"].get("character_model","")
                result=request_nod_sequence(self.server.asset_root,current,
                    request.get("expression"),bool(request.get("cached_only",False)))
                if self.path.split("?",1)[0]=="/api/motion_review":
                    if result["state"]!="ready" or result["id"]!=request.get("id"):
                        raise ValueError("请先完整预览当前版本的动作")
                    if not isinstance(request.get("reviewed"),bool):
                        raise ValueError("reviewed 必须是布尔值")
                    with studio.LOCK:
                        reviews=studio.read_json(studio.DATA/"sequence_reviews.json",{})
                        reviews[result["id"]]=request["reviewed"]
                        studio.atomic_json(studio.DATA/"sequence_reviews.json",reviews)
                    result["sequence"]["reviewed"]=request["reviewed"]
                    result["sequence"]["playable"]=request["reviewed"]
                return self.reply(200,result)
            except (ValueError,OSError) as exc:return self.err(exc)
        if self.path.split("?",1)[0]=="/api/expression_apply":
            try:
                self.verify_origin()
                request=json.loads(self.recv())
                current=studio.STATE["settings"].get("character_model","")
                if not current:
                    raise ValueError("请先选择角色模型")
                result=render_expression_state(self.server.asset_root,current,
                    request.get("label"),request.get("time",0),
                    request.get("motion_label"),request.get("motion_time",0))
                return self.reply(200,{"ok":True,**result})
            except (ValueError,FileNotFoundError,OSError) as exc:
                return self.err(exc)
            except Exception as exc:
                print("预设生成失败:",type(exc).__name__,exc)
                return self.err(RuntimeError("生成失败，请查看终端错误"),500)
        if self.path.split("?",1)[0]!="/api/character_model":
            return super().do_POST()
        try:
            self.verify_origin()
            data=json.loads(self.recv())
            requested=data.get("name","")
            if not isinstance(requested,str) or not model_meta.MODEL_PATTERN.fullmatch(requested):
                raise ValueError("未知的模型代号")
            root=self.server.asset_root
            selected=discover_model(root,requested)
            if selected is None or not selected["available"]:
                raise ValueError("模型尚未解包完整，请导出对应 JSON 和 PNG")
            with studio.LOCK:
                files,model=prepare_character(root,False,requested)
                register_pose_assets(root,files,model,requested)
            return self.reply(200,{
                "ok":True,
                "selected":requested,
                "manifest":studio.STATE["manifest"],
                "message":"已载入 "+requested+"。外观来自所选模型，无法从文件名推断是否有衣服。"
            })
        except (ValueError,FileNotFoundError,RuntimeError,OSError,json.JSONDecodeError) as exc:
            return self.err(exc)
        except Exception as exc:
            print("切换模型失败：",type(exc).__name__,str(exc))
            return self.err(RuntimeError("内部错误，请检查终端信息"),500)


def start_server(port=8765, root=None):
    from http.server import ThreadingHTTPServer
    root=Path(root or studio.STATE["settings"]["assets_dir"]).resolve()
    studio.PLAN_RENDER_ADAPTER=adapt_sequence_behavior
    try:
        server=ThreadingHTTPServer(("127.0.0.1",port),StudioHandler)
    except OSError:
        server=ThreadingHTTPServer(("127.0.0.1",0),StudioHandler)
    server.asset_root=root
    server.daemon_threads=True
    thread=threading.Thread(target=server.serve_forever,
                            kwargs={"poll_interval":0.4},daemon=True)
    thread.start()
    return server,thread


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",default=str(DEFAULT_ROOT))
    parser.add_argument("--model",help="优先选择某个已解包模型，如 kan_10 / tou_3")
    parser.add_argument("--list-models",action="store_true",help="只列出已解出的 角色模型")
    parser.add_argument("--list-backgrounds",action="store_true",help="显示已发现的背景数量及样例")
    parser.add_argument("--doctor",action="store_true",help="运行离线环境自检并退出，不连接外部服务")
    parser.add_argument("--browser",action="store_true",help="使用浏览器而不是本地 WebView2 窗口")
    parser.add_argument("--studio",action="store_true",help="打开开发工作台（默认进入游戏舞台）")
    parser.add_argument("--choose-root",action="store_true",help="启动时选择素材根目录")
    parser.add_argument("--force-render",action="store_true",help="强制重新生成基础表情及口型状态图")
    parser.add_argument("--no-poses",action="store_true",help="跳过自动姿势组装")
    parser.add_argument("--motion-probe",metavar="LABEL",help="导出一个真实动作的均匀采样验收帧")
    parser.add_argument("--probe-expression",default="笑顔Ａ",help="动作探针保持的面部预设")
    parser.add_argument("--probe-samples",type=int,default=9,help="动作探针采样数（5–31）")
    parser.add_argument("--probe-fps",type=int,default=24,help="候选帧序列目标 FPS（24–30）")
    parser.add_argument("--export-nod",action="store_true",help="导出实验 CPU 网格点头连续帧")
    parser.add_argument("--port",type=int,default=8765)
    args=parser.parse_args()
    setup_persistent_config()
    root=Path(args.root)
    if args.doctor:
        report=diagnostics.run(studio.DATA,root if root.is_dir() else None,
                               studio.STATE["settings"],
                               args.model or studio.STATE["settings"].get("character_model",""))
        print(diagnostics.format_text(report))
        return 0 if report["errors"]==0 else 3
    if args.choose_root or not root.is_dir():
        selected=select_folder()
        if not selected:
            print("没有选择有效的素材根目录，已退出。")
            return 2
        root=selected
    try:
        if args.list_backgrounds:
            found=backgrounds.discover(root,studio.DATA,force=True)
            print("本机发现的背景图片：",len(found),"张")
            for item in found[:18]:
                print(" ",item["category"],item["ref"])
            if not found:
                print("没有找到背景。请检查 _AI/assets/image/bg 或 _AI/image/bg，")
                print("也可以打开桌面程序，在「背景」页直接从电脑导入。")
            return 0
        candidates=discover_models(root)
        if args.list_models:
            print("已解出的模型：")
            for v in candidates.values():
                print(" ",v["label"],v["path"].relative_to(root))
            return 0
        chosen=args.model or studio.STATE["settings"].get("character_model","")
        if chosen not in candidates or not candidates[chosen]["available"]:
            options=[key for key,v in candidates.items() if v["available"]]
            if not options:
                raise FileNotFoundError(
                    "未找到任何已完整解包的 角色模型。"
                    "需要同名主 JSON、resx JSON 和该模型的全部纹理 PNG。"
                )
            # Never guess which is clothed. Prefer a nonzero model if locally available.
            chosen=("kan_10" if "kan_10" in options else options[0])
            print("自动选择已有模型：",chosen,"（不代表已确认有衣服）")
        if args.export_nod:
            result=request_nod_sequence(root,chosen,args.probe_expression)
            while result["state"]=="rendering":
                print("点头序列生成：",round(result["progress"]*100),"%",flush=True)
                threading.Event().wait(3)
                result=request_nod_sequence(root,chosen,args.probe_expression,True)
            print(json.dumps({k:v for k,v in result.items() if k!="sequence"},ensure_ascii=False))
            if result["state"]!="ready":return 4
            print("已输出",result["sequence"]["frame_count"],"帧；",
                  result["sequence"]["distinct_visual_frames"],"个不同画面；待人工验收")
            return 0
        if args.motion_probe:
            entry=candidates[chosen]
            model=PoseModel(entry["path"])
            renderer=AtlasRenderer(model,entry["textures"])
            safe_id=hashlib.sha256(
                (chosen+"\0"+args.probe_expression+"\0"+args.motion_probe).encode("utf-8")
            ).hexdigest()[:12]
            out=root/"character_exports"/"motion_probes"/(chosen+"_"+safe_id)
            result=export_motion_probe(
                model,renderer,out,expression_label=args.probe_expression,
                motion_label=args.motion_probe,samples=args.probe_samples,
                target_fps=args.probe_fps,size=POSE_SIZE)
            print(json.dumps(result,ensure_ascii=False,indent=2))
            print("动作探针目录：",out)
            return 0 if result["status"]=="needs_manual_review" else 4
        if not args.no_poses:
            print("正在读取真实 E-mote 部件、预设和纹理坐标...")
            output,model=prepare_character(root,args.force_render,chosen)
            register_pose_assets(root,output,model,chosen)
        else:
            with studio.LOCK:
                studio.STATE["settings"]["assets_dir"]=str(root.resolve())
        server,thread=start_server(args.port,root)
        url=f"http://127.0.0.1:{server.server_port}/?mode={'studio' if args.studio else 'game'}"
        print("Character Studio 地址：",url)
        print("默认进入游戏舞台，预设对话无语音、无需 AI；右上角设置可打开开发工作台。")
        try:
            use_browser=args.browser
            if not use_browser:
                try:
                    import webview
                except ImportError:
                    print("当前环境没有 pywebview，将临时使用浏览器模式。"
                          "安装 pip install pywebview 即可使用独立 Windows 窗口。")
                    use_browser=True
            if use_browser:
                webbrowser.open(url)
                print("按 Ctrl+C 退出后台程序。")
                thread.join()
            else:
                webview.create_window(
                    "Character Studio v0.11",url,
                    width=1280 if not args.studio else 1480,height=760 if not args.studio else 900,
                    min_size=(800,540) if not args.studio else (1030,670),
                    background_color="#0b101b"
                )
                # Force WebView2/EdgeChromium rather than obsolete IE rendering.
                webview.start(gui="edgechromium")
        except KeyboardInterrupt:
            pass
        finally:
            server.shutdown()
            server.server_close()
        return 0
    except Exception as exc:
        print("启动失败：",type(exc).__name__,str(exc))
        logfile=write_startup_error(exc)
        try:
            import tkinter as tk
            from tkinter import messagebox
            w=tk.Tk();w.withdraw()
            messagebox.showerror("Character Studio 启动失败",
                str(exc)+"\n\n错误日志："+str(logfile or "无法写入日志"))
            w.destroy()
        except Exception:
            pass
        return 1

if __name__=="__main__":
    try:
        result=main()
    except Exception as exc:
        logfile=write_startup_error(exc)
        print("启动时出现未处理异常：",str(exc),flush=True)
        print("日志路径：",logfile,flush=True)
        try:
            import tkinter as tk
            from tkinter import messagebox
            ui=tk.Tk();ui.withdraw()
            messagebox.showerror("启动失败",f"{exc}\n\n详细日志：{logfile}")
            ui.destroy()
        except Exception:
            pass
        result=1
    sys.exit(result)
