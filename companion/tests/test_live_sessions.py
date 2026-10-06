from datetime import datetime,timedelta,timezone
from threading import Event
import tempfile
import unittest
from ai_scoring.config import Config,Mode,InferenceConfig
from ai_scoring.services.sessions import SessionManager

class FakeObserver:
    def __init__(self,*args,**kwargs):
        self.started=0
        self.closed=Event()
        self.health={'status':'observing'}
    def start(self):
        self.started+=1
    def close(self,reason='shutdown'):
        self.closed.set()
        self.health={'status':'stopped','reason':reason}

class LiveSessionTests(unittest.TestCase):
    def test_inference_independent_recording_and_periodic_lease_lifetime(self):
        with tempfile.TemporaryDirectory() as directory:
            now=datetime(2026,1,1,tzinfo=timezone.utc)
            observers=[]
            def factory(*args,**kwargs):
                observer=FakeObserver(*args,**kwargs)
                observers.append(observer)
                return observer
            manager=SessionManager(Config(directory,Mode.DRY_RUN,inference=InferenceConfig(enabled=True,model='fixture')),
                clock=lambda:now,inference_factory=factory,watchdog_seconds=.01,
                recording_factory=lambda *a,**k:self.fail('recording constructed'))
            request={'sessionId':'s','mode':'dry-run','cameraAlias':'table'}
            try:
                response=manager.open(request)
                self.assertEqual(response['inferenceHealth']['status'],'observing')
                manager.open(request)
                self.assertEqual(len(observers),1)
                now+=timedelta(seconds=31)
                self.assertTrue(observers[0].closed.wait(1))
                manager.open(request)
                self.assertEqual(len(observers),2)
                manager.event('s',{'eventId':'stop','sequence':1,'type':'session_stopped'})
                self.assertTrue(observers[1].closed.is_set())
                manager.open(request)
                self.assertEqual(len(observers),2)
            finally:
                manager.close()
