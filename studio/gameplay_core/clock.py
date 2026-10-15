"""P2 deterministic, permissionless local/virtual time selection."""
from __future__ import annotations
from datetime import datetime
from .common import identifier

CLOCK_MODES=frozenset({"system","game","manual","off"})
TIMES=frozenset({"morning","day","evening","night","unknown"})

def time_period(hour: int) -> str:
    if type(hour) is not int or not 0<=hour<=23:raise ValueError("小时不合法")
    if 5<=hour<11:return "morning"
    if 11<=hour<17:return "day"
    if 17<=hour<21:return "evening"
    return "night"

def effective_time(mode: str, *, system_now: datetime | None=None,
                   game_hour: int | None=None, manual_time: str="unknown") -> str:
    if mode not in CLOCK_MODES:raise ValueError("时间模式无效")
    if mode=="off":return "unknown"
    if mode=="manual":
        if manual_time not in TIMES:raise ValueError("手动时间标签无效")
        return manual_time
    if mode=="game":
        return time_period(game_hour)
    value=system_now or datetime.now().astimezone()
    return time_period(value.hour)

def may_auto_transition(*, scene_locked: bool, cg_active: bool,
                        tts_active: bool, reply_active: bool,
                        manual_choice_pending: bool,
                        clock_mode: str) -> bool:
    if clock_mode not in CLOCK_MODES:raise ValueError("时间模式无效")
    return (clock_mode in ("system","game")
            and not any((scene_locked,cg_active,tts_active,reply_active,
                         manual_choice_pending)))
