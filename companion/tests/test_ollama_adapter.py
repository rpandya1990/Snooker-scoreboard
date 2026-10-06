import base64
import json
import struct
import unittest
from ai_scoring.domain.visual_adapter import TimestampedFrame, BoundaryContext
from ai_scoring.services.ollama_adapter import OllamaVisualAdapter, create, rgb_png, COLOURS

SETTINGS={'model':'gemma3:12b','windowFrames':4,'maxFrameGapSeconds':2,'minConfidence':.9,
          'calibration':{'version':'test-only','pockets':[[0,0],[.5,0],[1,0],[0,1],[.5,1],[1,1]],'pocketRadius':.15}}

def frame(second,asset='video-one',uncertainty=0):
    return TimestampedFrame(b'\x10\x20\x30'*4,f'2026-10-06T00:00:{second:02}+00:00',asset,second,uncertainty,2,2,'rgb24')
def context(run='run',physical='frame'):
    return BoundaryContext(physical,run,'2026-10-06T00:00:00+00:00','2026-10-06T00:00:00+00:00','2026-10-06T00:01:00+00:00')
def baseline(ids):
    return {'frameId':ids[-1],'reds':15,'phase':'red_colour','settled':True,'confidence':.99,'coloursPresent':COLOURS,
            'witnesses':[{'frameId':identifier,'reds':15,'coloursPresent':COLOURS,'settled':True,'confidence':.99} for identifier in ids[-3:]]}
def event(ids,ball='red'):
    return {'kind':'pot','ball':ball,'count':1,'confidence':.99,'beforeFrameId':ids[-3],
            'transitionFrameId':ids[-2],'afterFrameId':ids[-1],'beforePosition':[.5,.5],
            'transitionPosition':[.05,.05],'pocket':0,'beforeVisible':True,'afterVisible':False,
            'approachingPocket':True,'settledAfter':True,'respotOf':None}

class FakeVision:
    identity={'name':'gemma3:12b','digest':'test-only-digest'}
    def __init__(self): self.calls=[]; self.mode='baseline'; self.repeat=None
    def describe(self,images,prompt,schema,seed,**options):
        payload=json.loads(prompt[prompt.index('{'):]); ids=[f['frameId'] for f in payload['frames']]
        self.calls.append((images,payload))
        result={'visibility':'clear','uncertainty':[],'baseline':baseline(ids) if len(ids)>=3 and self.mode=='baseline' else None,'events':[]}
        if self.mode=='pot':
            self.repeat=event(ids); result['events']=[self.repeat]
        if self.mode=='repeat': result['events']=[self.repeat]
        if self.mode=='total': result['points']=15
        if self.mode=='overlap': result['events']=[event(ids[-4:-1]),event(ids[-3:])]
        if self.mode=='bad_refs': result['events']=[{**event(ids),'afterFrameId':'not-input'}]
        if self.mode=='low': result['events']=[{**event(ids),'confidence':.1}]
        if self.mode=='ambiguous': result['uncertainty']=['glare']
        return result

