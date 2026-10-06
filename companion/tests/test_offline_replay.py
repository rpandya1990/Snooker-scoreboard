import json
import tempfile
import unittest
import subprocess
import sys
import shutil
from unittest.mock import patch
from datetime import timedelta
from pathlib import Path
from ai_scoring.domain.scoring import PotObservation, Ball
from ai_scoring.domain.visual_adapter import TimestampedFrame, VisualResult
from ai_scoring.services.datasets import DatasetStore, utc
from ai_scoring.services.offline_replay import OfflineReplay
import test_datasets

class FakeFrames:
    def __init__(self): self.seen=[]
    def frames(self, path, segment, cutoff):
        anchor=utc(segment['captureStartUtc'])
        for second in (1,2,9,13):
            stamp=anchor+timedelta(seconds=second)
            if stamp <= cutoff:
                self.seen.append(second)
                yield TimestampedFrame(b'pixels',stamp.isoformat(),segment['assetId'],second,0)

class FakeAdapter:
    metadata={'adapterVersion':'TEST-ONLY','modelVersion':'synthetic-test','promptVersion':'none',
              'sampling':{'method':'fixture','maxFrameGapSeconds':10},'calibration':{'version':'fixture'},'runtime':{'deterministic':True},'externalInference':False}
    def __init__(self): self.contexts=[]
    def observe(self, frame, context):
        self.contexts.append(context)
        observations=()
        if frame.media_time==1: observations=(PotObservation('red',Ball.RED,frame.timestamp),)
        if frame.media_time==2: observations=(PotObservation('black',Ball.BLACK,frame.timestamp),)
        return VisualResult(observations,15 if frame.media_time==1 else None,(),frame.timestamp)

