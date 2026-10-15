# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
import urllib.request
from pathlib import Path

import main_desktop
from studio import app as studio
import tests.test_behavior as behavior_fixture

class V07APITests(unittest.TestCase):
    def test_runtime_renderer_doctor_import_and_model_metadata_endpoints(self):
        fixture=behavior_fixture.BehaviorPlanningTests(methodName="test_real_timeline_names_get_seed_tags")
        fixture.setUp()
        root=fixture.synthetic.folder.parent
        data=root/"v07_state"
        previous=(studio.DATA,studio.GEN,studio.SETTINGS_FILE,
                  studio.MANIFEST_FILE,studio.DB_FILE,studio.STATE)
        server=None
        try:
            studio.DATA=data;studio.GEN=data/"generated"
            studio.SETTINGS_FILE=data/"settings.json"
            studio.MANIFEST_FILE=data/"manifest.json"
            studio.DB_FILE=data/"history.sqlite3"
            studio.init()
            studio.STATE["settings"]["assets_dir"]=str(root)
            studio.STATE["settings"]["character_model"]="kan_0"
            studio.RUNTIME.reset("kan_0",now=100)
            server,_=main_desktop.start_server(0,root)
            url=f"http://127.0.0.1:{server.server_port}"
            def get(path):
                with urllib.request.urlopen(url+path,timeout=15) as result:
                    return json.load(result)
            def post(path,obj):
                req=urllib.request.Request(
                    url+path,data=json.dumps(obj,ensure_ascii=False).encode(),
                    headers={"Content-Type":"application/json","Origin":url})
                with urllib.request.urlopen(req,timeout=15) as result:
                    return json.load(result)

            with urllib.request.urlopen(url+"/api/health",timeout=10) as health_response:
                health=json.load(health_response)
                csp=health_response.headers.get("Content-Security-Policy","")
            self.assertEqual(health["version"],"0.7.0")
            self.assertIn("default-src 'self'",csp)
            runtime=get("/api/runtime")
            self.assertEqual(runtime["model"],"kan_0")
            caps=get("/api/renderer_capabilities")
            self.assertFalse(caps["current"]["continuous_motion"])
            self.assertTrue(any(x["renderer_id"]=="live2d_cubism_target"
                                for x in caps["available_or_planned"]))
            doctor=get("/api/diagnostics")
            self.assertTrue(any(x["key"]=="python" for x in doctor["items"]))
            self.assertIn("不主动连接",doctor["note"])

            locked=post("/api/runtime_event",{
                "event":"scene_lock","scene":"day","duration_seconds":120})
            self.assertTrue(locked["runtime"]["scene_lock"]["active"])
            unlocked=post("/api/runtime_event",{"event":"scene_unlock"})
            self.assertFalse(unlocked["runtime"]["scene_lock"]["active"])

            lib={"version":1,"models":{"kan_0":{
                "motion_tags":{"思考":{"tags":["think"],"sample_time":30}},
                "expression_map":{"thinking":"照れＡ"}}}}
            imported=post("/api/behavior_import",{"library":lib,"mode":"merge"})
            self.assertTrue(imported["ok"])
            exported=get("/api/behavior_export")
            self.assertEqual(exported["models"]["kan_0"]["motion_tags"]["思考"]["tags"],["think"])

            meta=post("/api/model_metadata",{
                "model":"kan_0","record":{
                    "display_name":"测试服装","outfit":"test_outfit",
                    "pose_family":"standing_a","verified":True,"notes":"ok"}})
            self.assertTrue(meta["record"]["verified"])
            loaded=get("/api/model_metadata")
            self.assertEqual(loaded["record"]["outfit"],"test_outfit")

            remembered=post("/api/memory",{"action":"add","content":"用户喜欢安静的夜景"})
            memory_id=remembered["id"]
            self.assertEqual(len(get("/api/memories")["items"]),1)
            self.assertIn("安静的夜景",studio.memory_context())
            post("/api/memory",{"action":"toggle","id":memory_id,"enabled":False})
            self.assertNotIn("安静的夜景",studio.memory_context())
            post("/api/memory",{"action":"toggle","id":memory_id,"enabled":True})
            self.assertIn("安静的夜景",studio.memory_context())
            post("/api/memory",{"action":"delete","id":memory_id})
            self.assertEqual(get("/api/memories")["items"],[])

            # Privacy toggle is persisted as a regular boolean setting; when false,
            # chat_response will not call memory_context for the LLM prompt.
            settings=post("/api/settings",{"memory_enabled_for_llm":False})
            self.assertFalse(settings["settings"]["memory_enabled_for_llm"])
            settings=post("/api/settings",{"memory_enabled_for_llm":True})
            self.assertTrue(settings["settings"]["memory_enabled_for_llm"])

            logs=get("/api/log_tail")
            self.assertTrue(any("GET /api/runtime" in line for line in logs["lines"]))
            self.assertIn("不记录聊天请求正文",logs["note"])
        finally:
            if server:
                server.shutdown();server.server_close()
            (studio.DATA,studio.GEN,studio.SETTINGS_FILE,
             studio.MANIFEST_FILE,studio.DB_FILE,studio.STATE)=previous
            fixture.tearDown()

if __name__=="__main__":
    unittest.main()
