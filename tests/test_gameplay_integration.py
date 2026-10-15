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


if __name__=='__main__':unittest.main()
