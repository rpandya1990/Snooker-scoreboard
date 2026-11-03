from datetime import datetime,timedelta,timezone
import tempfile
import unittest
from ai_scoring.config import InferenceConfig
from ai_scoring.dao.jsonl import JsonlSessionStore
from ai_scoring.domain.ball_detection import Inventory
from ai_scoring.domain.visual_adapter import TimestampedFrame
from ai_scoring.clients.live_capture import CapturedFrame
from ai_scoring.services.inventory_adapter import InventoryVisualAdapter, COLOURS
from ai_scoring.services.scoring import ScoringService
from ai_scoring.services.live_observer import LiveObserver

ALL=frozenset(COLOURS)
NO_BLUE=ALL-{'blue'}
# Frame value -> what the detector would read from that frame.
TABLES={0:Inventory('clear',15,ALL),1:Inventory('clear',14,ALL),2:Inventory('clear',14,NO_BLUE),
        3:Inventory('occluded',0,frozenset()),4:Inventory('clear',13,ALL),5:Inventory('clear',15,ALL-{'pink'})}

class ShotObserverTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.store=JsonlSessionStore(self.directory.name,'s')
        self.now=datetime(2026,1,1,tzinfo=timezone.utc);self.mono=0
        self.service=ScoringService(self.store,clock=lambda:self.now)
        self.service.apply_event({'eventId':'frame','sequence':1,'type':'frame_started','frameId':'f','runId':'r'})
        self.reads=[]
        def reader(frame):
            self.reads.append(frame.media_time);return TABLES[frame.data[0]]
        self.adapter=InventoryVisualAdapter({'stableSeconds':.5},reader=reader)
        self.settings=InferenceConfig(enabled=True,inference_trigger='shot',max_frame_gap_seconds=.5,capture_uncertainty_ms=100,stable_seconds=.5)
        self.observer=LiveObserver(self.service,self.settings,None,adapter=self.adapter,clock=lambda:self.now,monotonic=lambda:self.mono)
        self.second=0.
    def tearDown(self):
        self.observer.close();self.store.close();self.directory.cleanup()
    def feed(self,value,seconds=.2):
        """Feed frames of one table state at 10 fps for the given duration."""
        for _ in range(round(seconds*10)):
            self.second=round(self.second+.1,3)
            self.now=datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(seconds=self.second);self.mono=self.second
            frame=TimestampedFrame(bytes([value])*4*4*3,self.now.isoformat(),'fixture',self.second,100,4,4)
            self.observer.submit(CapturedFrame(frame,'capture',self.now.isoformat(),self.second,'estimated'))
    def prediction(self):
        return self.service.latest_prediction()
    def test_every_frame_is_read_and_stable_table_becomes_baseline(self):
        self.feed(0,.3)
        self.assertFalse(self.service.baseline_initialized)
        self.feed(0,.4)
        self.assertTrue(self.service.baseline_initialized)
        self.assertEqual(len(self.reads),7)
        self.assertEqual((self.prediction()['status'],self.prediction()['points']),('available',0))
        self.assertEqual(self.observer.health['trackingState'],'steady')
    def test_pot_hides_suggestion_until_stable_then_scores(self):
        self.feed(0,1)
        self.feed(1,.2)
        self.assertEqual(self.prediction()['status'],'unavailable')
        self.feed(1,.5)
        self.assertEqual((self.prediction()['status'],self.prediction()['points']),('available',1))
    def test_colour_pot_and_respot_seen_between_busy_frames_scores_both(self):
        self.feed(0,1)
        self.feed(3,2);self.feed(1,.7)          # player over table, red potted
        self.feed(3,1);self.feed(2,.7)          # blue potted, waiting for respot
        self.feed(3,1);self.feed(1,.7)          # blue back on its spot
        self.assertEqual((self.prediction()['status'],self.prediction()['points']),('available',6))
        kinds=[(r['payload']['kind'],r['payload']['ball']) for r in self.store.records if r['type']=='observation']
        self.assertEqual(kinds,[('pot','red'),('pot','blue'),('respot','blue')])
    def test_occluded_and_flickering_frames_never_confirm_a_change(self):
        self.feed(0,1)
        for _ in range(5):self.feed(1,.2);self.feed(3,.2)
        self.feed(0,.3)
        self.assertEqual(self.service.rules.points,0)
        self.assertEqual((self.prediction()['status'],self.prediction()['points']),('available',0))
    def test_impossible_change_abstains_for_the_frame(self):
        self.feed(0,1)
        self.feed(1,.7);self.feed(0,.7)
        self.assertIn('inventory_reds_increased',self.service.reasons)
        self.assertEqual(self.prediction()['status'],'unavailable')
    def test_uninterpretable_start_waits_and_logs_once(self):
        self.feed(5,3)
        self.assertFalse(self.service.baseline_initialized)
        checks=[r for r in self.store.records if r['type']=='visual_diagnostic' and r['payload']['reason']=='baseline_check']
        self.assertEqual(len(checks),1)
        self.feed(0,.7)
        self.assertTrue(self.service.baseline_initialized)
    def test_capture_gap_after_baseline_blocks_later_changes(self):
        self.feed(0,1)
        self.second+=2;self.feed(0,.2)
        self.assertIn('sample_coverage_gap',self.service.reasons)
        self.feed(1,.7)
        self.assertIn('capture_discontinuity',self.service.reasons)
        self.assertEqual(self.service.rules.points,0)
    def test_config_rejects_invalid_tracking_limits(self):
        for kwargs in ({'inference_trigger':'bad'},{'stable_seconds':0},{'stable_seconds':11}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):InferenceConfig(**kwargs)

if __name__=='__main__':
    unittest.main()
