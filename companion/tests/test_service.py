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
    def test_full_table_baseline_clears_earlier_failures_but_not_ongoing_conditions(self):
        self.service.apply_event({'eventId':'f2','sequence':2,'type':'frame_started','frameId':'f2','runId':'r2'})
        self.service.discontinuity('inference_queue_dropped_window')
        self.service.visual_failure('exposure_time_unresolved',discontinue=False)
        self.service.confirm_baseline(self.now.isoformat())
        self.assertEqual(self.service.reasons,{'exposure_time_unresolved'})
        replayed=ScoringService(self.store,clock=lambda:self.now)
        self.assertIn('exposure_time_unresolved',replayed.reasons)
        self.assertNotIn('inference_queue_dropped_window',replayed.reasons)
    def test_midframe_baseline_scores_only_from_next_visit(self):
        self.service.apply_event({'eventId':'f2','sequence':2,'type':'frame_started','frameId':'f2','runId':'r2'})
        self.service.confirm_baseline(self.now.isoformat(),9,('yellow','green','brown','blue','pink','black'))
        self.assertEqual(self.service.rules.reds,9)
        self.assertIn('run_started_before_baseline',self.service.reasons)
        self.service.apply_event({'eventId':'c','sequence':3,'type':'break_committed','frameId':'f2','runId':'r2','nextRunId':'r3','entryId':'entry2','attemptId':'a',
            'inputStartedAt':self.now.isoformat(),'committedAt':self.now.isoformat(),'predictionId':None,'submittedPoints':5,'appliedScoreDelta':5,'source':'manual'})
        self.assertEqual(self.service.reasons,set())
        self.service.observe(PotObservation('p2',Ball.RED,self.now.isoformat()))
        self.assertEqual(self.service.publish_prediction()['points'],1)
        replayed=ScoringService(self.store,clock=lambda:self.now)
        self.assertEqual((replayed.rules.reds,replayed.rules.points),(8,1))
    def test_clearance_baseline_starts_at_lowest_remaining_colour(self):
        self.service.apply_event({'eventId':'f2','sequence':2,'type':'frame_started','frameId':'f2','runId':'r2'})
        self.service.confirm_baseline(self.now.isoformat(),0,('blue','pink','black'))
        self.assertEqual(self.service.rules.ball_on,'blue')
        with self.assertRaises(ValueError):self.service.confirm_baseline(self.now.isoformat(),0,('yellow','black'))
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

    def test_pending_work_suppresses_cached_prediction_without_poisoning_rules(self):
        context,epoch=self.service.visual_context(self.now.isoformat())
        prediction=self.service.publish_prediction()
        token=self.service.mark_inference_pending(context,epoch)
        self.assertIn('shot_in_progress',self.service.latest_prediction()['qualityReasons'])
        self.assertIsNone(self.service.latest_prediction()['points'])
        self.assertNotIn('shot_in_progress',self.service.reasons)
        self.assertTrue(self.service.finish_inference_pending(token,context,epoch))
        self.assertIn('new_activity',self.service.latest_prediction()['qualityReasons'])
        self.assertGreater(self.service.activity_version,prediction['activityVersion'])

    def test_old_work_cannot_clear_new_token_and_commit_invalidates_unresolved_physics(self):
        context,epoch=self.service.visual_context(self.now.isoformat())
        first=self.service.mark_inference_pending(context,epoch)
        self.assertTrue(self.service.finish_inference_pending(first,context,epoch))
        second=self.service.mark_inference_pending(context,epoch)
        self.assertFalse(self.service.finish_inference_pending(first,context,epoch))
        self.assertIn('shot_in_progress',self.service.latest_prediction()['qualityReasons'])
        self.service.apply_event(self.commit())
        self.assertFalse(self.service.finish_inference_pending(second,context,epoch))
        self.assertIn('boundary_unsynchronised',self.service.latest_prediction()['qualityReasons'])

    def test_quiet_renewal_requires_no_pending_or_hard_uncertainty_and_known_clock(self):
        from ai_scoring.domain.visual_adapter import TimestampedFrame
        self.service.publish_prediction(ttl_seconds=1)
        self.now+=timedelta(seconds=2)
        context,epoch=self.service.visual_context(self.now.isoformat())
        quiet=TimestampedFrame(b'pixels',self.now.isoformat(),'asset',2,0)
        token=self.service.mark_inference_pending(context,epoch)
        self.assertFalse(self.service.advance_verified_quiet(context,epoch,quiet))
        self.service.finish_inference_pending(token,context,epoch)
        self.assertTrue(self.service.advance_verified_quiet(context,epoch,quiet))
        self.assertEqual(self.service.latest_prediction()['status'],'available')
        self.service.discontinuity('feed_gap')
        self.assertFalse(self.service.advance_verified_quiet(context,epoch,quiet))

    def test_resolved_result_atomically_clears_only_its_work_and_publishes_new_score(self):
        from ai_scoring.domain.visual_adapter import TimestampedFrame, VisualResult
        self.service.publish_prediction()
        self.now+=timedelta(seconds=1)
        context,epoch=self.service.visual_context(self.now.isoformat())
        token=self.service.mark_inference_pending(context,epoch)
        frame=TimestampedFrame(b'pixels',self.now.isoformat(),'asset',1,0)
        result=VisualResult((PotObservation('red1',Ball.RED,self.now.isoformat()),),None,(),self.now.isoformat())
        self.assertTrue(self.service.apply_visual_result(result,context,epoch,frame,{'modelVersion':'test'},10,3,work_id=token))
        prediction=self.service.latest_prediction()
        self.assertEqual(prediction['status'],'available'); self.assertEqual(prediction['points'],1)
        self.assertFalse(self.service.finish_inference_pending(token,context,epoch))
        newer=self.service.mark_inference_pending(context,epoch)
        self.assertFalse(self.service.apply_visual_result(result,context,epoch,frame,{'modelVersion':'test'},10,3,work_id=token))
        self.assertIn('shot_in_progress',self.service.latest_prediction()['qualityReasons'])
        self.assertTrue(self.service.finish_inference_pending(newer,context,epoch,resolved=False,reason='ambiguous_shot'))
        self.assertIn('ambiguous_shot',self.service.latest_prediction()['qualityReasons'])

    def test_quiet_cannot_keep_republishing_same_or_stale_capture(self):
        from ai_scoring.domain.visual_adapter import TimestampedFrame
        self.service.publish_prediction()
        context,epoch=self.service.visual_context(self.now.isoformat())
        same=TimestampedFrame(b'pixels',self.now.isoformat(),'asset',0,0)
        self.assertFalse(self.service.advance_verified_quiet(context,epoch,same))
        self.now+=timedelta(seconds=10)
        stale=TimestampedFrame(b'pixels',(self.now-timedelta(seconds=9)).isoformat(),'asset',1,0)
        context,epoch=self.service.visual_context(self.now.isoformat())
        self.assertFalse(self.service.advance_verified_quiet(context,epoch,stale))

    def test_commit_pending_work_records_uncertain_comparison_even_matching_score(self):
        prediction=self.service.publish_prediction()
        context,epoch=self.service.visual_context(self.now.isoformat())
        self.service.mark_inference_pending(context,epoch)
        self.service.apply_event(self.commit(prediction['predictionId'],points=0))
        comparison=self.store.records[-1]['payload']['comparison']
        self.assertTrue(comparison['boundaryUncertain']); self.assertTrue(comparison['reviewRequired'])

    def test_verified_quiet_renewals_are_throttled_until_ttl_half(self):
        from ai_scoring.domain.visual_adapter import TimestampedFrame
        self.service.publish_prediction(ttl_seconds=4)
        before=len(self.store.records)
        self.now+=timedelta(seconds=1)
        context,epoch=self.service.visual_context(self.now.isoformat())
        quiet=TimestampedFrame(b'pixels',self.now.isoformat(),'asset',1,0)
        self.assertTrue(self.service.advance_verified_quiet(context,epoch,quiet,ttl_seconds=4))
        self.assertEqual(len(self.store.records),before)
        self.now+=timedelta(seconds=2)
        context,epoch=self.service.visual_context(self.now.isoformat())
        quiet=TimestampedFrame(b'pixels',self.now.isoformat(),'asset',3,0)
        self.assertTrue(self.service.advance_verified_quiet(context,epoch,quiet,ttl_seconds=4))
        self.assertEqual(len(self.store.records),before+2)

    def test_new_visit_quiet_uses_prior_model_provenance_not_prior_run_points(self):
        from ai_scoring.domain.visual_adapter import TimestampedFrame
        self.service.observe(PotObservation('red',Ball.RED,self.now.isoformat()))
        previous=self.service.publish_prediction('identified-model',3)
        self.service.apply_event(self.commit(previous['predictionId'],points=1))
        self.now+=timedelta(seconds=1)
        context,epoch=self.service.visual_context(self.now.isoformat())
        frame=TimestampedFrame(b'pixels',self.now.isoformat(),'asset',1,0)
        self.assertTrue(self.service.advance_verified_quiet(context,epoch,frame))
        current=self.service.latest_prediction()
        self.assertEqual(current['runId'],'r2'); self.assertEqual(current['points'],0)
        self.assertEqual(current['modelVersion'],'identified-model')
        self.assertEqual(self.service.rules.reds,14)
