"""Training-frame extraction from recorded sessions, pre-labelled by the colour-blob detector.

Output (YOLO detection layout, under <data-directory>/dataset/):
  images/<session>-<segment>-<n>.jpg   frame at 1280 px wide
  labels/<same>.txt                    one "class cx cy w h" line per ball (normalised)
  classes.txt                          class names in id order
  manifest.jsonl                       provenance and pre-label quality per image
  sessions.json                        sessions already processed

Pre-labels are a starting point for human review, never ground truth: occluded
frames and touching reds are flagged in the manifest so review can start there.
"""
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
from ai_scoring.domain.ball_detection import BallDetector
from ai_scoring.domain.visual_adapter import TimestampedFrame

CLASSES=('red','yellow','green','brown','blue','pink','black','white')
DETECT_WIDTH,DETECT_HEIGHT=768,432
IMAGE_WIDTH=1280
PRELABEL_SOURCE='colour-blob-v1'


def _write(path,data):
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    with os.fdopen(descriptor,'wb') as handle:handle.write(data)


def closed_segments(records):
    """Finished recording segments, in capture order."""
    segments=[record['payload'] for record in records if record['type']=='segment_closed']
    return sorted(segments,key=lambda payload:(payload.get('captureStartUtc') or '',payload['relativePath']))


def recording_finished(records):
    return any(record['type']=='recording_stopped' for record in records)


def _same_scene(previous,current,tolerance=3):
    if previous is None or len(previous)!=len(current): return False
    remaining=list(previous)
    for label,x,y,_ in current:
        match=next((item for item in remaining if item[0]==label and abs(item[1]-x)<=tolerance and abs(item[2]-y)<=tolerance),None)
        if match is None: return False
        remaining.remove(match)
    return True


class DatasetBuilder:
    def __init__(self,data_directory,calibration,every_seconds=2.0,runner=subprocess.run):
        if type(every_seconds) not in (int,float) or not .2<=every_seconds<=60:
            raise ValueError('frame interval must be 0.2..60 seconds')
        self.root=Path(data_directory)
        self.output=self.root/'dataset'
        self.detector=BallDetector(calibration)
        self.every_seconds=every_seconds
        self._run=runner

    def processed(self):
        try:
            return set(json.loads((self.output/'sessions.json').read_text()))
        except (OSError,ValueError):
            return set()

    def _mark_processed(self,session_id):
        done=sorted(self.processed()|{session_id})
        _write(self.output/'sessions.json',json.dumps(done).encode())

    def build_session(self,session_id,records):
        """Extract and pre-label one finished session; returns images written."""
        if session_id in self.processed() or not recording_finished(records):
            return 0
        for folder in ('images','labels'):
            (self.output/folder).mkdir(mode=0o700,parents=True,exist_ok=True)
        _write(self.output/'classes.txt',('\n'.join(CLASSES)+'\n').encode())
        session_folder=self.root/'sessions'/session_id
        entries=[]
        previous=None
        for segment in closed_segments(records):
            path=session_folder/segment['relativePath']
            if not path.is_file() or path.is_symlink():
                continue
            for index,(jpeg,inventory,offset) in enumerate(self._frames(path)):
                if _same_scene(previous,inventory.balls):
                    continue
                previous=inventory.balls
                stem=f"{session_id}-{Path(segment['relativePath']).stem.rsplit('-',1)[-1]}-{index:05d}"
                _write(self.output/'images'/(stem+'.jpg'),jpeg)
                _write(self.output/'labels'/(stem+'.txt'),self._labels(inventory).encode())
                entries.append(json.dumps({'image':f'images/{stem}.jpg','session':session_id,'segment':segment['relativePath'],
                    'segmentOffsetSeconds':round(offset,3),'segmentCaptureStartUtc':segment.get('captureStartUtc'),
                    'prelabel':{'source':PRELABEL_SOURCE,'visibility':inventory.visibility,'causes':list(inventory.causes),
                        'touchingReds':any(ball[0]=='red' and ball[3]>160 for ball in inventory.balls)},
                    'reviewed':False},sort_keys=True)+'\n')
        # Manifest lines and the processed mark are written only after the whole
        # session succeeds, so a failed run can be repeated without duplicates.
        with open(self.output/'manifest.jsonl','a') as manifest:
            manifest.writelines(entries)
        self._mark_processed(session_id)
        return len(entries)

    def _frames(self,path):
        """Yield (jpeg bytes, detector inventory, segment offset) at the sampling interval."""
        with tempfile.TemporaryDirectory() as scratch:
            graph=(f'fps=1/{self.every_seconds},split=2[d][j];'
                f'[d]scale={DETECT_WIDTH}:{DETECT_HEIGHT}:force_original_aspect_ratio=decrease,'
                f'pad={DETECT_WIDTH}:{DETECT_HEIGHT}:(ow-iw)/2:(oh-ih)/2[detect];'
                f'[j]scale={IMAGE_WIDTH}:-2[image]')
            result=self._run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-i',str(path),'-filter_complex',graph,
                '-map','[detect]','-f','rawvideo','-pix_fmt','rgb24','pipe:1',
                '-map','[image]','-q:v','3',os.path.join(scratch,'%05d.jpg')],capture_output=True,timeout=600,check=False)
            size=DETECT_WIDTH*DETECT_HEIGHT*3
            count=len(result.stdout)//size
            for index in range(count):
                jpeg_path=os.path.join(scratch,f'{index+1:05d}.jpg')
                if not os.path.isfile(jpeg_path):
                    break
                frame=TimestampedFrame(result.stdout[index*size:(index+1)*size],'1970-01-01T00:00:00+00:00',str(path),
                    index*self.every_seconds,0.0,DETECT_WIDTH,DETECT_HEIGHT)
                with open(jpeg_path,'rb') as handle:
                    yield handle.read(),self.detector.detect(frame),index*self.every_seconds

    def _labels(self,inventory):
        lines=[]
        for label,x,y,area in inventory.balls:
            if label not in CLASSES: continue
            # Blob area includes the ball's shadow; clamp to plausible ball sizes.
            diameter=min(14,max(6,2*math.sqrt(min(area,160)/math.pi)))
            lines.append(f'{CLASSES.index(label)} {x/DETECT_WIDTH:.6f} {y/DETECT_HEIGHT:.6f} {diameter/DETECT_WIDTH:.6f} {diameter/DETECT_HEIGHT:.6f}')
        return '\n'.join(lines)+('\n' if lines else '')


def build_pending(data_directory,calibration,every_seconds=2.0,log=print):
    """Build every finished, unprocessed session not held by a running companion."""
    from ai_scoring.dao.session_snapshot import read_session_snapshot,SnapshotError
    builder=DatasetBuilder(data_directory,calibration,every_seconds)
    sessions=Path(data_directory)/'sessions'
    total=0
    for folder in sorted(sessions.iterdir()) if sessions.is_dir() else ():
        if folder.name in builder.processed() or not (folder/'video').is_dir():
            continue
        try:
            records,_=read_session_snapshot(data_directory,folder.name)
        except SnapshotError:
            continue   # active writer or unreadable; a later run retries
        count=builder.build_session(folder.name,records)
        if count:
            log(f'dataset: {folder.name}: {count} frames')
        total+=count
    return total
