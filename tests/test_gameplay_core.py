"""Executable contracts for v0.15 P2–P5. No DeepSeek key or game materials."""
import json
import tempfile
import unittest
from pathlib import Path

from studio.gameplay_core import locations,events,media,touch,clock,director
from studio.gameplay_core.common import checked_file,identifier

def event_data():
    return {
        "id":"evening_tea","title":"晚间喝茶","type":"invitation",
        "enabled":True,"triggers":["chat","manual"],
        "conditions":{"affection_min":20,"location_any":["living_room"],
            "time_any":["evening","night"],"forbidden_flags":["already_tea"]},
        "cooldown":{"turns":5,"seconds":600},
        "required_media_ids":[],
        "choices":[
            {"id":"accept","label":"喝杯茶吧",
             "effect":{"stats":{"affection":1,"mood":2},
                        "set_flags":{"already_tea":True},
                        "location_id":"living_room"}},
            {"id":"decline","label":"今天先休息",
             "effect":{"stats":{},"set_flags":{}}}
        ]
    }

def event_context():
    return {
        "stats":{"affection":25,"trust":30,"mood":15,"energy":80},
        "location_id":"living_room","time_of_day":"evening",
        "relationship_stage":"familiar","flags":{},
        "proactive_enabled":True,"turn_index":8,"now_seconds":10000,
        "recent":{},"busy":False
    }

def hitbox():
    return {"profile_id":"kan10_head","model_id":"kan_10","pose_id":"standing",
        "outfit_id":None,"verified":True,
        "regions":[
            {"name":"head","z":5,"enabled":True,
             "polygon":[[0.2,0.1],[0.8,0.1],[0.8,0.4],[0.2,0.4]]},
            {"name":"hair","z":10,"enabled":True,
             "polygon":[[0.15,0.07],[0.22,0.07],[0.22,0.42],[0.15,0.42]]},
            {"name":"shoulder","z":2,"enabled":True,
             "polygon":[[0.15,0.41],[0.85,0.41],[0.85,0.65],[0.15,0.65]]},
        ]
    }

class LocationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/"bg").mkdir()
        for name in ("bg12aa.png","bg12ab.png","bg12ac.png","bg12af.png",
                     "bg13aa.png","bg14zz.png","bgFAIL.png"):
            (self.root/"bg"/name).write_bytes(name.encode("utf-8")+b"-mock")
        self.scan=locations.scan_backgrounds(self.root)

    def review(self, family="bg12", suffix="aa", *, name="living_room", time="day",
               default=False, auto=True):
        item=next(a for a in self.scan["families"][family] if a["suffix"]==suffix)
        return {"asset_id":item["asset_id"],"file_hash":item["file_hash"],
                "location_id":name,"location_name":"客厅","time_of_day":time,
                "verified":True,"allow_automatic":auto,"default":default}

    def test_bg_family_without_guessing_time(self):
        self.assertEqual(len(self.scan["families"]["bg12"]),4)
        self.assertEqual({x["suffix"] for x in self.scan["families"]["bg12"]},
                         {"aa","ab","ac","af"})
        self.assertTrue(all(x["time_of_day"]=="unknown" and not x["verified"]
                            for x in self.scan["families"]["bg12"]))
    def test_unknown_suffix_and_unmatched_are_reported(self):
        self.assertTrue(any(w["reason"]=="unknown_suffix" for w in self.scan["warnings"]))
        self.assertTrue(any("bgFAIL" in w["relative_path"]
                            for w in self.scan["unmatched"]))
    def test_no_unverified_locations_sent_to_ai(self):
        self.assertEqual(locations.locations_for_llm(self.scan),[])
        self.assertIsNone(locations.resolve_background(self.scan,"living_room","night"))
    def test_manual_verified_time_and_fallback(self):
        a=locations.apply_reviews(self.scan,
            [self.review(suffix="aa",time="day",default=True),
             self.review(suffix="ab",time="night")])
        actual=locations.resolve_background(a,"living_room","night")
        self.assertEqual(actual["suffix"],"ab")
        self.assertEqual(locations.resolve_background(a,"living_room","evening")["suffix"],"aa")
        self.assertNotIn("G:\\",str(locations.locations_for_llm(a)))
        self.assertNotIn("relative_path",str(locations.locations_for_llm(a)))
    def test_no_cross_location_fallback(self):
        updated=locations.apply_reviews(self.scan,[self.review()])
        self.assertIsNone(locations.resolve_background(updated,"unknown_park","day"))
    def test_tampered_hash_rejected(self):
        bad=self.review();bad["file_hash"]="0"*64
        with self.assertRaises(ValueError):locations.apply_reviews(self.scan,[bad])
    def test_change_invalidates_review_after_rescan(self):
        old=locations.apply_reviews(self.scan,[self.review()])
        (self.root/"bg"/"bg12aa.png").write_bytes(b"totally-changed-binary")
        fresh=locations.migrate_unchanged_reviews(old,locations.scan_backgrounds(self.root))
        self.assertFalse(any(x["verified"] for x in fresh["families"]["bg12"]))
    def test_unchanged_review_survives_rescan(self):
        old=locations.apply_reviews(self.scan,[self.review()])
        fresh=locations.migrate_unchanged_reviews(old,locations.scan_backgrounds(self.root))
        self.assertTrue(any(x["verified"] for x in fresh["families"]["bg12"]))
    def test_family_conflict_rejected(self):
        r=self.review()
        r2=self.review(suffix="ab",name="park")
        with self.assertRaises(ValueError):locations.apply_reviews(self.scan,[r,r2])
    def test_default_collision_rejected(self):
        r=self.review(default=True)
        r2=self.review(suffix="ab",default=True)
        with self.assertRaises(ValueError):locations.apply_reviews(self.scan,[r,r2])
    def test_symlink_outside_does_not_enter_scan(self):
        outside=self.root.parent/"outside-test-ignore.png"
        try:
            (self.root/"bg"/"bg29aa.png").symlink_to(outside)
        except (OSError,NotImplementedError):
            self.skipTest("Symlink unavailable")
        self.assertNotIn("bg29",locations.scan_backgrounds(self.root)["families"])
    def test_path_traversal_block(self):
        with self.assertRaises(ValueError):checked_file(self.root,"../outside.png")
    def test_numeric_family_name_not_outfit_assumption(self):
        self.assertEqual(locations.parse_background("bg00012AF"),("bg00012","af"))
        self.assertIsNone(locations.parse_background("bgSchoolaa"))

