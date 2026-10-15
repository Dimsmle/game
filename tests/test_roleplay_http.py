import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import urlopen,Request
from urllib.error import HTTPError

from tools.preview_server import make_server
from studio.roleplay_plus import bridge

class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.srv=make_server(cls.temp.name,0)
        cls.url=f"http://127.0.0.1:{cls.srv.server_port}"
        cls.worker=threading.Thread(target=cls.srv.serve_forever,daemon=True)
        cls.worker.start()
    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown();cls.worker.join(timeout=3);cls.srv.server_close()
        cls.temp.cleanup()
    def fetch(self,path,body=None):
        if body is None:
            with urlopen(self.url+path,timeout=5) as r:
                return r.status,r.read(),r.headers
        content=json.dumps(body,ensure_ascii=False).encode()
        req=Request(self.url+path,content,{"Content-Type":"application/json"},
                    method="POST")
        with urlopen(req,timeout=5) as r:
            return r.status,r.read(),r.headers
    def test_page_and_scripts(self):
        for path in ("/roleplay/","/roleplay/main.js","/roleplay/style.css","/roleplay/launcher.js"):
            status,raw,headers=self.fetch(path)
            self.assertEqual(status,200)
            self.assertGreater(len(raw),50)
        self.assertIn(b"ROLEPLAY",self.fetch("/roleplay/")[1])
    def test_current_state(self):
        status,raw,headers=self.fetch("/api/roleplay/status")
        obj=json.loads(raw)
        self.assertEqual(status,200)
        self.assertEqual(len(obj["presets"]),6)
        self.assertIn("game_state",obj)
        self.assertEqual(headers.get("X-Frame-Options"),"DENY")
    def test_save_card_through_http(self):
        body=bridge.store().get_card("legacy_character")
        body["data"]["name"]="HTTP角色"
        response=json.loads(self.fetch("/api/roleplay/card/save",{
            "data":body["data"],"expected_revision":body["revision"]})[1])
        self.assertEqual(response["data"]["name"],"HTTP角色")
    def test_unknown_route(self):
        with self.assertRaises(HTTPError) as ctx:self.fetch("/api/roleplay/unknown")
        self.assertEqual(ctx.exception.code,404)
    def test_untrusted_origin_denied(self):
        req=Request(self.url+"/api/roleplay/select",
            data=b'{}',headers={"Origin":"https://evil.example","Content-Type":"application/json"},
            method="POST")
        with self.assertRaises(HTTPError) as ctx:urlopen(req,timeout=5)
        self.assertEqual(ctx.exception.code,400)
    def test_illegal_event_rejected(self):
        with self.assertRaises(HTTPError) as ctx:
            self.fetch("/api/roleplay/event/offer",{"event_id":"add_100_affection"})
        self.assertEqual(ctx.exception.code,400)
    def test_event_commit_over_http(self):
        offer=json.loads(self.fetch("/api/roleplay/event/offer",{"event_id":"take_break"})[1])
        before=json.loads(self.fetch("/api/roleplay/game_state")[1])
        choice={"instance_id":offer["instance_id"],"choice_id":"accept","idempotency_key":"k_http"}
        result=json.loads(self.fetch("/api/roleplay/event/choose",choice)[1])
        self.assertGreaterEqual(result["game_state"]["state"]["energy"],before["state"]["energy"])
        self.assertEqual(result,json.loads(self.fetch("/api/roleplay/event/choose",choice)[1]))
    def test_prompt_preview_requires_consent(self):
        with self.assertRaises(HTTPError):
            self.fetch("/api/roleplay/prompt_preview",{"text":"你好"})
    def test_prompt_preview_is_not_api_call(self):
        obj=json.loads(self.fetch("/api/roleplay/prompt_preview",
                                  {"text":"你好","confirm":True})[1])
        self.assertIn("扩展段落",obj["note"])
        self.assertIn("角色核心",obj["addendum"])
    def test_lore_test(self):
        obj=json.loads(self.fetch("/api/roleplay/lore/test",{"text":"公园"})[1])
        self.assertIn("trace",obj)
    def test_bad_post_json(self):
        req=Request(self.url+"/api/roleplay/select",
          b"{broken",{"Content-Type":"application/json"},method="POST")
        with self.assertRaises(HTTPError) as e:urlopen(req,timeout=5)
        self.assertEqual(e.exception.code,400)

if __name__=="__main__":unittest.main()
