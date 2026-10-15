# -*- coding: utf-8 -*-
"""Renderer capability contract.

This module intentionally exposes capabilities rather than pretending every
backend can play the same resources. Chat/behavior code depends on this
contract, while real pixel rendering stays in the selected adapter.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Protocol

@dataclass(frozen=True)
class RendererCapabilities:
    renderer_id: str
    display_name: str
    expressions: bool
    expression_blend: bool
    motion_preview: bool
    continuous_motion: bool
    mesh_deformation: bool
    masks: bool
    physics: bool
    lip_sync: str
    transparent_background: bool
    notes: tuple[str,...]=()

    def to_dict(self):
        value=asdict(self);value["notes"]=list(self.notes);return value

class CharacterRenderer(Protocol):
    def capabilities(self)->RendererCapabilities: ...
    def load(self,model_config:dict): ...
    def set_expression(self,emotion:str,weight:float=1.0): ...
    def play_motion(self,motion_id:str,priority:int=0,loop:bool=False): ...
    def set_lip_amplitude(self,value:float): ...
    def update(self,dt_seconds:float): ...
    def dispose(self): ...

STATIC_PREVIEW=RendererCapabilities(
    renderer_id="static_emote_preview",
    display_name="E-mote JSON 静态近似预览",
    expressions=True,
    expression_blend=False,
    motion_preview=True,
    continuous_motion=False,
    mesh_deformation=False,
    masks=False,
    physics=False,
    lip_sync="three_state_png",
    transparent_background=True,
    notes=(
        "从 PsbDecompile JSON/纹理采样静态帧",
        "动作时间轴仅采样部分头部/身体变量",
        "不等价于原版 E-mote 连续动画",
    )
)

FRAME_SEQUENCE_TARGET=RendererCapabilities(
    renderer_id="frame_sequence_target",
    display_name="透明帧序列（规划中的中间后端）",
    expressions=True,expression_blend=False,motion_preview=True,
    continuous_motion=True,mesh_deformation=False,masks=False,physics=False,
    lip_sync="overlay_or_audio_amplitude",transparent_background=True,
    notes=("尚未实现；只有生成并人工验收的连续帧资源才能标记 playable",)
)

LIVE2D_TARGET=RendererCapabilities(
    renderer_id="live2d_cubism_target",
    display_name="Live2D Cubism（规划后端）",
    expressions=True,expression_blend=True,motion_preview=True,
    continuous_motion=True,mesh_deformation=True,masks=True,physics=True,
    lip_sync="parameter",transparent_background=True,
    notes=("需要合法制作并 rig 的 Cubism 模型，PSB 不能直接改名转换成 moc3",)
)

def current_capabilities(renderer_id="static_emote_preview"):
    table={x.renderer_id:x for x in (STATIC_PREVIEW,FRAME_SEQUENCE_TARGET,LIVE2D_TARGET)}
    return table.get(renderer_id,STATIC_PREVIEW).to_dict()

def all_capabilities():
    return [x.to_dict() for x in (STATIC_PREVIEW,FRAME_SEQUENCE_TARGET,LIVE2D_TARGET)]
