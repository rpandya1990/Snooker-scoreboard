from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
import unittest
from ai_scoring.debug_failures import load_report,DebugError,render_text
from ai_scoring.dao.jsonl import JsonlSessionStore

TIME='2026-01-01T00:00:00+00:00'

class DebugFailureTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.root=Path(self.directory.name)
        self.folder=self.root/'sessions'/'s'
        self.folder.mkdir(parents=True)
        self.log=self.folder/'session.jsonl'
        self.records=[]
    def tearDown(self):
        self.directory.cleanup()
    def add(self,kind,payload,timestamp=TIME):
        self.records.append({'id':str(len(self.records)),'type':kind,'timestamp':timestamp,'payload':payload})
    def save(self):
        self.log.write_text(''.join(json.dumps(record)+'\n' for record in self.records))
    def entry(self,identifier='e',prediction='p',points=12,source='manual',**extra):
        self.add('event',{'event':{'type':'frame_started','frameId':'f','runId':'r','eventId':'frame'}})
        event={'type':'break_committed','entryId':identifier,'eventId':'commit-'+identifier,'frameId':'f','runId':'r','nextRunId':'next',
               'predictionId':prediction,'submittedPoints':points,'source':source,'inputStartedAt':'2026-01-01T00:00:10+00:00',
               'committedAt':'2026-01-01T00:00:12+00:00'}
        event.update(extra)
        self.add('event',{'event':event,'comparison':{}},timestamp='2026-01-01T00:00:12+00:00')
    def test_mismatch_missing_unavailable_and_match_filter(self):
        self.add('prediction',{'predictionId':'p','status':'available','points':15})
        self.add('prediction',{'predictionId':'unavailable','status':'unavailable','points':None,'qualityReasons':['feed_gap']})
        self.entry('mismatch')
        self.entry('missing',prediction=None)
        self.entry('unavailable',prediction='unavailable')
        self.entry('match',points=15)
        self.save()
        report=load_report(self.root,'s')
        self.assertEqual([entry['classification'] for entry in report['entries']],['mismatch','missing_prediction','unavailable_prediction'])
        self.assertEqual(report['entries'][0]['errorPoints'],3)
        self.assertEqual(report['entries'][0]['expectedPoints'],12)
        self.assertEqual(report['entries'][2]['predictionReasons'],['feed_gap'])
        selected=load_report(self.root,'s','match')
        self.assertEqual(selected['entries'][0]['classification'],'match')
        self.assertIn('expected/submitted 12',render_text(report))
    def test_ai_influence_and_revision_flags_are_debug_not_truth(self):
        self.add('prediction',{'predictionId':'p','status':'available','points':15})
        self.entry(source='ai_selected_edited')
        self.add('event',{'event':{'type':'correction','eventId':'correct','affectedEntryIds':['e']}})
        self.add('event',{'event':{'type':'undo','eventId':'undo','entryId':'e'}})
        self.save()
        entry=load_report(self.root,'s')['entries'][0]
        self.assertTrue(entry['aiInfluenced'])
        self.assertTrue(entry['corrected'])
        self.assertTrue(entry['undone'])
        self.assertEqual(entry['expectedBasis'],'submitted_points_provisional_debug_label')
    def test_unknown_alignment_includes_distant_missing_candidates_no_offsets(self):
        self.entry(prediction=None)
        self.add('segment_closed',{'assetId':'asset','relativePath':'video/segment-one.mkv','captureStartUtc':'2026-02-01T00:00:00+00:00',
            'utcUncertaintyMs':None,'alignmentStatus':'unknown','mediaStart':0,'mediaDuration':60})
        self.save()
        segment=load_report(self.root,'s')['entries'][0]['segments'][0]
        self.assertEqual(segment['assetStatus'],'missing')
        self.assertEqual(segment['alignment'],'unknown_candidate_not_exact')
        self.assertIsNone(segment['mediaOffsetsSeconds'])
    def test_known_timing_returns_offsets_and_filters_nonoverlap(self):
        self.entry(prediction=None,clockUncertaintyMs=100)
        (self.folder/'video').mkdir()
        (self.folder/'video'/'segment-one.mkv').write_bytes(b'fixture')
        for name,anchor in (('one',TIME),('later','2026-02-01T00:00:00+00:00')):
            self.add('segment_closed',{'assetId':name,'relativePath':'video/segment-'+name+'.mkv','captureStartUtc':anchor,
                'utcUncertaintyMs':100,'alignmentStatus':'estimated','mediaStart':0,'mediaDuration':60})
        self.save()
        segments=load_report(self.root,'s')['entries'][0]['segments']
        self.assertEqual(len(segments),1)
        self.assertEqual(segments[0]['assetStatus'],'available')
        self.assertAlmostEqual(segments[0]['mediaOffsetsSeconds']['fileEnd'],12.2)
    def test_redaction_only_whitelisted_fields_and_paths(self):
        secret='rtsp://fake:private@password@host/stream'
        self.entry(prediction=None)
        self.add('capture_gap',{'reason':secret,'rawStderr':secret,'command':[secret]})
        self.add('segment_closed',{'assetId':secret,'relativePath':'video/'+secret,'rawSource':secret})
        self.save()
        output=json.dumps(load_report(self.root,'s'))
        self.assertNotIn(secret,output)
        self.assertNotIn('private',output)
        self.assertIn('redacted_reason',output)
        self.assertIn('unsafe_path',output)
    def test_missing_traversal_symlink_and_partial_reads_never_mutate(self):
        missing=self.root/'uncreated'
        with self.assertRaises(DebugError):
            load_report(missing,'s')
        self.assertFalse(missing.exists())
        with self.assertRaises(DebugError):
            load_report(self.root,'../s')
        target=self.root/'secret'
        target.write_bytes(b'unchanged')
        self.log.symlink_to(target)
        with self.assertRaises(DebugError):
            load_report(self.root,'s')
        self.assertEqual(target.read_bytes(),b'unchanged')
        self.log.unlink()
        self.log.write_bytes(b'{unfinished')
        with self.assertRaises(DebugError):
            load_report(self.root,'s')
        self.assertEqual(self.log.read_bytes(),b'{unfinished')
    def test_active_writer_is_rejected_and_snapshot_unchanged(self):
        self.entry(prediction=None)
        self.save()
        before=self.log.read_bytes()
        store=JsonlSessionStore(self.root,'s')
        try:
            with self.assertRaisesRegex(DebugError,'active writer'):
                load_report(self.root,'s')
        finally:
            store.close()
        self.assertEqual(self.log.read_bytes(),before)
        load_report(self.root,'s')
        self.assertEqual(self.log.read_bytes(),before)
    def test_unfinished_assets_and_symlink_session_are_safe_candidates(self):
        self.entry(prediction=None)
        self.add('segment_opened',{'assetId':'open','relativePath':'video/segment-open.mkv'})
        self.save()
        segment=load_report(self.root,'s')['entries'][0]['segments'][0]
        self.assertEqual(segment['assetStatus'],'unfinished')
        self.assertIsNone(segment['mediaOffsetsSeconds'])
        other=self.root/'sessions'/'alias'
        other.symlink_to(self.folder,target_is_directory=True)
        with self.assertRaises(DebugError):
            load_report(self.root,'alias')
    def test_fifo_log_is_rejected_without_blocking_or_recovery(self):
        import os
        os.mkfifo(self.log)
        with self.assertRaises(DebugError):
            load_report(self.root,'s')
        self.assertTrue(self.log.exists())
