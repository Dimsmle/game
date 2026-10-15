# -*- coding: utf-8 -*-
"""End-to-end integrated app tests with generated synthetic assets only."""
from __future__ import annotations
import json
import shutil
import tempfile
from pathlib import Path
import sys
import urllib.request
import urllib.error
import unittest

import tests.test_emote as synthetic
import main_desktop
from studio import app as studio

class IntegratedTests(unittest.TestCase):
    def test_pose_generation_binding_and_local_http(self):
        sample=synthetic.RealSchemaSyntheticTest(methodName="test_file_discovery")
        sample.setUp()
        old=(studio.DATA,studio.GEN,studio.SETTINGS_FILE,studio.MANIFEST_FILE,
             studio.DB_FILE,studio.STATE)
        try:
            root=sample.folder.parent
            state_dir=root/"test_appdata"
            studio.DATA=state_dir
            studio.GEN=state_dir/"generated"
            studio.SETTINGS_FILE=state_dir/"settings.json"
            studio.MANIFEST_FILE=state_dir/"manifest.json"
            studio.DB_FILE=state_dir/"history.sqlite3"
            studio.init()
            studio.STATE["settings"]["llm_mode"]="demo"
            files,model=main_desktop.prepare_character(root,force=True)
            self.assertEqual(len(files),9)
            self.assertTrue(all(p.exists() for p in files.values()))
            self.assertIn("blink",files)
            # Repeat to test idempotent cache.
            originals={key:p.stat().st_mtime_ns for key,p in files.items()}
            cached,_=main_desktop.prepare_character(root,force=False)
            self.assertEqual(originals,{key:p.stat().st_mtime_ns for key,p in cached.items()})
            main_desktop.register_pose_assets(root,files,model)
            # Create a second synthetic model sharing the same schema but with
            # its OWN atlas path. Test selecting costumes without changing source code.
            alt=root/"kan_1_decompiled"
            (alt/"kan_1").mkdir(parents=True)
            shutil.copy2(sample.path,alt/"kan_1.json")
            shutil.copy2(sample.texture,alt/"kan_1"/"tex-texture.png")
            (alt/"kan_1.resx.json").write_text(json.dumps({
                "Resources":{"0":"kan_1/tex-texture.png"}},ensure_ascii=False),encoding="utf-8")
            discovered=main_desktop.discover_models(root)
            self.assertEqual(set(discovered),{"kan_0","kan_1"})
            self.assertTrue(discovered["kan_1"]["available"])
            self.assertEqual(studio.STATE["manifest"]["poses"]["happy"],
                             "character_exports/kan_0_happy.png")
            self.assertEqual(studio.STATE["manifest"]["layers"][0]["id"],
                             "__auto_emote_character")
            server,thread=main_desktop.start_server(0)
            try:
                address=f"http://127.0.0.1:{server.server_port}"
                with urllib.request.urlopen(address+"/api/state",timeout=7) as response:
                    payload=json.load(response)
                self.assertEqual(payload["manifest"]["layers"][0]["slot"],"base")
                self.assertEqual(len(payload["manifest"]["poses"]),9)
                with urllib.request.urlopen(address+"/file/character_exports/kan_0_neutral.png",
                                             timeout=7) as response:
                    self.assertEqual(response.read(8),b"\x89PNG\r\n\x1a\n")
                body=json.dumps({"text":"你好"}).encode()
                req=urllib.request.Request(address+"/api/chat",
                    data=body,headers={"Content-Type":"application/json","Origin":address})
                with urllib.request.urlopen(req,timeout=7) as response:
                    reply=json.load(response)
                self.assertEqual(reply["source"],"demo")
                # v0.7 no longer invents a legacy body animation when the active
                # PSB has no motion tagged for the semantic action.
                self.assertEqual(reply["action"],"idle")
                self.assertEqual(reply["emotion"],"happy")
                self.assertIn("runtime",reply)
                with urllib.request.urlopen(address+"/api/expression_catalog",timeout=7) as response:
                    catalog=json.load(response)
                self.assertEqual(catalog["faces"],4)
                self.assertEqual(len(catalog["presets"]),4)
                emotion=json.dumps({"label":"笑顔Ａ","time":0},ensure_ascii=False).encode()
                req=urllib.request.Request(address+"/api/expression_apply",data=emotion,
                    headers={"Content-Type":"application/json","Origin":address})
                with urllib.request.urlopen(req,timeout=20) as response:
                    selected=json.load(response)
                self.assertEqual(selected["label"],"笑顔Ａ")
                self.assertEqual(set(selected["refs"]),{"normal","blink","talk"})
                self.assertTrue(all((root / ref).is_file() for ref in selected["refs"].values()))
                with urllib.request.urlopen(address+"/api/character_models",timeout=7) as response:
                    choices=json.load(response)
                self.assertEqual(len(choices["models"]),2)
                self.assertEqual(choices["selected"],"kan_0")
                switch=json.dumps({"name":"kan_1"}).encode()
                req=urllib.request.Request(address+"/api/character_model",data=switch,
                    headers={"Content-Type":"application/json","Origin":address})
                with urllib.request.urlopen(req,timeout=30) as response:
                    result=json.load(response)
                self.assertTrue(result["ok"])
                self.assertEqual(result["selected"],"kan_1")
                self.assertIn("kan_1_neutral.png",
                    result["manifest"]["poses"]["neutral"])
                self.assertTrue((root/"character_exports"/"kan_1_neutral.png").is_file())
                # Unauthorized paths must not be accepted as model names.
                invalid=urllib.request.Request(address+"/api/character_model",
                    data=json.dumps({"name":"../../other"}).encode(),
                    headers={"Content-Type":"application/json","Origin":address})
                try:
                    urllib.request.urlopen(invalid,timeout=6)
                    raise AssertionError("Unsafe model name was accepted")
                except urllib.error.HTTPError as expected:
                    self.assertEqual(expected.code,400)
            finally:
                server.shutdown()
                server.server_close()
        finally:
            (studio.DATA,studio.GEN,studio.SETTINGS_FILE,studio.MANIFEST_FILE,
             studio.DB_FILE,studio.STATE)=old
            sample.tearDown()

if __name__=="__main__":
    unittest.main()
