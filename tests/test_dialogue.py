import unittest

from studio import behavior,dialogue


class DialogueSceneTests(unittest.TestCase):
    def setUp(self):
        labels=list(dict.fromkeys(label for group in behavior.EMOTION_TO_PRESETS.values() for label in group))
        self.catalog=[{"label":label,"type":"face","index":i} for i,label in enumerate(labels)]

    def test_every_scene_branch_terminates_and_each_sentence_has_a_real_expression(self):
        expressions=set()
        for summary in dialogue.summaries():
            scene=dialogue.compile_scene(summary["id"],"kan_10",self.catalog,behavior.default_library())
            self.assertTrue(scene["silent"])
            nodes={node["id"]:node for node in scene["nodes"]}
            visited=set()
            def visit(id,path):
                self.assertNotIn(id,path,"dialogue must not loop without explicit restart")
                visited.add(id);node=nodes[id]
                plan=node["behavior"]
                self.assertEqual(plan["emotion"],node["emotion"])
                self.assertIsNone(plan["motion"])
                self.assertIsNotNone(plan["expression"])
                expressions.add(plan["expression"]["label"])
                targets=[node.get("next")]+[item["next"] for item in node.get("choices",[])]
                for target in filter(None,targets):visit(target,path|{id})
            visit(scene["start"],set())
            self.assertEqual(visited,set(nodes))
        self.assertGreaterEqual(len(expressions),10)

    def test_unknown_scene_and_missing_character_are_rejected(self):
        with self.assertRaises(ValueError):dialogue.compile_scene("../../file","kan_10",self.catalog,{})
        with self.assertRaises(ValueError):dialogue.compile_scene("promise","kan_10",[],{})

    def test_compilation_does_not_mutate_script_or_bypass_custom_mapping(self):
        custom={"version":1,"models":{"kan_10":{"expression_map":{"happy":"微笑みＡ"}}}}
        scene=dialogue.compile_scene("promise","kan_10",self.catalog,custom)
        last=next(node for node in scene["nodes"] if node["id"]=="end")
        self.assertEqual(last["behavior"]["expression"]["label"],"微笑みＡ")
        self.assertNotIn("behavior",dialogue.SCENES[0]["nodes"][0])


if __name__=="__main__":unittest.main()
