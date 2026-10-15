import unittest

from emote_mesh import MeshWarp, combinator_warps, inverse_point, warp_point
from studio.runtime import BehaviorRuntime


class MeshTests(unittest.TestCase):
    def test_cubic_translation_and_nested_inverse(self):
        inner=MeshWarp((10,20,100,200),tuple([.1,.05]*16),"head_UD")
        outer=MeshWarp((-50,-50,400,400),tuple([0,.025]*16),"head_UD")
        self.assertEqual(warp_point(60,120,(outer,inner)),(70,140))
        x,y=inverse_point(70,140,(outer,inner))
        self.assertAlmostEqual(x,60);self.assertAlmostEqual(y,120)

    def test_absolute_and_delta_cages_share_neutral_subtraction(self):
        grid=[c for row in range(4) for col in range(4) for c in (col/3,row/3)]
        low=[v+(.1 if i%2==0 else 0) for i,v in enumerate(grid)]
        high=[v-(.1 if i%2==0 else 0) for i,v in enumerate(grid)]
        node={"meshTransform":1,"meshCombinator":{"combinatorList":[{
            "meshType":1,"neutralIndex":1,"rawMeshList":"#resource@1",
            "variable":{"key":"head_UD","meshCount":3,"rangeBegin":-30,"rangeEnd":30}}]}}
        content={"src":"blank","icon":"100:100:50:50"}
        self.assertFalse(combinator_warps(node,content,(0,0),{"head_UD":0},{"@1":low+grid+high}))
        warp=combinator_warps(node,content,(0,0),{"head_UD":15},{"@1":low+grid+high})[0]
        x,y=warp.apply(0,0)
        self.assertAlmostEqual(x,-5);self.assertAlmostEqual(y,0)


class MotionLifecycleTests(unittest.TestCase):
    def test_stale_completion_cannot_interrupt_new_motion_or_speech(self):
        runtime=BehaviorRuntime()
        plan={"model":"kan_10","emotion":"happy","action_tag":"nod",
              "expression":{"label":"笑顔Ａ"},"motion":{"label":"うんうん"}}
        first=runtime.submit_plan(plan,source="manual",now=100)["runtime"]["action_token"]
        runtime.motion_started(first,2,now=100)
        second=runtime.submit_plan(plan,source="manual",now=100.2)["runtime"]["action_token"]
        runtime.speech_start(now=100.3)
        stale=runtime.motion_ended(first,now=100.4)
        self.assertIsNotNone(stale["motion"])
        result=runtime.motion_ended(second,now=100.5)
        self.assertEqual(result["phase"],"speaking")
        self.assertEqual(result["emotion"],"happy")
        self.assertEqual(result["active_behavior"]["expression"]["label"],"笑顔Ａ")
        self.assertIsNone(result["motion"])

    def test_manual_body_interrupt_keeps_active_speech(self):
        runtime=BehaviorRuntime()
        runtime.speech_start(now=10)
        state=runtime.cancel("manual_preview",now=11,keep_speech=True)
        self.assertTrue(state["speech_active"])
        self.assertEqual(state["phase"],"speaking")
        stopped=runtime.cancel("stop_all",now=12)
        self.assertFalse(stopped["speech_active"])


if __name__=="__main__":unittest.main()
