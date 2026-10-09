import tempfile
from pathlib import Path
import unittest
from ai_scoring.config import InferenceConfig,Config,Mode
from ai_scoring.clients.live_capture import LiveFrameSource,parse_pts,CaptureFailure

class LiveCaptureTests(unittest.TestCase):
    def test_disabled_does_not_launch(self):
        source=LiveFrameSource(InferenceConfig(),None,process_factory=lambda *a,**k:self.fail('launched'))
        self.assertEqual(list(source.frames()),[])
    def test_source_secret_preserved_one_argument_with_original_pts(self):
        secret='rtsp://fake:reserved@password@localhost:554/stream'
        command=LiveFrameSource(InferenceConfig(enabled=True,model='fixture'),secret).command()
        self.assertEqual(command[command.index('-i')+1],secret)
        self.assertIn('-copyts',command)
        self.assertNotIn('fps=',command[command.index('-vf')+1])
        self.assertIn('showinfo',command[command.index('-vf')+1])
    def test_pts_parser_discards_non_numeric_secrets(self):
        self.assertEqual(parse_pts('[Parsed_showinfo_2] n:  7 pts: 900 pts_time:1.25 duration: 40'),(7,1.25))
        self.assertIsNone(parse_pts('rtsp://secret@host packet failed'))
    def test_positive_allocations_and_loopback_only(self):
        for kwargs in ({'endpoint':'https://cloud.example'},{'sample_fps':0},{'width':0},{'queue_size':99},{'window_frames':2},{'roi':(.5,.5,.7,.2)},{'capture_uncertainty_ms':0},{'endpoint':'http://localhost:bad'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                InferenceConfig(**kwargs)
        with self.assertRaises(ValueError):
            InferenceConfig(enabled=True)
        with self.assertRaises(ValueError):
            Config('/tmp/uncreated',Mode.OFF,inference=InferenceConfig(enabled=True,model='fixture'))
    def test_local_file_source_explicit_and_paced(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'fixture.mp4'
            path.write_bytes(b'fixture')
            command=LiveFrameSource(InferenceConfig(enabled=True,model='fixture'),str(path),recorded_file=True).command()
            self.assertEqual(command[command.index('-i')+1],str(path.resolve()))
            self.assertIn('-readrate',command)
            self.assertNotIn('-rtsp_transport',command)
    def test_rgb_frames_pair_original_pts_with_unknown_exposure_using_fake_pipes(self):
        import os
        from datetime import datetime,timezone
        class Process:
            def __init__(self):
                output_read,output_write=os.pipe()
                error_read,error_write=os.pipe()
                os.write(output_write,b'a'*12+b'b'*12)
                os.close(output_write)
                os.write(error_write,b'private source ignored\n[Parsed_showinfo] n: 0 pts: 100 pts_time:1.0\n[Parsed_showinfo] n: 1 pts: 250 pts_time:2.5\n')
                os.close(error_write)
                self.stdout=os.fdopen(output_read,'rb',buffering=0)
                self.stderr=os.fdopen(error_read,'rb',buffering=0)
            def poll(self):
                return 0
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'fixture'
            path.write_bytes(b'fixture')
            calls=[]
            def factory(command,**kwargs):
                calls.append((command,kwargs))
                return Process()
            now=datetime(2026,1,1,tzinfo=timezone.utc)
            source=LiveFrameSource(InferenceConfig(enabled=True,model='fixture',width=2,height=2),
                str(path),recorded_file=True,process_factory=factory,clock=lambda:now,monotonic=lambda:10.)
            frames=list(source.frames())
            self.assertEqual([frame.frame.media_time for frame in frames],[1.,2.5])
            self.assertEqual([frame.frame.data for frame in frames],[b'a'*12,b'b'*12])
            self.assertEqual(frames[0].alignment_status,'unknown')
            self.assertIsNone(frames[0].frame.utc_uncertainty_ms)
            self.assertFalse(calls[0][1]['shell'])
            self.assertEqual(frames[1].frame.timestamp,'2026-01-01T00:00:01.500000+00:00')
    def test_endpoint_matches_numeric_loopback_client_contract(self):
        for endpoint in ('http://localhost:11434','http://127.0.0.1','https://127.0.0.1:11434','http://127.0.0.1:11434/api','http://user@127.0.0.1:11434','http://127.0.0.1:11434?x=1','http://192.168.0.1:11434'):
            with self.subTest(endpoint=endpoint),self.assertRaises(ValueError):
                InferenceConfig(endpoint=endpoint)
        for endpoint in ('http://127.0.0.1:11434','http://127.0.0.2:11434','http://[::1]:11434'):
            self.assertEqual(InferenceConfig(endpoint=endpoint).endpoint,endpoint)
