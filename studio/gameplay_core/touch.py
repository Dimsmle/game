"""P5 reviewed hitbox profile and non-explicit touch intent/cooldown.

Coordinates are character-local normalized values after Codex's CSS/WebView2
stage inverse transform. Untrusted frontend region guesses are ignored.
"""
from __future__ import annotations
from copy import deepcopy
import math
from collections import OrderedDict
from threading import RLock
from .common import identifier, require_keys, strict_integer

ALLOWED_REGIONS=frozenset({"head","hair","shoulder","hand","arm"})
ALLOWED_GESTURES=frozenset({"tap"})  # No uncontrolled gestures in v0.15.

def _number(value: object, *, label="坐标") -> float:
    if isinstance(value,bool) or not isinstance(value,(int,float)):
        raise ValueError(f"{label} 不是数字")
    x=float(value)
    if not math.isfinite(x) or not 0<=x<=1:
        raise ValueError(f"{label} 不在 0..1 范围")
    return x

def _inside_polygon(point: tuple[float,float], polygon: list[list[float]]) -> bool:
    # Winding-independent ray casting, with on-edge points treated as inside.
    x,y=point
    inside=False
    last=polygon[-1]
    for here in polygon:
        x1,y1=last;x2,y2=here
        cross=(x-x1)*(y2-y1)-(y-y1)*(x2-x1)
        if abs(cross)<1e-10 and min(x1,x2)-1e-10<=x<=max(x1,x2)+1e-10 and min(y1,y2)-1e-10<=y<=max(y1,y2)+1e-10:
            return True
        if (y1>y)!=(y2>y):
            intersect=x1+(y-y1)*(x2-x1)/(y2-y1)
            if x<intersect:inside=not inside
        last=here
    return inside

def _cross(a, b, c) -> float:
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def _polygon_crosses_itself(polygon: list[list[float]]) -> bool:
    """Reject tangled polygons; ambiguous overlap should never cause a touch."""
    n=len(polygon)
    for i in range(n):
        a,b=polygon[i],polygon[(i+1)%n]
        for j in range(i+1,n):
            # Adjacent edges share vertices by design; skip them.
            if j==i or j==(i+1)%n or (j+1)%n==i:
                continue
            c,d=polygon[j],polygon[(j+1)%n]
            cross1=_cross(a,b,c);cross2=_cross(a,b,d)
            cross3=_cross(c,d,a);cross4=_cross(c,d,b)
            if cross1*cross2 < -1e-14 and cross3*cross4 < -1e-14:
                return True
            # Nonadjacent edges sharing a vertex or collinear overlap is also
            # invalid even when strict crossing tests don't catch it.
            if a==c or a==d or b==c or b==d:
                return True
            for p,q,r in ((a,b,c),(a,b,d),(c,d,a),(c,d,b)):
                if (abs(_cross(p,q,r))<1e-12 and
                        min(p[0],q[0])-1e-12<=r[0]<=max(p[0],q[0])+1e-12 and
                        min(p[1],q[1])-1e-12<=r[1]<=max(p[1],q[1])+1e-12):
                    return True
    return False


def validate_hitbox_profile(profile: object) -> dict:
    raw=require_keys(profile,{"profile_id","model_id","outfit_id","pose_id",
                   "verified","regions"},{"profile_id","model_id","pose_id",
                   "verified","regions"},label="触摸区域配置")
    result=deepcopy(raw)
    for key in ("profile_id","model_id","pose_id"):
        identifier(result[key],key)
    if "outfit_id" in result and result["outfit_id"] is not None:
        identifier(result["outfit_id"],"服装 ID")
    if type(result["verified"]) is not bool:
        raise ValueError("区域人工确认字段必须是布尔值")
    regions=result["regions"]
    if not isinstance(regions,list) or not 1<=len(regions)<=30:
        raise ValueError("角色命中区数量不合法")
    unique=set()
    for region in regions:
        require_keys(region,{"name","polygon","z","enabled"},
                     {"name","polygon","z","enabled"},label="命中区域")
        if region["name"] not in ALLOWED_REGIONS:
            raise ValueError("不允许的交互区域")
        if type(region["enabled"]) is not bool:
            raise ValueError("命中区启用字段无效")
        strict_integer(region["z"],-1000,1000,"命中区层级")
        poly=region["polygon"]
        if not isinstance(poly,list) or not 3<=len(poly)<=20:
            raise ValueError("必须用 3–20 个顶点定义一个多边形")
        for point in poly:
            if not isinstance(point,list) or len(point)!=2:
                raise ValueError("多边形坐标结构错误")
            _number(point[0]);_number(point[1])
        if len({tuple(pt) for pt in poly})<3:
            raise ValueError("触摸区域退化为线段")
        area=abs(sum(poly[i][0]*poly[(i+1)%len(poly)][1]-
                     poly[(i+1)%len(poly)][0]*poly[i][1]
                     for i in range(len(poly))))/2
        if area<1e-5:
            raise ValueError("触摸区域面积过小")
        if _polygon_crosses_itself(poly):
            raise ValueError("触摸区域多边形存在自相交或重复顶点")
        if region["name"] in unique:
            raise ValueError("第一版每种语义区域只允许配置一个命中区")
        unique.add(region["name"])
    return result

def hit_test(profile: dict, x: float, y: float, *,
             overlay_blocked=False, character_visible=True) -> str | None:
    valid=validate_hitbox_profile(profile)
    px=_number(x);py=_number(y)
    if not valid["verified"] or overlay_blocked or not character_visible:
        return None
    for region in sorted(valid["regions"],key=lambda r:r["z"],reverse=True):
        if region["enabled"] and _inside_polygon((px,py),region["polygon"]):
            return region["name"]
    return None

