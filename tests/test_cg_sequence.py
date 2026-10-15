"""CG decoding and pinned bundles, all synthetic data and zero cloud calls."""
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from studio import cg_ipt,cg_sequence


def make_group(root):
    folder=Path('assets_pfs_003/image/ev/ev_shi_c04');p=root/folder;p.mkdir(parents=True)
    Image.new('RGBA',(8,6),(10,20,30,255)).save(p/'ev_shi_c04_01.png')
    Image.new('RGBA',(2,2),(210,20,30,128)).save(p/'ev_shi_c04_02.png')
    (p/'ev_shi_c04_02.ipt').write_text('ipt={mode="diff",base={"ev_shi_c04_01",x=-1,y=-2,w=8,h=6,ax=4,ay=3},{id=1,file="ev_shi_c04_02",x=2,y=1},}',encoding='utf-8')
    script=root/'assets_pfs_main/script';script.mkdir(parents=True)
    (script/'sample.ast').write_text('{"bg",file="ev_shi_c04_01",set="ev_shi_c04",path=":ev/ev_shi_c04/",time=0},\n{"bg",file="ev_shi_c04_02",set="ev_shi_c04",path=":ev/ev_shi_c04/",time=400,zoom=130},',encoding='utf-8')
    return folder


class CGSequenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.folder=make_group(self.root)

    def test_alpha_composite_and_negative_parent_offset(self):
        image,origin=cg_ipt.reconstruct(self.root,self.folder,'ev_shi_c04_02')
        self.assertEqual(image.size,(8,6));self.assertEqual(origin,{'x':-1,'y':-2})
        self.assertEqual(image.getpixel((0,0)),(10,20,30,255))
        self.assertEqual(image.getpixel((2,1)),(110,20,30,255));image.close()

    def test_no_executable_lua_or_path_traversal(self):
        for text in ('ipt={mode=os.execute("bad")}','ipt={mode="diff"};run()','ipt={mode="diff",mode="diff"}'):
            with self.subTest(text=text),self.assertRaises(ValueError):cg_ipt.literal_table(text,True)
        path=self.root/self.folder/'ev_shi_c04_02.ipt'
        path.write_text('ipt={mode="diff",base={"../outside"},{id=1,file="ev_shi_c04_02",x=0,y=0}}')
        with self.assertRaises(ValueError):cg_ipt.reconstruct(self.root,self.folder,'ev_shi_c04_02')

    def test_cycles_and_unsupported_mode_refused(self):
        path=self.root/self.folder/'ev_shi_c04_02.ipt'
        path.write_text('ipt={mode="diff",base={"ev_shi_c04_02"},{id=1,file="ev_shi_c04_02",x=0,y=0}}')
        with self.assertRaises(ValueError):cg_ipt.reconstruct(self.root,self.folder,'ev_shi_c04_02')
        path.write_text('ipt={mode="anime",base={"ev_shi_c04_01"}}')
        with self.assertRaises(ValueError):cg_ipt.reconstruct(self.root,self.folder,'ev_shi_c04_02')

    def test_bundle_inputs_output_and_script_order_pinned(self):
        before={p.name:p.read_bytes() for p in (self.root/self.folder).iterdir()}
        item=cg_sequence.build(self.root,'ev_shi_c04');doc=cg_sequence.load(self.root,item)
        self.assertEqual(len(doc['frames']),2);self.assertFalse(item['verified'])
        self.assertEqual([s['frame'] for s in doc['steps']],['ev_shi_c04_01','ev_shi_c04_02'])
        self.assertEqual(doc['steps'][1]['transition_ms'],400);self.assertIn('zoom',doc['unsupported'])
        public=cg_sequence.public(self.root,item)
        self.assertNotIn('relative_path',str(public));self.assertNotIn('assets_pfs',str(public))
        self.assertEqual(cg_sequence.build(self.root,'ev_shi_c04')['asset_id'],item['asset_id'])
        self.assertEqual(before,{p.name:p.read_bytes() for p in (self.root/self.folder).iterdir()})

    def test_original_or_derived_changes_invalidate(self):
        item=cg_sequence.build(self.root,'ev_shi_c04');doc=cg_sequence.load(self.root,item)
        frame=self.root/doc['frames'][0]['relative_path'];frame.write_bytes(b'corrupt')
        with self.assertRaises(ValueError):cg_sequence.load(self.root,item)
        item=cg_sequence.build(self.root,'ev_shi_c04')
        (self.root/self.folder/'ev_shi_c04_02.ipt').write_text('changed')
        with self.assertRaises(ValueError):cg_sequence.load(self.root,item)

    def test_patch_script_precedence_and_no_guess_without_script(self):
        patch=self.root/'assets_pfs_004/script';patch.mkdir(parents=True)
        (patch/'sample.ast').write_text('{"bg",file="ev_shi_c04_02",set="ev_shi_c04",path=":ev/ev_shi_c04/",time=900},')
        item=cg_sequence.build(self.root,'ev_shi_c04');doc=cg_sequence.load(self.root,item)
        self.assertEqual(len(doc['steps']),1);self.assertEqual(doc['steps'][0]['transition_ms'],900)
        self.assertTrue(doc['script'].startswith('assets_pfs_004/'))
        (patch/'sample.ast').write_text('no matching scene')
        with self.assertRaises(ValueError):cg_sequence.build(self.root,'ev_shi_c04')

    def test_strict_frame_index_and_group_identifier(self):
        item=cg_sequence.build(self.root,'ev_shi_c04')
        for index in (-1,True,99):
            with self.assertRaises(ValueError):cg_sequence.frame_bytes(self.root,item,index)
        with self.assertRaises(ValueError):cg_sequence.build(self.root,'../secret')

    def test_unknown_mode_never_runs(self):
        p=self.root/self.folder/'ev_shi_c04_02.ipt';p.write_text('ipt={mode="exani",base={"ev_shi_c04_01"},lua="run"}')
        with self.assertRaises(ValueError):cg_sequence.build(self.root,'ev_shi_c04')
