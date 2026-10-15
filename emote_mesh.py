"""Experimental cubic Bezier deformation from decompiled E-mote mesh data.

Only one-dimensional 4x4 combinators are supported.  This is an independent
CPU preview implementation, not the native E-mote engine.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class MeshWarp:
    bounds: tuple
    delta: tuple
    variable: str

    def apply(self,x,y):
        left,top,width,height=self.bounds
        # Extrapolation is intentional: children may extend past a parent cage.
        u=(x-left)/width;v=(y-top)/height
        bu=((1-u)**3,3*u*(1-u)**2,3*u*u*(1-u),u**3)
        bv=((1-v)**3,3*v*(1-v)**2,3*v*v*(1-v),v**3)
        dx=dy=0.0
        for row in range(4):
            for col in range(4):
                weight=bu[col]*bv[row]
                index=(row*4+col)*2
                dx+=self.delta[index]*weight
                dy+=self.delta[index+1]*weight
        return x+dx*width,y+dy*height


def combinator_warps(node,content,origin,variables,resources,enabled=("head_UD",)):
    if not node.get("meshTransform") or content.get("src")!="blank":
        return ()
    try:
        width,height,ox,oy=map(float,content["icon"].split(":"))
        if width<=0 or height<=0:return ()
    except (ValueError,KeyError,AttributeError):
        return ()
    result=[]
    for comb in (node.get("meshCombinator") or {}).get("combinatorList",[]):
        spec=comb.get("variable") or {}
        key=spec.get("key")
        if key not in enabled:continue
        values=resources.get(str(comb.get("rawMeshList","")).replace("#resource",""))
        count=spec.get("meshCount",0)
        neutral=comb.get("neutralIndex",0)
        if (comb.get("meshType")!=1 or not isinstance(count,int) or count<2
            or not isinstance(values,list) or len(values)!=count*32
            or not isinstance(neutral,int) or not 0<=neutral<count):
            continue
        lo=float(spec.get("rangeBegin",0));hi=float(spec.get("rangeEnd",0))
        if hi<=lo:continue
        default=lo+(hi-lo)*neutral/(count-1)
        value=variables.get(key,default)
        if not isinstance(value,(int,float)) or not math.isfinite(value):continue
        pos=max(0,min(count-1,(value-lo)/(hi-lo)*(count-1)))
        a=min(count-2,int(pos));fraction=pos-a
        delta=tuple(values[a*32+i]*(1-fraction)+values[(a+1)*32+i]*fraction
                    -values[neutral*32+i] for i in range(32))
        if max(abs(x) for x in delta)<1e-9:continue
        result.append(MeshWarp((origin[0]-ox,origin[1]-oy,width,height),delta,key))
    return tuple(result)


def warp_point(x,y,warps):
    for warp in reversed(warps):
        x,y=warp.apply(x,y)
    return x,y


def inverse_point(x,y,warps):
    # Undo each cage separately, outermost first; small nod motions converge fast.
    for warp in warps:
        tx,ty=x,y
        for _ in range(6):
            wx,wy=warp.apply(x,y)
            ex,ey=tx-wx,ty-wy
            x+=ex;y+=ey
            if abs(ex)+abs(ey)<1e-5:break
    return x,y


def warp_sprite(image,sprite,scale,divisions=6):
    """Return a cropped deformed sprite plus its world-space upper-left point."""
    from PIL import Image
    left=sprite.world[0]-sprite.origin[0]
    top=sprite.world[1]-sprite.origin[1]
    width,height=sprite.atlas[2:]
    points=[warp_point(left+width*x/4,top+height*y/4,sprite.warps)
            for y in range(5) for x in range(5)]
    xmin=min(p[0] for p in points)-2/scale
    ymin=min(p[1] for p in points)-2/scale
    xmax=max(p[0] for p in points)+2/scale
    ymax=max(p[1] for p in points)+2/scale
    w=max(1,math.ceil((xmax-xmin)*scale))
    h=max(1,math.ceil((ymax-ymin)*scale))
    if w>3000 or h>4000:
        raise ValueError("网格变形超出预览边界")
    sx=image.width/width;sy=image.height/height
    xs=sorted(set(round(i*w/divisions) for i in range(divisions+1)))
    ys=sorted(set(round(i*h/divisions) for i in range(divisions+1)))
    coords={}
    for py in ys:
        for px in xs:
            x,y=inverse_point(xmin+px/scale,ymin+py/scale,sprite.warps)
            coords[(px,py)]=((x-left)*sx,(y-top)*sy)
    mesh=[]
    for y0,y1 in zip(ys,ys[1:]):
        for x0,x1 in zip(xs,xs[1:]):
            quad=tuple(c for p in ((x0,y0),(x0,y1),(x1,y1),(x1,y0)) for c in coords[p])
            mesh.append(((x0,y0,x1,y1),quad))
    return image.transform((w,h),Image.Transform.MESH,mesh,
                           resample=Image.Resampling.BICUBIC),xmin,ymin
