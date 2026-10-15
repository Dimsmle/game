# -*- coding: utf-8 -*-
"""Background library and HTTP/manifest regression tests.
Uses generated abstract test rectangles; does not package any game assets.
"""
import io
import json
import tempfile
import unittest
from pathlib import Path
import urllib.error
import urllib.request

from PIL import Image

import main_desktop
from studio import app as studio
from studio import backgrounds

def fake_image(color=(20,75,150),size=(640,360),format="PNG"):
    im=Image.new("RGB",size,color)
    buffer=io.BytesIO()
    im.save(buffer,format=format)
    return buffer.getvalue()

class BackgroundTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        root=Path(self.tmp.name)
        self.root=root/"_AI"
        self.root.mkdir()
        self.data=root/"app_data"
        self.bg_dir=self.root/"assets"/"image"/"bg"
        self.bg_dir.mkdir(parents=True)
        self.day=self.bg_dir/"bg_classroom_day.png"
        self.day.write_bytes(fake_image())
        self.night=self.bg_dir/"bg_street_night.jpg"
        self.night.write_bytes(fake_image((5,7,25),format="JPEG"))
        self.fake_texture=self.root/"kan_10_decompiled"/"kan_10"
        self.fake_texture.mkdir(parents=True)
        (self.fake_texture/"tex#000-texture.png").write_bytes(fake_image())
        self.saved=(studio.DATA,studio.GEN,studio.SETTINGS_FILE,
                    studio.MANIFEST_FILE,studio.DB_FILE,studio.STATE)
        studio.DATA=self.data
        studio.GEN=self.data/"generated"
        studio.SETTINGS_FILE=self.data/"settings.json"
        studio.MANIFEST_FILE=self.data/"manifest.json"
        studio.DB_FILE=self.data/"history.sqlite3"
        studio.init()
        studio.STATE["settings"]["assets_dir"]=str(self.root)

    def tearDown(self):
        (studio.DATA,studio.GEN,studio.SETTINGS_FILE,studio.MANIFEST_FILE,
         studio.DB_FILE,studio.STATE)=self.saved
        self.tmp.cleanup()

    def test_discovery_prefers_backgrounds_and_ignores_character_atlas(self):
        items=backgrounds.discover(self.root,self.data,force=True)
        self.assertEqual(len(items),2)
        self.assertEqual({p["category"] for p in items},{"day","night"})
        self.assertTrue(all("tex#000" not in x["ref"] for x in items))
        self.assertIn("assets/image/bg/bg_classroom_day.png",{x["ref"] for x in items})

    def test_import_validation_and_storage(self):
        imported=backgrounds.import_image(self.data,fake_image(),"我的教室夜间背景.png")
        self.assertTrue(imported["ref"].startswith("background:"))
        self.assertEqual(imported["width"],640)
        target=backgrounds.background_file(self.data,imported["ref"])
        self.assertTrue(target.is_file())
        self.assertIn(imported["ref"],{i["ref"] for i in
                      backgrounds.discover(self.root,self.data,force=True)})
        self.assertIsNone(backgrounds.background_file(self.data,"background:../../secrets"))
        with self.assertRaises(ValueError):
            backgrounds.import_image(self.data,b"not an image","invalid")

    def test_background_import_http_scene_binding_and_settings(self):
        server,thread=main_desktop.start_server(0,self.root)
        address=f"http://127.0.0.1:{server.server_port}"
        def get(path):
            with urllib.request.urlopen(address+path,timeout=8) as response:
                return json.load(response)
        def post(path,payload):
            req=urllib.request.Request(
                address+path,data=json.dumps(payload,ensure_ascii=False).encode(),
                headers={"Content-Type":"application/json","Origin":address})
            with urllib.request.urlopen(req,timeout=8) as response:
                return json.load(response)
        try:
            found=get("/api/backgrounds")
            self.assertEqual(found["count"],2)
            imported_bytes=fake_image((30,40,80))
            req=urllib.request.Request(address+"/api/background_import?name=room_scene.png",
                  data=imported_bytes,
                  headers={"Content-Type":"image/png","Origin":address})
            with urllib.request.urlopen(req,timeout=12) as response:
                image_meta=json.load(response)["item"]
            self.assertEqual(get("/api/backgrounds")["count"],3)
            with urllib.request.urlopen(
                address+"/background/"+image_meta["ref"].split(":")[1]+".png",
                timeout=8) as response:
                self.assertEqual(response.read(8),b"\x89PNG\r\n\x1a\n")
            manifest=dict(studio.STATE["manifest"])
            manifest["scenes"]={
                "day":"assets/image/bg/bg_classroom_day.png",
                "night":"assets/image/bg/bg_street_night.jpg",
                "evening":image_meta["ref"],
                "bedroom":image_meta["ref"],
            }
            manifest["background_fit"]="contain"
            result=post("/api/manifest",manifest)
            self.assertEqual(result["manifest"]["background_fit"],"contain")
            self.assertEqual(result["manifest"]["scenes"]["evening"],image_meta["ref"])
            settings=post("/api/settings",{"auto_scene":True})
            self.assertTrue(settings["settings"]["auto_scene"])
            self.assertEqual(get("/api/state")["manifest"]["scenes"]["night"],
                             "assets/image/bg/bg_street_night.jpg")
            # Never accept paths outside the sandboxed asset root.
            with self.assertRaises(urllib.error.HTTPError) as err:
                post("/api/manifest",{"layers":[],"scenes":{"day":"../private.png"},
                       "events":[]})
            self.assertEqual(err.exception.code,400)
        finally:
            server.shutdown()
            server.server_close()
