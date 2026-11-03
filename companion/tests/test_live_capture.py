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
    def test_loopback_relay_source_only(self):
        settings=InferenceConfig(enabled=True,model='fixture')
        command=LiveFrameSource(settings,'udp://127.0.0.1:40123').command()
        self.assertTrue(command[command.index('-i')+1].startswith('udp://127.0.0.1:40123?'))
        self.assertNotIn('-rtsp_transport',command)
        for source in ('udp://192.168.1.5:40123','udp://127.0.0.1:40123?localaddr=0.0.0.0','udp://0.0.0.0:1'):
            with self.subTest(source=source),self.assertRaises(CaptureFailure):
                LiveFrameSource(settings,source).command()
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
    def test_failure_markers_emit_only_fixed_codes(self):
        from ai_scoring.clients.live_capture import failure_marker
        cases={
            'method DESCRIBE failed: 401 Unauthorized':'camera_auth_failed',
            'method SETUP failed: 453 Not Enough Bandwidth':'camera_session_limit',
            'Connection to tcp://private-host failed: Connection refused':'camera_connection_failed',
            'Error reinitializing filters!':'capture_filter_failed',
            'Error while decoding stream #0:0':'capture_decoder_failed',
            'ff_frame_thread_encoder_init failed':'capture_encoder_failed',
        }
        for line,expected in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(failure_marker(line+' rtsp://fake:private@host/stream'),expected)
        self.assertIsNone(failure_marker('rtsp://fake:private@host/stream unknown diagnostic'))

    def test_failed_fake_source_reports_marker_without_raw_stderr(self):
        import os
        class Process:
            def __init__(self):
                output_read,output_write=os.pipe()
                error_read,error_write=os.pipe()
                os.close(output_write)
                os.write(error_write,b'[rtsp] method SETUP failed: 453 Not Enough Bandwidth rtsp://fake:private@host/stream\n')
                os.close(error_write)
                self.stdout=os.fdopen(output_read,'rb',buffering=0)
                self.stderr=os.fdopen(error_read,'rb',buffering=0)
            def poll(self):
                return 1
        source=LiveFrameSource(InferenceConfig(enabled=True,model='fixture'),'rtsp://fake:private@host/stream',process_factory=lambda *a,**k:Process())
        with self.assertRaises(CaptureFailure) as error:
            list(source.frames())
        self.assertEqual(str(error.exception),'camera_session_limit')
        self.assertNotIn('private',str(error.exception))
    def test_burst_pairs_and_progress_carriage_return_do_not_create_false_backlog(self):
        import os
        class Process:
            def __init__(self):
                output_read,output_write=os.pipe()
                error_read,error_write=os.pipe()
                os.write(output_write,b'x'*12*20)
                os.close(output_write)
                for index in range(20):
                    prefix=b'frame=1 fps=0 speed=1x\r' if index==1 else b''
                    os.write(error_write,prefix+f'[Parsed_showinfo] n: {index} pts: {index} pts_time:{index}.0\n'.encode())
                os.close(error_write)
                self.stdout=os.fdopen(output_read,'rb',buffering=0)
                self.stderr=os.fdopen(error_read,'rb',buffering=0)
            def poll(self):return 0
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'fixture';path.write_bytes(b'fixture')
            source=LiveFrameSource(InferenceConfig(enabled=True,model='fixture',width=2,height=2),str(path),recorded_file=True,process_factory=lambda *a,**k:Process())
            self.assertIn('-nostats',source.command())
            frames=list(source.frames())
            self.assertEqual(len(frames),20)
            self.assertEqual([frame.frame.media_time for frame in frames],list(range(20)))
    def test_real_ffmpeg_unpaced_local_file_burst_preserves_pairs(self):
        import shutil
        import subprocess
        if not shutil.which('ffmpeg'):
            self.skipTest('optional FFmpeg not installed')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'burst.mp4'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc=size=64x36:rate=30',
                '-t','2','-c:v','libx264','-pix_fmt','yuv420p','-threads','1',str(path)],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,timeout=15)
            def unpaced(command,**kwargs):
                command=list(command)
                offset=command.index('-readrate')
                del command[offset:offset+2]
                return subprocess.Popen(command,**kwargs)
            source=LiveFrameSource(InferenceConfig(enabled=True,model='fixture',sample_fps=10,width=64,height=36),
                str(path),recorded_file=True,process_factory=unpaced)
            try:
                frames=list(source.frames())
            finally:
                source.close()
            self.assertGreaterEqual(len(frames),15)
            self.assertTrue(all(len(frame.frame.data)==64*36*3 for frame in frames))
            self.assertTrue(all(second.frame.media_time>first.frame.media_time for first,second in zip(frames,frames[1:])))

    def test_unmatched_presentation_backlog_still_fails_with_bounded_counts(self):
        import os
        class Process:
            def __init__(self):
                output_read,output_write=os.pipe();error_read,error_write=os.pipe()
                os.close(output_write)
                for index in range(17):
                    os.write(error_write,f'[Parsed_showinfo] n: {index} pts: {index} pts_time:{index}.0\n'.encode())
                os.close(error_write)
                self.stdout=os.fdopen(output_read,'rb',buffering=0)
                self.stderr=os.fdopen(error_read,'rb',buffering=0)
            def poll(self):return 0
        source=LiveFrameSource(InferenceConfig(enabled=True,model='fixture',width=2,height=2),
            'rtsp://fake:private@host/stream',process_factory=lambda *a,**k:Process())
        with self.assertRaises(CaptureFailure) as error:
            list(source.frames())
        self.assertEqual(str(error.exception),'capture_backlog')
        self.assertEqual(error.exception.details['queuedPresentationTimestamps'],17)
        self.assertNotIn('private',str(error.exception.details))
