"""Regressions against the real P1 app, not the standalone addon preview."""
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from http.server import ThreadingHTTPServer
import json
import sqlite3
import threading
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch

from studio import app,llm
from studio.roleplay_plus import bridge,domain
from studio.roleplay_plus.store import RoleplayStore
from studio.roleplay_plus.composer import PromptComposer
from tests import test_ai_providers as fixtures


class MigrationTests(unittest.TestCase):
    def test_long_legacy_identity_preserved_once(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'history.sqlite3'
            store=RoleplayStore(path)
            original='旧人设完整段落。'*1200
            store.initialize({'role_name':'旧角色','persona':original})
            self.assertEqual(store.get_card('legacy_character')['data']['description'],original)
            store.initialize({'role_name':'不能覆盖','persona':'不同的新默认值'})
            self.assertEqual(store.get_card('legacy_character')['data']['description'],original)
            self.assertFalse(store.get_persona('default_player')['data']['share_with_llm'])
            trace=PromptComposer().compose(store.snapshot(),'你好')['trace']
            self.assertTrue(any(p['section']=='人物完整介绍' and p['truncated'] for p in trace['parts']))
            self.assertLessEqual(trace['addendum_tokens_estimate'],4000)

    def test_failed_seed_rolls_back_schema_and_closes_backup(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'history.sqlite3'
            with closing(sqlite3.connect(path)) as db,db:
                db.execute('CREATE TABLE original(value TEXT)')
                db.execute("INSERT INTO original VALUES('preserved')")
            with patch.object(domain,'builtin_presets',side_effect=RuntimeError('seed failed')):
                with self.assertRaisesRegex(RuntimeError,'seed failed'):RoleplayStore(path).initialize({})
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT value FROM original').fetchone()[0],'preserved')
                self.assertFalse(db.execute("SELECT name FROM sqlite_master WHERE name='rp_meta'").fetchall())
            # Windows rename is a strong check that the backup handle was closed.
            backup=next((path.parent/'roleplay_backups').glob('*.sqlite3'))
            moved=backup.with_suffix('.closed.sqlite3');backup.rename(moved)
            RoleplayStore(path).initialize({})


class IntegratedRoleplayTests(unittest.TestCase):
    def setUp(self):
        self.previous=(bridge._STORE,bridge._MAIN_GAME)
        self.fixture=fixtures.PipelineTests('test_semantic_validation_and_atomic_history');self.fixture.setUp()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.fixture.tearDown();bridge._STORE,bridge._MAIN_GAME=self.previous
    def get(self,path):
        with urllib.request.urlopen(self.url+path,timeout=8) as response:return json.load(response)
    def post(self,path,data,origin=None,content_type='application/json'):
        request=urllib.request.Request(self.url+path,json.dumps(data).encode(),
            {'Content-Type':content_type,'Origin':origin or self.url})
        with urllib.request.urlopen(request,timeout=8) as response:return json.load(response)
    def generate(self,text='你好'):
        return list(app.stream_chat(text,'integration_12345'))[-1]['result']
    def provider(self,captured):
        def service(provider,messages,cancel):
            captured.append(messages)
            yield json.dumps({'segments':[{'speech':'第一句。','emotion':'gentle'},
                                         {'speech':'第二句。','emotion':'happy'}]},ensure_ascii=False)
        return service
    def add_lore(self,**changes):
        entry={'entry_id':'school','title':'学校背景','content':'学校有一间蓝色阅览室。',
               'keywords':['学校'],'activation':'keyword','conditions':{}}
        entry.update(changes)
        return self.post('/api/roleplay/lore/save',{'card_id':'legacy_character','data':entry,'expected_revision':0})

    def test_six_presets_reach_actual_stream_request(self):
        captured=[];seen=[]
        with patch.object(llm.OpenAICompatibleProvider,'stream',self.provider(captured)):
            for preset in domain.builtin_presets():
                self.post('/api/roleplay/select',{'preset_id':preset['preset_id']})
                result=self.generate()
                self.assertEqual(len(result['segments']),2)
                self.assertIn(preset['name'],captured[-1][0]['content'])
                self.assertIn('JSON',captured[-1][0]['content'])
                self.assertEqual(self.get('/api/roleplay/prompt_trace')['trace']['preset_id'],preset['preset_id'])
                seen.append(captured[-1][0]['content'])
        self.assertEqual(len(set(seen)),6);self.assertEqual(app.history(),[])

    def test_keyword_conditions_memory_and_player_privacy(self):
        self.add_lore()
        self.post('/api/roleplay/persona/save',{'data':{'persona_id':'writer','name':'测试玩家',
            'description':'PLAYER_PRIVATE_MARKER','share_with_llm':False},'expected_revision':0})
        self.post('/api/roleplay/select',{'persona_id':'writer'})
        app.add_memory('MEMORY_PRIVATE_MARKER');app.STATE['settings']['memory_enabled_for_llm']=False
        captured=[]
        with patch.object(llm.OpenAICompatibleProvider,'stream',self.provider(captured)):
            self.generate('今天读书');self.assertNotIn('蓝色阅览室',captured[-1][0]['content'])
            self.generate('学校有什么');self.assertIn('蓝色阅览室',captured[-1][0]['content'])
        self.assertNotIn('PLAYER_PRIVATE_MARKER',captured[-1][0]['content'])
        self.assertNotIn('MEMORY_PRIVATE_MARKER',captured[-1][0]['content'])
        entry=bridge.store().list_lore('legacy_character')[0]
        entry['data']['conditions']={'affection_min':90}
        self.post('/api/roleplay/lore/save',{'card_id':'legacy_character','data':entry['data'],'expected_revision':entry['revision']})
        with patch.object(llm.OpenAICompatibleProvider,'stream',self.provider(captured)):
            self.generate('学校有什么');self.assertNotIn('蓝色阅览室',captured[-1][0]['content'])

    def test_edit_invalidates_unread_tail_and_keeps_read_history(self):
        with patch.object(llm.OpenAICompatibleProvider,'stream',self.provider([])):result=self.generate()
        app.activate_reply(result['turn_id'],0)
        self.post('/api/roleplay/select',{'preset_id':'daily'})
        with self.assertRaises(ValueError):app.activate_reply(result['turn_id'],1)
        self.assertEqual(app.history()[-1]['content'],'第一句。')

    def test_edit_during_request_cannot_commit_even_after_aba(self):
        def service(provider,messages,cancel):
            yield '{"speech":"'
            self.post('/api/roleplay/select',{'preset_id':'daily'})
            self.post('/api/roleplay/select',{'preset_id':'immersive_galgame'})
            yield '旧回复"}'
        with patch.object(llm.OpenAICompatibleProvider,'stream',service):
            with self.assertRaises(llm.Cancelled):self.generate()
        self.assertEqual(app.history(),[])

    def test_first_chat_on_new_profile_and_bindings_persist(self):
        app.game_store().create('2Q-New','新档案');app.select_game_profile('2Q-New')
        with patch.object(llm.OpenAICompatibleProvider,'stream',self.provider([])):self.generate()
        self.post('/api/roleplay/select',{'preset_id':'daily'})
        self.assertEqual(RoleplayStore(app.DB_FILE).binding('2Q-New')['preset_id'],'daily')
        app.select_game_profile('default')
        self.assertEqual(self.get('/api/roleplay/status')['binding']['preset_id'],'immersive_galgame')

    def test_card_controls_stage_name_not_legacy_setting(self):
        card=bridge.store().get_card('legacy_character')['data']
        card.update(card_id='new_actor',name='新角色',description='NEW_CARD_MARKER')
        self.post('/api/roleplay/card/save',{'data':card,'expected_revision':0})
        self.post('/api/roleplay/select',{'card_id':'new_actor'})
        state=self.get('/api/state')
        self.assertEqual(state['roleplay']['name'],'新角色')
        self.assertNotEqual(state['settings']['role_name'],'新角色')
        captured=[]
        with patch.object(llm.OpenAICompatibleProvider,'stream',self.provider(captured)):self.generate()
        self.assertIn('NEW_CARD_MARKER',captured[0][0]['content'])

    def test_stale_workbench_cannot_select_preset_for_a_different_profile(self):
        session=self.get('/api/roleplay/status')['session']
        app.game_store().create('second','two');app.select_game_profile('second')
        with self.assertRaises(urllib.error.HTTPError):
            self.post('/api/roleplay/select',{'preset_id':'daily','expected_session':session})
        self.assertEqual(bridge.store().binding('second')['preset_id'],'immersive_galgame')

    def test_preview_does_not_replace_actual_request_trace(self):
        with patch.object(llm.OpenAICompatibleProvider,'stream',self.provider([])):self.generate()
        previous=bridge._COMPOSER.last_trace()
        self.post('/api/roleplay/select',{'preset_id':'daily'})
        self.post('/api/roleplay/prompt_preview',{'confirm':True,'text':'学校有什么？'})
        self.assertEqual(bridge._COMPOSER.last_trace(),previous)

    def test_sync_compatibility_route_also_uses_composer(self):
        self.post('/api/roleplay/select',{'preset_id':'literary'})
        def service(url,payload,*args,**kwargs):
            self.assertIn('剧情小说',payload['messages'][0]['content'])
            return {'choices':[{'message':{'content':'{"speech":"兼容接口。"}'}}]}
        with patch.object(app,'http_json',side_effect=service):result=app.chat_response('你好')
        self.assertEqual(result['speech'],'兼容接口。')

    def test_addon_events_and_wrong_origin_cannot_write_state(self):
        before=app.game_store().read()
        for path,body in (('/api/roleplay/event/offer',{'event_id':'take_break'}),
                          ('/api/roleplay/event/choose',{'instance_id':'fake','choice_id':'accept'})):
            with self.assertRaises(urllib.error.HTTPError):self.post(path,body)
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/roleplay/select',{'preset_id':'daily'},origin='https://other.invalid')
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/roleplay/select',{'preset_id':'daily'},content_type='text/plain')
        self.assertEqual(app.game_store().read(),before)
        self.assertEqual(self.get('/api/roleplay/game_state')['state']['affection'],before['stats']['affection'])


if __name__=='__main__':unittest.main()
