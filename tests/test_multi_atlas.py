# -*- coding: utf-8 -*-
"""Two-texture PSB regression, no proprietary game assets included."""
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from emote_model import PoseModel
from pose_renderer import AtlasRenderer
from main_desktop import discover_models, prepare_character

class MultiAtlasTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)/"_AI"
        self.group=self.root/"kan_10_decompiled"
        (self.group/"kan_10").mkdir(parents=True)
        icon=lambda x,y: {
            "0001":{"left":x,"top":y,"width":20,"height":20,
                    "originX":10,"originY":10,"attr":0,"metadata":{"zorder":0}}
        }
        layer=lambda name,atlas,x: {
            "label":name,"type":0,
            "frameList":[{"time":0,"content":{"src":atlas,"icon":"0001",
                                             "coord":[x,200,0]}}],
            "children":[]
        }
        values=[("普通Ａ",0),("笑顔Ａ",0),("驚きＡ",0),("悲しみＡ",0)]
        data={
            "object":{"all_parts":{"motion":{
                "全体構造":{"parameter":[],"layer":[
                    layer("clothes","tex#000",100),
                    layer("face","tex#001",100),
                ]}
            }}},
            "source":{
                "tex#000":{"type":2,"icon":icon(10,10),
                       "texture":{"width":50,"height":50,"pixel":"#resource#0"}},
                "tex#001":{"type":2,"icon":icon(10,10),
                       "texture":{"width":50,"height":50,"pixel":"#resource#1"}},
            },
            "metadata":{"timelineControl":[
                {"label":label,"variableList":[{"label":"face_eye_open",
                         "frameList":[{"time":0,"content":{"value":value}}]}]}
                for label,value in values
            ]},
        }
        self.path=self.group/"kan_10.json"
        self.path.write_text(json.dumps(data,ensure_ascii=False),encoding="utf-8")
        (self.group/"kan_10.resx.json").write_text(json.dumps({
            "Resources":{"0":"kan_10/tex#000-texture.png",
                         "1":"kan_10/tex#001-texture.png"}
        }),encoding="utf-8")
        self.png0=self.group/"kan_10"/"tex#000-texture.png"
        self.png1=self.group/"kan_10"/"tex#001-texture.png"
        im0=Image.new("RGBA",(50,50),(0,0,0,0))
        im1=Image.new("RGBA",(80,40),(0,0,0,0))
        for y in range(10,30):
            for x in range(10,30):
                im0.putpixel((x,y),(255,22,10,255))
                im1.putpixel((x,y),(10,140,255,160))
        im0.save(self.png0)
        im1.save(self.png1)

    def tearDown(self):
        self.temp.cleanup()

    def test_two_sources_with_same_icon_id_are_distinct(self):
        model=PoseModel(self.path)
        sprites=model.build_pose("普通Ａ")
        self.assertEqual(len(sprites),2)
        self.assertEqual({x.source for x in sprites},{"tex#000","tex#001"})
        self.assertEqual(model.icon_count,2)
        textures=model.discover_textures(self.root)
        self.assertEqual(set(textures),{"tex#000","tex#001"})
        painter=AtlasRenderer(model,textures)
        result=painter.render("普通Ａ",size=(350,500))
        self.assertIsNotNone(result.getchannel("A").getbbox())
        self.assertEqual(len(painter.sprite_cache),2)
        self.assertNotEqual(painter.atlas_scales["tex#000"],
                            painter.atlas_scales["tex#001"])
        self.assertEqual({x["key"] for x in painter.draw_info},
                         {"tex#000:0001","tex#001:0001"})
        self.assertEqual(painter.last_skipped,[])

    def test_discovery_requires_both_pages(self):
        models=discover_models(self.root)
        self.assertTrue(models["kan_10"]["available"])
        self.assertEqual(models["kan_10"]["total_pages"],2)
        self.png1.unlink()
        models=discover_models(self.root)
        self.assertFalse(models["kan_10"]["available"])
        self.assertEqual(models["kan_10"]["loaded_pages"],1)
        self.assertIn("tex#001",models["kan_10"]["missing"])
        with self.assertRaises(FileNotFoundError):
            PoseModel(self.path).discover_textures(self.root)

    def test_full_model_produces_six_outfit_pose_files(self):
        files,model=prepare_character(self.root,model_name="kan_10")
        self.assertEqual(len(files),9)
        self.assertTrue(all(file.is_file() for file in files.values()))
        self.assertEqual(len(model.icon_groups),2)
        saved=files["neutral"].stat().st_mtime_ns
        second,_=prepare_character(self.root,model_name="kan_10")
        self.assertEqual(saved,second["neutral"].stat().st_mtime_ns)

if __name__=="__main__":
    unittest.main()
