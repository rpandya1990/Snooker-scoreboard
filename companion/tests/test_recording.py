import json
import subprocess
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from datetime import datetime, timezone, timedelta
from ai_scoring.config import Config, Mode, RecordingConfig
from ai_scoring.dao.jsonl import JsonlSessionStore
from ai_scoring.clients.recording import RecordingWorker

class FakeProcess:
    def __init__(self):
        self.returncode=None
        self.stopped=False
    def poll(self):
        return self.returncode
    def communicate(self, input=None, timeout=None):
        self.stopped=True
        self.returncode=0
    def terminate(self):
        self.returncode=-15
    def kill(self):
        self.returncode=-9
    def wait(self,timeout=None):
        return self.returncode

class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.store=JsonlSessionStore(self.directory.name,'session')
        self.now=datetime(2026,1,1,tzinfo=timezone.utc)
        self.config=RecordingConfig(True,60,10000,100,5)
        self.calls=[]
        self.process=FakeProcess()
        def factory(command,**kwargs):
            self.calls.append((command,kwargs))
            return self.process
        self.factory=factory
        self.source='rtsp://fake:reserved@password@127.0.0.1:554/stream'
        self.worker=RecordingWorker(self.store,self.config,self.source,clock=lambda:self.now,
            monotonic=lambda:12.0,process_factory=factory,disk_usage=lambda _:SimpleNamespace(free=100000),
            metadata_runner=lambda *a,**k:subprocess.CompletedProcess(a[0],0,'{"streams":[{"codec_name":"h264","time_base":"1/1000"}]}',''))
    def tearDown(self):
        self.worker.close()
        self.store.close()
        self.directory.cleanup()
    def test_enabled_requires_explicit_settings_and_off_prevents_recording(self):
        with self.assertRaises(ValueError):
            RecordingConfig(True)
        with self.assertRaises(ValueError):
            Config(self.directory.name,Mode.OFF,recording=self.config)
        disabled=RecordingWorker(self.store,RecordingConfig(),self.source,process_factory=lambda *a,**k:self.fail('process launched'))
        disabled.start()
        self.assertEqual(disabled.health['status'],'disabled')
    def test_start_idempotent_and_secret_safe(self):
        self.worker.start(background=False)
        self.worker.start(background=False)
        self.assertEqual(len(self.calls),1)
        command,kwargs=self.calls[0]
        self.assertEqual(command[command.index('-i')+1],self.source)
        self.assertFalse(kwargs['shell'])
        self.assertNotIn(self.source,json.dumps(self.store.records))
        self.assertNotIn(self.source,repr(self.worker.health))
        self.assertEqual(self.store.records[-1]['payload']['alignmentStatus'],'unknown')
    def make_segment(self,closed=True):
        directory=self.store.path.parent/'video'
        name=self.worker._prefix+'000000.mkv'
        path=directory/name
        path.write_bytes(b'finalized video fixture')
        if closed:
            self.worker._list_path.write_text(name+',0.0,5.5\n')
        return path
    def test_closed_segment_checksum_timeline_and_retention_active_preserved(self):
        self.worker.start(background=False)
        path=self.make_segment()
        active=self.store.path.parent/'video'/(self.worker._prefix+'000001.mkv')
        active.write_bytes(b'active')
        self.worker.tick()
        records=[r for r in self.store.records if r['type']=='segment_closed']
        self.assertEqual(len(records),1)
        payload=records[0]['payload']
        self.assertEqual(payload['mediaDuration'],5.5)
        self.assertEqual(len(payload['sha256']),64)
        self.assertIsNone(payload['utcUncertaintyMs'])
        self.assertEqual(payload['alignmentStatus'],'unknown')
        self.assertEqual(payload['codec'],'h264')
        self.assertEqual(payload['timeBase'],'1/1000')
        self.now+=timedelta(seconds=61)
        self.worker.cleanup()
        self.assertFalse(path.exists())
        self.assertTrue(active.exists())
        self.assertEqual(self.store.records[-1]['type'],'asset_expired')
    def test_storage_insufficiency_records_loss_without_process(self):
        self.worker._disk_usage=lambda _:SimpleNamespace(free=0)
        self.worker.start(background=False)
        self.assertEqual(self.worker.health['reason'],'storage_limits')
        self.assertFalse(self.calls)
        self.assertEqual(self.store.records[-1]['type'],'capture_gap')
    def test_worker_failure_sanitized(self):
        def broken(*args,**kwargs):
            raise OSError(self.source)
        self.worker._factory=broken
        self.worker.start(background=False)
        self.assertEqual(self.worker.health['status'],'failed')
        self.assertNotIn(self.source,json.dumps(self.store.records))
    def test_stop_flags_unfinished_and_no_active_deletion(self):
        self.worker.start(background=False)
        path=self.make_segment(closed=False)
        self.worker.stop()
        self.assertTrue(self.process.stopped)
        self.assertTrue(path.exists())
        reasons=[r['payload'].get('reason') for r in self.store.records if r['type']=='capture_gap']
        self.assertIn('unfinished_segment',reasons)
    def test_paths_confined_and_symlink_rejected(self):
        self.worker.start(background=False)
        for relative in ('../other','video/../../outside','video/nested/part.mkv'):
            with self.assertRaises(ValueError):
                self.worker._safe_path(relative)
        target=Path(self.directory.name)/'outside'
        target.write_bytes(b'private')
        (self.store.path.parent/'video'/'link.mkv').symlink_to(target)
        with self.assertRaises(ValueError):
            self.worker._safe_path('video/link.mkv')
        self.assertTrue(target.exists())
    def test_start_log_failure_terminates_process(self):
        from unittest.mock import patch
        with patch.object(self.worker,'_record',side_effect=OSError('disk')):
            self.worker.start(background=False)
        self.assertNotEqual(self.process.poll(),None)
        self.assertEqual(self.worker.health['status'],'failed')

    def test_restart_purge_closes_only_expired_assets(self):
        from ai_scoring.clients.recording import purge_expired_sessions
        self.worker.start(background=False)
        path=self.make_segment()
        self.worker.tick()
        self.worker.close()
        self.store.close()
        self.now+=timedelta(seconds=61)
        purge_expired_sessions(self.directory.name,self.config,clock=lambda:self.now)
        self.assertFalse(path.exists())
        self.store=JsonlSessionStore(self.directory.name,'session')
        self.assertEqual(self.store.records[-1]['type'],'asset_expired')

    def test_restart_marks_unfinished_and_new_epoch(self):
        self.worker.start(background=False)
        path=self.make_segment(closed=False)
        self.worker.tick()
        old_epoch=self.worker.health['observationEpoch']
        self.worker.close()
        worker=RecordingWorker(self.store,self.config,self.source,clock=lambda:self.now,
            process_factory=self.factory,disk_usage=lambda _:SimpleNamespace(free=100000))
        worker.start(background=False)
        self.assertNotEqual(worker.health['observationEpoch'],old_epoch)
        self.assertTrue(path.exists())
        self.assertIn('unfinished_segment_after_restart',[r['payload'].get('reason') for r in self.store.records])
        worker.close()
    def test_process_cleanup_errors_never_escape_stop(self):
        class BrokenProcess(FakeProcess):
            def communicate(self,**kwargs):
                raise subprocess.TimeoutExpired('hidden',3)
            def terminate(self):
                raise ProcessLookupError('secret')
            def kill(self):
                raise OSError('secret')
            def wait(self,timeout=None):
                raise subprocess.TimeoutExpired('hidden',timeout)
        self.worker._factory=lambda *a,**k:BrokenProcess()
        self.worker.start(background=False)
        self.worker.stop()
        self.assertEqual(self.worker.health['status'],'stopped')
        self.assertEqual(self.worker.health['reason'],'capture_process_stop_failed')
        self.assertTrue(self.worker._done.is_set())
        self.assertNotIn('secret',json.dumps(self.store.records))
    def test_rtsp_exit_is_collection_loss_even_success_exit_code(self):
        self.worker.start(background=False)
        self.process.returncode=0
        self.worker.tick()
        self.assertEqual(self.worker.health['status'],'failed')
        self.assertEqual(self.worker.health['reason'],'unexpected_source_termination')
        self.assertIn('unexpected_source_termination',[r['payload'].get('reason') for r in self.store.records if r['type']=='capture_gap'])
        self.assertNotIn(self.source,json.dumps(self.store.records))

    def test_recorded_file_eof_normal_but_nonzero_exit_failure(self):
        path=Path(self.directory.name)/'source.mkv'
        path.write_bytes(b'fixture')
        for returncode,expected in ((0,'stopped'),(1,'failed')):
            with self.subTest(returncode=returncode):
                process=FakeProcess()
                worker=RecordingWorker(self.store,self.config,str(path),recorded_file=True,
                    clock=lambda:self.now,process_factory=lambda *a,**k:process,
                    disk_usage=lambda _:SimpleNamespace(free=100000))
                worker.start(background=False)
                process.returncode=returncode
                worker.tick()
                self.assertEqual(worker.health['status'],expected)
                worker.close()