class OllamaAdapterTests(unittest.TestCase):
    def adapter(self):
        client=FakeVision(); adapter=OllamaVisualAdapter(SETTINGS,client); return adapter,client
    def ready(self,adapter):
        results=[adapter.observe(frame(i),context()) for i in (1,2,3)]
        self.assertIsNone(results[0].baseline_reds); self.assertEqual(results[-1].baseline_reds,15)
    def test_baseline_three_witnesses_png_and_no_score_inputs(self):
        adapter,client=self.adapter(); self.ready(adapter)
        png=base64.b64decode(client.calls[-1][0][0]); self.assertEqual(png[:8],b'\x89PNG\r\n\x1a\n')
        self.assertEqual(struct.unpack('>II',png[16:24]),(2,2))
        text=json.dumps(client.calls[-1][1]); self.assertNotIn('submittedPoints',text); self.assertNotIn('actualPoints',text)
        self.assertFalse(adapter.metadata['runtime']['deterministic']); self.assertFalse(adapter.metadata['externalInference'])
    def test_pot_dedup_across_overlapping_windows_and_run_asset_changes(self):
        adapter,client=self.adapter(); self.ready(adapter); client.mode='pot'
        first=adapter.observe(frame(4),context()); self.assertEqual(len(first.observations),1)
        self.assertEqual(first.observations[0].timestamp,frame(4).timestamp)
        client.mode='repeat'; again=adapter.observe(frame(5,asset='next-video'),context(run='new-run'))
        self.assertEqual(again.observations,()); self.assertEqual(again.quality_reasons,())
        self.assertTrue(adapter.baseline)
        client.mode='baseline'; reset=adapter.observe(frame(6),context(physical='new-physical-frame'))
        self.assertIsNone(reset.baseline_reds); self.assertFalse(adapter.baseline)
    def test_scalar_total_unknown_frame_refs_and_low_confidence_abstain(self):
        for mode in ('total','bad_refs','low','ambiguous'):
            with self.subTest(mode=mode):
                adapter,client=self.adapter(); self.ready(adapter); client.mode=mode
                result=adapter.observe(frame(4),context()); self.assertEqual(result.observations,()); self.assertTrue(result.quality_reasons)
    def test_gap_and_unknown_clock_never_produce_available_evidence(self):
        adapter,client=self.adapter(); self.ready(adapter)
        result=adapter.observe(frame(9),context()); self.assertIn('sampled_frame_gap',result.quality_reasons)
        adapter,client=self.adapter(); result=adapter.observe(frame(1,uncertainty=None),context())
        self.assertIn('clock_alignment_unknown',result.quality_reasons)
    def test_disabled_factory_and_close_no_model_work(self):
        disabled=create({}); self.assertIn('adapter_not_configured',disabled.observe(frame(1),context()).quality_reasons)
        adapter,client=self.adapter(); adapter.close(); self.assertIn('adapter_stopped',adapter.observe(frame(1),context()).quality_reasons)
        self.assertEqual(client.calls,[])
    def test_unconfigured_pockets_cannot_assert_pot(self):
        client=FakeVision(); adapter=OllamaVisualAdapter({**SETTINGS,'calibration':{}},client)
        for second in (1,2,3): adapter.observe(frame(second),context())
        client.mode='pot'; result=adapter.observe(frame(4),context())
        self.assertIn('table_not_calibrated',result.quality_reasons); self.assertEqual(result.observations,())

    def test_same_output_overlapping_transitions_cannot_double_count(self):
        adapter,client=self.adapter(); self.ready(adapter); client.mode='none'
        adapter.observe(frame(4),context()); adapter.observe(frame(5),context())
        client.mode='overlap'; result=adapter.observe(frame(6),context())
        self.assertEqual(result.observations,()); self.assertIn('ambiguous_repeated_transition',result.quality_reasons)
        self.assertEqual(adapter.accepted,{})

    def test_warmup_collects_frames_without_model_calls(self):
        adapter,client=self.adapter()
        for second in (1,2):
            result=adapter.observe(frame(second),context())
            self.assertIn('window_incomplete',result.quality_reasons)
            self.assertEqual(client.calls,[])
        result=adapter.observe(frame(3),context()); self.assertEqual(len(client.calls),1)
        self.assertEqual(result.baseline_reds,15)
        self.assertEqual(adapter.metadata['runtime']['numPredict'],2048)
        self.assertEqual(adapter.metadata['runtime']['numCtx'],16384)

    def test_missing_calibration_baseline_and_empty_events_remain_unavailable(self):
        client=FakeVision(); adapter=OllamaVisualAdapter({**SETTINGS,'calibration':{}},client)
        results=[adapter.observe(frame(second),context()) for second in (1,2,3,4)]
        self.assertTrue(all('table_not_calibrated' in result.quality_reasons for result in results))
        self.assertTrue(all(result.baseline_reds is None and not result.observations for result in results))
        self.assertFalse(adapter.baseline); self.assertEqual(adapter.accepted,{})
