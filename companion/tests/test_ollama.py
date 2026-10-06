import unittest
from unittest.mock import patch
from ai_scoring.clients.ollama import _NoRedirect
from ai_scoring.clients.ollama import OllamaClient, OllamaError

class FakeLocal:
    def __init__(self): self.calls=[]
    def __call__(self, method, path, body):
        self.calls.append((method,path,body))
        if path=='/api/version': return {'version':'test-only-0.34'}
        if path=='/api/tags': return {'models':[{'name':'gemma3:12b','digest':'sha256:local'}]}
        if path=='/api/show': return {'capabilities':['vision','completion'],'details':{'family':'gemma3'}}
        if path=='/api/chat': return {'done':True,'message':{'role':'assistant','content':'{"visibility":"clear"}'}}
        raise AssertionError(path)

class OllamaClientTests(unittest.TestCase):
    def test_remote_endpoints_and_cloud_models_rejected_before_transport(self):
        for endpoint in ('https://ollama.com','http://localhost:11434','http://10.0.0.2:11434','http://127.0.0.1:11434/path','http://user:pass@127.0.0.1:11434'):
            with self.subTest(endpoint=endpoint),self.assertRaises(OllamaError): OllamaClient('gemma3:12b',endpoint=endpoint,transport=FakeLocal())
        with self.assertRaises(OllamaError): OllamaClient('gemma4:cloud',transport=FakeLocal())
    def test_local_vision_verified_and_chat_schema_uses_images_fixed_seed(self):
        fake=FakeLocal(); client=OllamaClient('gemma3:12b',transport=fake)
        result=client.describe(['cG5n'],'prompt',{'type':'object'},seed=7)
        self.assertEqual(result['visibility'],'clear')
        body=fake.calls[-1][2]
        self.assertEqual(body['messages'][0]['images'],['cG5n'])
        self.assertEqual(body['options'],{'temperature':0,'seed':7})
        self.assertEqual(body['format'],{'type':'object'})
        self.assertFalse(body['stream'])
        self.assertEqual(client.identity['digest'],'sha256:local')

    def test_proxy_environment_ignored_redirects_rejected_and_close_prevents_inference(self):
        with patch('urllib.request.getproxies',side_effect=AssertionError('proxy environment consulted')):
            client=OllamaClient('gemma3:12b',transport=FakeLocal())
        with self.assertRaises(OllamaError): _NoRedirect().redirect_request(None,None,302,'redirect',{},'https://example.com')
        client.close()
        with self.assertRaises(OllamaError): client.describe([],'prompt',{},seed=0)
    def test_missing_vision_or_local_digest_is_rejected(self):
        for capability in ([],['completion']):
            def transport(method,path,body):
                if path=='/api/version': return {'version':'test-only'}
                if path=='/api/tags': return {'models':[{'name':'gemma3:12b','digest':'local'}]}
                return {'capabilities':capability}
            with self.assertRaises(OllamaError): OllamaClient('gemma3:12b',transport=transport)
