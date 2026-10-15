from http.server import ThreadingHTTPServer
import json
import threading
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch
from studio import app,llm
from tests import test_ai_providers as fixtures


class GameAPITests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.PipelineTests('test_semantic_validation_and_atomic_history');self.fixture.setUp()
        app.STATE['settings']['llm_mode']='demo'
        self.server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.fixture.tearDown()
    def get(self,path):
        with urllib.request.urlopen(self.url+path,timeout=8) as response:return json.load(response)
    def post(self,path,obj,origin=None):
        request=urllib.request.Request(self.url+path,json.dumps(obj).encode(),{'Content-Type':'application/json','Origin':origin or self.url})
        with urllib.request.urlopen(request,timeout=8) as response:return json.load(response)

    def test_read_only_state_profiles_backup_and_origin(self):
        initial=self.get('/api/game/state')
        self.assertEqual(initial['profile_id'],'default');self.assertNotIn('settings',initial)
        for body in ({'action':'create','id':'../x','display_name':'x'},
                     {'action':'create','id':'new','display_name':'x','stats':{'affection':100}}):
            with self.assertRaises(urllib.error.HTTPError):self.post('/api/game/profile',body)
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/game/profile',{'action':'select','id':'default'},'https://other.invalid')
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/game/set_affection',{'delta':100})
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/game/backup',{'path':'C:\\escape'})
        value=self.post('/api/game/backup',{})
        self.assertNotIn('path',value);self.assertNotIn('\\',value['backup_id'])
        self.assertEqual(self.get('/api/game/state'),initial)

    def test_profile_history_memory_isolation_and_clear_scope(self):
        app.add_history('user','old private text','user');memory_id=app.add_memory('old private memory')
        self.post('/api/game/profile',{'action':'create','id':'second','display_name':'<script>not markup</script>'})
        self.post('/api/game/profile',{'action':'select','id':'second'})
        self.assertEqual(app.history(),[]);self.assertEqual(app.memories(),[])
        with self.assertRaises(ValueError):app.delete_memory(memory_id)
        app.add_history('user','second text','user')
        self.post('/api/clear_history',{})
        self.post('/api/game/profile',{'action':'select','id':'default'})
        self.assertEqual(app.history()[0]['content'],'old private text')
        self.assertEqual(app.memories()[0]['content'],'old private memory')

    def test_partial_reply_keeps_only_read_prefix_and_switch_invalidates_tail(self):
        initial=self.get('/api/game/state')
        value=list(app.stream_chat('逐句表情','game_partial_123'))[-1]['result']
        app.activate_reply(value['turn_id'],0)
        app.game_store().create('second','two');app.select_game_profile('second');app.select_game_profile('default')
        with self.assertRaises(ValueError):app.activate_reply(value['turn_id'],1)
        self.assertEqual(app.history()[-1]['content'],value['segments'][0]['speech'])
        self.assertEqual(self.get('/api/game/state'),initial)

    def test_switch_during_provider_aborts_result_even_after_switching_back(self):
        app.STATE['settings']['llm_mode']='openai';app.game_store().create('second','two')
        def service(provider,messages,cancel):
            self.assertIn('可信游戏存档',messages[0]['content'])
            yield '{"speech":"你好"'
            app.select_game_profile('second');app.select_game_profile('default')
            yield '}'
        with patch.object(llm.OpenAICompatibleProvider,'stream',service):
            with self.assertRaises(llm.Cancelled):list(app.stream_chat('hi','game_switch_123'))
        self.assertEqual(app.history(),[])

    def test_llm_numeric_effect_and_events_cannot_change_state(self):
        initial=app.game_store().read();app.STATE['settings']['llm_mode']='openai'
        app.STATE['manifest']['scenes']['night']='local_registered_image'
        raw=json.dumps({'segments':[{'speech':'你好','emotion':'gentle','affection':100,'scene':'night'}],
                        'event_proposal':{'event_id':'unknown'},'stats':{'affection':100}})
        with patch.object(llm.OpenAICompatibleProvider,'stream',return_value=iter([raw])):
            result=list(app.stream_chat('hi','game_inject_123'))[-1]['result']
        app.activate_reply(result['turn_id'],0)
        self.assertEqual(app.game_store().read(),initial)
        self.assertNotIn('event_proposal',result)
        self.assertEqual(result['scene'],'')


if __name__=='__main__':unittest.main()
