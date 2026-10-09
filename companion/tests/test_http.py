import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone, timedelta
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from ai_scoring.config import Config, Mode
from ai_scoring.services.sessions import SessionManager
from ai_scoring.services.scoring import EventConflict
from ai_scoring.activity.http import handler_for

class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.manager=SessionManager(Config(self.directory.name, Mode.DRY_RUN))
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(self.manager,'test-secret-token'))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.manager.close()
        self.directory.cleanup()
    def request(self, method, path, body=None, authorized=True):
        connection=HTTPConnection('127.0.0.1',self.server.server_port)
        headers={'Authorization':'Bearer test-secret-token'} if authorized else {}
        data=json.dumps(body) if body is not None else None
        connection.request(method,path,data,headers)
        response=connection.getresponse()
        result=(response.status,json.loads(response.read()))
        connection.close()
        return result
    def test_lifecycle_auth_idempotency_and_conflict(self):
        session={'sessionId':'s','mode':'dry-run'}
        self.assertEqual(self.request('POST','/v1/sessions',session,False)[0],401)
        self.assertEqual(self.request('POST','/v1/sessions',session)[0],200)
        self.assertEqual(self.request('POST','/v1/sessions',session)[0],200)
        self.assertEqual(len(self.manager.get('s').store.records),1)
        self.assertEqual(self.request('POST','/v1/sessions',dict(session,sessionId='other'))[0],409)
        event={'eventId':'f','sequence':1,'type':'frame_started','frameId':'f','runId':'r'}
        self.assertEqual(self.request('POST','/v1/sessions/s/events',event)[0],200)
        self.assertEqual(self.request('POST','/v1/sessions/s/events',event)[0],200)
        status,pred=self.request('GET','/v1/sessions/s/prediction')
        self.assertEqual(status,200)
        self.assertEqual(pred['status'],'unavailable')
        self.assertIn('serverTimestamp',self.request('POST','/v1/sessions/s/heartbeat',{})[1])
    def test_off_and_lease(self):
        now=datetime.now(timezone.utc)
        manager=SessionManager(Config(self.directory.name,Mode.OFF),clock=lambda:now)
        with self.assertRaises(EventConflict):
            manager.open({'sessionId':'s','mode':'dry-run'})
        manager=SessionManager(Config(self.directory.name,Mode.DRY_RUN),clock=lambda:now)
        manager.open({'sessionId':'leased','mode':'dry-run'})
        now += timedelta(seconds=31)
        with self.assertRaises(EventConflict):
            manager.get('leased')
        manager.close()
    def test_stopped_event_retry_retains_ack(self):
        self.request('POST','/v1/sessions',{'sessionId':'s','mode':'dry-run'})
        stop={'eventId':'stop','sequence':1,'type':'session_stopped'}
        first=self.request('POST','/v1/sessions/s/events',stop)
        self.assertEqual(first[0],200)
        self.assertEqual(first,self.request('POST','/v1/sessions/s/events',stop))
        self.assertTrue(self.request('POST','/v1/sessions',{'sessionId':'s','mode':'dry-run'})[1]['stopped'])
    def test_session_contract_without_alias_or_camera_credentials(self):
        secret='rtsp://fake:private@host/stream'
        status,response=self.request('POST','/v1/sessions',{'sessionId':'s','mode':'dry-run','cameraUrl':secret})
        self.assertEqual(status,200)
        self.assertNotIn('cameraAlias',response)
        self.assertNotIn(secret,json.dumps(response))
        opened=self.manager.get('s').store.records[0]['payload']
        self.assertEqual(opened,{'sessionId':'s','mode':'dry-run'})
