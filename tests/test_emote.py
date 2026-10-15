# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image

from emote_model import PoseModel,find_model
from pose_renderer import AtlasRenderer
from desktop import export_poses,export_gif

class RealSchemaSyntheticTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        base=Path(self.tmp.name)/"汉字 目录"/"kan_0_decompiled"
        (base/"kan_0").mkdir(parents=True)
        self.folder=base
        self.texture=base/"kan_0"/"tex-texture.png"
        atlas=Image.new("RGBA",(50,50),(0,0,0,0))
        for y in range(10,20):
            for x in range(10,20):atlas.putpixel((x,y),(255,60,120,255))
        for y in range(25,35):
            for x in range(25,35):atlas.putpixel((x,y),(45,175,232,255))
        atlas.save(self.texture)
        frames=lambda c:[{"time":0,"type":2,"content":c},{"time":61,"type":0}]
        model={
            "metadata":{"timelineControl":[
                {"label":"普通Ａ","variableList":[{"label":"face_mouth","frameList":[{"time":0,"content":{"value":0}}]}]},
                {"label":"笑顔Ａ","variableList":[{"label":"face_mouth","frameList":[{"time":0,"content":{"value":60}}]}]}
            ]},
            "object":{"all_parts":{"motion":{
                "全体構造":{"parameterize":None,"parameter":[],"layer":[
                    {"label":"base","type":2,"frameList":frames({"coord":[100,200,0]}),
                     "children":[
                         {"label":"leaf","type":0,"frameList":[
                            {"time":0,"content":{"src":"tex","icon":"0001"},"type":3},
                            {"time":60,"content":{"src":"tex","icon":"0002"},"type":2}],
                          "parameterize":0,"children":[]}
                     ]}
                ]}}}},
            "source":{"tex":{"texture":{"width":100,"height":100},
                             "icon":{
                                "0001":{"left":20,"top":20,"width":20,"height":20,
                                        "originX":10,"originY":10,"attr":0,
                                        "metadata":{"zorder":1}},
                                "0002":{"left":50,"top":50,"width":20,"height":20,
                                        "originX":10,"originY":10,"attr":0,
                                        "metadata":{"zorder":1}}
                            }}}
        }
        # Four recognized timeline labels are enough to exercise the integrated auto-renderer.
        model["metadata"]["timelineControl"].extend([
            {"label":"驚きＡ","variableList":[{"label":"face_eye_open",
                "frameList":[{"time":0,"content":{"value":37}}]}]},
            {"label":"悲しみＡ","variableList":[{"label":"face_mouth",
                "frameList":[{"time":0,"content":{"value":18}}]}]}
        ])
        # motion param shared by nested leaf
        model["object"]["all_parts"]["motion"]["全体構造"]["parameter"]=[
          {"id":"face_mouth","rangeBegin":0,"rangeEnd":60,"division":60}
        ]
        self.path=base/"kan_0.json"
        self.path.write_text(json.dumps(model,ensure_ascii=False),encoding="utf-8")
        (base/"kan_0.resx.json").write_text(json.dumps({"Resources":{"0":"kan_0/tex-texture.png"}}),
                                                 encoding="utf-8")
        self.m=PoseModel(self.path)
    def tearDown(self):
        self.tmp.cleanup()
    def test_file_discovery(self):
        self.assertEqual(find_model(self.folder),self.path)
        self.assertEqual(self.m.discover_texture(self.folder),self.texture)
    def test_single_sprite_neutral(self):
        sprites=self.m.build_pose(0)
        self.assertEqual(len(sprites),1)
        self.assertEqual(sprites[0].icon,"0001")
        self.assertEqual(sprites[0].world[:2],(100.0,200.0))
    def test_parameter_expression_selects_icon(self):
        # leaf parameterize=0 and preset face_mouth=60 selects second sprite
        sprites=self.m.build_pose("笑顔Ａ")
        self.assertEqual(sprites[0].icon,"0002")
    def test_texture_scale_and_alpha(self):
        r=AtlasRenderer(self.m,self.texture)
        self.assertEqual((r.atlas_sx,r.atlas_sy),(.5,.5))
        image=r.render(0,size=(320,420))
        self.assertEqual(image.mode,"RGBA")
        self.assertIsNotNone(image.getchannel("A").getbbox())
        self.assertEqual(len(r.draw_info),1)
    def test_exports(self):
        r=AtlasRenderer(self.m,self.texture)
        out=self.folder/"out"
        exported=export_poses(r,out,("普通Ａ","笑顔Ａ"),(300,450))
        self.assertEqual(len(exported),2)
        self.assertTrue(all(x.is_file() for x in exported))
        gif=export_gif(r,out/"motion.gif","普通Ａ",size=(180,270))
        self.assertTrue(gif.is_file())
    def test_future_sprite_never_leaks_into_neutral_frame(self):
        frames=[
            {"time":0,"content":{}},
            {"time":1,"content":{"src":"tex","icon":"tear_icon"}},
            {"time":2,"content":{"src":"blank","icon":"blank_shape"}}
        ]
        self.assertIsNone(PoseModel._sample_key(frames,0,"src"))
        self.assertIsNone(PoseModel._sample_key(frames,0,"icon"))
        self.assertEqual(PoseModel._sample_key(frames,1,"icon"),"tear_icon")
        self.assertEqual(PoseModel._sample_key(frames,2,"src"),"blank")

    def test_type_zero_end_marker_clears_fade_sprite(self):
        frames=[
            {"time":0,"type":2,"content":{"src":"tex","icon":"overlay"}},
            {"time":60,"type":0}
        ]
        self.assertEqual(PoseModel._sample_key(frames,59,"icon"),"overlay")
        self.assertIsNone(PoseModel._sample_key(frames,60,"src"))
        self.assertIsNone(PoseModel._sample_key(frames,60,"icon"))

    def test_eye_blink_keeps_special_eye_shapes(self):
        # Neutral=0; closed eye=10. Special 31..50 are actual expression IDs.
        self.assertEqual(self.m.safe_blink_override("普通Ａ"),{"face_eye_open":10})
        self.assertEqual(len(self.m.expression_catalog()),4)

    def test_coord_interpolation(self):
        self.assertEqual(PoseModel._sample_coord([
          {"time":0,"content":{"coord":[-20,10,0]}},
          {"time":30,"content":{"mask":0}},
          {"time":60,"content":{"coord":[20,30,0]}}
        ],30),(0.0,20.0,0.0))
if __name__=="__main__":unittest.main()
