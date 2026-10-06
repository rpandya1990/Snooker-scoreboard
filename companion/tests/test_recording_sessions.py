from datetime import datetime, timezone, timedelta
from threading import Event
import tempfile
import unittest
from ai_scoring.config import Config, Mode, RecordingConfig
from ai_scoring.services.sessions import SessionManager

class FakeRecorder:
    def __init__(self,store,config,source,**kwargs):
        self.store=store
        self.started=0
        self.closed=Event()
        self.reason=None
    def start(self):
        self.started+=1
    def close(self,reason='shutdown'):
        self.reason=reason
        self.closed.set()
    def cleanup(self):
        pass

class RecordingSessionTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.now=datetime(2026,1,1,tzinfo=timezone.utc)
        self.recorders=[]
        def factory(*args,**kwargs):
            recorder=FakeRecorder(*args,**kwargs)
            self.recorders.append(recorder)
            return recorder
        self.manager=SessionManager(Config(self.directory.name,Mode.DRY_RUN,camera_url='rtsp://fake:fake@localhost/stream',
            recording=RecordingConfig(True,60,10000,100,5)),clock=lambda:self.now,recording_factory=factory,watchdog_seconds=.01)
        self.metadata={'sessionId':'s','mode':'dry-run','cameraAlias':'table'}
    def tearDown(self):
        self.manager.close()
        self.directory.cleanup()
    def test_lease_expiry_stops_without_an_api_request(self):
        self.manager.open(self.metadata)
        self.now+=timedelta(seconds=31)
        self.assertTrue(self.recorders[0].closed.wait(1))
        self.assertEqual(self.recorders[0].reason,'lease_expired')
        self.assertIsNone(self.manager._active)
    def test_reopen_and_stopped_ack_do_not_restart_recording(self):
        self.manager.open(self.metadata)
        self.manager.open(self.metadata)
        self.assertEqual(len(self.recorders),1)
        self.assertEqual(self.recorders[0].started,1)
        stop={'eventId':'stop','sequence':1,'type':'session_stopped'}
        ack=self.manager.event('s',stop)
        self.assertTrue(self.recorders[0].closed.is_set())
        self.assertTrue(self.manager.open(self.metadata)['stopped'])
        self.assertEqual(ack,self.manager.event('s',stop))
        self.assertEqual(len(self.recorders),1)
    def test_capture_factory_failure_does_not_reject_score_events(self):
        def broken(*args,**kwargs):
            raise OSError('fake secret cannot be exposed')
        self.manager._recording_factory=broken
        self.manager.open(self.metadata)
        self.manager.event('s',{'eventId':'frame','sequence':1,'type':'frame_started','frameId':'f','runId':'r'})
        self.assertEqual(self.manager.get('s').sequence,1)
    def test_shutdown_finalizes_before_store_close(self):
        self.manager.open(self.metadata)
        self.manager.close()
        self.assertTrue(self.recorders[0].closed.is_set())
        self.assertEqual(self.recorders[0].reason,'shutdown')
    def test_expired_lease_reopen_starts_one_new_worker(self):
        self.manager.open(self.metadata)
        original=self.recorders[0]
        self.now+=timedelta(seconds=31)
        self.manager.open(self.metadata)
        self.assertTrue(original.closed.is_set())
        self.assertEqual(original.reason,'lease_expired')
        self.assertEqual(len(self.recorders),2)
        self.assertIsNot(self.recorders[1],original)
        self.assertEqual(self.recorders[1].started,1)
        self.manager.open(self.metadata)
        self.assertEqual(len(self.recorders),2)
        self.assertIn('lease_expired',[r['payload'].get('reason') for r in self.manager.get('s').store.records])

    def test_completed_source_does_not_restart_on_duplicate_open(self):
        self.manager.open(self.metadata)
        self.recorders[0].close('source_ended')
        self.manager.open(self.metadata)
        self.assertEqual(len(self.recorders),1)
        self.assertEqual(self.recorders[0].started,1)
