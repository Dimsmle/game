# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path

from studio import behavior, diagnostics

class BehaviorConfigTests(unittest.TestCase):
    def test_import_validation_and_merge(self):
        a={"version":1,"models":{"kan_10":{
            "motion_tags":{"うんうん":{"tags":["nod"],"sample_time":30}},
            "expression_map":{"happy":"笑顔Ａ"}}}}
        b={"version":1,"models":{"kan_10":{
            "motion_tags":{"思考":{"tags":["think"],"sample_time":40}},
            "expression_map":{"thinking":"考えるＡ"}}}}
        merged=behavior.merge_libraries(a,b)
        self.assertEqual(set(merged["models"]["kan_10"]["motion_tags"]),
                         {"うんうん","思考"})
        self.assertEqual(merged["models"]["kan_10"]["expression_map"]["happy"],"笑顔Ａ")
        self.assertEqual(merged["models"]["kan_10"]["expression_map"]["thinking"],"考えるＡ")

    def test_import_rejects_paths_and_unknown_tags(self):
        unsafe={"version":1,"models":{"../../etc":{
            "motion_tags":{},"expression_map":{}}}}
        with self.assertRaises(ValueError):
            behavior.validate_library_basic(unsafe)
        bad={"version":1,"models":{"kan_10":{
            "motion_tags":{"x":{"tags":["../../run"],"sample_time":0}},
            "expression_map":{}}}}
        with self.assertRaises(ValueError):
            behavior.validate_library_basic(bad)


    def test_expression_cache_prune_never_deletes_current_files(self):
        import main_desktop
        with tempfile.TemporaryDirectory() as temp:
            cache=Path(temp)
            files=[]
            for index in range(365):
                path=cache/f"kan_10_expr_{index:04d}_normal.png"
                path.write_bytes(b"x")
                files.append(path)
            keep=files[0]
            removed=main_desktop.prune_expression_cache(cache,[keep],max_files=360)
            self.assertGreaterEqual(removed,5)
            self.assertTrue(keep.exists())
            self.assertLessEqual(len(list(cache.glob("*.png"))),360)

    def test_diagnostics_is_offline_and_reports_missing_root(self):
        with tempfile.TemporaryDirectory() as temp:
            report=diagnostics.run(Path(temp)/"state",None,{"llm_mode":"demo"},"")
            self.assertFalse(next(x for x in report["items"] if x["key"]=="asset_root")["ok"])
            self.assertIn("不主动连接",report["note"])
            text=diagnostics.format_text(report)
            self.assertIn("Character Studio Doctor",text)

if __name__=="__main__":
    unittest.main()
