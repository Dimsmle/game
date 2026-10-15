import unittest
from studio.roleplay_plus import domain

class DomainTests(unittest.TestCase):
    def test_six_presets_are_valid(self):
        x=domain.builtin_presets()
        self.assertEqual(len(x),6)
        self.assertEqual({p["preset_id"] for p in x},set(domain.STYLES))
    def test_card_legacy_migration(self):
        c=domain.initial_card({"role_name":"千岁","persona":"旧人设：小心但主动"})
        self.assertEqual(c["name"],"千岁")
        self.assertIn("旧人设",c["description"])
        self.assertFalse(c["canon_verified"])
    def test_no_invalid_id(self):
        with self.assertRaises(ValueError):domain.ident("../secrets","bad")
        with self.assertRaises(ValueError):domain.ident("C:/foo","bad")
    def test_card_no_unknown_file_paths(self):
        c=domain.initial_card({"role_name":"角色"})
        self.assertEqual(set(c).intersection({"filesystem_path","api_key","command"}),set())
    def test_invalid_card_examples(self):
        c=domain.initial_card({})
        c["example_dialogues"]=[{"user":"hello","character":""}]
        with self.assertRaises(ValueError):domain.card(c)
    def test_bool_string_rejected(self):
        x={"persona_id":"player","name":"玩家","share_with_llm":"false"}
        with self.assertRaises(ValueError):domain.persona(x)
    def test_card_verified_must_be_bool(self):
        c=domain.initial_card({})
        c["canon_verified"]="false"
        with self.assertRaises(ValueError):domain.card(c)
    def test_state_rejects_floats_and_bool(self):
        s=domain.new_state()
        s["affection"]=True
        with self.assertRaises(ValueError):domain.validate_state(s)
        s["affection"]=3.5
        with self.assertRaises(ValueError):domain.validate_state(s)
    def test_state_range(self):
        s=domain.new_state();s["mood"]=-101
        with self.assertRaises(ValueError):domain.validate_state(s)
    def test_lore_rejects_unknown_condition(self):
        with self.assertRaises(ValueError):
            domain.lore({"entry_id":"abc","title":"X","content":"ABC",
                         "activation":"always","conditions":{"dangerous_command":"run"}})
    def test_lore_keyword_required(self):
        with self.assertRaises(ValueError):
            domain.lore({"entry_id":"abc","title":"X","content":"ABC",
                         "activation":"keyword","keywords":[]})
    def test_lore_valid(self):
        entry=domain.lore({"entry_id":"park","title":"公园","content":"景色",
                           "activation":"keyword","keywords":["公园"],
                           "conditions":{"affection_min":25,"location_any":["park"]}})
        self.assertEqual(entry["conditions"]["affection_min"],25)
    def test_preset_unknown_enum(self):
        item=domain.builtin_presets()[0]
        item["tone"]="run_python"
        with self.assertRaises(ValueError):domain.preset(item)

if __name__=="__main__":unittest.main()
