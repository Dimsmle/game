import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
import wave

from studio import app,behavior,llm,tts,replies


def audio_bytes():
    out=io.BytesIO()
    with wave.open(out,'wb') as stream:
        stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(16000);stream.writeframes(b'\0\0'*400)
    return out.getvalue()


class TransportTests(unittest.TestCase):
    def test_stop_finish_does_not_wait_for_done_or_socket_eof(self):
        class Stream(io.BytesIO):
            def readline(inner,*args):
                if inner.tell()==len(inner.getvalue()):raise AssertionError('read after stop')
                return super().readline(*args)
        stream=Stream(b'data: {"choices":[{"delta":{"content":"{}"},"finish_reason":"stop"}]}\n')
        with patch('urllib.request.OpenerDirector.open',return_value=stream):
            self.assertEqual(list(llm.OpenAICompatibleProvider(dict(app.DEFAULT_SETTINGS,llm_mode='openai')).stream([],threading.Event())),['{}'])

    def test_partial_json_only_displays_speech(self):
        raw='{"speech":"你\\n好\\u4f60", "emotion":"shy"}'
        self.assertEqual(llm.speech_prefix(raw),'你\n好你')
        self.assertEqual(llm.speech_prefix('{"speech":"你\\u4f'),'你')
        self.assertEqual(llm.speech_prefix('{"emotion":"shy"}'),'')

    def test_stream_contract_and_secret_only_in_authorization(self):
        content='{"speech":"你好","emotion":"happy","action_tag":"idle"}'
        lines=[json.dumps({'choices':[{'delta':{'content':p}}]},ensure_ascii=False) for p in (content[:12],content[12:])]
        stream=io.BytesIO((''.join('data: '+p+'\n\n' for p in lines)+'data: [DONE]\n').encode())
        class Opener:
            def open(inner,request,timeout):
                self.assertEqual(request.get_header('Authorization'),'Bearer not-a-real-secret')
                payload=json.loads(request.data)
                self.assertEqual(payload['model'],'deepseek-flash')
                self.assertEqual(payload['response_format'],{'type':'json_object'})
                self.assertNotIn('not-a-real-secret',request.data.decode())
                return stream
        with patch.dict(os.environ,{'DEEPSEEK_API_KEY':'not-a-real-secret'}),patch('urllib.request.build_opener',return_value=Opener()):
            value=''.join(llm.OpenAICompatibleProvider(dict(app.DEFAULT_SETTINGS,llm_mode='deepseek',llm_model='deepseek-flash')).stream([],threading.Event()))
        self.assertEqual(value,content)

    def test_missing_key_and_redacted_http_error(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaisesRegex(RuntimeError,'DEEPSEEK_API_KEY'):
                list(llm.OpenAICompatibleProvider(dict(app.DEFAULT_SETTINGS,llm_mode='deepseek')).stream([],threading.Event()))
        error=urllib.error.HTTPError('https://example.invalid',401,'secret',{},io.BytesIO(b'sensitive body'))
        with patch.dict(os.environ,{'DEEPSEEK_API_KEY':'not-real'}),patch('urllib.request.OpenerDirector.open',side_effect=error):
            with self.assertRaisesRegex(RuntimeError,'HTTP 401') as exc:
                list(llm.OpenAICompatibleProvider(dict(app.DEFAULT_SETTINGS,llm_mode='deepseek')).stream([],threading.Event()))
            self.assertNotIn('sensitive',str(exc.exception));self.assertNotIn('secret',str(exc.exception))

    def test_retry_before_output_and_truncated_stream(self):
        error=urllib.error.HTTPError('https://example.invalid',503,'Unavailable',{},io.BytesIO())
        valid=io.BytesIO(b'data: [DONE]\n')
        with patch('urllib.request.OpenerDirector.open',side_effect=[error,valid]) as opener:
            self.assertEqual(list(llm.OpenAICompatibleProvider(dict(app.DEFAULT_SETTINGS,llm_mode='openai')).stream([],threading.Event())),[])
            self.assertEqual(opener.call_count,2)
        with patch('urllib.request.OpenerDirector.open',return_value=io.BytesIO(b'')):
            with self.assertRaisesRegex(RuntimeError,'提前结束'):
                list(llm.OpenAICompatibleProvider(dict(app.DEFAULT_SETTINGS,llm_mode='openai')).stream([],threading.Event()))


class PipelineTests(unittest.TestCase):
    def test_complete_persona_in_first_and_later_system_context(self):
        card='日常角色资料。'*230+'末尾约束：不要替用户做决定。'
        self.assertGreater(len(card),1000)
        app.STATE['settings'].update(app.validate_settings({'persona':card,'role_name':'测试角色'}))
        captured=[]
        def service(provider,messages,cancel):
            captured.append(messages)
            yield '{"segments":[{"speech":"你好。","emotion":"gentle"}]}'
        with patch.object(llm.OpenAICompatibleProvider,'stream',service):
            for index in range(2):
                value=list(app.stream_chat('hello','persona_test_'+str(index)))[-1]['result']
                app.activate_reply(value['turn_id'],0)
        for messages in captured:
            self.assertEqual(messages[0]['role'],'system')
            self.assertIn(card,messages[0]['content'])
            self.assertIn('测试角色',messages[0]['content'])
            self.assertIn('JSON',messages[0]['content'])
        with self.assertRaises(ValueError):app.validate_settings({'persona':'字'*12001})

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.data=Path(self.tmp.name)
        self.old=(app.DATA,app.GEN,app.SETTINGS_FILE,app.MANIFEST_FILE,app.DB_FILE,app.STATE,app.RUNTIME,app.LLM_METRICS,app.REPLY_TURN)
        app.DATA=self.data;app.GEN=self.data/'generated';app.SETTINGS_FILE=self.data/'settings.json'
        app.MANIFEST_FILE=self.data/'manifest.json';app.DB_FILE=self.data/'history.sqlite3'
        app.RUNTIME=app.behavior_runtime.BehaviorRuntime();app.REPLY_TURN=replies.ReplyTurn();app.init()
        app.STATE['settings']['llm_mode']='openai'

    def tearDown(self):
        (app.DATA,app.GEN,app.SETTINGS_FILE,app.MANIFEST_FILE,app.DB_FILE,app.STATE,app.RUNTIME,app.LLM_METRICS,app.REPLY_TURN)=self.old
        self.tmp.cleanup()

    def test_semantic_validation_and_atomic_history(self):
        raw=json.dumps({'reply':'你好','emotion':'../psb','action_tag':'look_away','emotion_intensity':.7,'voice_style':'soft','scene':'file:///x'})
        with patch.object(llm.OpenAICompatibleProvider,'stream',return_value=iter([raw])):
            events=list(app.stream_chat('你好','test_1234'))
        result=events[-1]['result']
        self.assertEqual(result['emotion'],'neutral');self.assertEqual(result['action_tag'],'idle')
        self.assertEqual(result['scene'],'');self.assertEqual(result['voice_style'],'soft');self.assertEqual(result['intensity'],.7)
        self.assertEqual(app.history(),[])
        app.activate_reply(result['turn_id'],0)
        self.assertEqual(len(app.history()),2)

    def test_two_turns_keep_protocol_and_accept_whole_fence(self):
        captured=[]
        raw='```json\n'+json.dumps({'segments':[{'speech':'第一句。','emotion':'happy'},{'speech':'第二句。','emotion':'gentle'}]})+'\n```'
        def service(provider,messages,cancel):
            captured.append(messages)
            yield raw
        with patch.object(llm.OpenAICompatibleProvider,'stream',service):
            first=list(app.stream_chat('hello','test_first_json'))[-1]['result']
            app.activate_reply(first['turn_id'],0)
            second=list(app.stream_chat('again','test_second_json'))[-1]['result']
        self.assertEqual(len(second['segments']),2)
        assistant=next(x for x in captured[1] if x['role']=='assistant')
        self.assertEqual(json.loads(assistant['content']),{'segments':[{'speech':'第一句。'}]})
        self.assertNotIn('第二句。',assistant['content'])

    def test_cancelled_or_malformed_never_commits(self):
        raw='{"speech":"你好","emotion":"happy"}'
        with patch.object(llm.OpenAICompatibleProvider,'stream',return_value=iter([raw])):
            iterator=app.stream_chat('hi','test_cancel');self.assertEqual(next(iterator)['type'],'text')
            app.cancel_chat('wrong_id')
            self.assertFalse(app.ACTIVE_CHAT['cancel'].is_set())
            app.cancel_chat('test_cancel')
            with self.assertRaises(llm.Cancelled):next(iterator)
        self.assertEqual(app.history(),[])
        with patch.object(llm.OpenAICompatibleProvider,'stream',return_value=iter(['{"speech":"incomplete'])):
            with self.assertRaisesRegex(RuntimeError,'JSON'):list(app.stream_chat('hi','test_bad1'))
        self.assertEqual(app.history(),[])

    def test_model_switch_invalidates_and_memory_privacy(self):
        app.add_memory('do-not-send');app.STATE['settings']['memory_enabled_for_llm']=False
        def service(provider,messages,cancel):
            self.assertNotIn('do-not-send',str(messages))
            yield '{"speech":"你好"}'
            app.STATE['settings']['character_model']='kan_8'
        with patch.object(llm.OpenAICompatibleProvider,'stream',service):
            with self.assertRaises(llm.Cancelled):list(app.stream_chat('hi','test_model'))
        self.assertEqual(app.history(),[])

    def test_http_ndjson_settings_and_origin(self):
        from http.server import ThreadingHTTPServer
        server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        url=f'http://127.0.0.1:{server.server_port}'
        app.STATE['settings']['llm_mode']='demo'
        try:
            req=urllib.request.Request(url+'/api/chat_stream',data=json.dumps({'id':'http_test_123','text':'你好'}).encode(),headers={'Origin':url})
            with urllib.request.urlopen(req,timeout=10) as response:events=[json.loads(line) for line in response]
            self.assertEqual(events[-1]['type'],'final')
            turn=events[-1]['result']
            self.assertEqual(app.history(),[])
            def post(path,obj):
                req=urllib.request.Request(url+path,data=json.dumps(obj).encode(),headers={'Origin':url})
                with urllib.request.urlopen(req) as response:return json.load(response)
            played=post('/api/chat_segment',{'turn_id':turn['turn_id'],'index':0})
            self.assertEqual(played['segment_index'],0);self.assertEqual(len(app.history()),2)
            post('/api/chat_turn_cancel',{'turn_id':turn['turn_id']})
            with self.assertRaises(urllib.error.HTTPError) as stopped:
                post('/api/chat_segment',{'turn_id':turn['turn_id'],'index':0})
            self.assertEqual(stopped.exception.code,400);stopped.exception.close()
            with urllib.request.urlopen(url+'/reply_player.js') as response:self.assertEqual(response.status,200)
            with urllib.request.urlopen(url+'/api/provider_status') as response:status=json.load(response)
            self.assertNotIn('api_key',status);self.assertFalse(status['stt_enabled'])
            obj=app.validate_settings({'llm_mode':'deepseek','tts_provider':'qwen3_tts','api_key':'must-not-save'})
            self.assertNotIn('api_key',obj);self.assertEqual(obj['tts_provider'],'qwen3_tts')
            with self.assertRaises(ValueError):app.asr_audio(b'unused')
            req=urllib.request.Request(url+'/api/chat_cancel',data=b'{"id":"http_test_123"}',headers={'Origin':'https://evil.example'})
            with self.assertRaises(urllib.error.HTTPError) as exc:urllib.request.urlopen(req)
            self.assertEqual(exc.exception.code,400);exc.exception.close()
        finally:server.shutdown();server.server_close();worker.join()

    def test_optional_tts_cache_and_no_model_install(self):
        counts=[];service=tts.TTSService(lambda text:counts.append(text) or audio_bytes())
        settings=dict(app.DEFAULT_SETTINGS,tts_enabled=True)
        self.assertEqual(service.synthesize('你好',settings,self.data),audio_bytes())
        service.synthesize('你好',settings,self.data)
        self.assertEqual(counts,['你好']);self.assertTrue(service.last_metrics['cached'])
        settings['tts_prompt_text']='new reference'
        service.synthesize('你好',settings,self.data);self.assertEqual(len(counts),2)
        with self.assertRaisesRegex(RuntimeError,'不会自动下载'):service.synthesize('hi',dict(settings,tts_provider='qwen3_tts'),self.data)
        with self.assertRaises(RuntimeError):tts.validate_wav(b'not audio')
        self.assertIsNone(service.providers['qwen3_tts'].model)

    def test_sentence_actions_and_history_are_lazy_ordered_and_idempotent(self):
        payload={'segments':[
            {'speech':'真的吗？','emotion':'surprised','action_tag':'idle'},
            {'speech':'有点不好意思。','emotion':'shy','action_tag':'idle'},
            {'speech':'不过我很开心。','emotion':'happy','action_tag':'idle'}]}
        with patch.object(llm.OpenAICompatibleProvider,'stream',return_value=iter([json.dumps(payload)])):
            final=list(app.stream_chat('hi','test_segments'))[-1]['result']
        self.assertEqual(len(final['segments']),3);self.assertEqual(app.RUNTIME.snapshot()['emotion'],'neutral')
        self.assertEqual(app.history(),[])
        token=final['turn_id']
        with self.assertRaises(ValueError):app.activate_reply(token,1)
        first=app.activate_reply(token,0)
        self.assertEqual(first['emotion'],'surprised')
        self.assertEqual(app.history()[-1]['content'],'真的吗？')
        before=app.RUNTIME.snapshot()
        self.assertEqual(app.activate_reply(token,0),first)
        self.assertEqual(app.RUNTIME.snapshot()['emotion'],before['emotion']);self.assertEqual(len(app.history()),2)
        second=app.activate_reply(token,1)
        self.assertEqual(second['emotion'],'shy');self.assertEqual(app.RUNTIME.snapshot()['emotion'],'shy')
        self.assertEqual(app.history()[-1]['content'],'真的吗？\n有点不好意思。')
        with self.assertRaises(ValueError):app.activate_reply(token,0)
        app.REPLY_TURN.cancel(token)
        with self.assertRaises(ValueError):app.activate_reply(token,2)
        self.assertNotIn('不过我很开心',app.history()[-1]['content'])

    def test_new_turn_model_change_and_expiry_invalidate_playback(self):
        app.STATE['settings']['llm_mode']='demo'
        old=list(app.stream_chat('演示逐句表情','test_old_reply'))[-1]['result']
        current=list(app.stream_chat('你好','test_new_reply'))[-1]['result']
        with self.assertRaises(ValueError):app.activate_reply(old['turn_id'],0)
        app.STATE['settings']['character_model']='kan_8'
        with self.assertRaises(ValueError):app.activate_reply(current['turn_id'],0)
        final=list(app.stream_chat('你好','test_expiry'))[-1]['result']
        app.REPLY_TURN.current['expires']=0
        with self.assertRaises(ValueError):app.activate_reply(final['turn_id'],0)
        self.assertEqual(app.history(),[])

    def test_segment_schema_limits_and_semantic_whitelist(self):
        good=replies.normalize_segments({'segments':[{'reply':'你好','emotion':'shy','action_tag':'../../file',
            'scene':'https://bad','voice_style':'shell','emotion_intensity':.7}]},[])[0]
        self.assertEqual(good['speech'],'你好');self.assertEqual(good['action_tag'],'idle')
        self.assertEqual(good['scene'],'');self.assertEqual(good['voice_style'],'normal');self.assertEqual(good['intensity'],.7)
        for value in ({'segments':[]},{'segments':[{}]},{'segments':[None]},
                      {'segments':[{'speech':'x'}]*7},{'segments':[{'speech':'x'*401}]},
                      {'segments':[{'speech':'x'*350}]*3},{'segments':'bad'}):
            with self.subTest(value=str(value)[:80]),self.assertRaises(ValueError):replies.normalize_segments(value,[])

    def test_cleared_history_cannot_revive_partial_turn(self):
        app.STATE['settings']['llm_mode']='demo'
        final=list(app.stream_chat('逐句表情','test_clear_reply'))[-1]['result']
        app.activate_reply(final['turn_id'],0)
        with app.connect_db() as db:db.execute('DELETE FROM messages')
        with self.assertRaisesRegex(ValueError,'清理'):app.activate_reply(final['turn_id'],1)
        self.assertEqual(app.history(),[])

    def test_real_loopback_sse_transport_with_segment_protocol(self):
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        payload={'segments':[{'speech':'真的吗？','emotion':'surprised'}, {'speech':'谢谢，我很开心。','emotion':'happy'}]}
        requests=[]
        class Service(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                raw=json.dumps(payload,ensure_ascii=False)
                packets=[{'choices':[{'delta':{'content':raw[i:i+5]}}]} for i in range(0,len(raw),5)]
                body=(''.join('data: '+json.dumps(item,ensure_ascii=False)+'\n\n' for item in packets)+'data: [DONE]\n').encode()
                self.send_response(200);self.send_header('Content-Type','text/event-stream')
                self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        server=ThreadingHTTPServer(('127.0.0.1',0),Service)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        app.STATE['settings']['llm_url']=f'http://127.0.0.1:{server.server_port}/v1'
        try:
            events=list(app.stream_chat('你好','test_real_sse'))
            previews=[item['text'] for item in events if item['type']=='text']
            self.assertEqual(previews[-1],'真的吗？')  # no full-reply preview followed by a rewind
            final=events[-1]['result'];self.assertEqual([x['emotion'] for x in final['segments']],['surprised','happy'])
            self.assertTrue(requests[0]['stream']);self.assertIn('segments',requests[0]['messages'][0]['content'])
            self.assertEqual(app.history(),[])
            app.activate_reply(final['turn_id'],0);app.activate_reply(final['turn_id'],1)
            self.assertEqual(app.history()[-1]['content'],'真的吗？\n谢谢，我很开心。')
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
