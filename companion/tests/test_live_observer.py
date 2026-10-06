from datetime import datetime,timedelta,timezone
import tempfile
import unittest
from ai_scoring.config import InferenceConfig
from ai_scoring.dao.jsonl import JsonlSessionStore
from ai_scoring.domain.visual_adapter import TimestampedFrame,VisualResult
from ai_scoring.domain.scoring import Ball,PotObservation
from ai_scoring.clients.live_capture import CapturedFrame
from ai_scoring.services.scoring import ScoringService
from ai_scoring.services.live_observer import LiveObserver,InferenceJob

class Adapter:
    metadata={'modelVersion':'fixture','promptVersion':'fixture-v1','adapterVersion':'fixture'}
    def __init__(self,callback):
        self.callback=callback
        self.calls=[]
    def observe(self,frame,context):
        self.calls.append((frame,context))
        return self.callback(frame,context)

class LiveObserverTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.store=JsonlSessionStore(self.directory.name,'s')
        self.now=datetime(2026,1,1,tzinfo=timezone.utc)
        self.mono=10.
        self.service=ScoringService(self.store,clock=lambda:self.now)
        self.service.apply_event({'eventId':'frame','sequence':1,'type':'frame_started','frameId':'f','runId':'r'})
        self.settings=InferenceConfig(enabled=True,model='fixture',capture_uncertainty_ms=100)
        self.adapter=Adapter(lambda frame,ctx:VisualResult(baseline_reds=15,processed_through=frame.timestamp))
        self.observer=LiveObserver(self.service,self.settings,None,adapter=self.adapter,clock=lambda:self.now,monotonic=lambda:self.mono)
    def tearDown(self):
        self.observer.close()
        self.store.close()
        self.directory.cleanup()
    def captured(self,uncertainty=100,media_time=0):
        frame=TimestampedFrame(b'fixture',self.now.isoformat(),'asset',media_time,uncertainty,1,1)
        return CapturedFrame(frame,'capture',self.now.isoformat(),self.mono,'estimated' if uncertainty is not None else 'unknown')
    def process_next(self):
        self.observer.process(self.observer._queue.get_nowait())
    def commit(self):
        return {'eventId':'entry','sequence':2,'type':'break_committed','frameId':'f','runId':'r','nextRunId':'next','entryId':'e','attemptId':'a',
                'inputStartedAt':self.now.isoformat(),'committedAt':self.now.isoformat(),'predictionId':None,'submittedPoints':999,'appliedScoreDelta':999,'source':'manual'}
    def test_full_baseline_prediction_and_latency_record_without_submitted_scores(self):
        self.observer.submit(self.captured())
        self.process_next()
        self.assertEqual(self.service.latest_prediction()['points'],0)
        watermark=[r['payload'] for r in self.store.records if r['type']=='visual_watermark'][0]
        self.assertEqual(watermark['inferenceLatencyMs'],0)
        self.assertEqual(watermark['promptVersion'],'fixture-v1')
        self.assertFalse(hasattr(self.adapter.calls[0][1],'submittedPoints'))
    def test_unknown_exposure_mapping_never_available_including_new_frame(self):
        for sequence,frame_id in ((1,'f'),(2,'second')):
            if sequence>1:
                self.service.apply_event({'eventId':'second','sequence':sequence,'type':'frame_started','frameId':frame_id,'runId':'second-run'})
            self.observer.submit(self.captured(uncertainty=None,media_time=sequence))
            self.process_next()
            self.assertEqual(self.service.latest_prediction()['status'],'unavailable')
            self.assertIn('exposure_time_unresolved',self.service.latest_prediction()['qualityReasons'])
    def test_late_old_run_job_is_diagnostic_only(self):
        self.observer.submit(self.captured())
        job=self.observer._queue.get_nowait()
        self.service.apply_event(self.commit())
        before_reasons=set(self.service.reasons)
        self.observer.process(job)
        self.assertFalse(self.adapter.calls)
        self.assertEqual(self.service.rules.points,0)
        self.assertEqual(self.service.reasons,before_reasons)
        self.assertEqual(self.store.records[-1]['type'],'visual_diagnostic')
    def test_boundary_changes_during_model_call_cannot_mutate_new_run(self):
        def callback(frame,context):
            self.service.apply_event(self.commit())
            return VisualResult(observations=(PotObservation('p',Ball.RED,frame.timestamp),),processed_through=frame.timestamp)
        self.adapter.callback=callback
        self.observer.submit(self.captured())
        self.process_next()
        self.assertEqual(self.service.rules.points,0)
        self.assertEqual(self.service.rules.reds,15)
        self.assertEqual(self.store.records[-1]['type'],'visual_diagnostic')
    def test_bounded_queue_overflow_discontinues_instead_of_losing_coverage(self):
        self.observer.submit(self.captured(media_time=0))
        self.observer.submit(self.captured(media_time=1))
        self.observer.submit(self.captured(media_time=2))
        self.assertEqual(self.observer._queue.qsize(),0)
        self.assertIn('inference_queue_dropped_window',self.service.reasons)
    def test_slow_model_and_coverage_gap_suppress(self):
        self.observer.submit(self.captured())
        job=self.observer._queue.get_nowait()
        self.mono+=6
        self.observer.process(job)
        self.assertIn('inference_job_stale',self.service.reasons)
        self.assertFalse(self.adapter.calls)
        self.observer.submit(self.captured(media_time=20))
        self.assertIn('sample_coverage_gap',self.service.reasons)
    def test_midframe_baseline_does_not_invent_clearance(self):
        self.adapter.callback=lambda frame,ctx:VisualResult(baseline_reds=0,processed_through=frame.timestamp)
        self.observer.submit(self.captured())
        self.process_next()
        self.assertEqual(self.service.rules.reds,15)
        self.assertIn('physical_baseline_unresolved',self.service.reasons)
    def test_stop_ignores_inflight_return(self):
        def callback(frame,context):
            self.observer._done.set()
            return VisualResult(baseline_reds=15,processed_through=frame.timestamp)
        self.adapter.callback=callback
        self.observer.submit(self.captured())
        self.process_next()
        self.assertFalse(self.service.predictions)
    def test_failed_adapter_initialisation_never_starts_capture(self):
        from unittest.mock import patch
        observer=LiveObserver(self.service,self.settings,None,clock=lambda:self.now,
            capture_factory=lambda *a,**k:self.fail('capture started after failed adapter'),monotonic=lambda:self.mono)
        with patch('ai_scoring.services.ollama_adapter.create',side_effect=ValueError('private model details')):
            observer.start()
            for thread in observer._threads:
                thread.join(timeout=1)
        self.assertEqual(observer.health['status'],'failed')
        self.assertTrue(observer._done.is_set())
        self.assertIn('model_initialisation_failed',self.service.reasons)
        observer.close()
    def test_empty_visual_coverage_after_input_does_not_invalidate_break_boundary(self):
        self.observer.submit(self.captured())
        self.process_next()
        event=self.commit()
        self.now+=timedelta(seconds=1)
        self.observer.submit(self.captured(media_time=1))
        self.process_next()
        event['committedAt']=self.now.isoformat()
        self.service.apply_event(event)
        self.assertNotIn('boundary_unsynchronised',self.service.reasons)
        comparison=self.store.records[-1]['payload']['comparison']
        self.assertFalse(comparison['boundaryUncertain'])
    def test_initial_window_warmup_can_establish_fresh_baseline(self):
        self.adapter.callback=lambda frame,ctx:VisualResult(quality_reasons=('window_incomplete',),processed_through=frame.timestamp)
        self.observer.submit(self.captured())
        self.process_next()
        self.assertEqual(self.service.latest_prediction()['status'],'unavailable')
        self.now+=timedelta(seconds=1)
        self.adapter.callback=lambda frame,ctx:VisualResult(baseline_reds=15,processed_through=frame.timestamp)
        self.observer.submit(self.captured(media_time=1))
        self.process_next()
        prediction=self.service.latest_prediction()
        self.assertEqual(prediction['status'],'available')
        self.assertEqual(prediction['promptVersion'],'fixture-v1')
        self.assertEqual(prediction['inferenceLatencyMs'],0)
