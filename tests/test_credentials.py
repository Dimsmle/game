import ast
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from studio import credentials,llm,app
import release_source


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.path=self.root/'local_secrets.json'
        self.env=patch.dict(os.environ,{},clear=True);self.env.start()
        self.location=patch.object(credentials,'secrets_path',return_value=self.path);self.location.start()
    def tearDown(self):self.location.stop();self.env.stop();self.tmp.cleanup()

    def test_file_environment_precedence_and_live_reload(self):
        self.path.write_text(json.dumps({'DEEPSEEK_API_KEY':'file-value'}),encoding='utf-8')
        self.assertEqual(credentials.get_api_key('DEEPSEEK_API_KEY'),'file-value')
        self.assertEqual(credentials.status(),{'present':True,'source':'local_file'})
        self.path.write_text(json.dumps({'DEEPSEEK_API_KEY':'changed'}),encoding='utf-8')
        self.assertEqual(credentials.get_api_key('DEEPSEEK_API_KEY'),'changed')
        os.environ['DEEPSEEK_API_KEY']='environment-value'
        self.assertEqual(credentials.get_api_key('DEEPSEEK_API_KEY'),'environment-value')
        self.assertEqual(credentials.status()['source'],'environment')

    def test_missing_invalid_duplicate_and_oversized_are_safe(self):
        self.assertEqual(credentials.get_api_key('DEEPSEEK_API_KEY'),'')
        for raw in ('{"DEEPSEEK_API_KEY":"do-not-echo"',
                    '{"DEEPSEEK_API_KEY":"first","DEEPSEEK_API_KEY":"second"}',
                    '{"unexpected":"do-not-echo"}', '[]',
                    '{"DEEPSEEK_API_KEY":true}', '{"DEEPSEEK_API_KEY":"a\\r\\nInjected:value"}',
                    '{"DEEPSEEK_API_KEY":"不能作为密钥"}',
                    ' '*17000):
            self.path.write_text(raw,encoding='utf-8')
            with self.subTest(raw_length=len(raw)),self.assertRaises(RuntimeError) as failure:
                credentials.get_api_key('DEEPSEEK_API_KEY')
            self.assertNotIn('do-not-echo',str(failure.exception))
            self.assertEqual(credentials.status()['source'],'invalid')

    def test_local_key_only_in_http_authorization_not_payload_or_public_settings(self):
        self.path.write_text('{"DEEPSEEK_API_KEY":"private-test-value"}',encoding='utf-8')
        stream=io.BytesIO(b'data: [DONE]\n')
        class Opener:
            def open(inner,request,timeout):
                self.assertEqual(request.get_header('Authorization'),'Bearer private-test-value')
                self.assertNotIn(b'private-test-value',request.data)
                return stream
        with patch('urllib.request.build_opener',return_value=Opener()):
            self.assertEqual(list(llm.OpenAICompatibleProvider(dict(app.DEFAULT_SETTINGS,llm_mode='deepseek')).stream([],threading.Event())),[])
        self.assertNotIn('private-test-value',json.dumps(credentials.status()))
        self.assertNotIn('DEEPSEEK_API_KEY',app.DEFAULT_SETTINGS)

    def test_no_environment_assignment_in_app_source(self):
        source=Path(app.__file__).read_text(encoding='utf-8')
        for node in ast.walk(ast.parse(source)):
            if isinstance(node,ast.Assign):
                for target in node.targets:
                    if isinstance(target,ast.Subscript) and isinstance(target.value,ast.Attribute):
                        self.assertFalse(target.value.attr=='environ' and isinstance(target.slice,ast.Constant) and target.slice.value=='DEEPSEEK_API_KEY')

    def test_private_files_excluded_from_source_archive(self):
        (self.root/'studio').mkdir();(self.root/'tests').mkdir();(self.root/'docs').mkdir()
        (self.root/'local_secrets.json').write_text('{"secret":"test"}',encoding='utf-8')
        (self.root/'local_secrets.backup.txt').write_text('test',encoding='utf-8')
        (self.root/'app.py').write_text('pass',encoding='utf-8')
        files=release_source.source_files(self.root)
        self.assertEqual([p.name for p in files],['app.py'])


if __name__=='__main__':unittest.main()
