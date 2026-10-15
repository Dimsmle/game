# -*- coding: utf-8 -*-
"""Deterministic character runtime / behavior scheduler.

It does not render pixels. It owns *when* a semantic action is accepted,
suppressed by cooldown, interrupted, queued, and when speaking begins/ends.
This keeps LLM decisions independent from E-mote/Live2D render backends.
"""
from __future__ import annotations

from copy import deepcopy
from collections import deque
import time
from typing import Any

DEFAULT_COOLDOWNS={
    "idle":0.0, "talk":0.0, "nod":3.0, "agree":3.0, "disagree":3.0,
    "shake_head":3.0, "wave":8.0, "greet":8.0, "thank":7.0,
    "tilt_head":5.0, "curious":5.0, "surprise":7.0, "think":7.0,
    "smile":3.5, "laugh":7.0, "shy":7.0, "comfort":8.0,
    "approach":12.0, "walk":10.0, "celebrate":10.0, "playful":7.0,
    "sparkle":10.0, "reaction":4.0, "gesture":5.0,
    "affectionate":10.0, "sleep":12.0,
}
DEFAULT_PRIORITIES={"idle":0,"ai":40,"event":60,"manual":100}
MAX_QUEUE=6
HISTORY_LIMIT=24

class BehaviorRuntime:
    def __init__(self, clock=None):
        self.clock=clock or time.monotonic
        self._revision=0
        self._action_token=0
        self._active_behavior=None
        self._phase="idle"
        self._model=""
        self._emotion="neutral"
        self._action_tag="idle"
        self._motion=None
        self._speech_active=False
        self._reaction_until=0.0
        self._active_priority=-1
        self._last_action_at={}
        self._queue=deque(maxlen=MAX_QUEUE)
        self._history=deque(maxlen=HISTORY_LIMIT)
        self._scene_lock={"scene":"","until":0.0}
        self._last_plan=None

    def _now(self, now=None):
        return float(self.clock() if now is None else now)

    def reset(self, model="", now=None):
        now=self._now(now)
        self._revision+=1
        self._action_token+=1
        self._active_behavior=None
        self._phase="idle"
        self._model=str(model or "")
        self._emotion="neutral"
        self._action_tag="idle"
        self._motion=None
        self._speech_active=False
        self._reaction_until=0.0
        self._active_priority=-1
        self._queue.clear()
        self._last_plan=None
        self._record("reset",now,{"model":self._model})
        return self.snapshot(now)

    def _record(self,event,now,data=None):
        self._history.append({
            "event":event,"at":round(now,3),"data":deepcopy(data or {})
        })

    @staticmethod
    def _hold_seconds(plan):
        intensity=plan.get("intensity",0.5)
        try:intensity=max(0.0,min(1.0,float(intensity)))
        except (TypeError,ValueError):intensity=0.5
        tag=plan.get("action_tag","idle")
        if tag=="idle":return 0.0
        # Static preview hold; continuous renderer may ignore this and report duration.
        return round(0.75+intensity*0.9,2)

    def _cooldown(self,tag):
        return float(DEFAULT_COOLDOWNS.get(tag,5.0))

    def _cooldown_remaining(self,tag,now):
        last=self._last_action_at.get(tag)
        if last is None:return 0.0
        return max(0.0,self._cooldown(tag)-(now-last))

    def submit_plan(self,plan,*,source="ai",priority=None,now=None):
        """Accept a validated behavior plan and apply deterministic scheduling.

        The returned plan may have its motion suppressed due to cooldown while
        keeping the expression/emotion. A new equal/higher-priority reaction
        interrupts the old preview; lower priority can be queued.
        """
        now=self._now(now)
        self.tick(now)
        clean=deepcopy(plan if isinstance(plan,dict) else {})
        tag=str(clean.get("action_tag","idle"))
        model=str(clean.get("model","") or self._model)
        if model!=self._model:
            self.reset(model,now)
        priority=int(DEFAULT_PRIORITIES.get(source,40) if priority is None else priority)
        warnings=list(clean.get("warnings",[]) if isinstance(clean.get("warnings"),list) else [])
        motion=clean.get("motion") if isinstance(clean.get("motion"),dict) else None
        remaining=self._cooldown_remaining(tag,now) if motion else 0.0
        intensity=clean.get("intensity",0.5)
        try:intensity=float(intensity)
        except (TypeError,ValueError):intensity=.5

        decision="accepted"
        if motion and remaining>0 and intensity<0.9 and source!="manual":
            clean["motion"]=None
            clean["playback_status"]="expression_only"
            warnings.append(f"动作 {tag} 仍在冷却中（约 {remaining:.1f}s），保留表情但不重复动作")
            decision="cooldown_suppressed"
            motion=None

        current_priority=self._active_priority
        if motion and self._phase in ("reacting","speaking") and now<self._reaction_until and priority<current_priority:
            if len(self._queue)<MAX_QUEUE:
                queued=deepcopy(clean);queued["_priority"]=priority;queued["_source"]=source
                self._queue.append(queued)
                clean["motion"]=None
                clean["playback_status"]="queued"
                warnings.append("已有更高优先级动作，当前动作进入队列")
                decision="queued"
                motion=None
            else:
                clean["motion"]=None
                clean["playback_status"]="expression_only"
                warnings.append("动作队列已满，当前动作只保留表情")
                decision="queue_full"

        clean["warnings"]=warnings
        clean["runtime_decision"]=decision
        clean["_priority"]=priority
        clean["_source"]=source

        self._revision+=1
        self._emotion=str(clean.get("emotion","neutral"))
        self._last_plan=deepcopy(clean)
        if decision=="queued":
            # Face emotion may update immediately, but the active body reaction remains.
            self._record("plan_queued",now,{
                "emotion":self._emotion,"action_tag":tag,
                "motion":None,"source":source,"priority":priority
            })
            clean.pop("_priority",None);clean.pop("_source",None)
            clean["runtime"]=self.snapshot(now)
            return clean
        if motion:
            self._action_tag=tag
            self._motion=deepcopy(motion)
            self._active_priority=priority
            self._last_action_at[tag]=now
            self._phase="speaking" if self._speech_active else "reacting"
            self._reaction_until=now+self._hold_seconds(clean)
            self._action_token+=1
            self._active_behavior={
                key:deepcopy(clean.get(key)) for key in
                ("emotion","action_tag","intensity","scene","expression",
                 "motion","playback_status","warnings","runtime_decision")
            }
        elif not self._speech_active and not (
                self._phase=="reacting" and now<self._reaction_until):
            self._phase="idle"
            self._motion=None
            self._action_tag="idle"
            self._active_priority=-1
            self._active_behavior=None
            self._reaction_until=0.0
        self._record("plan_"+decision,now,{
            "emotion":self._emotion,"action_tag":tag,
            "motion":motion.get("label") if motion else None,
            "source":source,"priority":priority
        })
        clean.pop("_priority",None);clean.pop("_source",None)
        clean["runtime"]=self.snapshot(now)
        return clean

    def speech_start(self,now=None):
        now=self._now(now);self.tick(now)
        self._speech_active=True;self._phase="speaking";self._revision+=1
        self._record("speech_start",now,{"emotion":self._emotion})
        return self.snapshot(now)

    def speech_end(self,now=None):
        now=self._now(now)
        self._speech_active=False;self._revision+=1
        self._phase="reacting" if self._motion and now<self._reaction_until else "idle"
        self._record("speech_end",now,{})
        self.tick(now)
        return self.snapshot(now)

    def cancel(self,reason="cancelled",now=None):
        now=self._now(now)
        settle=self._settle_behavior()
        self._revision+=1;self._phase="idle";self._speech_active=False
        self._motion=None;self._reaction_until=0;self._active_priority=-1
        self._active_behavior=settle;self._action_token+=1;self._queue.clear()
        self._action_tag="idle"
        self._record("cancel",now,{"reason":str(reason)[:80]})
        return self.snapshot(now)

    def lock_scene(self,scene,duration=1800,now=None):
        now=self._now(now)
        duration=max(30.0,min(24*3600.0,float(duration)))
        self._scene_lock={"scene":str(scene)[:40],"until":now+duration}
        self._revision+=1
        self._record("scene_lock",now,{"scene":self._scene_lock["scene"],"seconds":duration})
        return self.snapshot(now)

    def unlock_scene(self,now=None):
        now=self._now(now);self._scene_lock={"scene":"","until":0.0};self._revision+=1
        self._record("scene_unlock",now,{})
        return self.snapshot(now)

    def scene_lock(self,now=None):
        now=self._now(now)
        if self._scene_lock["until"]<=now:
            self._scene_lock={"scene":"","until":0.0}
        return {
            "active":bool(self._scene_lock["scene"]),
            "scene":self._scene_lock["scene"],
            "remaining":round(max(0.0,self._scene_lock["until"]-now),1)
        }

    def _settle_behavior(self):
        previous=self._active_behavior if isinstance(self._active_behavior,dict) else {}
        expression=deepcopy(previous.get("expression"))
        if not expression:
            return None
        return {
            "emotion":self._emotion,"action_tag":"idle","intensity":0.0,
            "scene":"","expression":expression,"motion":None,
            "playback_status":"expression_only","warnings":[],
            "runtime_decision":"reaction_complete",
        }

    def tick(self,now=None):
        now=self._now(now)
        self.scene_lock(now)
        if not self._speech_active and self._phase=="reacting" and now>=self._reaction_until:
            settle=self._settle_behavior()
            self._motion=None;self._action_tag="idle";self._active_priority=-1
            self._phase="idle";self._revision+=1
            self._record("reaction_end",now,{})
            if self._queue:
                self._active_behavior=None
                queued=self._queue.popleft()
                priority=queued.pop("_priority",40);source=queued.pop("_source","ai")
                # queued item has already passed validation; submit at its actual start time.
                started=self.submit_plan(queued,source=source,priority=priority,now=now)
                return started["runtime"]
            self._active_behavior=settle
            if settle is not None:self._action_token+=1
        return self.snapshot(now,do_tick=False)

    def snapshot(self,now=None,do_tick=True):
        now=self._now(now)
        if do_tick:
            return self.tick(now)
        cooldowns={
            tag:round(rem,1) for tag in self._last_action_at
            if (rem:=self._cooldown_remaining(tag,now))>0
        }
        return {
            "revision":self._revision,"action_token":self._action_token,
            "phase":self._phase,"model":self._model,
            "emotion":self._emotion,"action_tag":self._action_tag,
            "motion":deepcopy(self._motion),
            "active_behavior":deepcopy(self._active_behavior),
            "speech_active":self._speech_active,
            "reaction_remaining":round(max(0.0,self._reaction_until-now),2),
            "queue_length":len(self._queue),"cooldowns":cooldowns,
            "scene_lock":self.scene_lock(now),
            "history":list(self._history)[-10:],
        }

    def context_hint(self,now=None):
        snap=self.snapshot(now)
        recent=[x["data"].get("action_tag") for x in snap["history"]
                if x["event"].startswith("plan_") and x["data"].get("action_tag") not in (None,"idle")]
        return (
            f"当前角色状态：emotion={snap['emotion']}, phase={snap['phase']}, "
            f"recent_actions={recent[-4:]}. "
            "除非语境确实需要，不要连续重复同一个显眼动作；自然对话可以使用 idle。"
        )
