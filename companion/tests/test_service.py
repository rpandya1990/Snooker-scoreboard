import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from ai_scoring.dao.jsonl import JsonlSessionStore, IdentityConflict
from ai_scoring.domain.scoring import Ball, PotObservation
from ai_scoring.services.scoring import ScoringService, EventConflict

class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = JsonlSessionStore(self.directory.name, 's')
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.service = ScoringService(self.store, clock=lambda: self.now)
        self.service.apply_event({'eventId':'f','sequence':1,'type':'frame_started','frameId':'f','runId':'r'})
        self.service.confirm_baseline(self.now.isoformat())
    def tearDown(self):
        self.store.close()
        self.directory.cleanup()
    def commit(self, prediction=None, source='manual', points=12):
        return {'eventId':'e','sequence':2,'type':'break_committed','frameId':'f','runId':'r','nextRunId':'r2','entryId':'entry','attemptId':'attempt', 'inputStartedAt':self.now.isoformat(),'committedAt':self.now.isoformat(),'predictionId':prediction,'submittedPoints':points,'appliedScoreDelta':points,'source':source}
    def test_frozen_prediction_mismatch_and_retry(self):
        self.service.observe(PotObservation('p', Ball.RED, self.now.isoformat()))
        prediction = self.service.publish_prediction()
        prediction['points'] = 999
        event = self.commit(prediction['predictionId'])
        ack = self.service.apply_event(event)
        self.assertEqual(ack, self.service.apply_event(event))
        self.assertEqual(self.service.rules.points, 0)
        self.assertEqual(self.service.rules.reds, 14)
        comparison = self.store.records[-1]['payload']['comparison']
        self.assertEqual(comparison['predictedPoints'], 1)
        self.assertFalse(comparison['agreement'])
        self.assertTrue(comparison['reviewRequired'])
        with self.assertRaises(IdentityConflict):
            self.service.apply_event(dict(event, submittedPoints=13))
    def test_null_prediction_and_undo(self):
        self.service.apply_event(self.commit())
        self.assertIsNone(self.store.records[-1]['payload']['comparison']['agreement'])
        self.service.apply_event({'eventId':'undo','sequence':3,'type':'undo','frameId':'f','entryId':'entry'})
        self.assertEqual(self.service.entries['entry']['labelStatus'],'invalidated')
        self.assertEqual(self.service.run_id,'r2')
    def test_ai_acceptance_not_independent_label(self):
        prediction = self.service.publish_prediction()
        self.service.apply_event(self.commit(prediction['predictionId'],'ai_selected',0))
        self.assertEqual(self.store.records[-1]['payload']['comparison']['labelStatus'],'ai_influenced')
    def test_missing_sequence_and_late_prediction(self):
        with self.assertRaises(EventConflict):
            self.service.apply_event(dict(self.commit(),sequence=3))
        prediction = self.service.publish_prediction()
        event = self.commit(prediction['predictionId'])
        event['inputStartedAt']=(self.now-timedelta(seconds=1)).isoformat()
        with self.assertRaises(EventConflict):
            self.service.apply_event(event)
    def test_discontinuity_and_restart_suppress(self):
        self.service.publish_prediction()
        self.service.discontinuity()
        self.assertEqual(self.service.latest_prediction()['status'],'unavailable')
        self.store.close()
        self.store=JsonlSessionStore(self.directory.name,'s')
        self.service=ScoringService(self.store,clock=lambda:self.now)
        self.assertIn('restart',self.service.latest_prediction()['qualityReasons'])
    def test_stale_prediction(self):
        self.service.publish_prediction()
        self.now += timedelta(seconds=4)
        self.assertIn('stale',self.service.latest_prediction()['qualityReasons'])
    def test_delayed_boundary_suppresses_next_run(self):
        prediction=self.service.publish_prediction()
        event=self.commit(prediction['predictionId'])
        self.now += timedelta(seconds=1)
        self.service.observe(PotObservation('later',Ball.RED,self.now.isoformat()))
        self.service.apply_event(event)
        self.assertIn('boundary_unsynchronised',self.service.publish_prediction()['qualityReasons'])
