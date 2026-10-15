# -*- coding: utf-8 -*-
"""Honest preflight for a PSB motion before enabling frame-sequence playback.

The current renderer can sample sprite/coordinate parameters but cannot apply
E-mote mesh deformation.  This probe deliberately refuses to call an action
playable when several points on its source timeline render to identical pixels.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

MOVEMENT_PREFIXES=("move_","head_","body_","act_","arm_","hair_","quake_")


def _pixel_digest(image):
    return hashlib.sha256(image.tobytes()).hexdigest()


def _timeline_entry(model,label):
    if label not in model.label_to_preset:
        raise ValueError("时间轴不存在："+label)
    return model.expression_catalog()[model.label_to_preset[label]]


def motion_overrides(model,label,time):
    """Keep motion controls separate from the selected facial expression."""
    return {
        key:value for key,value in model.preset_vars(label,time).items()
        if key.startswith(MOVEMENT_PREFIXES)
        and isinstance(value,(int,float)) and not isinstance(value,bool)
        and math.isfinite(value)
    }


def export_motion_probe(model,renderer,output_dir,*,expression_label,
                        motion_label,samples=9,target_fps=24,size=(740,1250)):
    """Render evenly-spaced audit frames and write a machine-readable verdict.

    This is a gate, not a fake player.  A visually varying result still needs
    human review before a full sequence can be marked playable.
    """
    if not isinstance(samples,int) or isinstance(samples,bool) or not 5<=samples<=31:
        raise ValueError("动作探针采样数需要在 5–31 之间")
    if target_fps not in range(24,31):
        raise ValueError("目标帧率需要在 24–30 FPS 之间")
    expression=_timeline_entry(model,expression_label)
    motion=_timeline_entry(model,motion_label)
    if expression["type"]!="face":
        raise ValueError("动作探针的基础表情必须是面部预设")
    if motion["type"]!="motion":
        raise ValueError("动作探针只接受动作时间轴")
    duration=float(motion["duration"])
    if duration<=0:
        raise ValueError("动作时间轴时长必须大于 0")

    output_dir=Path(output_dir)
    output_dir.mkdir(parents=True,exist_ok=True)
    times=[duration*i/(samples-1) for i in range(samples)]
    frames=[]
    digests=[]
    all_controls=set()
    transparent=True
    for index,time in enumerate(times):
        overrides=motion_overrides(model,motion_label,time)
        all_controls.update(overrides)
        image=renderer.render(expression_label,overrides=overrides,size=size)
        path=output_dir/f"sample_{index:02d}.png"
        image.save(path)
        digest=_pixel_digest(image)
        digests.append(digest)
        alpha_min,alpha_max=image.getchannel("A").getextrema()
        transparent=transparent and alpha_min<255
        frames.append({
            "index":index,"source_time":round(time,4),
            "file":path.name,"sha256_pixels":digest,
            "controls":overrides,
            "alpha_range":[alpha_min,alpha_max],
        })

    # One speech frame verifies that mouth state can remain a separate overlay
    # input without overwriting the chosen face or motion parameters.
    middle_time=times[len(times)//2]
    middle_overrides=motion_overrides(model,motion_label,middle_time)
    normal=renderer.render(expression_label,overrides=middle_overrides,size=size)
    talk=renderer.render(expression_label,
                         overrides={**middle_overrides,"face_talk":4},size=size)
    talk_path=output_dir/"talk_overlay_probe.png"
    talk.save(talk_path)
    distinct_count=len(set(digests))
    talk_distinct=_pixel_digest(normal)!=_pixel_digest(talk)
    status="needs_manual_review" if distinct_count>1 else "blocked_identical_frames"
    result={
        "version":1,"model":model.path.stem,
        "expression":expression_label,"motion":motion_label,
        "source_duration":duration,"sample_count":samples,
        "target_fps":target_fps,"transparent_background":transparent,
        "motion_controls":sorted(all_controls),
        "distinct_visual_frames":distinct_count,
        "talk_overlay_distinct":talk_distinct,
        "status":status,"playable":False,
        "frames":frames,"talk_probe":talk_path.name,
        "reason":(
            "采样点像素完全相同；当前静态渲染器没有还原该动作依赖的 E-mote mesh 变形。"
            if distinct_count<=1 else
            "采样点存在视觉变化，但必须人工检查头、身体、服装和遮罩后才能标记 playable。"
        ),
        "limitations":[
            "尚未实现 E-mote mesh/mask/physics",
            "这是均匀采样验收探针，不是原生 E-mote 播放器",
            "通过像素变化检查也不等于已经通过人工画面验收",
        ],
    }
    (output_dir/"probe.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return result
