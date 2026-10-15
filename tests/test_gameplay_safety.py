"""Selected v0.15.2 pure safety regressions; no cloud or preview database."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import math
from pathlib import Path
import tempfile
import unittest
from studio.gameplay_core import locations, media, touch
from studio.gameplay_core.common import VALID_IMAGE_EXTENSIONS, open_verified_asset

class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)
        (self.root/"bg12aa.png").write_bytes(b"fake-asset-data")
        self.path=self.root/"bg12aa.png"
        self.record={
            "asset_id":"bg_stable","relative_path":"bg12aa.png",
            "file_hash":hashlib.sha256(self.path.read_bytes()).hexdigest(),
            "verified":True}

    def test_verified_asset_file_descriptor(self):
        with open_verified_asset(self.root,self.record,
                                 allowed_extensions=VALID_IMAGE_EXTENSIONS) as handle:
            self.assertEqual(handle.read(),b"fake-asset-data")
            self.assertEqual(handle.name,str(self.path))

    def test_changed_binary_fails_before_serving(self):
        self.path.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError,"已经修改"):
            with open_verified_asset(self.root,self.record): pass

    def test_not_reviewed_never_served(self):
        entry=dict(self.record,verified=False)
        with self.assertRaisesRegex(ValueError,"未审核"):
            with open_verified_asset(self.root,entry):pass

    def test_digest_must_be_full_sha256(self):
        for bad in ("00", "g"*64, None, "A"*64):
            with self.subTest(bad=bad):
                entry=dict(self.record,file_hash=bad)
                with self.assertRaises(ValueError):
                    with open_verified_asset(self.root,entry):pass

    def test_absolute_path_rejected(self):
        entry=dict(self.record,relative_path=str(self.path.resolve()))
        with self.assertRaises(ValueError):
            with open_verified_asset(self.root,entry):pass

    def test_symlink_rejected(self):
        try:
            (self.root/"other.png").symlink_to(self.path)
        except (OSError,NotImplementedError):
            self.skipTest("Symlinks unsupported by host")
        entry=dict(self.record,relative_path="other.png")
        with self.assertRaises(ValueError):
            with open_verified_asset(self.root,entry):pass

    def test_duplicate_background_review_rejected(self):
        catalog=locations.scan_backgrounds(self.root)
        asset=catalog["families"]["bg12"][0]
        review={
            "asset_id":asset["asset_id"],"file_hash":asset["file_hash"],
            "location_id":"home","location_name":"家","time_of_day":"night",
            "verified":True}
        with self.assertRaisesRegex(ValueError,"重复"):
            locations.apply_reviews(catalog,[review,review])

    def test_unknown_time_cannot_auto_play(self):
        catalog=locations.scan_backgrounds(self.root)
        asset=catalog["families"]["bg12"][0]
        review={
            "asset_id":asset["asset_id"],"file_hash":asset["file_hash"],
            "location_id":"home","location_name":"家","time_of_day":"unknown",
            "verified":True,"allow_automatic":True}
        with self.assertRaises(ValueError):locations.apply_reviews(catalog,[review])
        review["allow_automatic"]=False
        reviewed=locations.apply_reviews(catalog,[review])
        self.assertIsNone(locations.resolve_background(reviewed,"home","night",auto=True))
        self.assertIsNotNone(locations.resolve_background(reviewed,"home","night",auto=False))

    def test_oversized_media_gets_diagnostic(self):
        from studio.gameplay_core.common import MAX_FILE_BYTES
        oversize=self.root/"huge.png"
        with oversize.open("wb") as handle:
            handle.truncate(MAX_FILE_BYTES+1)
        catalog=media.scan_media(self.root)
        self.assertTrue(any(
            "huge.png" in item["relative_path"]
            and item["reason"]=="file_rejected"
            for item in catalog["warnings"]))
        self.assertFalse(any(x["relative_path"]=="huge.png"
                             for x in catalog["assets"]))

    def test_duplicate_media_review_rejected(self):
        catalog=media.scan_media(self.root)
        item=catalog["assets"][0]
        review={
            "asset_id":item["asset_id"],"file_hash":item["file_hash"],
            "category":"cg_still","title":"已核实测试图片","verified":True}
        with self.assertRaisesRegex(ValueError,"重复"):
            media.review_media(catalog,[review,review])

class StrictTouchTests(unittest.TestCase):
    def setUp(self):
        self.profile={
            "profile_id":"test_head","model_id":"kan_10","pose_id":"standing",
            "verified":True,
            "regions":[{"name":"head","z":2,"enabled":True,
                        "polygon":[[.1,.1],[.9,.1],[.9,.9],[.1,.9]]}]}
    def test_self_intersecting_polygon_rejected(self):
        order=[0,2,4,1,3]
        pts=[[.5+.4*math.cos(2*math.pi*n/5),
              .5+.4*math.sin(2*math.pi*n/5)] for n in order]
        self.profile["regions"][0]["polygon"]=pts
        with self.assertRaises(ValueError):
            touch.validate_hitbox_profile(self.profile)

    def test_request_id_replay_global_and_region_cooldown(self):
        gate=touch.TouchRequestGate(region_seconds=3,global_seconds=.5)
        self.assertTrue(gate.permit(profile_id="a",region="head",
                                    request_id="r1",now=1))
        self.assertFalse(gate.permit(profile_id="a",region="head",
                                    request_id="r1",now=100))
        self.assertFalse(gate.permit(profile_id="a",region="head",
                                    request_id="r2",now=2))
        self.assertTrue(gate.permit(profile_id="a",region="hand",
                                   request_id="r3",now=2))
        self.assertFalse(gate.permit(profile_id="a",region="arm",
                                    request_id="r4",now=2.1))
        self.assertTrue(gate.permit(profile_id="b",region="head",
                                   request_id="r5",now=2))
        self.assertTrue(gate.permit(profile_id="a",region="head",
                                   request_id="r6",now=4.1))

    def test_clear_profile_resets_request_history(self):
        gate=touch.TouchRequestGate()
        self.assertTrue(gate.permit(profile_id="a",region="head",
                                    request_id="r1",now=1))
        gate.clear_profile("a")
        self.assertTrue(gate.permit(profile_id="a",region="head",
                                    request_id="r1",now=1))

    def test_parallel_duplicate_request_only_one(self):
        gate=touch.TouchRequestGate(region_seconds=0,global_seconds=0)
        def click(_):
            return gate.permit(profile_id="a",region="head",
                               request_id="one_request",now=1)
        with ThreadPoolExecutor(max_workers=10) as pool:
            accepted=list(pool.map(click,range(20)))
        self.assertEqual(sum(accepted),1)

    def test_reject_negative_or_non_finite_time(self):
        gate=touch.TouchRequestGate()
        for value in (-1,float("nan"),float("inf"),True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    gate.permit(profile_id="a",region="head",
                                request_id="rid",now=value)
