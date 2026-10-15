import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest

from studio.roleplay_plus.store import RoleplayStore
from studio.roleplay_plus import domain

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir=TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path=Path(self.dir.name)/"history.sqlite3"
        with closing(sqlite3.connect(self.path)) as conn,conn:
            conn.execute("CREATE TABLE messages(id INTEGER PRIMARY KEY,role TEXT,content TEXT)")
            conn.execute("INSERT INTO messages(role,content) VALUES('user','private old chat')")
        self.store=RoleplayStore(self.path)
        self.store.initialize({"role_name":"千岁","persona":"旧人设"})
    def test_preserves_history_and_backups_once(self):
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT content FROM messages").fetchone()[0],"private old chat")
        backups=list((self.path.parent/"roleplay_backups").glob("*.sqlite3"))
        self.assertEqual(len(backups),1)
        self.store.initialize({"role_name":"另一个角色","persona":"应当不覆盖"})
        self.assertEqual(len(list((self.path.parent/"roleplay_backups").glob("*.sqlite3"))),1)
        self.assertEqual(self.store.get_card("legacy_character")["data"]["name"],"千岁")
    def test_six_presets_seeded(self):
        self.assertEqual(len(self.store.list_presets()),6)
        self.assertEqual(self.store.binding()["preset_id"],"immersive_galgame")
    def test_default_player_private(self):
        self.assertFalse(self.store.get_persona("default_player")["data"]["share_with_llm"])
    def test_card_persist_revision(self):
        card=self.store.get_card("legacy_character")
        card["data"]["speech_style"]="非常自然"
        result=self.store.save_card(card["data"],card["revision"])
        self.assertEqual(result["revision"],2)
        reopened=RoleplayStore(self.path)
        self.assertEqual(reopened.get_card("legacy_character")["data"]["speech_style"],"非常自然")
    def test_revision_conflict_rejected(self):
        data=self.store.get_card("legacy_character")["data"]
        self.store.save_card(data,1)
        with self.assertRaisesRegex(ValueError,"revision"):
            self.store.save_card(data,1)
    def test_new_card_and_select(self):
        x=domain.initial_card({"role_name":"新角色"})
        x["card_id"]="new_actor"
        self.store.save_card(x,0)
        self.store.select(card_id="new_actor")
        self.assertEqual(self.store.snapshot()["card"]["name"],"新角色")
    def test_select_invalid_card_does_not_change(self):
        with self.assertRaises(ValueError):self.store.select(card_id="missing")
        self.assertEqual(self.store.binding()["card_id"],"legacy_character")
    def test_persona_privacy_saved(self):
        data={"persona_id":"writer","name":"用户","description":"不能自动发送","share_with_llm":False}
        self.store.save_persona(data,0)
        self.store.select(persona_id="writer")
        self.assertEqual(self.store.snapshot()["persona"]["description"],"不能自动发送")
        self.store.select(persona_id="")
        self.assertIsNone(self.store.snapshot()["persona"])
    def test_builtin_cannot_overwrite(self):
        with self.assertRaises(ValueError):
            self.store.save_preset(self.store.get_preset("daily")["data"],1)
    def test_custom_preset_save(self):
        d=self.store.get_preset("daily")["data"]
        d["preset_id"]="daily_custom";d["name"]="我的日常"
        r=self.store.save_preset(d,0)
        self.store.select(preset_id=r["id"])
        self.assertEqual(self.store.snapshot()["preset"]["name"],"我的日常")
    def test_lore_save_and_revision(self):
        entry={"entry_id":"park","title":"公园","content":"在花坛附近聊天",
               "activation":"keyword","keywords":["公园"],"enabled":True}
        res=self.store.save_lore("legacy_character",entry,0)
        self.assertEqual(res["revision"],1)
        res["data"]["content"]="公园的回忆"
        r2=self.store.save_lore("legacy_character",res["data"],1)
        self.assertEqual(r2["revision"],2)
        with self.assertRaises(ValueError):
            self.store.delete_lore("legacy_character","park",1)
        self.store.delete_lore("legacy_character","park",2)
        self.assertEqual(self.store.list_lore("legacy_character"),[])
    def test_state_persistent(self):
        old=self.store.game_state()
        self.assertEqual(old["state"]["affection"],25)
        reopened=RoleplayStore(self.path)
        self.assertEqual(reopened.game_state(),old)
    def test_events_not_automatic(self):
        before=self.store.game_state()
        self.store.offer_event("take_break")
        self.assertEqual(self.store.game_state(),before)
    def test_event_decline_has_no_penalty(self):
        before=self.store.game_state()
        r=self.store.offer_event("share_hobby")
        res=self.store.choose_event(r["instance_id"],"decline","k_decline")
        self.assertEqual(res["effects"],{})
        self.assertEqual(self.store.game_state(),before)
        self.assertEqual(self.store.journal()[-1]["choice_id"],"decline")
    def test_event_accepted_once(self):
        r=self.store.offer_event("share_hobby")
        x=self.store.choose_event(r["instance_id"],"accept","k_first")
        self.assertEqual(x["game_state"]["state"]["affection"],26)
        y=self.store.choose_event(r["instance_id"],"accept","k_first")
        self.assertEqual(x,y)
        self.assertEqual(len(self.store.journal()),1)
        with self.assertRaises(ValueError):
            self.store.choose_event(r["instance_id"],"accept","k_other")
    def test_verified_location_only(self):
        with self.assertRaises(ValueError):
            self.store.sync_verified_location("park",{"home"})
        self.assertEqual(self.store.game_state()["state"]["location_id"],"")
        result=self.store.sync_verified_location("park",{"home","park"})
        self.assertEqual(result["state"]["location_id"],"park")
        again=self.store.sync_verified_location("park",{"home","park"})
        self.assertEqual(result["revision"],again["revision"])

    def test_bad_event_not_offered(self):
        with self.assertRaises(ValueError):self.store.offer_event("give_me_100_affection")
        self.assertEqual(self.store.game_state()["state"]["affection"],25)
    def test_only_one_pending_event(self):
        self.store.offer_event("take_break")
        with self.assertRaises(ValueError):self.store.offer_event("share_hobby")
    def test_wrong_option_no_stat_change(self):
        offer=self.store.offer_event("take_break")
        with self.assertRaises(ValueError):
            self.store.choose_event(offer["instance_id"],"100_affection","k_inject")
        self.assertEqual(self.store.game_state()["state"]["energy"],80)
    def test_parallel_click_idempotent(self):
        offer=self.store.offer_event("share_hobby")
        results=[]
        barrier=threading.Barrier(2)
        def attempt():
            barrier.wait()
            try:results.append(("ok",self.store.choose_event(offer["instance_id"],"accept","k_parallel")))
            except Exception as e:results.append(("error",str(e)))
        workers=[threading.Thread(target=attempt) for _ in range(2)]
        for t in workers:t.start()
        for t in workers:t.join(timeout=8)
        self.assertFalse(any(t.is_alive() for t in workers))
        self.assertEqual([r[0] for r in results],["ok","ok"])
        self.assertEqual(self.store.game_state()["state"]["affection"],26)
        self.assertEqual(len(self.store.journal()),1)
    def test_epoch_changes_only_on_real_write(self):
        epoch=self.store.epoch()
        self.store.snapshot()
        self.assertEqual(self.store.epoch(),epoch)
        self.store.select(preset_id="daily")
        self.assertGreater(self.store.epoch(),epoch)
    def test_event_idempotency_key_cannot_be_reused(self):
        one=self.store.offer_event("share_hobby")
        self.store.choose_event(one["instance_id"],"accept","k_x")
        two=self.store.offer_event("take_break")
        with self.assertRaises(ValueError):
            self.store.choose_event(two["instance_id"],"accept","k_x")

if __name__=="__main__":unittest.main()
