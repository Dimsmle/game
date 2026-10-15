# -*- coding: utf-8 -*-
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import main_desktop
from studio import app as studio, model_meta
import tests.test_emote as emote_fixture

class ModelMetadataTests(unittest.TestCase):
    def test_metadata_validation_and_human_label(self):
        lib=model_meta.empty()
        lib=model_meta.update(lib,"kan_10",{
            "display_name":"校服","outfit":"school_uniform",
            "pose_family":"standing_a","verified":True,
            "notes":"人工确认"
        })
        self.assertEqual(lib["models"]["kan_10"]["outfit"],"school_uniform")
        self.assertIn("校服",model_meta.label_for(lib,"kan_10"))
        self.assertIn("✓",model_meta.label_for(lib,"kan_10"))
        with self.assertRaises(ValueError):
            model_meta.update(lib,"kan_10",{"outfit":"../bad"})
        with self.assertRaises(ValueError):
            model_meta.update(lib,"unknown_1",{"display_name":"x"})

    def test_discover_models_supports_five_character_code_scheme(self):
        fixture=emote_fixture.RealSchemaSyntheticTest(methodName="test_file_discovery")
        fixture.setUp()
        old_data=studio.DATA
        try:
            root=fixture.folder.parent
            studio.DATA=root/"state"
            studio.DATA.mkdir()
            # Keep fixture kan_0, add one model using another known heroine code.
            alt=root/"tou_2_decompiled"
            (alt/"tou_2").mkdir(parents=True)
            shutil.copy2(fixture.path,alt/"tou_2.json")
            shutil.copy2(fixture.texture,alt/"tou_2"/"tex-texture.png")
            (alt/"tou_2.resx.json").write_text(json.dumps({
                "Resources":{"0":"tou_2/tex-texture.png"}
            }),encoding="utf-8")
            found=main_desktop.discover_models(root)
            self.assertIn("kan_0",found)
            self.assertIn("tou_2",found)
            self.assertTrue(found["tou_2"]["available"])
            metadata=model_meta.update(model_meta.empty(),"tou_2",{
                "display_name":"测试造型","outfit":"casual","verified":True
            })
            studio.atomic_json(studio.DATA/"model_metadata.json",metadata)
            found=main_desktop.discover_models(root)
            self.assertIn("测试造型",found["tou_2"]["label"])
        finally:
            studio.DATA=old_data
            fixture.tearDown()

if __name__=="__main__":
    unittest.main()
