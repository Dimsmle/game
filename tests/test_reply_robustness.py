import json
import unittest
from studio import replies,behavior
from tests import test_emote as synthetic


class ReplyProtocolTests(unittest.TestCase):
    def test_narration_and_dialogue_kinds_are_validated(self):
        result=replies.normalize_segments({'segments':[{'speech':'风吹过海面。','kind':'narration','action_tag':'wave'},
                                                     {'speech':'（微笑）一起走走吧。'}]},[])
        self.assertEqual([x['kind'] for x in result],['narration','dialogue'])
        self.assertEqual(result[0]['action_tag'],'idle')
        history=replies.history_message({'role':'assistant','content':'【旁白】风吹过海面。\n你好。'})
        self.assertEqual([x['kind'] for x in json.loads(history['content'])['segments']],['narration','dialogue'])
        for kind in ('command','<script>',{},None):
            with self.subTest(kind=kind),self.assertRaises(ValueError):replies.normalize_segments({'segments':[{'speech':'test','kind':kind}]},[])

    def test_fences_complete_only(self):
        raw='{"segments":[{"speech":"你好"}]}'
        self.assertEqual(replies.parse_reply('```json\n'+raw+'\n```'),json.loads(raw))
        for invalid in ('{"speech":"unfinished','text '+raw,raw+' '+raw,'', 'just prose'):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):replies.parse_reply(invalid)

    def test_second_turn_context_keeps_json_protocol_and_read_prefix(self):
        row={'role':'assistant','content':'已读的第一句。'}
        value=replies.history_message(row)
        self.assertEqual(json.loads(value['content']),{'segments':[{'speech':row['content']}]})
        self.assertEqual(replies.history_message({'role':'user','content':'你好'})['content'],'你好')
        self.assertIn('每个 segments',behavior.llm_instructions([],segmented=True))


class OpacityTests(unittest.TestCase):
    def test_b_family_faces_are_not_motions(self):
        fixture=synthetic.RealSchemaSyntheticTest('test_file_discovery');fixture.setUp()
        try:
            model=fixture.m
            for preset in model.presets:preset['label']=preset['label'][:-1]+'Ｂ'
            catalog=model.expression_catalog()
            self.assertTrue(all(item['type']=='face' for item in catalog))
            self.assertEqual(behavior._choose_expression('happy',catalog,{}),'笑顔Ｂ')
            self.assertEqual(behavior._choose_expression('neutral',catalog,{}),'普通Ｂ')
        finally:fixture.tearDown()

    def test_hidden_parent_hides_child_and_reopening_restores_it(self):
        fixture=synthetic.RealSchemaSyntheticTest('test_file_discovery');fixture.setUp()
        try:
            model=fixture.m
            motion=model.objects['all_parts']['motion']['全体構造']
            parent=motion['layer'][0]
            parent['parameterize']=0
            parent['frameList']=[
                {'time':0,'content':{'mask':0,'coord':[100,200,0]}},
                {'time':20,'content':{'mask':1024,'opa':0}},
                {'time':41,'content':{'mask':0}}]
            self.assertEqual(len(model.build_pose(0,{'face_mouth':0})),1)
            self.assertEqual(model.build_pose(0,{'face_mouth':20}),[])
            self.assertEqual(model.build_pose(0,{'face_mouth':40}),[])
            self.assertEqual(len(model.build_pose(0,{'face_mouth':41})),1)
        finally:fixture.tearDown()


if __name__=='__main__':unittest.main()
