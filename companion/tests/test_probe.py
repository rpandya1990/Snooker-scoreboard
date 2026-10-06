import json
import subprocess
import unittest
from ai_scoring.clients.probe import MediaProbe

class ProbeTests(unittest.TestCase):
    def test_rtsp_metadata_preserves_reserved_password_and_selects_video(self):
        calls=[]
        source='rtsp://test-user:fake@password@127.0.0.1:554/stream1'
        def runner(command,**kwargs):
            calls.append((command,kwargs))
            return subprocess.CompletedProcess(command,0,json.dumps({'streams':[{'codec_type':'video','codec_name':'h264','width':1920,'height':1080,'avg_frame_rate':'30000/1001','tags':{'secret':source}}]}),'secret stderr '+source)
        times=iter((1.0,1.125))
        result=MediaProbe(runner=runner,monotonic=lambda:next(times)).inspect(source,mode='dry-run')
        self.assertEqual(result.status,'available')
        self.assertEqual((result.codec,result.width,result.height),('h264',1920,1080))
        self.assertAlmostEqual(result.fps,29.97002997)
        self.assertEqual(result.elapsed_ms,125)
        self.assertEqual(calls[0][0][-1],source)
        self.assertNotIn(source,repr(result))
        self.assertNotIn('secret',repr(result))
        self.assertFalse(calls[0][1]['shell'])
        self.assertEqual(calls[0][1]['timeout'],10)
    def test_off_never_invokes_subprocess(self):
        def runner(*args,**kwargs):
            self.fail('off performed a subprocess')
        result=MediaProbe(runner=runner).inspect(None)
        self.assertEqual(result.status,'disabled')

    def test_timeout_and_failure_redact_sensitive_details(self):
        source='rtsp://fake:fake@secret@127.0.0.1/stream1'
        def timed_out(command,**kwargs):
            raise subprocess.TimeoutExpired(command,1,output=source,stderr=source)
        result=MediaProbe(runner=timed_out).inspect(source,mode='dry-run')
        self.assertEqual(result.reason,'probe_timeout')
        self.assertNotIn(source,json.dumps(result.to_dict()))
        def failing(command,**kwargs):
            return subprocess.CompletedProcess(command,1,source,source)
        result=MediaProbe(runner=failing).inspect(source,mode='assist')
        self.assertEqual(result.reason,'probe_failed')
        self.assertNotIn('fake',repr(result))

    def test_missing_tool(self):
        def absent(command,**kwargs):
            raise FileNotFoundError('sensitive command contents')
        self.assertEqual(MediaProbe(runner=absent).inspect('rtsp://example/stream',mode='dry-run').reason,'ffprobe_missing')

    def test_malformed_and_no_video(self):
        for stdout,reason in (('not JSON','invalid_probe_metadata'),('{"streams":[]}','no_video_stream'),('{"streams":[{"codec_type":"audio"}]}','no_video_stream'),('{"streams":[{"codec_type":"video","width":"1920","height":1080}]}','invalid_probe_metadata')):
            with self.subTest(reason=reason,stdout=stdout):
                def runner(command,**kwargs):
                    return subprocess.CompletedProcess(command,0,stdout,'')
                self.assertEqual(MediaProbe(runner=runner).inspect('rtsp://example/stream',mode='dry-run').reason,reason)

    def test_recorded_file_is_read_only_and_has_no_rtsp_transport(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'fixture.mp4'
            path.write_bytes(b'fixture untouched')
            calls=[]
            def runner(command,**kwargs):
                calls.append(command)
                return subprocess.CompletedProcess(command,0,'{"streams":[{"codec_type":"video","codec_name":"hevc","width":640,"height":480,"avg_frame_rate":"0/0","r_frame_rate":"25/1"}]}','')
            result=MediaProbe(runner=runner).inspect(str(path),mode='dry-run',recorded_file=True)
            self.assertEqual(result.fps,25)
            self.assertNotIn('-rtsp_transport',calls[0])
            self.assertEqual(calls[0][-1],str(path.resolve()))
            self.assertEqual(path.read_bytes(),b'fixture untouched')

    def test_unknown_codec_and_credentials_in_metadata_not_exposed(self):
        source='rtsp://fake:fake@example/stream'
        def runner(command,**kwargs):
            return subprocess.CompletedProcess(command,0,json.dumps({'streams':[{'codec_type':'video','codec_name':source,'width':640,'height':480,'avg_frame_rate':source}]}),'')
        result=MediaProbe(runner=runner).inspect(source,mode='dry-run')
        self.assertEqual(result.codec,'unknown')
        self.assertIsNone(result.fps)
        self.assertNotIn(source,repr(result))

    def test_invalid_source_and_missing_recorded_file_skip_subprocess(self):
        def runner(*args,**kwargs):
            self.fail('invalid source performed subprocess')
        probe=MediaProbe(runner=runner)
        for source in (None,'','https://example','rtsp://example\nsecret'):
            self.assertEqual(probe.inspect(source,mode='dry-run').reason,'invalid_source')
        self.assertEqual(probe.inspect('/definitely/missing/fixture.mp4',mode='dry-run',recorded_file=True).reason,'missing_recorded_file')

    def test_invalid_timeouts(self):
        for timeout in (0,-1,float('inf'),float('nan'),True):
            with self.assertRaises(ValueError):
                MediaProbe(timeout_seconds=timeout)
