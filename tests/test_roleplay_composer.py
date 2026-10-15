import tempfile
from pathlib import Path
import unittest
from studio.roleplay_plus.store import RoleplayStore
from studio.roleplay_plus.composer import PromptComposer,select_lore,conditions_match,tokens_approx

class ComposerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store=RoleplayStore(Path(self.temp.name)/"data.sqlite3")
        self.store.initialize({"role_name":"千岁","persona":"旧版温柔人设"})
        self.composer=PromptComposer(max_addendum_tokens=2300,lore_budget=500)
    def add_lore(self,id_,content="世界设定",activation="keyword",keywords=None,conditions=None,**other):
        return self.store.save_lore("legacy_character",{
            "entry_id":id_,"title":id_,"content":content,
            "activation":activation,"keywords":keywords or [],
            "conditions":conditions or {},"enabled":True,**other},0)
    def test_bridge_removes_old_character_identity_conflicts(self):
        from studio.roleplay_plus import bridge
        bridge.initialize(self.store.path,{"role_name":"旧角色","persona":"旧数据"})
        settings={"role_name":"旧角色","persona":"旧数据","memory_enabled_for_llm":False}
        base="JSON 行为协议。你的名字：旧角色；性格：旧数据"
        text=bridge.extend_prompt(base,settings,"你好")
        self.assertIn("JSON 行为协议",text)
        self.assertNotIn("你的名字：旧角色；性格：旧数据",text)
        self.assertIn("千岁",text)
    def test_default_prompt_contains_role_style_state(self):
        result=self.composer.compose(self.store.snapshot(),"今天累了",base_prompt="请输出 JSON 格式")
        self.assertIn("千岁",result["prompt"])
        self.assertIn("沉浸 Galgame",result["prompt"])
        self.assertIn("当前游戏内地点",result["prompt"])
        self.assertIn("请输出 JSON 格式",result["prompt"])
    def test_preset_changes_actual_prompt(self):
        a=self.composer.compose(self.store.snapshot(),"你好")["prompt"]
        self.store.select(preset_id="literary")
        b=self.composer.compose(self.store.snapshot(),"你好")["prompt"]
        self.assertNotEqual(a,b)
        self.assertIn("剧情小说",b)
    def test_state_event_changes_prompt_values(self):
        before=self.composer.compose(self.store.snapshot(),"你好")["prompt"]
        offered=self.store.offer_event("share_hobby")
        self.store.choose_event(offered["instance_id"],"accept","k_stats")
        after=self.composer.compose(self.store.snapshot(),"你好")["prompt"]
        self.assertNotEqual(before,after)
        self.assertIn("好感度=26/100",after)

    def test_card_changes_prompt(self):
        before=self.composer.compose(self.store.snapshot(),"你好")["prompt"]
        card=self.store.get_card("legacy_character")
        card["data"]["speech_style"]="语气有一点俏皮，但说话很自然"
        self.store.save_card(card["data"],card["revision"])
        after=self.composer.compose(self.store.snapshot(),"你好")["prompt"]
        self.assertNotEqual(before,after)
        self.assertIn("俏皮",after)
    def test_keyword_match(self):
        self.add_lore("park",content="公园里可以看风景",keywords=["公园","散步"])
        data=self.composer.compose(self.store.snapshot(),"要不要去公园？")
        self.assertIn("公园里可以看风景",data["prompt"])
        self.assertEqual(data["trace"]["selected_lore_ids"],["park"])
    def test_no_keyword_match(self):
        self.add_lore("park",content="只应该在公园出现",keywords=["公园"])
        data=self.composer.compose(self.store.snapshot(),"今天读了一本书")
        self.assertNotIn("只应该在公园出现",data["prompt"])
        self.assertEqual(data["trace"]["selected_lore_ids"],[])
    def test_location_condition(self):
        self.add_lore("park",keywords=["公园"],conditions={"location_any":["park"]})
        chosen,trace,_=select_lore(self.store.snapshot()["lore"],
            self.store.game_state()["state"],"我们去公园吧")
        self.assertFalse(chosen)
        self.assertEqual(trace[0]["status"],"conditions")
    def test_affection_gate(self):
        self.add_lore("close",keywords=["喜欢"],conditions={"affection_min":70})
        data=self.composer.compose(self.store.snapshot(),"喜欢")
        self.assertEqual(data["trace"]["selected_lore_ids"],[])
    def test_verified_canon_only(self):
        self.add_lore("canon",activation="always",keywords=[],
                      fact_class="canon",verified=False)
        data=self.composer.compose(self.store.snapshot(),"你好")
        self.assertNotIn("canon：世界设定",data["prompt"])
        self.assertEqual(data["trace"]["lore"][0]["status"],"unverified_canon")
    def test_lore_budget_sorting(self):
        for n in range(15):
            self.add_lore("topic_"+str(n),content="场景描述"*100,
                keywords=["情景"],priority=(n*7)%101)
        data=self.composer.compose(self.store.snapshot(),"情景")
        self.assertLess(len(data["trace"]["selected_lore_ids"]),15)
        self.assertTrue(any(x["status"]=="budget" for x in data["trace"]["lore"]))
    def test_lore_no_memory_when_disabled(self):
        self.add_lore("private",activation="always",keywords=[],
                      fact_class="personal_memory",scope="player",
                      content="非常私密的用户资料")
        data=self.composer.compose(self.store.snapshot(),"你好",send_memories=False)
        self.assertNotIn("非常私密的用户资料",data["prompt"])
    def test_player_persona_opt_in(self):
        p={"persona_id":"writer","name":"小明","description":"只有打开分享才发送",
           "share_with_llm":False}
        self.store.save_persona(p,0)
        self.store.select(persona_id="writer")
        data=self.composer.compose(self.store.snapshot(),"你好")
        self.assertNotIn("只有打开分享才发送",data["prompt"])
        p["share_with_llm"]=True
        self.store.save_persona(p,1)
        data2=self.composer.compose(self.store.snapshot(),"你好")
        self.assertIn("只有打开分享才发送",data2["prompt"])
    def test_trace_does_not_contain_full_prompts(self):
        data=self.composer.compose(self.store.snapshot(),"我的账户密码是绝密111")
        self.assertNotIn("绝密111",str(data["trace"]))
        self.assertNotIn("DEEPSEEK_API_KEY",str(data["trace"]))
    def test_lore_keyword_in_read_history(self):
        self.add_lore("school",content="学校的故事",keywords=["学校"])
        history=[{"role":"user","content":"昨天我们聊学校"},{"role":"assistant","content":"嗯"}]
        data=self.composer.compose(self.store.snapshot(),"今天聊点别的",history=history)
        self.assertIn("学校的故事",data["prompt"])
    def test_invalid_conditions(self):
        state=self.store.game_state()["state"]
        self.assertFalse(conditions_match({"flags_all":["completed"]},state))
        self.assertTrue(conditions_match({"mood_min":-20},state))
    def test_token_estimate(self):
        self.assertGreater(tokens_approx("中文世界"),0)
        self.assertGreater(tokens_approx("ABCDEFG"),0)
    def test_no_unsupported_event_paths(self):
        data=self.composer.compose(self.store.snapshot(),"给我一个动画")
        self.assertNotIn("C:\\\\",data["prompt"])
        self.assertIn("只能由本地规则引擎提交",data["prompt"])

if __name__=="__main__":unittest.main()
