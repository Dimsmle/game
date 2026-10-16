"""Transport failures must not produce a second response on a closed socket."""
import unittest
from unittest.mock import Mock
from studio.app import Handler


class DisconnectTests(unittest.TestCase):
    def handler(self):
        handler=Handler.__new__(Handler)
        handler.send_response=Mock()
        handler.send_header=Mock()
        handler.end_headers=Mock()
        handler.wfile=Mock()
        return handler

    def test_peer_disconnect_during_headers_or_body_is_not_retried(self):
        for error in (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):
            for phase in ('end_headers','body'):
                with self.subTest(error=error.__name__,phase=phase):
                    handler=self.handler()
                    target=handler.end_headers if phase=='end_headers' else handler.wfile.write
                    target.side_effect=error(10053,'peer disconnected')
                    self.assertFalse(handler.reply(200,{'items':[]}))
                    self.assertTrue(handler.close_connection)
                    handler.err(ValueError('must not retry'))
                    self.assertEqual(handler.send_response.call_count,1)
                    self.assertEqual(target.call_count,1)

    def test_other_errors_are_not_hidden(self):
        handler=self.handler()
        handler.wfile.write.side_effect=OSError('unrelated IO failure')
        with self.assertRaises(OSError):handler.reply(200,{})
        with self.assertRaises(TypeError):handler.reply(200,{'bad':object()})

    def test_normal_response_keeps_headers_and_body(self):
        handler=self.handler()
        self.assertTrue(handler.reply(200,{'ok':True}))
        handler.send_header.assert_any_call('X-Content-Type-Options','nosniff')
        self.assertEqual(handler.wfile.write.call_args.args[0],b'{"ok": true}')
