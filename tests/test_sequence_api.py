import json
from pathlib import Path
import time
import unittest
import urllib.error
import urllib.request

from emote_model import PoseModel
import main_desktop as main
from studio import app
from studio.frame_sequence import SequenceJobs, export_nod_sequence, sequence_key
from pose_renderer import AtlasRenderer
from tests import test_emote as synthetic


class SequenceAPITests(unittest.TestCase):
    def test_mesh_export_cache_review_and_stale_model_guard(self):
        fixture=synthetic.RealSchemaSyntheticTest("test_file_discovery");fixture.setUp()
        previous=(app.DATA,app.GEN,app.SETTINGS_FILE,app.MANIFEST_FILE,app.DB_FILE,app.STATE,main.SEQUENCE_JOBS)
        server=None
        try:
            data=json.loads(fixture.path.read_text(encoding="utf-8"))
            motion=data["object"]["all_parts"]["motion"]["全体構造"]
            original=motion["layer"]
            motion["layer"]=[{
                "label":"mesh cage","meshTransform":1,
                "frameList":[{"time":0,"content":{"src":"blank","icon":"100:100:0:0"}}],
                "meshCombinator":{"combinatorList":[{
                    "meshType":1,"neutralIndex":1,"rawMeshList":"#resource@1",
                    "variable":{"key":"head_UD","meshCount":3,"rangeBegin":-30,"rangeEnd":30}}]},
                "children":original}]
            data["metadata"]["timelineControl"].append({"label":"うんうん","variableList":[{
                "label":"head_UD","frameList":[{"time":0,"content":{"value":0}},
                                                {"time":6,"content":{"value":30}}]}]})
            fixture.path.write_text(json.dumps(data),encoding="utf-8")
            resx=fixture.path.with_name("kan_0.resx.json")
            value=json.loads(resx.read_text(encoding="utf-8"))
            value["ExtraFlattenArrays"]={"@1":[-.2,0]*16+[0,0]*16+[.2,0]*16}
            resx.write_text(json.dumps(value),encoding="utf-8")
            root=fixture.folder.parent
            app.DATA=root/"qa";app.GEN=app.DATA/"generated"
            app.SETTINGS_FILE=app.DATA/"settings.json";app.MANIFEST_FILE=app.DATA/"manifest.json"
            app.DB_FILE=app.DATA/"history.sqlite3";app.init()
            app.STATE["settings"].update(assets_dir=str(root),character_model="kan_0")
            main.SEQUENCE_JOBS=SequenceJobs()
            server,_=main.start_server(0,root)
            url=f"http://127.0.0.1:{server.server_port}"

            def post(route,value):
                req=urllib.request.Request(url+route,json.dumps(value).encode(),
                    {"Content-Type":"application/json","Origin":url})
                with urllib.request.urlopen(req,timeout=15) as response:return json.load(response)

            request={"expression":"笑顔Ａ"}
            job=post("/api/motion_sequence",request)
            deadline=time.monotonic()+15
            while job["state"]=="rendering" and time.monotonic()<deadline:
                time.sleep(.05)
                job=post("/api/motion_sequence",{**request,"cached_only":True})
            self.assertEqual(job["state"],"ready",job)
            sequence=job["sequence"]
            self.assertGreater(sequence["distinct_visual_frames"],1)
            self.assertFalse(sequence["playable"])
            self.assertEqual(sequence["fps"],24)
            self.assertTrue(all((root/ref).is_file() for frame in sequence["frames"] for ref in frame["refs"].values()))
            review=post("/api/motion_review",{**request,"id":job["id"],"reviewed":True,"cached_only":True})
            self.assertTrue(review["sequence"]["playable"])
            response=post("/api/chat",{"text":"请点头"})
            self.assertEqual(response["behavior"]["motion"]["label"],"うんうん")
            self.assertEqual(response["behavior"]["playback_status"],"playable")
            with self.assertRaises(urllib.error.HTTPError):
                post("/api/motion_review",{**request,"id":"stale","reviewed":True,"cached_only":True})
            with self.assertRaises(urllib.error.HTTPError):
                post("/api/motion_sequence",{"expression":"../../secret"})
            self.assertNotEqual(sequence_key("kan_0","笑顔Ａ","old"),sequence_key("kan_0","笑顔Ａ","new"))
        finally:
            if server:server.shutdown();server.server_close()
            (app.DATA,app.GEN,app.SETTINGS_FILE,app.MANIFEST_FILE,app.DB_FILE,app.STATE,main.SEQUENCE_JOBS)=previous
            fixture.tearDown()


if __name__=="__main__":unittest.main()
