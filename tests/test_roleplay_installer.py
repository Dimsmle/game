import ast
import importlib.util
from pathlib import Path
import unittest
import os
import tempfile
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("rp_installer",ROOT/"tools/install_addon.py")
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)

class InstallerTests(unittest.TestCase):
    def test_unguarded_replacement_rejected(self):
        with self.assertRaises(ValueError):installer.patch_app("import os\n")
    def test_double_install_rejected(self):
        with self.assertRaisesRegex(ValueError,"已经接入"):
            installer.patch_app(installer.MARKER+"\n")
    def test_once_requires_unique_anchor(self):
        with self.assertRaises(ValueError):installer.once("aaa","a","b","fail")
    def test_secret_scrub_only_recognized_literal(self):
        source='import os\nos.environ["DEEPSEEK_API_KEY"] = "sk-' + 'not-a-real-key-for-test' + '"\n'
        clean,count=installer.scrub_embedded_key(source)
        self.assertEqual(count,1)
        self.assertNotIn('not-a-real-key-for-test',clean)
        self.assertIn('configure DEEPSEEK_API_KEY',clean)
        ast.parse(clean)

    def test_secret_scrub_rejects_unknown_secret_expression(self):
        with self.assertRaisesRegex(ValueError,'密钥'):
            installer.scrub_embedded_key('token="sk-'+'unknown_fake_secret_00000'+'"')

    def test_diff_redacts_secret(self):
        text='-os.environ["DEEPSEEK_API_KEY"] = "sk-'+'unreal_dummy_1234567890'+'"'
        cleaned=installer.redact_diff(text)
        self.assertNotIn('unreal_dummy',cleaned)
        self.assertIn('sk-REDACTED',cleaned)

    def test_env_loader_only_reads_authorized_name(self):
        from studio.roleplay_plus.bridge import load_project_env
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'.env'
            p.write_text('ANOTHER_KEY=secret123\nDEEPSEEK_API_KEY="sk-'+'dummy_only_1234'+'"\n',encoding='utf-8')
            with mock.patch.dict(os.environ,{},clear=True):
                self.assertTrue(load_project_env(d))
                self.assertEqual(os.environ.get('DEEPSEEK_API_KEY'),'sk-'+'dummy_only_1234')
                self.assertNotIn('ANOTHER_KEY',os.environ)
                self.assertFalse(load_project_env(d))

    def test_env_loader_preserves_existing_value(self):
        from studio.roleplay_plus.bridge import load_project_env
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'.env').write_text('DEEPSEEK_API_KEY=unused',encoding='utf-8')
            with mock.patch.dict(os.environ,{'DEEPSEEK_API_KEY':'already-set'},clear=True):
                self.assertFalse(load_project_env(d))
                self.assertEqual(os.environ['DEEPSEEK_API_KEY'],'already-set')

    def test_addon_import_syntax(self):
        for file in (ROOT/"studio/roleplay_plus").glob("*.py"):
            ast.parse(file.read_text(encoding="utf-8"))

if __name__=="__main__":unittest.main()
