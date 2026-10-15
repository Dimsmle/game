"""Build/cache transparent CPU mesh preview sequences, with bounded background jobs."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import threading
import time

from motion_probe import motion_overrides

SEQUENCE_VERSION="cpu-nod-1"
SOURCE_FPS=60
OUTPUT_SIZE=(444,750)


def sequence_key(model_name,expression,signature):
    return hashlib.sha256((SEQUENCE_VERSION+"\0"+model_name+"\0"+expression+
                           "\0"+signature).encode()).hexdigest()[:24]


def export_nod_sequence(model,renderer,asset_root,key,expression,progress=None):
    catalog={entry["label"]:entry for entry in model.expression_catalog()}
    if expression not in catalog or catalog[expression]["type"]!="face":
        raise ValueError("请选择当前模型的面部表情")
    motion=catalog.get("うんうん")
    if not motion or motion["type"]!="motion":
        raise ValueError("当前模型没有うんうん时间轴")
    duration=float(motion["duration"])
    if not math.isfinite(duration) or not 0<duration<=240:
        raise ValueError("点头时间轴超出实验预览支持范围")
    root=Path(asset_root).resolve()
    folder=root/"character_exports"/"sequences"/key
    folder.mkdir(parents=True,exist_ok=True)
    fps=24
    count=math.ceil(duration/SOURCE_FPS*fps)+1
    frames=[];pixel_hashes=set();deformed=0
    started=time.monotonic()
    for i in range(count):
        source_time=min(duration,i*SOURCE_FPS/fps)
        overrides=motion_overrides(model,"うんうん",source_time)
        states={"normal":{},"blink":model.safe_blink_override(expression),"talk":{"face_talk":4}}
        refs={}
        for state,extra in states.items():
            image=renderer.render(expression,overrides={**overrides,**extra},
                                  size=OUTPUT_SIZE,mesh_preview=True)
            if state=="normal":
                pixel_hashes.add(hashlib.sha256(image.tobytes()).hexdigest())
                deformed=max(deformed,sum(bool(s.warps) for s in
                    model.build_pose(expression,overrides,mesh_preview=True)))
            path=folder/f"{i:03d}_{state}.png"
            image.save(path)
            refs[state]=path.relative_to(root).as_posix()
        frames.append({"source_time":source_time,"refs":refs})
        if progress:progress(i+1,count)
    if len(pixel_hashes)<2 or not deformed:
        raise ValueError("当前模型没有产生有效网格变化，保留静态预览")
    settled={}
    for state,extra in states.items():
        path=folder/("settled_"+state+".png")
        renderer.render(expression,overrides=extra,size=OUTPUT_SIZE).save(path)
        settled[state]=path.relative_to(root).as_posix()
    result={
        "id":key,"model":model.path.stem,"expression":expression,"motion":"うんうん",
        "renderer_id":"cpu_mesh_sequence_preview","fps":fps,
        "source_fps":SOURCE_FPS,"source_duration":duration,
        "duration_seconds":duration/SOURCE_FPS,"size":list(OUTPUT_SIZE),
        "frame_count":count,"distinct_visual_frames":len(pixel_hashes),
        "deformed_sprites":deformed,"frames":frames,"settled_refs":settled,
        "render_seconds":round(time.monotonic()-started,2),
        "reviewed":False,"playable":False,
        "limitations":"实验 CPU Bezier 点头；仅 head_UD，不含完整 E-mote mask/physics。",
    }
    temp=folder/"sequence.json.tmp"
    temp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    temp.replace(folder/"sequence.json")
    return result


class SequenceJobs:
    """One renderer at a time; progress polls never enqueue duplicate work."""
    def __init__(self):
        self.lock=threading.RLock()
        self.jobs={}
        self.active=None

    @staticmethod
    def read_cached(root,key):
        path=Path(root)/"character_exports"/"sequences"/key/"sequence.json"
        try:
            value=json.loads(path.read_text(encoding="utf-8"))
            if value.get("id")!=key or not value.get("frames"):return None
            for refs in [x["refs"] for x in value["frames"]]+[value["settled_refs"]]:
                for ref in refs.values():
                    file=(Path(root)/ref).resolve()
                    if not file.is_relative_to(Path(root).resolve()) or not file.is_file():return None
            return value
        except (OSError,ValueError,TypeError,KeyError):return None

    def request(self,root,key,builder=None):
        with self.lock:
            if key in self.jobs:
                if self.jobs[key]["state"]=="failed" and builder is not None:
                    del self.jobs[key]
                else:return deepcopy(self.jobs[key])
            cached=self.read_cached(root,key)
            if cached:return {"id":key,"state":"ready","progress":1,"sequence":cached}
            if builder is None:return {"id":key,"state":"missing","progress":0}
            if self.active is not None:
                raise ValueError("正在生成另一套动作，请等待当前任务结束")
            if len(self.jobs)>=12:
                self.jobs={k:v for k,v in self.jobs.items() if v["state"]=="rendering"}
            self.jobs[key]={"id":key,"state":"rendering","progress":0}
            self.active=key

            def progress(done,total):
                with self.lock:self.jobs[key]["progress"]=round(done/total,3)

            def run():
                try:
                    value=builder(progress)
                    with self.lock:self.jobs[key]={"id":key,"state":"ready","progress":1,"sequence":value}
                except Exception as exc:
                    with self.lock:self.jobs[key]={"id":key,"state":"failed","progress":0,
                                                  "error":str(exc)[:250]}
                finally:
                    with self.lock:self.active=None
            threading.Thread(target=run,name="sequence-render",daemon=True).start()
            return deepcopy(self.jobs[key])