def normalize_touch_message(value: object, profile: dict,
                            *, current_model_id: str,
                            current_pose_id: str,
                            current_outfit_id: str | None = None,
                            blocked=False) -> dict | None:
    raw=require_keys(value,{"request_id","gesture","x","y","region"},
                    {"request_id","gesture","x","y"},label="触摸输入")
    request=identifier(raw["request_id"],"触摸请求 ID")
    if raw["gesture"] not in ALLOWED_GESTURES:
        raise ValueError("本阶段仅允许单次轻点")
    reviewed=validate_hitbox_profile(profile)
    if (reviewed["model_id"]!=current_model_id or reviewed["pose_id"]!=current_pose_id
        or reviewed.get("outfit_id")!=current_outfit_id):
        raise ValueError("触摸映射与当前模型/姿势/服装不符")
    region=hit_test(reviewed,raw["x"],raw["y"],overlay_blocked=blocked)
    if not region:return None
    # The region sent by the browser, if present, is intentionally ignored.
    return {"type":"touch","request_id":request,"region":region,"gesture":"tap",
            "model_id":current_model_id,"pose_id":current_pose_id}

class TouchCooldown:
    def __init__(self,seconds: float=3.0):
        if isinstance(seconds,bool) or not isinstance(seconds,(float,int)) or not 0.5<=seconds<=30:
            raise ValueError("点击间隔不合法")
        self.seconds=float(seconds)
        self._last={}
    def permit(self, *, profile_id: str, region: str, now: float) -> bool:
        identifier(profile_id,"存档 ID")
        if region not in ALLOWED_REGIONS:raise ValueError("未知触摸区域")
        if isinstance(now,bool) or not isinstance(now,(float,int)) or not math.isfinite(now):
            raise ValueError("单调计时数值无效")
        key=(profile_id,region)
        last=self._last.get(key)
        if last is not None and now-last<self.seconds:
            return False
        self._last[key]=float(now)
        return True
    def reset(self,profile_id: str | None=None) -> None:
        if profile_id is None:self._last.clear()
        else:
            identifier(profile_id)
            self._last={key:v for key,v in self._last.items() if key[0]!=profile_id}

def touch_for_llm(touch: dict) -> str:
    """Only semantic intent; no physical-contact claim or raw long-term coords."""
    if touch.get("type")!="touch" or touch.get("region") not in ALLOWED_REGIONS:
        raise ValueError("非法触摸事件")
    translations={"head":"头部","hair":"头发","shoulder":"肩膀",
                  "hand":"手部","arm":"手臂"}
    return (f"玩家刚才在虚拟角色立绘的{translations[touch['region']]}区域点击了一下。"
            "请根据人物性格、心情与关系阶段自然回应；可以友善拒绝。"
            "这只是游戏内的点击互动，并非现实身体接触。"
            "不能仅凭这次触摸自动增加好感度或信任度。")


class TouchRequestGate:
    """Bounded, thread-safe deduplication + per-region/global touch cooldown.

    This is best-effort local throttling, not a substitute for the main app's
    profile lock or any durable event choice idempotency.
    """
    def __init__(self, *, region_seconds=3.0, global_seconds=0.5,
                 max_remembered=2048):
        for value,name in ((region_seconds,"区域"),(global_seconds,"全局")):
            if isinstance(value,bool) or not isinstance(value,(int,float)):
                raise ValueError(name+"冷却不是数字")
            if not math.isfinite(value) or not 0 <= value <= 30:
                raise ValueError(name+"冷却不在允许范围")
        if type(max_remembered) is not int or not 32<=max_remembered<=100_000:
            raise ValueError("触摸去重容量无效")
        self.region_seconds=float(region_seconds)
        self.global_seconds=float(global_seconds)
        self.max_remembered=max_remembered
        self._lock=RLock()
        self._requests=OrderedDict()
        self._last_region={}
        self._last_profile={}

    def permit(self, *, profile_id: str, region: str,
               request_id: str, now: float) -> bool:
        profile_id=identifier(profile_id,"角色档案")
        identifier(request_id,"触摸请求")
        if region not in ALLOWED_REGIONS:
            raise ValueError("不允许的触摸部位")
        if isinstance(now,bool) or not isinstance(now,(int,float)) or not math.isfinite(now):
            raise ValueError("触摸时间戳无效")
        stamp=float(now)
        if stamp<0:
            raise ValueError("触摸时间戳不能为负")
        with self._lock:
            pair=(profile_id,request_id)
            if pair in self._requests:
                return False
            # All attempts are remembered to reject late replay even when
            # the first attempt was throttled.
            self._requests[pair]=stamp
            if len(self._requests)>self.max_remembered:
                self._requests.popitem(last=False)
            if (stamp-self._last_profile.get(profile_id,float("-inf"))
                    < self.global_seconds):
                return False
            if (stamp-self._last_region.get((profile_id,region),float("-inf"))
                    < self.region_seconds):
                return False
            self._last_region[(profile_id,region)]=stamp
            self._last_profile[profile_id]=stamp
            return True

    def clear_profile(self,profile_id: str) -> None:
        identifier(profile_id)
        with self._lock:
            self._requests=OrderedDict(
                (key,value) for key,value in self._requests.items()
                if key[0]!=profile_id)
            self._last_region={
                key:value for key,value in self._last_region.items()
                if key[0]!=profile_id}
            self._last_profile.pop(profile_id,None)

    def reset(self, profile_id=None):
        if profile_id is not None:
            return self.clear_profile(profile_id)
        with self._lock:
            self._requests.clear()
            self._last_region.clear()
            self._last_profile.clear()
