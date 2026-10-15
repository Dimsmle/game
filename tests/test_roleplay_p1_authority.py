"""P1 GameStore adapter regressions: never create a competing relationship authority."""
import ast
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from studio.roleplay_plus import bridge

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("rp_installer_p1",ROOT/"tools/install_addon.py")
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)


class FakeGameStore:
    def __init__(self,profile_id="secondary"):
        self.profile_id=profile_id
        self.snapshots=0

    def snapshot(self):
        self.snapshots+=1
        return (
          {"profile_id":self.profile_id,"generation":3},
          {"schema":1,"profile_id":self.profile_id,"character_id":"legacy_character",
           "revision":9,"stats":{"affection":77,"trust":66,"mood":-15,"energy":25},
           "relationship_stage":"intimate","milestones":[],"flags":{"visited_park":True},
           "scene":{"location_id":"unknown","time_of_day":"unknown","lock":False},
           "event":{"instance_id":None,"status":"idle"},"clock_mode":"manual",
           "toggles":{"proactive_events":False,"touch_interaction":False}}
        )


class Handler:
    headers={"Content-Type":"application/json"}
    def __init__(self):self.response=None
    def reply(self,status,value,content_type=None):self.response=(status,value)


class MainAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        bridge.initialize(Path(self.temp.name)/"history.sqlite3",
                          {"role_name":"测试人物","persona":"初始人设"})
        self.main=FakeGameStore()
        self.before=bridge._MAIN_GAME
        bridge._MAIN_GAME=self.main

    def tearDown(self):
        bridge._MAIN_GAME=self.before
        self.temp.cleanup()

    def test_p1_profile_uses_main_authoritative_state(self):
        response=Handler()
        self.assertTrue(bridge.try_get(response,"/api/roleplay/status",{}))
        body=response.response[1]
        self.assertEqual(body["authority_mode"],"game_db")
        self.assertEqual(body["game_state"]["state"]["affection"],77)
        self.assertEqual(body["game_state"]["state"]["relationship_stage"],"intimate")
        self.assertEqual(body["binding"]["profile_id"],"secondary")
        self.assertEqual(body["events"],[])
        # rp_state is deliberately inert while main GameStore owns affinity.
        self.assertEqual(bridge.store().game_state("secondary")["state"]["affection"],25)

    def test_p1_event_offer_cannot_mutate_preview_or_main(self):
        with self.assertRaisesRegex(ValueError,"GameStore"):
            bridge.try_post(Handler(),"/api/roleplay/event/offer",{"event_id":"take_break"})
        with self.assertRaisesRegex(ValueError,"GameStore"):
            bridge.try_post(Handler(),"/api/roleplay/event/choose",
                            {"instance_id":"e_fake","choice_id":"accept","idempotency_key":"k_fake"})
        self.assertEqual(bridge._game_state()["state"]["mood"],-15)
        self.assertIsNone(bridge.store().active_event("secondary"))

    def test_profile_aware_preset_and_prompt(self):
        response=Handler()
        bridge.try_post(response,"/api/roleplay/select",{"preset_id":"daily"})
        self.assertEqual(response.response[1]["binding"]["profile_id"],"secondary")
        self.assertEqual(bridge.store().binding("default")["preset_id"],"immersive_galgame")
        prompt=bridge.extend_prompt("可信游戏规则，请输出合法 JSON",{
            "_game_session":{"profile_id":"secondary","generation":3},"memory_enabled_for_llm":False
        },"你好")
        self.assertIn("好感度=77/100",prompt)
        self.assertIn("自然日常",prompt)
        self.assertNotIn("事件 take_break，玩家选择",prompt)
        self.assertEqual(self.main.profile_id,"secondary")

    def test_old_profile_snapshot_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError,"存档已切换"):
            bridge.extend_prompt("JSON 规则",{"_game_session":{"profile_id":"other","generation":3}},"你好")


class P1InstallerTests(unittest.TestCase):
    @staticmethod
    def fake_current_source():
        return '''from pathlib import Path
import urllib.parse
from studio import replies

def init():
    from .game_db import migrate
    migrate(DB_FILE)
    return STATE

def chat_settings():
    session,state=game_store().snapshot()
    return dict(STATE['settings'],_game_session=session,_game_state=state)

def chat_response(user_text):
    profile_id='default'
    settings={}
    prompt=('chat'+persona_context(settings))
    if True:
        conversation=[{"role":"system","content":prompt}]

def stream_chat(user_text):
    settings={}
    prompt=('stream'+persona_context(settings))
    if True:
        if True:
            messages=[{"role":"system","content":prompt}]

class Handler:
    def do_GET(self):
        route=urllib.parse.urlsplit(self.path)
        path=route.path
        query=urllib.parse.parse_qs(route.query)
        try:
            if path=="/":
                return self.static(WEB/'index.html')
        except Exception:pass

    def do_POST(self):
        try:
            if not isinstance(obj,dict):
                raise ValueError("请求体必须是对象")
            if path=="/api/settings":
                return self.reply(200,{})
        except Exception:
            pass
'''

    def test_current_p1_branch_inserts_roleplay_epoch_and_main_authority(self):
        source=self.fake_current_source()
        modified=installer.patch_app(source)
        ast.parse(modified)
        self.assertIn('use_existing_game_state=True',modified)
        self.assertIn('_roleplay_epoch=roleplay_bridge.epoch()',modified)
        self.assertIn('history(6,settings["_game_session"]["profile_id"])',modified)
        self.assertEqual(modified.count('角色卡为准'),2)
        self.assertIn('roleplay_bridge.try_get',modified)
        self.assertIn('roleplay_bridge.try_post',modified)
        with self.assertRaisesRegex(ValueError,'已经接入'):
            installer.patch_app(modified)

    def test_unrecognized_p1_structure_fails_guarded_instead_of_overwrite(self):
        src=self.fake_current_source().replace('    migrate(DB_FILE)','    migrate_new(DB_FILE)')
        with self.assertRaisesRegex(ValueError,'无法安全合并'):
            installer.patch_app(src)


if __name__=='__main__':unittest.main()
