"""Additional v0.14.1 P1/current-credentials and bounded-prompt regressions."""
import tempfile
import unittest
import importlib.util
from pathlib import Path

from studio.roleplay_plus import domain,bridge
from studio.roleplay_plus.store import RoleplayStore
from studio.roleplay_plus.composer import PromptComposer,tokens_approx

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("install_addon_current",ROOT/"tools/install_addon.py")
installer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class LatestRepositoryCompat(unittest.TestCase):
    def test_main_profile_ids_may_start_with_digits_or_uppercase(self):
        self.assertEqual(domain.profile_ident("2Q-Test"),"2Q-Test")
        with tempfile.TemporaryDirectory() as folder:
            store=RoleplayStore(Path(folder)/"test.sqlite3")
            store.initialize({"role_name":"千岁","persona":"旧人设"})
            binding=store.ensure_profile("2Q-Test")
            self.assertEqual(binding["profile_id"],"2Q-Test")
            self.assertEqual(store.binding("2Q-Test")["preset_id"],"immersive_galgame")
        with self.assertRaises(ValueError):
            domain.ident("2Q-Test","角色卡 ID")

    def test_native_credentials_not_shadowed_by_env_loader(self):
        from test_roleplay_p1_authority import P1InstallerTests
        source=P1InstallerTests.fake_current_source()
        native=installer.patch_app(source,native_credentials=True)
        self.assertIn('from studio.roleplay_plus import bridge as roleplay_bridge',native)
        self.assertNotIn("load_project_env(",native)
        self.assertIn("use_existing_game_state=True",native)
        old=installer.patch_app(source,native_credentials=False)
        self.assertIn("load_project_env(",old)

    def test_installer_auto_detects_native_credentials(self):
        from test_roleplay_p1_authority import P1InstallerTests
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/"studio").mkdir()
            (root/"studio/__init__.py").write_text("",encoding="utf-8")
            (root/"studio/credentials.py").write_text("def get_api_key(name): return ''\n",encoding="utf-8")
            (root/"studio/app.py").write_text(P1InstallerTests.fake_current_source(),encoding="utf-8")
            original,changed,copy,html=installer.plans(root)
            self.assertIn('use_existing_game_state=True',changed)
            self.assertNotIn('load_project_env(',changed)
            self.assertNotEqual(original,changed)
            self.assertGreater(len(copy),0)

    def test_generation_aba_switch_rejected(self):
        from test_roleplay_p1_authority import FakeGameStore
        with tempfile.TemporaryDirectory() as folder:
            previous=bridge._MAIN_GAME
            try:
                bridge.initialize(Path(folder)/"history.sqlite3",{"role_name":"千岁","persona":"测试"})
                bridge._MAIN_GAME=FakeGameStore()
                with self.assertRaisesRegex(RuntimeError,"切换"):
                    bridge.extend_prompt("JSON 协议",{
                        "_game_session":{"profile_id":"secondary","generation":2}
                    },"你好")
            finally:
                bridge._MAIN_GAME=previous


class RobustPromptBudget(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store=RoleplayStore(Path(self.temp.name)/"history.sqlite3")
        self.store.initialize({"role_name":"千岁","persona":"原始人设"})

    def test_very_long_core_does_not_hide_state_or_preset(self):
        card=self.store.get_card("legacy_character")
        obj=card["data"]
        obj["description"]="长篇人物背景"*480
        obj["speech_style"]="明快、有自己的判断。"*200
        obj["traits"]=["内心很细腻"*25 for i in range(12)]
        self.store.save_card(obj,card["revision"])
        result=PromptComposer(max_addendum_tokens=1100).compose(self.store.snapshot(),"今天天气很好")
        self.assertIn("【可信游戏状态】",result["prompt"])
        self.assertIn("【角色核心】",result["prompt"])
        self.assertIn("【叙事预设】",result["prompt"])
        self.assertIn("好感度=25/100",result["prompt"])
        self.assertIn("沉浸 Galgame",result["prompt"])
        self.assertLessEqual(result["trace"]["addendum_tokens_estimate"],1100)

    def test_cjk_budget_is_strict(self):
        self.store.save_lore("legacy_character",{
            "entry_id":"huge_lore","title":"剧情补充",
            "content":"中文剧情"*400,
            "activation":"always","keywords":[],
            "priority":100,"enabled":True
        },0)
        composed=PromptComposer(max_addendum_tokens=900,lore_budget=300).compose(
            self.store.snapshot(),"我想谈谈这个话题")
        self.assertLessEqual(tokens_approx(composed["addendum"]),900)
        self.assertLessEqual(composed["trace"]["addendum_tokens_estimate"],900)
        self.assertIn("可信游戏状态",composed["prompt"])

    def test_traces_dropped_lore_correctly(self):
        card=self.store.get_card("legacy_character")
        card["data"]["description"]="成长故事"*700
        self.store.save_card(card["data"],card["revision"])
        self.store.save_lore("legacy_character",{
            "entry_id":"episode","title":"重要但很长的背景","content":"很长的世界书"*250,
            "activation":"always","keywords":[],"priority":100,"enabled":True,
        },0)
        result=PromptComposer(max_addendum_tokens=660,lore_budget=300).compose(
            self.store.snapshot(),"你好")
        if "世界书" not in [item["section"] for item in result["trace"]["parts"]]:
            self.assertNotIn("episode",result["trace"]["selected_lore_ids"])
        self.assertLessEqual(result["trace"]["addendum_tokens_estimate"],660)


if __name__=="__main__":
    unittest.main()