class EventTests(unittest.TestCase):
    def setUp(self):
        self.data=event_data()
        self.event=events.validate_event(self.data,
                    verified_locations={"living_room"},verified_media=set())
        self.context=event_context()
    def test_candidate_eligible(self):
        self.assertEqual(events.candidate_event_ids([self.event],self.context),
                         ["evening_tea"])
    def test_invalid_location_not_registered(self):
        data=event_data();data["choices"][0]["effect"]["location_id"]="unknown"
        with self.assertRaises(ValueError):
            events.validate_event(data,verified_locations={"living_room"},
                                  verified_media=set())
    def test_unverified_media_rejected(self):
        data=event_data();data["required_media_ids"]=["media_unknown"]
        with self.assertRaises(ValueError):
            events.validate_event(data,verified_locations={"living_room"},
                                  verified_media=set())
    def test_llm_cannot_set_delta(self):
        with self.assertRaises(ValueError):
            events.parse_event_proposal({"event_id":"evening_tea","presentation":"after_last_segment",
                                        "affection_delta":99},{"evening_tea"})
    def test_llm_cannot_invent_id(self):
        with self.assertRaises(ValueError):
            events.parse_event_proposal({"event_id":"unknown",
                        "presentation":"after_last_segment"},{"evening_tea"})
    def test_model_envelope_legacy_only(self):
        d=events.parse_director_envelope({"segments":[{"speech":"早上好"}]},set())
        self.assertIsNone(d["event_id"])
    def test_model_envelope_valid_proposal(self):
        d=events.parse_director_envelope({"segments":[{"speech":"来喝茶吗"}],
           "event_proposal":{"event_id":"evening_tea",
                             "presentation":"after_last_segment"}},{"evening_tea"})
        self.assertEqual(d["event_id"],"evening_tea")
    def test_model_envelope_reject_extra_top_level(self):
        with self.assertRaises(ValueError):
            events.parse_director_envelope({"segments":[{"speech":"hi"}],
                              "set_affection":99},set())
    def test_event_reject_extra_effect(self):
        data=event_data()
        data["choices"][0]["effect"]["run_file"]="foo.py"
        with self.assertRaises(ValueError):
            events.validate_event(data,verified_locations={"living_room"},
                                  verified_media=set())
    def test_event_reject_unbounded_delta(self):
        data=event_data()
        data["choices"][0]["effect"]["stats"]["affection"]=50
        with self.assertRaises(ValueError):
            events.validate_event(data,verified_locations={"living_room"},
                                  verified_media=set())
    def test_affection_gate(self):
        self.context["stats"]["affection"]=0
        yes,reason=events.eligibility(self.event,self.context)
        self.assertFalse(yes);self.assertIn("low_affection",reason)
    def test_off_and_busy(self):
        self.context.update(proactive_enabled=False,busy=True)
        ok,reasons=events.eligibility(self.event,self.context)
        self.assertFalse(ok);self.assertIn("proactive_off",reasons)
        self.assertIn("busy",reasons)
    def test_cooldown_and_flags(self):
        self.context["flags"]["already_tea"]=True
        self.context["recent"]["evening_tea"]={"turn_index":7,"at_seconds":9900}
        ok,reasons=events.eligibility(self.event,self.context)
        self.assertFalse(ok)
        self.assertIn("forbidden_flags",reasons)
        self.assertIn("time_cooldown",reasons)
        self.assertIn("turn_cooldown",reasons)
    def test_decline_no_penalty(self):
        plan=events.choice_plan(self.event,"decline")
        self.assertEqual(plan["effect"]["stats"],{})
        self.assertIsNone(plan["effect"]["location_id"])
    def test_bad_choice_rejected(self):
        with self.assertRaises(ValueError):
            events.choice_plan(self.event,"nonexistent")
    def test_no_unknown_milestone(self):
        data=event_data()
        data["choices"][0]["effect"]["milestone"]="instant_marriage"
        with self.assertRaises(ValueError):
            events.validate_event(data,verified_locations={"living_room"},
                                  verified_media=set())

