# -*- coding: utf-8 -*-
"""Pillow sprite compositor (approximate, no mesh deformation)."""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw
import math
from emote_model import Sprite
from emote_mesh import warp_sprite

RESAMPLE=Image.Resampling.LANCZOS
class AtlasRenderer:
    def __init__(self, model, texture_path):
        self.model=model
        if isinstance(texture_path,dict):
            pages={key:Path(value) for key,value in texture_path.items()}
        else:
            if len(model.icon_groups)!=1:
                raise ValueError("多图集模型须传入 source_name → PNG路径 的完整映射")
            pages={model.first_source:Path(texture_path)}
        missing=set(model.icon_groups)-set(pages)
        if missing:
            raise ValueError("纹理页缺失："+", ".join(sorted(missing)))
        self.texture_paths={name:p.resolve() for name,p in pages.items()}
        self.atlases={}
        self.atlas_scales={}
        for name,filename in self.texture_paths.items():
            with Image.open(filename) as source:
                atlas=source.convert("RGBA")
            self.atlases[name]=atlas
            info=model.texture_infos[name]
            width=float(info.get("width") or atlas.width)
            height=float(info.get("height") or atlas.height)
            self.atlas_scales[name]=(atlas.width/width,atlas.height/height)
        # Retain old diagnostic fields for the single-atlas debugger.
        self.texture_path=self.texture_paths[model.first_source]
        self.atlas=self.atlases[model.first_source]
        self.atlas_sx,self.atlas_sy=self.atlas_scales[model.first_source]
        self.sprite_cache={}
        self.reference_bounds=model.get_bounds(model.build_pose(0))
        self.draw_info=[]
        self.last_skipped=[]

    def _sprite_source(self,sprite):
        key=(sprite.source,sprite.icon)
        if key in self.sprite_cache:
            return self.sprite_cache[key]
        if sprite.source not in self.atlases:
            self.last_skipped.append((str(key),"未知纹理页"))
            return None
        atlas=self.atlases[sprite.source]
        sx,sy=self.atlas_scales[sprite.source]
        x,y,w,h=sprite.atlas
        left=round(x*sx)
        top=round(y*sy)
        right=round((x+w)*sx)
        bottom=round((y+h)*sy)
        box=(max(0,left),max(0,top),min(atlas.width,right),min(atlas.height,bottom))
        if box[2]<=box[0] or box[3]<=box[1]:
            self.last_skipped.append((str(key),"纹理范围越界"))
            return None
        cropped=atlas.crop(box)
        self.sprite_cache[key]=cropped
        return cropped

    @staticmethod
    def _paste_rgba(canvas, image, x, y):
        # Image.alpha_composite(..., dest=(x,y)) accepts negative origins on supported Pillow versions,
        # but explicitly clipping works more reliably across Windows builds.
        x=int(round(x));y=int(round(y))
        l=max(x,0);t=max(y,0)
        r=min(x+image.width,canvas.width);b=min(y+image.height,canvas.height)
        if r<=l or b<=t:return
        cropped=image.crop((l-x,t-y,r-x,b-y))
        canvas.alpha_composite(cropped,(l,t))

    def render(self, preset=0, overrides=None, size=(740,1250),
               hidden_icons=None, adjust_origin=(0,0), zoom=1.0, time=0,
               mesh_preview=False):
        if not isinstance(size,(list,tuple)) or len(size)!=2:
            raise ValueError("size 必须是 (宽,高)")
        W,H=int(size[0]),int(size[1])
        if not (128<=W<=2500 and 128<=H<=3500):
            raise ValueError("渲染尺寸需要在 128–2500 × 128–3500")
        ops=self.model.build_pose(preset,overrides,time=time,mesh_preview=mesh_preview)
        xmin,ymin,xmax,ymax=self.reference_bounds
        padx=80;pady=90
        world_w=(xmax-xmin)+2*padx
        world_h=(ymax-ymin)+2*pady
        scale=min(W/world_w,H/world_h)*float(zoom)
        cx=(xmin+xmax)/2+adjust_origin[0]
        cy=(ymin+ymax)/2+adjust_origin[1]
        canvas=Image.new("RGBA",(W,H),(0,0,0,0))
        self.draw_info=[]
        self.last_skipped=[]
        hidden_icons=set(hidden_icons or ())
        for sprite in ops:
            unique_key=f"{sprite.source}:{sprite.icon}"
            if unique_key in hidden_icons or sprite.icon in hidden_icons:continue
            source=self._sprite_source(sprite)
            if source is None:continue
            sdx=max(1,round(sprite.atlas[2]*scale))
            sdy=max(1,round(sprite.atlas[3]*scale))
            # Atlas texels and virtual dimensions may differ (uploaded/preview PNG often half-res).
            try:
                resized=source.resize((sdx,sdy),RESAMPLE)
            except (MemoryError,ValueError):
                self.last_skipped.append((unique_key,"图像缩放失败"))
                continue
            world_x=sprite.world[0]-sprite.origin[0]
            world_y=sprite.world[1]-sprite.origin[1]
            if sprite.warps:
                resized,world_x,world_y=warp_sprite(source,sprite,scale)
            screen_x=(world_x-cx)*scale+W/2
            screen_y=(world_y-cy)*scale+H/2
            self._paste_rgba(canvas,resized,screen_x,screen_y)
            self.draw_info.append({"icon":sprite.icon,"source":sprite.source,
               "key":unique_key,"label":sprite.label,
               "x":round(screen_x,2),"y":round(screen_y,2),
               "w":sdx,"h":sdy,"z":sprite.z,
               "group":sprite.group,"attr":sprite.attr})
        return canvas

    @staticmethod
    def preview_checker(im,checker=18,colors=((32,40,57),(47,59,76))):
        background=Image.new("RGBA",im.size,(0,0,0,255))
        d=ImageDraw.Draw(background)
        for y in range(0,im.height,checker):
            for x in range(0,im.width,checker):
                color=colors[(x//checker+y//checker)%2]
                d.rectangle((x,y,x+checker,y+checker),fill=(*color,255))
        return Image.alpha_composite(background,im)
