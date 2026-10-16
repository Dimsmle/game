"""Real app/SQLite contracts for v0.15. Only generated, synthetic test media."""
import json
from pathlib import Path
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from PIL import Image
from studio import app,llm,gameplay,gameplay_catalog,game_db
from tests import test_ai_providers as fixtures


class GameplayIntegration(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.PipelineTests('test_semantic_validation_and_atomic_history');self.fixture.setUp()
        self.root=app.DATA/'assets';(self.root/'bg').mkdir(parents=True)
        for i in range(1,4):Image.new('RGBA',(32,20),(i*60,80,100,255)).save(self.root/'bg'/f'bg{i:02}aa.png')
        Image.new('RGBA',(32,20),(0,180,80,255)).save(self.root/'cg.png')
        self.old_prepared=dict(gameplay._PREPARED);gameplay._PREPARED.clear();gameplay._TOUCH.reset()
        app.STATE['settings']['assets_dir']=str(self.root)
        self.cat=gameplay.Catalog(app.DB_FILE,self.root);self.cat.scan('locations');self.cat.scan('media')
        self.server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();gameplay._PREPARED.clear();gameplay._PREPARED.update(self.old_prepared);self.fixture.tearDown()
    def post(self,path,data):
        request=urllib.request.Request(self.url+path,json.dumps(data).encode(),{'Content-Type':'application/json','Origin':self.url})
        with urllib.request.urlopen(request,timeout=10) as r:return json.load(r)
    def get(self,path):
        with urllib.request.urlopen(self.url+path,timeout=10) as r:return json.load(r)
    def review_location(self,number=1):
        data=self.cat.get('locations');item=data['data']['families'][f'bg{number:02}'][0]
        self.cat.review('locations',dict(asset_id=item['asset_id'],file_hash=item['file_hash'],location_id=f'Loc_{number}',location_name=f'合成地点{number}',time_of_day='day',verified=True,allow_automatic=True,default=True),data['revision'])
        return item
    def enable(self):
        app.game_store().interaction_settings(gameplay.binding(app),{'proactive_events':True,'touch_interaction':True,'clock_mode':'manual'})
        with game_db.connect(app.DB_FILE) as db:
            for i in range(5):db.execute('INSERT INTO game_completed_turns VALUES(?,?,?,?)',(f'prime{i}','default','{}',0))
    def generate(self,event='take_break'):
        def service(provider,messages,cancel):
            self.captured=messages
            yield json.dumps({'segments':[{'speech':'先说第一句。','emotion':'neutral'},{'speech':'我们一起休息吗？','emotion':'gentle'}],
                'event_proposal':{'event_id':event,'presentation':'after_last_segment'}},ensure_ascii=False)
        with patch.object(llm.OpenAICompatibleProvider,'stream',service):return list(app.stream_chat('你好','gameplay_test_123'))[-1]['result']
    def finish(self,result):
        for i in range(len(result['segments'])):app.activate_reply(result['turn_id'],i)
        return self.post('/api/game/turn/complete',{'turn_id':result['turn_id'],'displayed':True,'tts_finished':True})['event']

    def test_scan_never_approves_and_no_public_paths(self):
        Image.new('RGB',(32,20),'gray').save(self.root/'bg'/'zbg01ab.jpg')
        self.cat.scan('locations')
        response=self.get('/api/game/catalog?kind=locations')
        self.assertEqual(response['count'],4);self.assertFalse(any(x['verified'] for x in response['items']))
        self.assertNotIn('relative_path',json.dumps(response));self.assertNotIn(str(self.root),json.dumps(response))
        self.assertEqual(self.get('/api/game/locations')['items'],[])

    def test_prepare_before_commit_and_hash_change_rolls_back(self):
        self.review_location();before=app.game_store().read()
        prepared=self.post('/api/game/scene/prepare',{'location_id':'Loc_1'})
        self.assertEqual(app.game_store().read(),before)
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/game/commit',{'prepare_token':prepared['prepare_token'],'loaded':False})
        Image.new('RGB',(32,20),'red').save(self.root/'bg'/'bg01aa.png')
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/game/commit',{'prepare_token':prepared['prepare_token'],'loaded':True})
        self.assertEqual(app.game_store().read(),before)

    def test_manual_scene_persists_and_reaches_lore_and_prompt(self):
        self.review_location();p=self.post('/api/game/scene/prepare',{'location_id':'Loc_1'})
        result=self.post('/api/game/commit',{'prepare_token':p['prepare_token'],'loaded':True})
        self.assertEqual(result['state']['scene']['location_id'],'Loc_1')
        self.assertEqual(app.game_store().read()['scene'],result['state']['scene'])
        app.roleplay_bridge.store().save_lore('legacy_character',{'entry_id':'place','title':'本地知识','content':'地点命中标记',
            'activation':'location','keywords':[],'conditions':{'location_any':['Loc_1']}},0)
        self.generate('unknown')
        self.assertIn('合成地点1',self.captured[0]['content']);self.assertIn('地点命中标记',self.captured[0]['content'])

    def test_final_ack_only_and_duplicate_ack_same_offer(self):
        self.enable();result=self.generate();self.assertTrue(result['event_pending'])
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/game/turn/complete',{'turn_id':result['turn_id'],'displayed':True,'tts_finished':True})
        app.activate_reply(result['turn_id'],0);app.activate_reply(result['turn_id'],1)
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/game/turn/complete',{'turn_id':result['turn_id'],'displayed':True,'tts_finished':False})
        body={'turn_id':result['turn_id'],'displayed':True,'tts_finished':True}
        first=self.post('/api/game/turn/complete',body);second=self.post('/api/game/turn/complete',body)
        self.assertEqual(first,second);self.assertEqual(len(app.history()),2)

    def test_bad_proposal_does_not_discard_plain_reply_or_write_stats(self):
        self.enable();state=app.game_store().read();result=self.generate('invented_event')
        self.assertFalse(result['event_pending']);self.assertIsNone(self.finish(result));self.assertEqual(app.game_store().read(),state)

    def test_cancel_unread_never_presents(self):
        self.enable();result=self.generate();app.activate_reply(result['turn_id'],0)
        self.post('/api/chat_turn_cancel',{'turn_id':result['turn_id']})
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/game/turn/complete',{'turn_id':result['turn_id'],'displayed':True,'tts_finished':True})
        self.assertIsNone(app.game_store().active_event());self.assertEqual(app.history()[-1]['content'],'先说第一句。')

    def test_choice_atomic_idempotent_and_player_diary(self):
        self.enable();event=self.finish(self.generate());before=app.game_store().read()
        p=self.post('/api/game/event/prepare',{'instance_id':event['instance_id'],'choice_id':'accept'})
        body={'prepare_token':p['prepare_token'],'loaded':True,'idempotency_key':'once'}
        first=self.post('/api/game/commit',body);second=self.post('/api/game/commit',body)
        self.assertEqual(first,second);self.assertEqual(first['state']['stats']['energy'],before['stats']['energy']+3)
        self.assertEqual(len(self.get('/api/game/diary')['items']),1)
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/game/commit',dict(body,idempotency_key='different'))

    def test_stale_profile_or_roleplay_epoch_cannot_choose(self):
        self.enable();event=self.finish(self.generate());p=self.post('/api/game/event/prepare',{'instance_id':event['instance_id'],'choice_id':'accept'})
        app.roleplay_bridge.store().select(preset_id='daily')
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/game/commit',{'prepare_token':p['prepare_token'],'loaded':True,'idempotency_key':'stale'})
        self.assertEqual(app.game_store().read()['stats']['energy'],80)

    def test_transaction_failure_does_not_partially_apply_choice(self):
        self.enable();event=self.finish(self.generate());before=app.game_store().read();b=gameplay.binding(app)
        with game_db.connect(app.DB_FILE) as db:db.execute("CREATE TRIGGER fail_gameplay BEFORE INSERT ON game_event_choices BEGIN SELECT RAISE(ABORT,'failure'); END")
        with self.assertRaises(Exception):app.game_store().choose_event(event['instance_id'],'accept','fail',b,lambda effect:{'scene':None,'media':None})
        self.assertEqual(app.game_store().read(),before);self.assertEqual(app.game_store().diary(),[])

    def test_decline_and_dismiss_have_no_stat_penalty(self):
        self.enable();event=self.finish(self.generate());stats=app.game_store().read()['stats']
        p=self.post('/api/game/event/prepare',{'instance_id':event['instance_id'],'choice_id':'decline'})
        self.post('/api/game/commit',{'prepare_token':p['prepare_token'],'loaded':True,'idempotency_key':'decline'})
        self.assertEqual(app.game_store().read()['stats'],stats)

    def test_media_locked_until_event_and_blocks_stage(self):
        media_doc=self.cat.get('media');item=next(x for x in media_doc['data']['assets'] if x['relative_path']=='cg.png')
        self.cat.review('media',dict(asset_id=item['asset_id'],file_hash=item['file_hash'],category='cg_still',title='合成测试CG',safe_for_auto=True,verified=True),media_doc['revision'])
        self.assertEqual(self.get('/api/game/gallery')['items'],[])
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/game/media/begin',{'asset_id':item['asset_id']})
        rules=self.cat.get('events');rules['data'][0]['choices'][0]['effect']['media_id']=item['asset_id'];self.cat.save_events(rules['data'],rules['revision'])
        self.enable();event=self.finish(self.generate());p=self.post('/api/game/event/prepare',{'instance_id':event['instance_id'],'choice_id':'accept'})
        result=self.post('/api/game/commit',{'prepare_token':p['prepare_token'],'loaded':True,'idempotency_key':'media'})
        self.assertTrue(gameplay.busy(app));self.assertEqual(len(self.get('/api/game/gallery')['items']),1)
        self.post('/api/game/media/end',{'token':result['media']['playback_token']});self.assertFalse(gameplay.busy(app))

    def test_same_choice_concurrent_calls_only_one_journal_and_gain(self):
        self.enable();event=self.finish(self.generate());b=gameplay.binding(app)
        def choose(_):return app.game_store().choose_event(event['instance_id'],'accept','concurrent',b,lambda effect:{'scene':None,'media':None})
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(choose,range(8)))
        self.assertTrue(all(x==results[0] for x in results));self.assertEqual(len(app.game_store().diary()),1)
        self.assertEqual(app.game_store().read()['stats']['energy'],83)

    def test_touch_checked_model_alpha_cooldown_and_no_stat_gain(self):
        self.enable();pose=self.root/'pose.png';Image.new('RGBA',(740,1250),(100,100,100,255)).save(pose)
        app.STATE['settings']['character_model']='test_10';app.STATE['manifest']['poses']={'neutral':'pose.png'}
        signature=gameplay.touch_signature(app)
        profile={k:signature[k] for k in ('profile_id','model_id','pose_id','outfit_id')}
        profile.update(verified=True,regions=[{'name':'head','polygon':[[.2,.1],[.8,.1],[.8,.4],[.2,.4]],'z':1,'enabled':True}])
        self.cat.save_hitbox(profile,self.cat.get('touch')['revision'],signature);before=app.game_store().read()
        value=self.post('/api/game/touch',{'request_id':'touch1','gesture':'tap','x':.5,'y':.2,'region':'hand'})
        self.assertEqual(value['region'],'head');self.assertNotIn('x',value)
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/game/touch',{'request_id':'touch2','gesture':'tap','x':.5,'y':.2})
        self.assertEqual(app.game_store().read(),before)
        app.STATE['settings']['character_model']='other_10'
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/game/touch',{'request_id':'touch3','gesture':'tap','x':.5,'y':.2})

    def test_catalog_reinitialization_preserves_private_rows_and_backup(self):
        app.add_history('user','private test content','user');app.add_memory('private memory')
        messages=app.history();memories=app.memories()
        gameplay_catalog.initialize(app.DB_FILE)
        self.assertEqual(app.history(),messages);self.assertEqual(app.memories(),memories)
        self.assertTrue(list((app.DB_FILE.parent/'backups').glob('*.sqlite3')))

    def test_scene_binding_expires_on_profile_aba(self):
        self.review_location();p=self.post('/api/game/scene/prepare',{'location_id':'Loc_1'})
        app.game_store().create('second','second');app.select_game_profile('second');app.select_game_profile('default')
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/game/commit',{'prepare_token':p['prepare_token'],'loaded':True})
        self.assertEqual(app.game_store().read()['scene']['location_id'],'unknown')

    def test_stale_cancel_token_cannot_dismiss_current_invitation(self):
        self.enable();result=self.generate();event=self.finish(result)
        self.post('/api/chat_turn_cancel',{'turn_id':'old_token_123'})
        self.assertEqual(app.game_store().active_event()['instance_id'],event['instance_id'])
        self.post('/api/game/event/dismiss',{'instance_id':'old_instance_123'})
        self.assertIsNotNone(app.game_store().active_event())
        self.post('/api/game/event/dismiss',{'instance_id':event['instance_id']})
        self.assertIsNone(app.game_store().active_event())

    def test_game_clock_only_switches_reviewed_variant_after_unlock(self):
        self.review_location()
        Image.new('RGB',(32,20),'navy').save(self.root/'bg'/'bg01ab.png');self.cat.scan('locations')
        doc=self.cat.get('locations');night=next(x for x in doc['data']['families']['bg01'] if x['suffix']=='ab')
        self.cat.review('locations',dict(asset_id=night['asset_id'],file_hash=night['file_hash'],location_id='Loc_1',location_name='合成地点1',time_of_day='night',verified=True,allow_automatic=True,default=False),doc['revision'])
        p=self.post('/api/game/scene/prepare',{'location_id':'Loc_1','time_of_day':'day'})
        self.post('/api/game/commit',{'prepare_token':p['prepare_token'],'loaded':True})
        app.game_store().interaction_settings(gameplay.binding(app),{'proactive_events':False,'touch_interaction':False,'clock_mode':'game','game_hour':23})
        self.assertIsNone(self.post('/api/game/scene/auto',{})['prepared'])
        self.post('/api/game/scene/unlock',{})
        p=self.post('/api/game/scene/auto',{})['prepared'];self.assertEqual(p['scene']['time_of_day'],'night')
        result=self.post('/api/game/commit',{'prepare_token':p['prepare_token'],'loaded':True})
        self.assertEqual(result['state']['scene']['time_of_day'],'night');self.assertFalse(result['state']['scene']['lock'])

    def test_event_target_scene_and_fact_reach_next_model_request(self):
        self.review_location();rules=self.cat.get('events');rules['data'][0]['choices'][0]['effect']['location_id']='Loc_1'
        self.cat.save_events(rules['data'],rules['revision']);self.enable()
        event=self.finish(self.generate());p=self.post('/api/game/event/prepare',{'instance_id':event['instance_id'],'choice_id':'accept'})
        outcome=self.post('/api/game/commit',{'prepare_token':p['prepare_token'],'loaded':True,'idempotency_key':'scene_event'})
        self.assertEqual(outcome['state']['scene']['location_id'],'Loc_1')
        self.assertEqual(outcome['scene']['location_name'],'合成地点1')
        self.generate('unknown')
        self.assertIn('Loc_1',self.captured[0]['content']);self.assertIn('take_break',self.captured[0]['content'])

    def test_media_review_keeps_character_restriction_after_rescan(self):
        doc=self.cat.get('media');item=next(x for x in doc['data']['assets'] if x['relative_path']=='cg.png')
        self.cat.review('media',dict(asset_id=item['asset_id'],file_hash=item['file_hash'],category='cg_still',title='只给原角色',safe_for_auto=True,verified=True,character_ids=['legacy_character']),doc['revision'])
        self.cat.scan('media');self.assertTrue(gameplay.media_fits(app,item['asset_id']))
        card=app.roleplay_bridge.store().get_card('legacy_character')['data'];card.update(card_id='new_card',name='另一个角色')
        app.roleplay_bridge.store().save_card(card,0);app.roleplay_bridge.store().select(card_id='new_card')
        self.assertFalse(gameplay.media_fits(app,item['asset_id']))

    def import_test_cg(self):
        from tests.test_cg_sequence import make_group
        make_group(self.root)
        result=self.post('/api/game/catalog/cg',{'group':'ev_shi_c04','revision':self.cat.get('media')['revision']})
        return next(x for x in self.cat.get('media')['data']['assets'] if x.get('extension')=='.cgseq')

    def test_cg_preview_has_no_story_unlock_or_stat_effects(self):
        item=self.import_test_cg();before=app.game_store().read()
        public=self.get('/api/game/catalog?kind=media');entry=next(x for x in public['items'] if x['asset_id']==item['asset_id'])
        self.assertFalse(entry['verified']);self.assertNotIn('relative_path',str(entry))
        sequence=self.get(entry['sequence_url']);self.assertEqual(len(sequence['steps']),2)
        with urllib.request.urlopen(self.url+sequence['frames'][1]['url']) as response:self.assertEqual(response.headers['Content-Type'],'image/png')
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/game/cg/preview',{'asset_id':item['asset_id'],'confirm':False,'binding':gameplay.binding(app)})
        lease=self.post('/api/game/cg/preview',{'asset_id':item['asset_id'],'confirm':True,'binding':gameplay.binding(app)})
        self.assertTrue(lease['preview_only']);self.assertTrue(gameplay.busy(app));self.assertEqual(app.game_store().read(),before)
        self.assertEqual(self.get('/api/game/gallery')['items'],[]);self.assertEqual(app.game_store().diary(),[])
        self.post('/api/game/media/end',{'token':lease['media']['playback_token']});self.assertFalse(gameplay.busy(app))

    def test_cg_event_uses_existing_choice_transaction_after_review(self):
        item=self.import_test_cg();rules=self.cat.get('events');rules['data'][0]['choices'][0]['effect']['media_id']=item['asset_id']
        with self.assertRaises(ValueError):self.cat.save_events(rules['data'],rules['revision'])
        self.cat.review('media',dict(asset_id=item['asset_id'],file_hash=item['file_hash'],category='cg_sequence',title='合成测试演出',safe_for_auto=True,verified=True),self.cat.get('media')['revision'])
        self.cat.scan('media');self.cat.save_events(rules['data'],rules['revision']);self.enable()
        event=self.finish(self.generate());p=self.post('/api/game/event/prepare',{'instance_id':event['instance_id'],'choice_id':'accept'})
        self.assertEqual(p['media']['category'],'cg_sequence')
        self.assertEqual(self.get('/api/game/gallery')['items'],[])
        result=self.post('/api/game/commit',{'prepare_token':p['prepare_token'],'loaded':True,'idempotency_key':'cg_choice'})
        self.assertEqual(result['media']['category'],'cg_sequence');self.assertTrue(gameplay.busy(app));self.assertEqual(len(app.game_store().diary()),1)
        self.assertEqual(len(self.get('/api/game/gallery')['items']),1)
        self.post('/api/game/media/end',{'token':result['media']['playback_token']})

    def test_cg_changes_and_profile_aba_reject_old_preview(self):
        item=self.import_test_cg();binding=gameplay.binding(app)
        app.game_store().create('cg_other','second');app.select_game_profile('cg_other');app.select_game_profile('default')
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/game/cg/preview',{'asset_id':item['asset_id'],'confirm':True,'binding':binding})
        from studio import cg_sequence
        doc=cg_sequence.load(self.root,item);(self.root/doc['frames'][0]['relative_path']).write_bytes(b'changed')
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/game/cg/preview',{'asset_id':item['asset_id'],'confirm':True,'binding':gameplay.binding(app)})
        self.assertFalse(gameplay.busy(app))

    def test_cg_reimport_preserves_only_unchanged_approval(self):
        item=self.import_test_cg()
        self.cat.review('media',dict(asset_id=item['asset_id'],file_hash=item['file_hash'],category='cg_sequence',title='合成CG',verified=True),self.cat.get('media')['revision'])
        self.cat.import_cg('ev_shi_c04',self.cat.get('media')['revision'])
        self.assertTrue(self.cat.item('media',item['asset_id'])['verified'])
        Image.new('RGB',(8,6),'green').save(self.root/'assets_pfs_003/image/ev/ev_shi_c04/ev_shi_c04_01.png')
        self.cat.import_cg('ev_shi_c04',self.cat.get('media')['revision'])
        rows=[x for x in self.cat.get('media')['data']['assets'] if x.get('extension')=='.cgseq']
        self.assertEqual(len(rows),1);self.assertNotEqual(rows[0]['asset_id'],item['asset_id']);self.assertFalse(rows[0]['verified'])

    def cg_scene(self):
        from studio import cg_events
        self.import_test_cg();self.review_location()
        app.STATE['settings']['character_model']='shi_15'
        rules=cg_events.validate_rules([dict(cg_events.DEFAULT[0],scenes=['Loc_1'],keywords=['海边','玩水','散步'],min_affection=0)])
        self.cat._save('cg_rules',rules,self.cat.get('cg_rules')['revision'])
        p=self.post('/api/game/scene/prepare',{'location_id':'Loc_1','time_of_day':'day'})
        self.post('/api/game/commit',{'prepare_token':p['prepare_token'],'loaded':True})

    def cg_reply(self,action='enter',event_id='shi_beach'):
        def service(provider,messages,cancel):
            self.captured=messages
            yield json.dumps({'segments':[{'speech':'我们在海边聊一会儿。','emotion':'gentle'}],
                              'cg_event':{'action':action,'event_id':event_id}},ensure_ascii=False)
        with patch.object(llm.OpenAICompatibleProvider,'stream',service):
            result=list(app.stream_chat('开始吧','cg_mock_'+action))[-1]['result']
        app.activate_reply(result['turn_id'],0)
        return result

    def test_dialogue_cg_needs_no_approval_choice_or_stat_effect(self):
        from studio import cg_events
        self.cg_scene();before=app.game_store().read()
        self.assertFalse(next(x for x in self.cat.get('media')['data']['assets'] if x.get('extension')=='.cgseq')['verified'])
        reply=self.cg_reply();command=self.post('/api/game/turn/complete',{'turn_id':reply['turn_id'],'displayed':True,'tts_finished':True})
        self.assertIsNone(command['event']);self.assertEqual(command['cg_action']['action'],'enter')
        prepared=self.post('/api/game/cg/prepare',{'turn_id':reply['turn_id']});self.assertEqual(prepared['media']['category'],'cg_sequence')
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/game/cg/apply',{'turn_id':reply['turn_id'],'loaded':False})
        body={'turn_id':reply['turn_id'],'loaded':True};first=self.post('/api/game/cg/apply',body);self.assertEqual(first,self.post('/api/game/cg/apply',body))
        self.assertTrue(cg_events.active(app)['loop']);self.assertEqual(app.game_store().read(),before)
        self.assertEqual(app.game_store().diary(),[])
        self.assertIn('玩水',self.captured[0]['content'])

    def test_cg_dialogue_can_continue_and_exit_without_choice(self):
        from studio import cg_events
        self.cg_scene();reply=self.cg_reply();self.post('/api/game/turn/complete',{'turn_id':reply['turn_id'],'displayed':True,'tts_finished':True})
        self.post('/api/game/cg/apply',{'turn_id':reply['turn_id'],'loaded':True})
        self.assertTrue(gameplay.busy(app))
        reply=self.cg_reply('exit');self.assertIn('"active": {"event_id": "shi_beach"',self.captured[0]['content'])
        command=self.post('/api/game/turn/complete',{'turn_id':reply['turn_id'],'displayed':True,'tts_finished':True})
        self.assertEqual(command['cg_action']['action'],'exit')
        self.post('/api/game/cg/apply',{'turn_id':reply['turn_id'],'loaded':True});self.assertIsNone(cg_events.active(app));self.assertFalse(gameplay.busy(app))

    def test_cg_invalid_scene_character_ids_or_effects_are_ignored(self):
        from studio import cg_events
        self.cg_scene();app.STATE['settings']['character_model']='kan_10'
        self.assertEqual(cg_events.candidates(app),[]);reply=self.cg_reply();self.assertIsNone(app.REPLY_TURN.current['cg_decision'])
        app.STATE['settings']['character_model']='shi_15';reply=self.cg_reply(event_id='arbitrary')
        self.assertIsNone(app.REPLY_TURN.current['cg_decision'])
        self.assertIsNone(cg_events.decision({'action':'enter','event_id':'shi_beach','stats':{'trust':5}},cg_events.candidates(app),None))
        app.game_store().move_location(gameplay.binding(app),'unknown','unknown');self.assertEqual(cg_events.candidates(app),[])

    def test_cg_unread_cancel_aba_and_cache_changes_cannot_enter(self):
        from studio import cg_events
        self.cg_scene();reply=self.cg_reply()
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/game/cg/apply',{'turn_id':reply['turn_id'],'loaded':True})
        self.post('/api/game/turn/complete',{'turn_id':reply['turn_id'],'displayed':True,'tts_finished':True})
        app.game_store().create('cg_aba','second');app.select_game_profile('cg_aba');app.select_game_profile('default')
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/game/cg/apply',{'turn_id':reply['turn_id'],'loaded':True})
        self.assertIsNone(cg_events.active(app))

    def test_bg05_mapping_both_variants_no_other_family_guesses(self):
        from studio import cg_events
        self.import_test_cg();folder=self.root/'assets_pfs_002/image/bg';folder.mkdir(parents=True)
        for suffix in ('aa','ab'):Image.new('RGB',(32,20),'blue').save(folder/('bg05'+suffix+'.png'))
        cg_events.setup_beach(app);doc=self.cat.get('locations')['data'];family=doc['families']['bg05']
        app.game_store().edit_stats(gameplay.binding(app),dict(app.game_store().read()['stats'],affection=50))
        self.assertEqual({x['location_name'] for x in family},{'海边'})
        self.assertEqual({x['suffix']:x['time_of_day'] for x in family},{'aa':'morning','ab':'unknown'})
        self.assertFalse(doc['families']['bg02'][0]['verified'])
        app.STATE['settings']['character_model']='shi_15'
        for period in ('morning','unknown'):
            prepared=self.post('/api/game/scene/prepare',{'location_id':'bg05','time_of_day':period})
            self.post('/api/game/commit',{'prepare_token':prepared['prepare_token'],'loaded':True})
            self.assertTrue(cg_events.candidates(app))

    def test_shi_drafts_all_groups_preserve_user_rules_and_idempotent_scan(self):
        from studio import cg_events
        self.import_test_cg()
        for group in ('ev_shi_c08','ev_shi_h19'):
            path=self.root/'assets_pfs_003/image/ev'/group;path.mkdir()
            for i in range(51 if group.endswith('c08') else 1):Image.new('RGB',(8,6),'gray').save(path/f'{group}_{i:02}.png')
        old=self.cat.get('cg_rules');rules=old['data'];rules[0]['keywords']=['自定义'];self.cat._save('cg_rules',rules,old['revision'])
        self.post('/api/game/catalog/cg_shi',{})
        doc=self.cat.get('cg_rules');self.assertEqual(len(doc['data']),3)
        self.assertEqual(doc['data'][0]['keywords'],['自定义'])
        for row in doc['data'][1:]:self.assertFalse(row['enabled']);self.assertEqual(row['title'],'');self.assertEqual(row['scenes'],[])
        self.post('/api/game/catalog/cg_shi',{});self.assertEqual(self.cat.get('cg_rules'),doc)
        invalid=dict(doc['data'][1],enabled=True)
        with self.assertRaises(ValueError):cg_events.validate_rules([invalid])

    def test_keyword_and_affection_force_even_when_model_returns_null(self):
        self.cg_scene()
        def service(provider,messages,cancel):
            self.captured=messages
            yield json.dumps({'segments':[{'speech':'我明白了。'}],'cg_event':None})
        with patch.object(llm.OpenAICompatibleProvider,'stream',service):result=list(app.stream_chat('海边','diagnose_cg'))[-1]['result']
        diagnostic=result['cg_diagnostic'];self.assertEqual(diagnostic['status'],'accepted')
        self.assertEqual(diagnostic['keyword_matched_ids'],['shi_beach'])
        self.assertEqual(app.REPLY_TURN.current['cg_decision'],{'action':'enter','event_id':'shi_beach'})
        self.assertIn('不能只在台词中答应却遗漏cg_event',self.captured[0]['content'])
        self.assertNotIn('海边',json.dumps(diagnostic,ensure_ascii=False))

    def test_narration_prefix_only_history_and_no_runtime_action(self):
        def service(provider,messages,cancel):
            yield json.dumps({'segments':[{'kind':'narration','speech':'风吹过海面。'},{'speech':'（微笑）你好。'}]})
        with patch.object(llm.OpenAICompatibleProvider,'stream',service):result=list(app.stream_chat('你好','narrative_turn'))[-1]['result']
        with patch.object(app.RUNTIME,'submit_plan',wraps=app.RUNTIME.submit_plan) as submit:
            value=app.activate_reply(result['turn_id'],0)
            self.assertEqual(value['kind'],'narration');submit.assert_not_called()
        self.assertEqual(app.history()[-1]['content'],'【旁白】风吹过海面。')
        self.assertNotIn('微笑',app.history()[-1]['content'])
        app.activate_reply(result['turn_id'],1);self.assertIn('（微笑）你好。',app.history()[-1]['content'])

    def test_stats_editor_is_profile_bound_strict_and_not_ai_reward(self):
        old=gameplay.binding(app);state=self.post('/api/game/stats',{'binding':old,'stats':dict(app.game_store().read()['stats'],affection=85),'confirm':True})['state']
        self.assertEqual(state['stats']['affection'],85)
        self.assertTrue(list((app.DB_FILE.parent/'backups').glob('*.sqlite3')))
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/game/stats',{'binding':old,'stats':state['stats'],'confirm':True})
        for bad in (True,101,1.5):
            with self.assertRaises(urllib.error.HTTPError):self.post('/api/game/stats',{'binding':gameplay.binding(app),'stats':dict(state['stats'],affection=bad),'confirm':True})
        app.game_store().create('another_stats','Other');app.select_game_profile('another_stats')
        self.assertEqual(app.game_store().read()['stats']['affection'],25)
        with game_db.connect(app.DB_FILE) as db:self.assertEqual(db.execute("SELECT count(*) FROM game_journal WHERE kind='manual_stats'").fetchone()[0],1)

    def test_keyword_threshold_boundary_and_null_model_still_enters(self):
        from studio import cg_events
        self.cg_scene();doc=self.cat.get('cg_rules');row=dict(doc['data'][0],min_affection=50);self.cat._save('cg_rules',[row],doc['revision'])
        for affection,allowed in ((49,False),(50,True),(51,True)):
            app.game_store().edit_stats(gameplay.binding(app),dict(app.game_store().read()['stats'],affection=affection))
            self.assertEqual(bool(cg_events.keyword_decision(app,'海边',cg_events.candidates(app))),allowed)
        with self.assertRaises(ValueError):cg_events.validate_rules([dict(row,min_affection=True)])

    def test_user_scene_table_labels_zbg_times_and_reimport_preserves_edits(self):
        from studio import scene_labels
        folder=self.root/'assets_pfs_002/image/bg';folder.mkdir(parents=True)
        for name in ('bg05aa','bg05ab','bg05ba','bg05ac','bg05ad','bg05af','zbg25ac','bg99aa'):
            Image.new('RGB',(32,20),'blue').save(folder/(name+'.png'))
        self.assertTrue(scene_labels.install(app));doc=self.cat.get('locations');family=doc['data']['families']['bg05']
        self.assertEqual({x['location_name'] for x in family},{'海边'})
        self.assertEqual({x['suffix']:x['time_of_day'] for x in family},{'aa':'morning','ab':'day','ba':'morning','ac':'evening','ad':'night','af':'unknown'})
        self.assertEqual(len(scene_labels.NAMES),40);self.assertTrue(all(len(x)<=4 for x in scene_labels.NAMES.values()))
        self.assertTrue(doc['data']['families']['bg25'][0]['verified'])
        self.assertIsNone(scene_labels.proposal(app,{'location_id':'bg99'}))
        family[0]['location_name']='自定';self.cat._save('locations',doc['data'],doc['revision']);self.assertFalse(scene_labels.install(app))
        self.assertEqual(self.cat.get('locations')['data']['families']['bg05'][0]['location_name'],'自定')

    def test_fixed_time_survives_scene_fallback_and_travel_choice(self):
        self.review_location(1);self.review_location(2)
        prepared=self.post('/api/game/scene/prepare',{'location_id':'Loc_1','time_of_day':'night'})
        result=self.post('/api/game/commit',{'prepare_token':prepared['prepare_token'],'loaded':True})
        self.assertEqual(result['state']['scene']['time_of_day'],'night')
        prepared=self.post('/api/game/scene/prepare',{'location_id':'Loc_2'})
        result=self.post('/api/game/commit',{'prepare_token':prepared['prepare_token'],'loaded':True})
        self.assertEqual(result['state']['scene']['time_of_day'],'night')
        def service(provider,messages,cancel):
            self.captured=messages
            yield json.dumps({'segments':[{'speech':'我们去另一个地方吧。'}],'scene_proposal':{'location_id':'Loc_1'}})
        with patch.object(llm.OpenAICompatibleProvider,'stream',service):reply=list(app.stream_chat('去合成地点1','travel_test'))[-1]['result']
        self.assertTrue(reply['event_pending']);app.activate_reply(reply['turn_id'],0)
        offer=self.post('/api/game/turn/complete',{'turn_id':reply['turn_id'],'displayed':True,'tts_finished':True})['event']
        self.assertEqual(app.game_store().read()['scene']['location_id'],'Loc_2')
        prepared=self.post('/api/game/event/prepare',{'instance_id':offer['instance_id'],'choice_id':'accept'})
        result=self.post('/api/game/commit',{'prepare_token':prepared['prepare_token'],'loaded':True,'idempotency_key':'travel_test_choice'})
        self.assertEqual(result['state']['scene']['location_id'],'Loc_1');self.assertEqual(result['state']['scene']['time_of_day'],'night')

    def test_wardrobe_preview_uses_cached_png_and_rejects_paths(self):
        import main_desktop
        original=self.server.RequestHandlerClass
        self.server.RequestHandlerClass=main_desktop.StudioHandler;self.server.asset_root=self.root
        folder=self.root/'character_exports';folder.mkdir(exist_ok=True);Image.new('RGBA',(740,1250),'blue').save(folder/'shi_37_neutral.png')
        try:
            with urllib.request.urlopen(self.url+'/api/model_preview/shi_37') as response:
                from io import BytesIO
                with Image.open(BytesIO(response.read())) as im:self.assertLessEqual(im.width,190);self.assertLessEqual(im.height,320)
            with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(self.url+'/api/model_preview/..%2Fsecret')
        finally:self.server.RequestHandlerClass=original

    def test_empty_scenes_unrestricted_and_legacy_flag_cannot_override_scenes(self):
        from studio import cg_events
        self.cg_scene();doc=self.cat.get('cg_rules');row=dict(doc['data'][0],scenes=[],any_location=True)
        self.cat._save('cg_rules',cg_events.validate_rules([row]),doc['revision'])
        app.game_store().move_location(gameplay.binding(app),'unknown','morning')
        self.assertTrue(cg_events.keyword_decision(app,'海边',cg_events.candidates(app)))
        clean=cg_events.validate_rules([dict(row,any_location=False)])
        self.assertNotIn('any_location',clean[0])
        limited=dict(row,scenes=['bg05'],any_location=True)
        current=self.cat.get('cg_rules')
        self.cat._save('cg_rules',[limited],current['revision'])
        self.assertEqual(cg_events.candidates(app),[])
        current=self.cat.get('cg_rules')
        self.cat._save('cg_rules',clean,current['revision'])
        app.STATE['settings']['character_model']='kan_10';self.assertEqual(cg_events.candidates(app),[])
        with self.assertRaises(ValueError):cg_events.validate_rules([dict(row,any_location='true')])

    def test_current_clothing_reaches_actual_prompt_and_edit_invalidates_old_turn(self):
        app.STATE['settings']['character_model']='shi_37'
        def service(provider,messages,cancel):
            self.captured=messages
            yield json.dumps({'segments':[{'speech':'我们聊聊吧。'}]})
        self.post('/api/model_metadata',{'model':'shi_37','expected_current':True,'record':{'outfit_name':'测试浴衣'}})
        with patch.object(llm.OpenAICompatibleProvider,'stream',service):reply=list(app.stream_chat('你穿什么','appearance_test'))[-1]['result']
        prompt=self.captured[0]['content'];self.assertIn('测试浴衣',prompt);self.assertIn('姿势B',prompt)
        self.assertNotIn(str(self.root),prompt)
        self.post('/api/model_metadata',{'model':'shi_37','expected_current':True,'record':{'outfit_name':'测试校服'}})
        with self.assertRaises(ValueError):app.activate_reply(reply['turn_id'],0)
        app.STATE['settings']['character_model']='shi_15'
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/model_metadata',{'model':'shi_37','expected_current':True,'record':{'outfit_name':'旧造型'}})


if __name__=='__main__':unittest.main()
