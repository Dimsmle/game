# -*- coding: utf-8 -*-
"""HTTP pipeline test: model timeline → editable tags → chat → planned behavior."""
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import main_desktop
from studio import app as studio
import tests.test_behavior as behavior_fixture

class BehaviorHTTPTests(unittest.TestCase):
    def test_catalog_annotation_chat_and_expression_composition(self):
        fixture=behavior_fixture.BehaviorPlanningTests(methodName="test_real_timeline_names_get_seed_tags")
        fixture.setUp()
        root=fixture.synthetic.folder.parent
        settings_dir=root/"local_state"
        previous=(studio.DATA,studio.GEN,studio.SETTINGS_FILE,
                  studio.MANIFEST_FILE,studio.DB_FILE,studio.STATE)
        server=None
        try:
            studio.DATA=settings_dir
            studio.GEN=settings_dir/"generated"
            studio.SETTINGS_FILE=settings_dir/"settings.json"
            studio.MANIFEST_FILE=settings_dir/"manifest.json"
            studio.DB_FILE=settings_dir/"history.sqlite3"
            studio.init()
            studio.STATE["settings"]["assets_dir"]=str(root)
            studio.STATE["settings"]["character_model"]="kan_0"
            server,_=main_desktop.start_server(0,root)
            url=f"http://127.0.0.1:{server.server_port}"
            def get(path):
                with urllib.request.urlopen(url+path,timeout=12) as result:
                    return json.load(result)
            def post(path,body):
                req=urllib.request.Request(url+path,data=json.dumps(body,
                    ensure_ascii=False).encode(),
                    headers={"Content-Type":"application/json",
                             "Origin":url})
                with urllib.request.urlopen(req,timeout=15) as result:
                    return json.load(result)
            catalog=get("/api/behavior_catalog")
            self.assertEqual(catalog["model"],"kan_0")
            self.assertIn("think",next(x for x in catalog["entries"]
                                      if x["label"]=="思考")["tags"])
            self.assertEqual(post("/api/behavior_tags",{
                "label":"思考","tags":["wave","greet"],"sample_time":40
            })["tags"],["wave","greet"])
            post("/api/behavior_expression",{
                "emotion":"happy","label":"照れＡ"
            })
            response=post("/api/chat",{"text":"你好"})
            self.assertEqual(response["emotion"],"happy")
            self.assertEqual(response["behavior"]["expression"]["label"],"照れＡ")
            self.assertEqual(response["behavior"]["model"],"kan_0")
            waved=post("/api/chat",{"text":"请挥手"})
            self.assertEqual(waved["behavior"]["action_tag"],"wave")
            self.assertEqual(waved["behavior"]["motion"]["label"],"思考")
            image=post("/api/expression_apply",{
                "label":"照れＡ","motion_label":"思考",
                "motion_time":40,"time":0
            })
            self.assertEqual(set(image["refs"]),{"normal","blink","talk"})
            self.assertEqual(image["motion_label"],"思考")
            self.assertEqual(image["motion_time"],40)
            self.assertTrue((settings_dir/"animation_tags.json").is_file())
            with self.assertRaises(urllib.error.HTTPError) as err:
                post("/api/behavior_tags",{
                    "label":"思考","tags":["../windows"],"sample_time":0
                })
            self.assertEqual(err.exception.code,400)
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            (studio.DATA,studio.GEN,studio.SETTINGS_FILE,
             studio.MANIFEST_FILE,studio.DB_FILE,studio.STATE)=previous
            fixture.tearDown()

if __name__=="__main__":
    unittest.main()
