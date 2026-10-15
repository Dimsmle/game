"""Safe preview regressions using synthetic local images, never cloud calls."""
from io import BytesIO
from pathlib import Path
import hashlib
import tempfile
import unittest
from PIL import Image
from studio.gameplay_images import checked_image_bytes


class PreviewImages(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.path=self.root/'test.jpg'
        Image.new('RGB',(32,20),'blue').save(self.path)
        self.record=dict(asset_id='image_test',relative_path='test.jpg',verified=True,
                         file_hash=hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_preview_decodes_and_reencodes(self):
        data=checked_image_bytes(self.root,self.record)
        with Image.open(BytesIO(data)) as image:
            self.assertEqual(image.format,'PNG')
            self.assertEqual(image.size,(32,20))

    def test_only_review_endpoint_can_open_unapproved(self):
        self.record['verified']=False
        with self.assertRaises(ValueError):checked_image_bytes(self.root,self.record)
        self.assertTrue(checked_image_bytes(self.root,self.record,require_verified=False))

    def test_changed_content_rejected(self):
        self.path.write_bytes(b'not an image')
        with self.assertRaises(ValueError):checked_image_bytes(self.root,self.record,require_verified=False)

    def test_sqlite_verified_is_strict(self):
        for value in ('1',1.0,False,2):
            with self.subTest(value=value),self.assertRaises(ValueError):
                checked_image_bytes(self.root,dict(self.record,verified=value))
        self.assertTrue(checked_image_bytes(self.root,dict(self.record,verified=1)))
