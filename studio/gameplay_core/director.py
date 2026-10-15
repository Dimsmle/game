"""P3 deterministic, offline event presentation gate (NO database writes).

Codex must persist this state using event_instances/event_choices and call the
main GameStore in a single authoritative transaction; this memory-only gate is
an executable contract for ordered-ReplyTurn and UI-completion semantics.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from copy import deepcopy

from .common import identifier
from .events import choice_plan

@dataclass(frozen=True)
class TurnIdentity:
    profile_id: str
    generation: int
    game_revision: int
    roleplay_epoch: int
    token: str

    def __post_init__(self):
        identifier(self.profile_id,"存档 ID")
        identifier(self.token,"ReplyTurn 令牌")
        for value in (self.generation,self.game_revision,self.roleplay_epoch):
            if type(value) is not int or value<0:
                raise ValueError("ReplyTurn 绑定修订号无效")

class PendingEvent:
    """One event for one ReplyTurn. If cancelled/unread, no options/effects."""
    def __init__(self,event: dict,identity: TurnIdentity,segments_count: int,
                 instance_id: str):
        identifier(instance_id,"事件实例 ID")
        if type(segments_count) is not int or not 1<=segments_count<=6:
            raise ValueError("回复必须是 1–6 句")
        self.event=deepcopy(event)
        self.identity=identity
        self.segments_count=segments_count
        self.instance_id=instance_id
        self.activated_index=-1
        self.status="pending"  # pending -> presented -> resolved/cancelled
        self.selection=None

    def _assert_identity(self,identity: TurnIdentity):
        if identity!=self.identity:
            raise ValueError("档案、角色设定、版本或会话已过期")

    def activate(self,index: int,identity: TurnIdentity) -> None:
        self._assert_identity(identity)
        if self.status!="pending":
            raise ValueError("不是尚未播完的 ReplyTurn")
        if type(index) is not int or not 0<=index<self.segments_count:
            raise ValueError("台词编号不合法")
        if index==self.activated_index:return
        if index!=self.activated_index+1:
            raise ValueError("台词不能跳过，事件不能提前出现")
        self.activated_index=index

    def complete_ui(self,identity: TurnIdentity,*,displayed: bool,
                    tts_finished: bool) -> dict:
        self._assert_identity(identity)
        if self.status=="presented":
            return self._public_offer()
        if self.status!="pending":
            raise ValueError("已取消或已完成的事件不能重新呈现")
        if (self.activated_index!=self.segments_count-1 or displayed is not True
                or tts_finished is not True):
            raise ValueError("最后一句尚未显示/语音未结束，禁止事件弹出")
        self.status="presented"
        return self._public_offer()

    def _public_offer(self):
        return {"instance_id":self.instance_id,"event_id":self.event["id"],
                "title":self.event["title"],"status":self.status,
                "choices":[{"id":x["id"],"label":x["label"]}
                           for x in self.event["choices"]]}

    def choose(self,choice_id: str,identity: TurnIdentity):
        self._assert_identity(identity)
        if self.status=="resolved":
            if self.selection and self.selection["choice_id"]==choice_id:
                return deepcopy(self.selection)
            raise ValueError("事件已有不同结果，不能再次结算")
        if self.status!="presented":
            raise ValueError("玩家尚未读完/未获得有效选项")
        plan=choice_plan(self.event,choice_id)
        self.selection=plan
        self.status="resolved"
        # This is an uncommitted plan! Codex must atomically insert it.
        return deepcopy(plan)

    def cancel(self,identity: TurnIdentity):
        self._assert_identity(identity)
        if self.status=="resolved":raise ValueError("已选择的事件不能默默取消")
        self.status="cancelled"
