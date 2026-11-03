import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from ai_scoring.config import Config, Mode, RecordingConfig, InferenceConfig
from ai_scoring.services.dataset_builder import DatasetBuilder, CLASSES
from test_ball_detection import table, spread, CALIBRATION

def records(*relative,stopped=True):
    items=[{'type':'segment_closed','payload':{'relativePath':path,'captureStartUtc':f'2026-01-01T00:0{i}:00+00:00'}} for i,path in enumerate(relative)]
    return items+([{'type':'recording_stopped','payload':{}}] if stopped else [])

class FakeFfmpeg:
    """Writes one JPEG per supplied table frame and returns their detector-size RGB."""
    def __init__(self,frames):self.frames=frames;self.calls=0
    def __call__(self,command,**kwargs):
        self.calls+=1
        pattern=command[-1]
        for index in range(len(self.frames)):
            Path(pattern%(index+1)).write_bytes(b'jpeg-%d'%index)
        return subprocess.CompletedProcess(command,0,b''.join(frame.data for frame in self.frames),b'')

class DatasetBuilderTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.root=Path(self.directory.name)
        video=self.root/'sessions'/'s1'/'video';video.mkdir(parents=True)
        (video/'segment-e-000000.mkv').write_bytes(b'video')
    def tearDown(self):self.directory.cleanup()
    def builder(self,frames):
        self.ffmpeg=FakeFfmpeg(frames)
        return DatasetBuilder(self.root,CALIBRATION,2.0,runner=self.ffmpeg)
    def test_prelabels_in_yolo_format_with_provenance(self):
        builder=self.builder([table(spread())])
        self.assertEqual(builder.build_session('s1',records('video/segment-e-000000.mkv')),1)
        out=self.root/'dataset'
        self.assertEqual((out/'classes.txt').read_text().split(),list(CLASSES))
        labels=(out/'labels'/'s1-000000-00000.txt').read_text().splitlines()
        self.assertEqual(len(labels),22)   # 15 reds, six colours, cue ball
        self.assertEqual(sorted({int(line.split()[0]) for line in labels}),list(range(8)))
        for line in labels:
            values=[float(v) for v in line.split()[1:]]
            self.assertTrue(all(0<v<1 for v in values))
        entry=json.loads((out/'manifest.jsonl').read_text())
        self.assertEqual((entry['session'],entry['reviewed'],entry['prelabel']['visibility']),('s1',False,'clear'))
        self.assertEqual(os.stat(out/'images'/'s1-000000-00000.jpg').st_mode&0o777,0o600)
    def test_unchanged_table_frames_are_kept_once(self):
        frames=[table(spread()),table(spread()),table(spread(reds=14)),table(spread(reds=14))]
        self.assertEqual(self.builder(frames).build_session('s1',records('video/segment-e-000000.mkv')),2)
    def test_unfinished_or_already_processed_sessions_are_skipped(self):
        builder=self.builder([table(spread())])
        self.assertEqual(builder.build_session('s1',records('video/segment-e-000000.mkv',stopped=False)),0)
        self.assertEqual(builder.build_session('s1',records('video/segment-e-000000.mkv')),1)
        self.assertEqual(builder.build_session('s1',records('video/segment-e-000000.mkv')),0)
        self.assertEqual(self.ffmpeg.calls,1)
    def test_config_requires_recording_and_calibration(self):
        recording=RecordingConfig(True,60,10000,100,5)
        with self.assertRaises(ValueError):
            Config(self.root,Mode.DRY_RUN,recording=recording,dataset_every_seconds=2)
        with self.assertRaises(ValueError):
            Config(self.root,Mode.DRY_RUN,inference=InferenceConfig(calibration=CALIBRATION),dataset_every_seconds=2)
        Config(self.root,Mode.DRY_RUN,recording=recording,inference=InferenceConfig(calibration=CALIBRATION),dataset_every_seconds=2)

if __name__=='__main__':
    unittest.main()
