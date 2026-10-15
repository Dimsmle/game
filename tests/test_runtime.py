# -*- coding: utf-8 -*-
import unittest

from studio.runtime import BehaviorRuntime
from studio import renderers

class FakeClock:
    def __init__(self):self.value=100.0
    def __call__(self):return self.value
    def advance(self,seconds):self.value+=seconds

def plan(action="nod",emotion="happy",motion=True,intensity=.5):
    return {
        "emotion":emotion,"action_tag":action,"intensity":intensity,"scene":"",
        "expression":{"label":"笑顔Ａ","time":0},
        "motion":{"label":"うんうん","sample_time":30,"tags":[action]}
                 if motion else None,
        "playback_status":"preview_only" if motion else "expression_only",
        "warnings":[],"model":"kan_10"
    }

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.clock=FakeClock()
        self.r=BehaviorRuntime(self.clock)
        self.r.reset("kan_10")

    def test_cooldown_suppresses_repeat_but_keeps_expression(self):
        first=self.r.submit_plan(plan(),now=self.clock())
        self.assertEqual(first["runtime_decision"],"accepted")
        self.clock.advance(1)
        second=self.r.submit_plan(plan(),now=self.clock())
        self.assertEqual(second["runtime_decision"],"cooldown_suppressed")
        self.assertIsNone(second["motion"])
        self.assertEqual(second["expression"]["label"],"笑顔Ａ")
        self.assertTrue(any("冷却" in x for x in second["warnings"]))

    def test_high_priority_interrupt_and_low_priority_queue(self):
        manual=self.r.submit_plan(plan("wave"),source="manual",now=self.clock())
        self.assertEqual(manual["runtime"]["action_tag"],"wave")
        low=self.r.submit_plan(plan("think"),source="ai",now=self.clock())
        self.assertEqual(low["runtime_decision"],"queued")
        self.assertEqual(low["runtime"]["action_tag"],"wave")
        self.assertEqual(low["runtime"]["queue_length"],1)
        high=self.r.submit_plan(plan("surprise"),source="manual",now=self.clock())
        self.assertEqual(high["runtime_decision"],"accepted")
        self.assertEqual(high["runtime"]["action_tag"],"surprise")

    def test_speech_lifecycle_does_not_lose_emotion(self):
        self.r.submit_plan(plan("nod","shy"),now=self.clock())
        speaking=self.r.speech_start()
        self.assertEqual(speaking["phase"],"speaking")
        self.assertEqual(speaking["emotion"],"shy")
        self.clock.advance(.5)
        ended=self.r.speech_end()
        self.assertIn(ended["phase"],("reacting","idle"))
        self.assertEqual(ended["emotion"],"shy")


    def test_reaction_completion_emits_expression_only_settle(self):
        accepted=self.r.submit_plan(plan("nod","happy"),now=self.clock())
        token=accepted["runtime"]["action_token"]
        self.clock.advance(2)
        snap=self.r.tick()
        self.assertEqual(snap["phase"],"idle")
        self.assertEqual(snap["action_tag"],"idle")
        self.assertGreater(snap["action_token"],token)
        self.assertIsNone(snap["active_behavior"]["motion"])
        self.assertEqual(snap["active_behavior"]["expression"]["label"],"笑顔Ａ")
        self.assertEqual(snap["active_behavior"]["emotion"],"happy")

    def test_scene_lock_expires(self):
        locked=self.r.lock_scene("classroom",30)
        self.assertTrue(locked["scene_lock"]["active"])
        self.clock.advance(31)
        self.assertFalse(self.r.snapshot()["scene_lock"]["active"])

    def test_reaction_expires_and_queued_motion_starts(self):
        self.r.submit_plan(plan("wave"),source="manual",now=self.clock())
        self.r.submit_plan(plan("think"),source="ai",now=self.clock())
        before=self.r.snapshot()["action_token"]
        self.clock.advance(2)
        snap=self.r.tick()
        self.assertEqual(snap["action_tag"],"think")
        self.assertEqual(snap["queue_length"],0)
        self.assertGreater(snap["action_token"],before)
        self.assertEqual(snap["active_behavior"]["motion"]["label"],"うんうん")

    def test_context_hint_contains_recent_actions(self):
        self.r.submit_plan(plan("nod"),now=self.clock())
        hint=self.r.context_hint()
        self.assertIn("recent_actions",hint)
        self.assertIn("nod",hint)

class RendererContractTests(unittest.TestCase):
    def test_static_renderer_is_truthful_about_missing_native_features(self):
        cap=renderers.current_capabilities()
        self.assertTrue(cap["expressions"])
        self.assertTrue(cap["motion_preview"])
        self.assertFalse(cap["continuous_motion"])
        self.assertFalse(cap["mesh_deformation"])
        self.assertFalse(cap["physics"])
        self.assertIn("静态",cap["display_name"])

    def test_planned_live2d_backend_is_not_current_renderer(self):
        all_caps=renderers.all_capabilities()
        live=next(x for x in all_caps if x["renderer_id"]=="live2d_cubism_target")
        current=renderers.current_capabilities()
        self.assertTrue(live["continuous_motion"])
        self.assertNotEqual(live["renderer_id"],current["renderer_id"])

if __name__=="__main__":
    unittest.main()
