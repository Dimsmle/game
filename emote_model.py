# -*- coding: utf-8 -*-
"""E-mote PSB-decompiled JSON reader and approximate neutral-pose compositor.

Scope:
- Parses real object/motion/layer trees, texture atlas icon definitions and presets.
- Evaluates parameterized sprite replacement, position and draw depth.
- Does NOT implement E-mote mesh deformation, masks, physics, blending or runtime ABI.
Only run with locally owned/authorized model data.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from collections import Counter
from typing import Any
import math
import re

@dataclass
class Sprite:
    icon: str
    label: str
    group: str
    atlas: tuple[float,float,float,float]
    origin: tuple[float,float]
    world: tuple[float,float,float]
    z: float
    attr: int = 0
    path: str = ""
    source: str = "tex"

class PoseModel:
    def __init__(self, model_path, resx_path=None):
        self.path=Path(model_path).resolve()
        self.data=json.loads(self.path.read_text(encoding="utf-8-sig"))
        if "object" not in self.data or "source" not in self.data:
            raise ValueError("结构 JSON 缺少 object/source，请选择 PsbDecompile 的主 JSON")
        self.resx_path=Path(resx_path).resolve() if resx_path else self.path.with_name(self.path.stem+".resx.json")
        self.resx={}
        if self.resx_path.exists():
            self.resx=json.loads(self.resx_path.read_text(encoding="utf-8-sig"))
        # Each atlas source has its own icon table, dimensions and resource ID.
        self.icon_groups={
            name: value["icon"] for name,value in self.data["source"].items()
            if isinstance(value,dict) and isinstance(value.get("icon"),dict)
            and isinstance(value.get("texture"),dict)
        }
        if not self.icon_groups:
            raise ValueError("主结构 JSON source 内没有可识别的图集")
        self.texture_infos={
            name:self.data["source"][name]["texture"] for name in self.icon_groups
        }
        self.first_source=next(iter(self.icon_groups))
        self.texture_info=self.texture_infos[self.first_source]
        self.icons=self.icon_groups[self.first_source]
        self.objects=self.data.get("object",{})
        self.presets=self.data.get("metadata",{}).get("timelineControl",[])
        self.profile=self.data.get("metadata",{}).get("charaProfile",{})
        self.errors=[]
        self._warned=set()
        self.icon_count=sum(len(g) for g in self.icon_groups.values())
        self.reference=self.resx.get("Resources",{}).get("0","")
        self.label_to_preset={v.get("label",""):i for i,v in enumerate(self.presets)}
        self.active_preset=0

    @staticmethod
    def _first_value(frames):
        for f in frames:
            content=f.get("content")
            if isinstance(content,dict) and "value" in content:
                return content["value"]
        return None

    def preset_vars(self, name_or_index=0, time=0):
        if isinstance(name_or_index,str):
            index=self.label_to_preset.get(name_or_index)
            if index is None:
                raise ValueError("不存在的时间轴预设："+name_or_index)
        else:
            index=int(name_or_index)
        if not (0<=index<len(self.presets)):
            raise ValueError("预设序号不在范围内")
        answer={}
        for variable in self.presets[index].get("variableList",[]):
            frames=[]
            for f in variable.get("frameList",[]):
                content=f.get("content")
                if isinstance(content,dict) and isinstance(content.get("value"),(int,float)):
                    frames.append((float(f.get("time",0)),content["value"]))
            if not frames:
                answer[variable["label"]]=self._first_value(variable.get("frameList",[]))
                continue
            prev=frames[0]
            value=prev[1]
            for nxt in frames[1:]:
                if time<nxt[0]:
                    if prev[0]<=time and nxt[0]>prev[0]:
                        # Continuous values for action timeline scrubbing; not native
                        # E-mote nonlinear mesh/physics interpolation.
                        fraction=max(0,min(1,(time-prev[0])/(nxt[0]-prev[0])))
                        value=prev[1]+(nxt[1]-prev[1])*fraction
                    break
                prev=nxt
                value=nxt[1]
            answer[variable["label"]]=value
        return answer

    def expression_catalog(self):
        # Real kan_10: three families of 36 face presets, then 20 motion timelines.
        # Avoid assuming every future model contains exactly 108 face presets.
        result=[]
        for i,preset in enumerate(self.presets):
            label=preset["label"]
            group="face" if label.endswith("Ａ") else "motion"
            result.append({"label":label,"type":group,
                           "index":i,"duration":max(
                               (float(frame.get("time",0))
                                for v in preset.get("variableList",[])
                                for frame in v.get("frameList",[])),default=0)})
        return result

    def safe_blink_override(self,preset):
        eye=self.preset_vars(preset).get("face_eye_open",0)
        # 0=normal, 10=closed, 20=smiling eyes closed,
        # 31..50 are special expressions; never replace with a magic 38.
        if not isinstance(eye,(int,float)) or eye>=10:
            return {}
        return {"face_eye_open":10}


    @staticmethod
    def _param_time(node, motion, variables):
        idx=node.get("parameterize")
        if not isinstance(idx,int) or isinstance(idx,bool):
            idx=motion.get("parameterize")
        params=motion.get("parameter") or []
        # Many E-mote leaf motions (e.g. 目L/目R) define a single global parameter
        # without setting parameterize on individual descendants.
        if idx is None and len(params)==1:
            idx=0
        if not isinstance(idx,int) or isinstance(idx,bool) or idx<0 or idx>=len(params):
            return 0.0
        p=params[idx]
        lo=float(p.get("rangeBegin",0))
        hi=float(p.get("rangeEnd",0))
        count=float(p.get("division",60))
        default=(lo+hi)/2 if lo<0 else lo
        value=variables.get(p.get("id"),default)
        if not isinstance(value,(int,float)) or not math.isfinite(value):
            value=default
        if hi==lo:return 0
        return max(0.0,min(count,(value-lo)/(hi-lo)*count))

    @staticmethod
    def _sample_key(frames, target, key):
        # Sprite switching is discrete; changes to an icon/sprite apply at its keyframe.
        # Non-owning time/key markers do not cancel an earlier icon.
        valid=[]
        for frame in frames:
            content=frame.get("content")
            if isinstance(content,dict) and key in content:
                valid.append((float(frame.get("time",0)),content[key]))
        if not valid:return None
        selected=None
        for time,value in valid:
            if time<=target+0.000001:
                selected=value
            else:
                break
        # Critical bugfix: NEVER activate an icon from a future frame.
        # Tears are defined from frame 1; neutral frame 0 must stay blank.
        return selected

    @staticmethod
    def _sample_coord(frames, target):
        # Coordinate keys are interpolated for the neutral (zero) parameter state.
        # E-mote's nonlinear transforms and mesh blending are not replicated.
        coords=[]
        for f in frames:
            content=f.get("content")
            if isinstance(content,dict) and isinstance(content.get("coord"),list):
                v=content["coord"]
                if len(v)>=2 and all(isinstance(q,(float,int)) for q in v[:2]):
                    coords.append((float(f.get("time",0)),[
                        float(v[0]),float(v[1]),float(v[2]) if len(v)>2 else 0.0
                    ]))
        if not coords:return (0.0,0.0,0.0)
        if target<=coords[0][0]:return tuple(coords[0][1])
        if target>=coords[-1][0]:return tuple(coords[-1][1])
        for (t0,v0),(t1,v1) in zip(coords,coords[1:]):
            if t0<=target<=t1:
                t=(target-t0)/(t1-t0) if t1!=t0 else 0
                return tuple(v0[i]+(v1[i]-v0[i])*t for i in range(3))
        return tuple(coords[0][1])

    def build_pose(self, preset=0, overrides=None, time=0):
        vars=dict(self.preset_vars(preset,time))
        vars.update(overrides or {})
        self.errors=[]
        self._warned.clear()
        seen_count=0
        sprites=[]
        referenced=Counter()
        def visit_motion(objname,motionname,origin,stack):
            nonlocal seen_count
            key=(objname,motionname)
            if key in stack:
                self._warning("递归依赖环："+repr(key))
                return
            motion=self.objects.get(objname,{}).get("motion",{}).get(motionname)
            if not isinstance(motion,dict):
                self._warning("找不到运动对象："+repr(key))
                return
            stack=stack+(key,)
            for root in motion.get("layer",[]):
                visit_node(root,motion,origin,stack)
        def visit_node(node,motion,parent,stack):
            nonlocal seen_count
            seen_count+=1
            if seen_count>30000:
                raise ValueError("层级超过安全遍历上限")
            frames=node.get("frameList",[])
            t=self._param_time(node,motion,vars)
            offset=self._sample_coord(frames,t)
            position=tuple(parent[i]+offset[i] for i in range(3))
            src=self._sample_key(frames,t,"src")
            icon=self._sample_key(frames,t,"icon")
            if (isinstance(src,str) and src in self.icon_groups
                    and isinstance(icon,str) and icon in self.icon_groups[src]):
                ic=self.icon_groups[src][icon]
                metadata=ic.get("metadata") or {}
                z=float(metadata.get("zorder",position[2]))
                sprites.append(Sprite(
                    icon=icon,label=node.get("label",""),
                    group=stack[-1][0],
                    atlas=(float(ic.get("left",0)),float(ic.get("top",0)),
                           float(ic.get("width",0)),float(ic.get("height",0))),
                    origin=(float(ic.get("originX",0)),float(ic.get("originY",0))),
                    world=position,z=z,attr=int(ic.get("attr",0)),source=src,
                    path="/".join((key[0]+":"+key[1]) for key in stack)+"/"+node.get("label","")))
                referenced[(src,icon)]+=1
            elif isinstance(src,str) and src in self.objects:
                if not isinstance(icon,str):
                    self._warning(f"子动画引用缺少名称：{node.get('label')}")
                else:
                    visit_motion(src,icon,position,stack)
            for child in node.get("children",[]):
                visit_node(child,motion,position,stack)
        # Full-character root. The `タイムライン構造` object wraps this as its child.
        visit_motion("all_parts","全体構造",(0.0,0.0,0.0),())
        sprites.sort(key=lambda x:(x.z,x.path))
        self.last_summary={
            "total_layers_visited":seen_count,
            "sprites":len(sprites),
            "unique_icons":len(referenced),
            "unresolved":list(self.errors),
            "atlas_declared":[self.texture_info.get("width"),self.texture_info.get("height")],
            "visual_bounds":self.get_bounds(sprites),
        }
        return sprites

    def _warning(self,msg):
        if msg not in self._warned:
            self.errors.append(msg)
            self._warned.add(msg)

    def get_bounds(self,sprites):
        if not sprites:return [0,0,0,0]
        boxes=[]
        for s in sprites:
            x=s.world[0]-s.origin[0]
            y=s.world[1]-s.origin[1]
            boxes.append((x,y,x+s.atlas[2],y+s.atlas[3]))
        return [round(min(q[0] for q in boxes),1),
                round(min(q[1] for q in boxes),1),
                round(max(q[2] for q in boxes),1),
                round(max(q[3] for q in boxes),1)]

    def find_texture_pages(self, base=None):
        """Match PSB source[N].texture.pixel to resx Resources[N], per model."""
        roots=[self.path.parent,self.path.parent.parent]
        if base is not None:
            roots.insert(0,Path(base))
        roots=[p.resolve() for p in roots if p.is_dir()]
        resources=self.resx.get("Resources",{})
        found={}
        missing={}
        for source_name,info in self.texture_infos.items():
            match=re.search(r"#resource#(\d+)",str(info.get("pixel","")))
            resource_id=match.group(1) if match else None
            mapped=resources.get(resource_id) if resource_id is not None else None
            filename=f"{source_name}-texture.png"
            candidates=[]
            if isinstance(mapped,str) and mapped:
                rel=Path(mapped.replace("\\","/"))
                if not rel.is_absolute() and ".." not in rel.parts:
                    candidates += [root/rel for root in roots]
                    candidates += [self.path.parent/rel.name,
                                   self.path.parent/self.path.stem/rel.name]
            candidates.extend([
                self.path.parent/self.path.stem/filename,
                self.path.parent/filename,
            ])
            hit=next((c.resolve() for c in candidates if c.is_file()),None)
            if hit is None:
                missing[source_name]={"resource_id":resource_id,
                                      "expected":filename,"mapped":mapped}
            else:
                found[source_name]=hit
        return found,missing

    def discover_textures(self, base=None):
        found,missing=self.find_texture_pages(base)
        if missing:
            msg="；".join(
                f"{src}: {item['mapped'] or item['expected']}"
                for src,item in missing.items()
            )
            raise FileNotFoundError(
                f"{self.path.stem} 需要 {len(self.texture_infos)} 张图集，"
                f"找到 {len(found)} 张；缺少：{msg}。"
                "请保留模型对应的全部 tex#NNN-texture.png。"
            )
        return found

    def discover_texture(self, base=None):
        """Legacy single-atlas API, never silently drop pages of multi-atlas models."""
        textures=self.discover_textures(base)
        if len(textures)!=1:
            raise ValueError("该模型有多张图集，请使用 discover_textures()")
        return next(iter(textures.values()))

def find_model(base):
    base=Path(base)
    if base.is_file():
        if base.name.endswith(".resx.json"):
            raise ValueError("请选择主 JSON，不是 resx JSON")
        return base
    patterns=["kan_0.json","*_0.json","*.json"]
    for pattern in patterns:
        candidates=sorted(p for p in base.glob("**/"+pattern)
                          if not p.name.endswith(".resx.json")
                          and p.stat().st_size>100)
        if candidates:
            return candidates[0]
    raise FileNotFoundError("在所选目录及子目录中未找到主结构 JSON。")