class OfflineReplayTests(unittest.TestCase):
    def fixture(self, root, alignment='estimated'):
        source=test_datasets.DatasetTests().fixture(root,alignment=alignment)
        path=source/'session.jsonl'
        records=[json.loads(line) for line in path.read_text().splitlines()]
        records[-1]['payload']['event']['clockUncertaintyMs']=0
        records.insert(1,{'id':'frame','type':'event','timestamp':'2026-10-05T00:00:00+00:00','payload':{'event':{
            'clockUncertaintyMs':0,'type':'frame_started','frameId':'frame','runId':'run','timestamp':'2026-10-05T00:00:00+00:00'}}})
        path.write_text(''.join(json.dumps(r)+'\n' for r in records))
        store=DatasetStore(root/'datasets'); dataset=store.import_session(source); store.assign_cohort(dataset,'tuning')
        return store,dataset,source
    def test_cutoff_score_stripping_and_separate_immutable_results(self):
        with tempfile.TemporaryDirectory() as temp:
            store,dataset,source=self.fixture(Path(temp).resolve()); before=(source/'session.jsonl').read_bytes()
            frames=FakeFrames(); adapters=[]
            def factory():
                adapter=FakeAdapter(); adapters.append(adapter); return adapter
            replay=OfflineReplay(store,frames); result=replay.run(dataset,factory)
            self.assertEqual(result['results'][0]['points'],8)
            self.assertNotIn(13,frames.seen)
            self.assertNotIn('15',repr(adapters[0].contexts))
            self.assertNotIn('submitted',repr(adapters[0].contexts))
            self.assertEqual((source/'session.jsonl').read_bytes(),before)
            self.assertFalse(result['originalLivePredictionsChanged'])
            self.assertEqual(replay.comparisons(dataset,result['replayRunId'])[0]['replay']['points'],8)
    def test_unknown_alignment_stays_unavailable_until_versioned_mapping(self):
        with tempfile.TemporaryDirectory() as temp:
            store,dataset,_=self.fixture(Path(temp).resolve(),'unknown')
            replay=OfflineReplay(store,FakeFrames())
            self.assertEqual(replay.run(dataset,FakeAdapter)['results'][0]['status'],'unavailable')
            store.align(dataset,{'version':'review-1','reviewer':'operator','assets':[
                {'assetId':'asset','captureStartUtc':'2026-10-05T00:00:00+00:00','utcUncertaintyMs':100}]})
            self.assertEqual(replay.run(dataset,FakeAdapter)['results'][0]['points'],8)
    def test_truncated_footage_never_produces_available_prediction(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve(); source=test_datasets.DatasetTests().fixture(root)
            path=source/'session.jsonl'; records=[json.loads(x) for x in path.read_text().splitlines()]
            records[1]['payload']['mediaDuration']=1
            records[-1]['payload']['event']['clockUncertaintyMs']=0
            records.insert(1,{'id':'frame','type':'event','timestamp':'2026-10-05T00:00:00+00:00','payload':{'event':{
                'clockUncertaintyMs':0,'type':'frame_started','frameId':'frame','runId':'run','timestamp':'2026-10-05T00:00:00+00:00'}}})
            path.write_text(''.join(json.dumps(r)+'\n' for r in records))
            store=DatasetStore(root/'datasets'); dataset=store.import_session(source); store.assign_cohort(dataset,'tuning')
            result=OfflineReplay(store,FakeFrames()).run(dataset,FakeAdapter)
            self.assertEqual(result['results'][0]['status'],'unavailable')
            self.assertIn('recording_tail_missing',result['results'][0]['qualityReasons'])
    def test_no_adapter_is_unavailable_not_perfect_score(self):
        with tempfile.TemporaryDirectory() as temp:
            store,dataset,_=self.fixture(Path(temp).resolve())
            result=OfflineReplay(store,FakeFrames()).run(dataset)
            self.assertIsNone(result['results'][0]['points'])
            self.assertIn('adapter_not_configured',result['results'][0]['qualityReasons'])

    def test_reviewed_replay_metrics_use_truth_not_entered_15(self):
        with tempfile.TemporaryDirectory() as temp:
            store,dataset,_=self.fixture(Path(temp).resolve())
            replay=OfflineReplay(store,FakeFrames()); result=replay.run(dataset,FakeAdapter)
            store.review(dataset,{'entryId':'entry','reviewer':'independent','independent':True,'eligible':True,'evidenceSufficient':True,'actualPoints':8})
            metrics=replay.evaluate(dataset,result['replayRunId'])
            self.assertEqual(metrics['metrics']['exactAccuracy'],1)
            self.assertEqual(metrics['metrics']['heldOutReviewed'],0)
            self.assertFalse(metrics['rolloutApproved'])
            unavailable=replay.run(dataset)
            self.assertEqual(replay.evaluate(dataset,unavailable['replayRunId'])['metrics']['missingPredictions'],1)
    def test_decode_timeout_kills_stalled_stream(self):
        from ai_scoring.services.offline_replay import FFmpegFrameSource
        from ai_scoring.services.datasets import DatasetError
        probe={'streams':[{'width':1,'height':1,'start_time':'0'}],'frames':[{'best_effort_timestamp_time':'0'}]}
        real_popen=subprocess.Popen
        def stalled(*args,**kwargs):
            return real_popen([sys.executable,'-c','import time; time.sleep(5)'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        with patch('ai_scoring.services.offline_replay.subprocess.run',return_value=subprocess.CompletedProcess([],0,json.dumps(probe).encode())), patch('ai_scoring.services.offline_replay.subprocess.Popen',side_effect=stalled):
            segment={'captureStartUtc':'2026-10-05T00:00:00+00:00','utcUncertaintyMs':0,'assetId':'a','mediaStart':0}
            with self.assertRaises(DatasetError): list(FFmpegFrameSource(decode_timeout=.05).frames(Path('fake'),segment,utc('2026-10-05T00:00:01+00:00')))

    def test_prior_uncertain_boundary_and_delayed_observation_are_unavailable(self):
        for uncertainty, delayed in ((500,False),(0,True)):
            with self.subTest(uncertainty=uncertainty,delayed=delayed), tempfile.TemporaryDirectory() as temp:
                store,dataset,_=self.fixture(Path(temp).resolve())
                # Reimport a separate complete capture fixture containing two submissions.
                source=Path(temp).resolve()/'second'; source.mkdir()
                original=store.path(dataset)
                import shutil
                shutil.copytree(original/'video',source/'video')
                records=[json.loads(x) for x in (original/'session.jsonl').read_text().splitlines()]
                first=records[-1]['payload']['event']; first['inputStartedAt']='2026-10-05T00:00:02+00:00'; first['committedAt']='2026-10-05T00:00:03+00:00'
                first['clockUncertaintyMs']=uncertainty; first['nextRunId']='run2'
                second={'id':'entry2','type':'event','timestamp':'2026-10-05T00:00:10+00:00','payload':{'event':{
                    **first,'entryId':'entry2','runId':'run2','inputStartedAt':'2026-10-05T00:00:10+00:00',
                    'committedAt':'2026-10-05T00:00:11+00:00','clockUncertaintyMs':0}}}
                records.append(second); (source/'session.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
                second_dataset=store.import_session(source); store.assign_cohort(second_dataset,'tuning')
                class DelayedAdapter(FakeAdapter):
                    def observe(self,frame,context):
                        result=super().observe(frame,context)
                        if frame.media_time==9:
                            if delayed: return VisualResult((PotObservation('late',Ball.RED,'2026-10-05T00:00:02+00:00'),),None,(),frame.timestamp)
                        return result
                class NearBoundaryFrames(FakeFrames):
                    def frames(self,path,segment,cutoff):
                        anchor=utc(segment['captureStartUtc'])
                        for seconds in (1,2,3.1,9):
                            t=anchor+timedelta(seconds=seconds)
                            if t<=cutoff: yield TimestampedFrame(b'pixels',t.isoformat(),segment['assetId'],seconds,0)
                result=OfflineReplay(store,NearBoundaryFrames()).run(second_dataset,DelayedAdapter)
                last=result['results'][-1]
                self.assertEqual(last['status'],'unavailable')
                self.assertIn('late_cross_boundary_observation' if delayed else 'boundary_time_ambiguous',last['qualityReasons'])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg not installed')
    def test_real_synthetic_h264_decode_preserves_dimensions_and_cutoff(self):
        from ai_scoring.services.offline_replay import FFmpegFrameSource
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'synthetic.mkv'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc2=size=64x48:rate=4',
                            '-t','1','-c:v','libx264',str(path)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
            segment={'captureStartUtc':'2026-10-05T00:00:00+00:00','utcUncertaintyMs':0,'assetId':'synthetic-only','mediaStart':0}
            cutoff=utc('2026-10-05T00:00:00.500000+00:00')
            frames=list(FFmpegFrameSource(max_frames=10).frames(path,segment,cutoff))
            self.assertEqual(len(frames),3)
            self.assertTrue(all(utc(frame.timestamp)<=cutoff for frame in frames))
            self.assertTrue(all((frame.width,frame.height,frame.pixel_format)==(64,48,'rgb24') for frame in frames))
            self.assertTrue(all(len(frame.data)==64*48*3 for frame in frames))

    def test_future_gap_does_not_exclude_earlier_review_or_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve(); store,dataset,source=self.fixture(root)
            path=source/'session.jsonl'
            with path.open('a') as stream:
                stream.write(json.dumps({'id':'late-gap','type':'capture_gap','timestamp':'2026-10-05T00:00:20+00:00',
                                         'payload':{'reason':'later_capture_loss'}})+'\n')
            earlier=store.import_session(source); store.assign_cohort(earlier,'tuning')
            replay=OfflineReplay(store,FakeFrames()); result=replay.run(earlier,FakeAdapter)
            self.assertEqual(result['results'][0]['points'],8)
            store.review(earlier,{'entryId':'entry','reviewer':'independent','independent':True,'eligible':True,'evidenceSufficient':True,'actualPoints':8})
            metrics=replay.evaluate(earlier,result['replayRunId'])
            self.assertEqual(metrics['metrics']['eligibleReviewed'],1)
            self.assertEqual(metrics['metrics']['exactAccuracy'],1)
            self.assertIn('capture_gap',metrics['collectionIssues'])
            self.assertEqual(metrics['evidenceIssues'],{})

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg not installed')
    def test_slow_inference_consumer_does_not_consume_decode_timeout(self):
        from ai_scoring.services.offline_replay import FFmpegFrameSource
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'synthetic.mkv'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc2=size=64x48:rate=4',
                            '-t','1','-c:v','libx264',str(path)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
            clock=[0.0]
            source=FFmpegFrameSource(max_frames=10,decode_timeout=1,clock=lambda:clock[0])
            segment={'captureStartUtc':'2026-10-05T00:00:00+00:00','utcUncertaintyMs':0,'assetId':'synthetic','mediaStart':0}
            frames=[]
            for frame in source.frames(path,segment,utc('2026-10-05T00:00:00.500000+00:00')):
                frames.append(frame)
                clock[0]+=100 # Simulated synchronous local model latency.
            self.assertEqual(len(frames),3)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg not installed')
    def test_sampling_uses_original_pts_without_future_frames(self):
        from ai_scoring.services.offline_replay import FFmpegFrameSource
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'synthetic.mkv'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc2=size=64x48:rate=8',
                            '-t','2','-c:v','libx264',str(path)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
            segment={'captureStartUtc':'2026-10-05T00:00:00+00:00','utcUncertaintyMs':0,'assetId':'synthetic','mediaStart':0}
            cutoff=utc('2026-10-05T00:00:01.500000+00:00')
            source=FFmpegFrameSource(max_frames=20,sample_fps=2)
            frames=list(source.frames(path,segment,cutoff))
            self.assertEqual([frame.media_time for frame in frames],[0,.5,1,1.5])
            self.assertTrue(all(utc(frame.timestamp)<=cutoff for frame in frames))
            self.assertEqual(source.sampling_metadata['sampleFps'],2)
            with self.assertRaises(ValueError): FFmpegFrameSource(sample_fps=float('nan'))