class DirectorTests(unittest.TestCase):
    def setUp(self):
        self.event=events.validate_event(event_data(),
                        verified_locations={"living_room"},verified_media=set())
        self.identity=director.TurnIdentity("default",3,15,2,"ab12cdef")
        self.pending=director.PendingEvent(self.event,self.identity,3,"inst_01")
    def test_not_offered_before_read(self):
        self.pending.activate(0,self.identity)
        with self.assertRaises(ValueError):
            self.pending.complete_ui(self.identity,displayed=True,tts_finished=True)
    def test_not_offered_before_tts(self):
        for idx in range(3):self.pending.activate(idx,self.identity)
        with self.assertRaises(ValueError):
            self.pending.complete_ui(self.identity,displayed=True,tts_finished=False)
    def test_offer_idempotent_only_after_final_ack(self):
        for idx in range(3):self.pending.activate(idx,self.identity)
        a=self.pending.complete_ui(self.identity,displayed=True,tts_finished=True)
        b=self.pending.complete_ui(self.identity,displayed=True,tts_finished=True)
        self.assertEqual(a,b)
        self.assertEqual(set(a["choices"][0]),{"id","label"})
    def test_cannot_choose_before_ack(self):
        with self.assertRaises(ValueError):
            self.pending.choose("accept",self.identity)
    def test_cancel_never_revives(self):
        self.pending.activate(0,self.identity)
        self.pending.cancel(self.identity)
        with self.assertRaises(ValueError):self.pending.activate(1,self.identity)
        with self.assertRaises(ValueError):
            self.pending.complete_ui(self.identity,displayed=True,tts_finished=True)
    def test_stale_profile_generation_rejected(self):
        stale=director.TurnIdentity("default",4,15,2,"ab12cdef")
        with self.assertRaises(ValueError):self.pending.activate(0,stale)
    def test_choice_idempotent_result(self):
        for idx in range(3):self.pending.activate(idx,self.identity)
        self.pending.complete_ui(self.identity,displayed=True,tts_finished=True)
        a=self.pending.choose("accept",self.identity)
        b=self.pending.choose("accept",self.identity)
        self.assertEqual(a,b)
        with self.assertRaises(ValueError):self.pending.choose("decline",self.identity)
    def test_no_skip(self):
        with self.assertRaises(ValueError):self.pending.activate(2,self.identity)

