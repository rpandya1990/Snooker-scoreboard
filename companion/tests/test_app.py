import importlib.util
import io
from contextlib import redirect_stderr,redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from ai_scoring.app import main

class AppBootstrapTests(unittest.TestCase):
    def test_ordinary_lan_http_requires_token_but_no_certificates(self):
        server=Mock()
        server.serve_forever.side_effect=KeyboardInterrupt
        manager=Mock()
        with tempfile.TemporaryDirectory() as directory,patch.dict('os.environ',{'AI_SCORING_API_TOKEN':'test-pairing-token'}),patch('ai_scoring.app.SessionManager',return_value=manager),patch('ai_scoring.app.ThreadingHTTPServer',return_value=server) as factory,patch('ai_scoring.app.ssl.SSLContext') as tls:
            main(['--data-directory',directory,'--mode','dry-run','--host','0.0.0.0'])
            self.assertEqual(factory.call_args.args[0],('0.0.0.0',8443))
            tls.assert_not_called()
            server.server_close.assert_called_once()
            manager.close.assert_called_once()
    def test_partial_tls_options_rejected_before_service_activation(self):
        with patch.dict('os.environ',{'AI_SCORING_API_TOKEN':'test-pairing-token'}),patch('ai_scoring.app.SessionManager') as manager:
            with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                main(['--data-directory','/unused','--mode','dry-run','--cert','/unused-cert'])
            manager.assert_not_called()
    def test_optional_tls_uses_supplied_certificate_and_key(self):
        server=Mock()
        server.serve_forever.side_effect=KeyboardInterrupt
        context=Mock()
        with patch.dict('os.environ',{'AI_SCORING_API_TOKEN':'test-pairing-token'}),patch('ai_scoring.app.SessionManager'),patch('ai_scoring.app.ThreadingHTTPServer',return_value=server),patch('ai_scoring.app.ssl.SSLContext',return_value=context):
            main(['--data-directory','/unused','--mode','dry-run','--cert','/cert','--key','/key'])
            context.load_cert_chain.assert_called_once_with(Path('/cert'),Path('/key'))
            context.wrap_socket.assert_called_once()
    def test_off_constructs_no_service(self):
        with redirect_stdout(io.StringIO()),patch('ai_scoring.app.SessionManager') as manager,patch('ai_scoring.app.ThreadingHTTPServer') as server:
            main(['--data-directory','/unused'])
            manager.assert_not_called()
            server.assert_not_called()
    def test_retired_tools_not_present_in_installed_package(self):
        for name in ('replay','dataset','recorded_dataset','probe','services.evaluation','services.offline_replay','services.datasets','clients.probe'):
            with self.subTest(name=name):
                self.assertIsNone(importlib.util.find_spec('ai_scoring.'+name))
