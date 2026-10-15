# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path

from studio import behavior
import tests.test_emote as emote_fixture
from emote_model import PoseModel

class BehaviorPlanningTests(unittest.TestCase):
    def setUp(self):
        self.synthetic=emote_fixture.RealSchemaSyntheticTest(methodName="test_file_discovery")
        self.synthetic.setUp()
        path=self.synthetic.path
        data=json.loads(path.read_text(encoding="utf-8"))
        # Extend synthetic E-mote schema with one face and two genuine-looking
        # named motion timelines. No extracted artwork is distributed.
        metadata=data["metadata"]["timelineControl"]
        metadata.extend([
            {"label":"照れＡ","variableList":[
               {"label":"face_eye_open","frameList":[
                    {"time":0,"content":{"value":10}},
               ]}]},
            {"label":"うんうん","variableList":[
                {"label":"head_UD","frameList":[
                    {"time":0,"content":{"value":0}},
                    {"time":30,"content":{"value":18}},
                    {"time":60,"content":{"value":0}},
                ]}]},
            {"label":"思考","variableList":[
                {"label":"head_UD","frameList":[
                    {"time":0,"content":{"value":0}},
                    {"time":60,"content":{"value":-12}},
                ]}]},
        ])
        path.write_text(json.dumps(data,ensure_ascii=False),encoding="utf-8")
        self.model=PoseModel(path)
        self.default=behavior.default_library()
        self.catalog=behavior.motion_catalog(self.model,"kan_0",self.default)

    def tearDown(self):
        self.synthetic.tearDown()

    def test_real_timeline_names_get_seed_tags(self):
        nod=next(x for x in self.catalog if x["label"]=="うんうん")
        self.assertEqual(nod["type"],"motion")
        self.assertIn("nod",nod["tags"])
        self.assertEqual(nod["sample_time"],30)
        self.assertEqual(nod["playback"],"sample_only")

    def test_safe_llm_reply_parsing_and_validation(self):
        reply=behavior.normalize_llm_reply(
            '```json\n{"speech":"我在思考","emotion":"thinking","action_tag":"think",'
            '"scene":"classroom","intensity":3}\n```',
            ["classroom"])
        self.assertEqual(reply["emotion"],"thinking")
        self.assertEqual(reply["action_tag"],"think")
        self.assertEqual(reply["scene"],"classroom")
        self.assertEqual(reply["intensity"],1)
        unsafe=behavior.normalize_llm_reply(
            '{"speech":"嗨","emotion":"not_allowed","action_tag":"../../etc","scene":"../../"}',
            ["classroom"])
        self.assertEqual(unsafe["action_tag"],"idle")
        self.assertEqual(unsafe["emotion"],"neutral")
        self.assertEqual(unsafe["scene"],"")

    def test_selects_emotion_and_action_independently(self):
        plan=behavior.resolve_behavior(
            {"speech":"是的","emotion":"happy","action_tag":"nod","scene":""},
            "kan_0",self.catalog,self.default,[])
        self.assertEqual(plan["expression"]["label"],"笑顔Ａ")
        self.assertEqual(plan["motion"]["label"],"うんうん")
        self.assertEqual(plan["playback_status"],"preview_only")
        self.assertTrue(any("单帧" in x for x in plan["warnings"]))

    def test_missing_motion_does_not_invent_wave(self):
        plan=behavior.resolve_behavior({"emotion":"shy","action_tag":"wave"},
                "kan_0",self.catalog,self.default,[])
        self.assertEqual(plan["expression"]["label"],"照れＡ")
        self.assertIsNone(plan["motion"])
        self.assertEqual(plan["playback_status"],"expression_only")
        self.assertTrue(plan["warnings"])

    def test_can_override_emotion_mapping_and_motion_tags(self):
        library=behavior.annotate_expression(self.default,"kan_0","happy","照れＡ",self.catalog)
        library=behavior.annotate_motion(
            library,"kan_0","思考",["wave","greet"],self.catalog,40)
        updated=behavior.motion_catalog(self.model,"kan_0",library)
        plan=behavior.resolve_behavior({"emotion":"happy","action_tag":"wave"},
                                       "kan_0",updated,library,[])
        self.assertEqual(plan["expression"]["label"],"照れＡ")
        self.assertEqual(plan["motion"]["label"],"思考")
        self.assertEqual(plan["motion"]["sample_time"],40)
        self.assertEqual(next(x for x in updated if x["label"]=="思考")["tag_source"],"manual")
        with tempfile.TemporaryDirectory() as t:
            file=Path(t)/"animation_tags.json"
            file.write_text(json.dumps(library,ensure_ascii=False),encoding="utf-8")
            self.assertEqual(behavior.load_library(file),library)

    def test_rejects_malicious_tag_and_missing_preset(self):
        with self.assertRaises(ValueError):
            behavior.annotate_motion(self.default,"../other","うんうん",["nod"],self.catalog,0)
        with self.assertRaises(ValueError):
            behavior.annotate_motion(self.default,"kan_0","missing",["nod"],self.catalog,0)
        with self.assertRaises(ValueError):
            behavior.annotate_motion(self.default,"kan_0","うんうん",["../../evil"],self.catalog,0)
        with self.assertRaises(ValueError):
            behavior.annotate_expression(self.default,"kan_0","happy","missing",self.catalog)

    def test_plain_text_fallback_is_safe(self):
        x=behavior.normalize_llm_reply("你说得对，我听着。",[])
        self.assertEqual(x["speech"],"你说得对，我听着。")
        self.assertEqual(x["emotion"],"neutral")
        self.assertEqual(x["action_tag"],"idle")

if __name__=="__main__":
    unittest.main()