class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/"cg01.png").write_bytes(b"fake-cg-metadata-only")
        (self.root/"se01.ogg").write_bytes(b"fake-audio-metadata-only")
        (self.root/"scene01.psb").write_bytes(b"psb-candidate")
        self.scan=media.scan_media(self.root)
    def review(self,name,kind,auto=True):
        item=next(x for x in self.scan["assets"] if x["relative_path"]==name)
        return {"asset_id":item["asset_id"],"file_hash":item["file_hash"],
                "category":kind,"title":"经过确认的测试媒体",
                "verified":True,"safe_for_auto":auto}
    def test_every_asset_starts_unreviewed(self):
        self.assertTrue(all(not x["verified"] for x in self.scan["assets"]))
        self.assertEqual(media.playable_ids(self.scan),set())
    def test_psb_not_claimed_playable(self):
        with self.assertRaises(ValueError):
            media.review_media(self.scan,[self.review("scene01.psb","cg_still")])
    def test_review_and_resolve(self):
        checked=media.review_media(self.scan,[self.review("cg01.png","cg_still")])
        asset_id=next(iter(media.playable_ids(checked)))
        actual=media.resolve_playback(checked,asset_id)
        self.assertEqual(actual["relative_path"],"cg01.png")
        self.assertNotIn("relative_path",str(media.media_summaries_for_ai(checked)))
    def test_no_unauthorized_auto(self):
        checked=media.review_media(self.scan,[self.review("cg01.png","cg_still",False)])
        self.assertEqual(media.playable_ids(checked),set())
        self.assertEqual(len(media.playable_ids(checked,auto=False)),1)
    def test_changed_binary_invalidates_review(self):
        reviewed=media.review_media(self.scan,[self.review("cg01.png","cg_still")])
        (self.root/"cg01.png").write_bytes(b"new-media")
        changed=media.merge_unchanged_media(reviewed,media.scan_media(self.root))
        self.assertEqual(media.playable_ids(changed),set())
    def test_incorrect_format_rejected(self):
        with self.assertRaises(ValueError):
            media.review_media(self.scan,[self.review("se01.ogg","cg_still")])

class TouchTests(unittest.TestCase):
    def setUp(self):self.profile=hitbox()
    def test_head_region(self):
        self.assertEqual(touch.hit_test(self.profile,0.5,0.25),"head")
    def test_overlay_blocks(self):
        self.assertIsNone(touch.hit_test(self.profile,0.5,0.25,overlay_blocked=True))
    def test_unverified_ignored(self):
        self.profile["verified"]=False
        self.assertIsNone(touch.hit_test(self.profile,0.5,0.25))
    def test_background_not_touch(self):
        self.assertIsNone(touch.hit_test(self.profile,0.98,0.99))
    def test_cooldown(self):
        gate=touch.TouchCooldown(2)
        self.assertTrue(gate.permit(profile_id="p1",region="head",now=3))
        self.assertFalse(gate.permit(profile_id="p1",region="head",now=4))
        self.assertTrue(gate.permit(profile_id="p2",region="head",now=4))
        self.assertTrue(gate.permit(profile_id="p1",region="head",now=5))
    def test_do_not_trust_browser_region_guess(self):
        msg=touch.normalize_touch_message({
          "request_id":"request1","gesture":"tap","x":0.5,"y":0.25,
          "region":"shoulder"},self.profile,
          current_model_id="kan_10",current_pose_id="standing")
        self.assertEqual(msg["region"],"head")
        self.assertNotIn("x",msg)
    def test_mismatched_model_rejected(self):
        with self.assertRaises(ValueError):
            touch.normalize_touch_message({
              "request_id":"req","gesture":"tap","x":0.5,"y":0.25},self.profile,
              current_model_id="shi_15",current_pose_id="standing")
    def test_invalid_coord_rejected(self):
        for x in (-1,100,float("nan"),True):
            with self.assertRaises(ValueError):
                touch.hit_test(self.profile,x,0.2)
    def test_sensitive_region_rejected(self):
        self.profile["regions"][0]["name"]="chest"
        with self.assertRaises(ValueError):touch.validate_hitbox_profile(self.profile)
    def test_touch_prompt_no_stat_effect(self):
        msg=touch.touch_for_llm({"type":"touch","region":"head"})
        self.assertIn("虚拟角色",msg)
        self.assertIn("不能仅凭",msg)

class ClockTests(unittest.TestCase):
    def test_dayparts(self):
        self.assertEqual([clock.time_period(x) for x in (6,12,18,23)],
                         ["morning","day","evening","night"])
    def test_manual(self):
        self.assertEqual(clock.effective_time("manual",manual_time="evening"),"evening")
    def test_game_time(self):
        self.assertEqual(clock.effective_time("game",game_hour=22),"night")
    def test_lock_blocks_auto(self):
        self.assertFalse(clock.may_auto_transition(scene_locked=True,cg_active=False,
               tts_active=False,reply_active=False,manual_choice_pending=False,
               clock_mode="system"))
    def test_reply_blocks_auto(self):
        self.assertFalse(clock.may_auto_transition(scene_locked=False,cg_active=False,
               tts_active=False,reply_active=True,manual_choice_pending=False,
               clock_mode="system"))
    def test_free_clock_allows(self):
        self.assertTrue(clock.may_auto_transition(scene_locked=False,cg_active=False,
               tts_active=False,reply_active=False,manual_choice_pending=False,
               clock_mode="system"))

if __name__=="__main__":
    unittest.main()
