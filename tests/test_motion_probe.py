# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from motion_probe import export_motion_probe


class _ProbeModel:
    path=Path("kan_10.json")
    label_to_preset={"笑顔Ａ":0,"うんうん":1}

    def expression_catalog(self):
        return [
            {"label":"笑顔Ａ","type":"face","index":0,"duration":1.0},
            {"label":"うんうん","type":"motion","index":1,"duration":118.0},
        ]

    def preset_vars(self,label,time=0):
        if label=="うんうん":
            return {"head_UD":float(time),"face_mouth":40}
        return {"face_mouth":30}


class _FlatRenderer:
    def render(self,preset=0,overrides=None,size=(740,1250),**_):
        color=(200,80,120,255) if (overrides or {}).get("face_talk") else (40,90,140,255)
        image=Image.new("RGBA",size,(0,0,0,0))
        image.putpixel((size[0]//2,size[1]//2),color)
        return image


class MotionProbeTests(unittest.TestCase):
    def test_identical_motion_samples_are_never_marked_playable(self):
        with tempfile.TemporaryDirectory() as folder:
            result=export_motion_probe(
                _ProbeModel(),_FlatRenderer(),folder,
                expression_label="笑顔Ａ",motion_label="うんうん",
                samples=5,target_fps=24,size=(128,128))
            self.assertEqual(result["status"],"blocked_identical_frames")
            self.assertFalse(result["playable"])
            self.assertEqual(result["distinct_visual_frames"],1)
            self.assertEqual(result["motion_controls"],["head_UD"])
            self.assertTrue(result["transparent_background"])
            self.assertTrue(result["talk_overlay_distinct"])
            saved=json.loads((Path(folder)/"probe.json").read_text(encoding="utf-8"))
            self.assertFalse(saved["playable"])

    def test_probe_rejects_non_motion_label(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,"动作时间轴"):
                export_motion_probe(
                    _ProbeModel(),_FlatRenderer(),folder,
                    expression_label="笑顔Ａ",motion_label="笑顔Ａ")


if __name__=="__main__":
    unittest.main()
