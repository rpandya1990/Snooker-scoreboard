"""Read-only sampled RGB capture with paired original presentation timestamps.

UTC is an estimated first-receipt anchor, never camera exposure certification.
Only numeric showinfo fields are parsed; source diagnostics are discarded.
"""
from dataclasses import dataclass
from datetime import timedelta
import math
import os
from pathlib import Path
import re
import selectors
import subprocess
from threading import Event, Lock
import time
from uuid import uuid4
from ai_scoring.domain.visual_adapter import TimestampedFrame
from ai_scoring.services.scoring import utc_now

@dataclass(frozen=True)
class CapturedFrame:
    frame: TimestampedFrame
    capture_epoch: str
    received_utc: str
    received_monotonic: float
    alignment_status: str

class CaptureFailure(RuntimeError):
    pass

SHOWINFO=re.compile(r'^\[Parsed_showinfo(?:_\d+)?(?: @ [^\]]+)?\]\s+n:\s*(\d+)\s+.*?\bpts_time:\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)')

def parse_pts(line):
    match=SHOWINFO.search(line)
    if not match:
        return None
    index,pts=int(match[1]),float(match[2])
    if not math.isfinite(pts):
        raise CaptureFailure('invalid_media_timestamp')
    return index,pts

class LiveFrameSource:
    def __init__(self,settings,source,recorded_file=False,process_factory=subprocess.Popen,
                 clock=utc_now,monotonic=time.monotonic):
        self.settings=settings
        self._source=source
        self._recorded_file=recorded_file
        self._factory=process_factory
        self._clock,self._monotonic=clock,monotonic
        self._done=Event()
        self._lock=Lock()
        self._process=None
        self.epoch=str(uuid4())

    def command(self):
        if not isinstance(self._source,str) or not self._source or any(c in self._source for c in ('\n','\r','\x00')):
            raise CaptureFailure('invalid_source')
        if self._recorded_file:
            source=Path(self._source)
            if not source.is_file():
                raise CaptureFailure('missing_recorded_file')
            input_options=['-readrate','1']
            target=str(source.resolve())
        elif self._source.lower().startswith(('rtsp://','rtsps://')):
            input_options=['-rtsp_transport','tcp']
            target=self._source
        else:
            raise CaptureFailure('invalid_source')
        filters=[]
        if self.settings.roi:
            x,y,width,height=self.settings.roi
            filters.append(f'crop=iw*{width}:ih*{height}:iw*{x}:ih*{y}')
        interval=1/self.settings.sample_fps
        filters += [f"select=isnan(prev_selected_t)+gte(t-prev_selected_t\\,{interval})",
            f'scale={self.settings.width}:{self.settings.height}:force_original_aspect_ratio=decrease',
            f'pad={self.settings.width}:{self.settings.height}:(ow-iw)/2:(oh-ih)/2', 'showinfo']
        return ['ffmpeg','-nostdin','-hide_banner','-loglevel','info','-copyts',*input_options,'-i',target,
            '-map','0:v:0','-an','-vf',','.join(filters),'-fps_mode','passthrough','-pix_fmt','rgb24',
            '-f','rawvideo','pipe:1']

    def frames(self):
        if not self.settings.enabled:
            return
        process=None
        selector=selectors.DefaultSelector()
        try:
            process=self._factory(self.command(),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,shell=False,bufsize=0)
            with self._lock:
                self._process=process
            if self._done.is_set():
                return
            selector.register(process.stdout,selectors.EVENT_READ,'rgb')
            selector.register(process.stderr,selectors.EVENT_READ,'pts')
            raw=bytearray()
            lines=bytearray()
            timestamps={}
            index=0
            first_pts=None
            anchor=None
            last_pts=None
            frame_bytes=self.settings.width*self.settings.height*3
            last_progress=self._monotonic()
            while not self._done.is_set():
                if self._monotonic()-last_progress > self.settings.capture_timeout_seconds:
                    raise CaptureFailure('capture_stalled')
                for key,_ in selector.select(.1):
                    chunk=os.read(key.fileobj.fileno(),65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    if key.data=='rgb':
                        raw.extend(chunk)
                    else:
                        lines.extend(chunk)
                        while b'\n' in lines:
                            line,_,remaining=lines.partition(b'\n')
                            lines=bytearray(remaining)
                            parsed=parse_pts(line.decode('ascii',errors='ignore'))
                            if parsed:
                                timestamps[parsed[0]]=parsed[1]
                        if len(lines)>16384:
                            lines.clear()
                    if len(raw)>frame_bytes*4 or len(timestamps)>16:
                        raise CaptureFailure('capture_backlog')
                while len(raw)>=frame_bytes and index in timestamps:
                    pts=timestamps.pop(index)
                    if last_pts is not None and pts <= last_pts:
                        raise CaptureFailure('nonmonotonic_media_timestamp')
                    received=self._clock()
                    receipt_mono=self._monotonic()
                    if anchor is None:
                        anchor=received
                        first_pts=pts
                    mapped=anchor+timedelta(seconds=pts-first_pts)
                    data=bytes(raw[:frame_bytes])
                    del raw[:frame_bytes]
                    frame=TimestampedFrame(data,mapped.isoformat(),f'{self.epoch}:{index}',pts,
                        self.settings.capture_uncertainty_ms,self.settings.width,self.settings.height,'rgb24')
                    index+=1
                    last_pts=pts
                    last_progress=receipt_mono
                    yield CapturedFrame(frame,self.epoch,received.isoformat(),receipt_mono,
                        'estimated' if self.settings.capture_uncertainty_ms is not None else 'unknown')
                if not selector.get_map():
                    returncode=process.poll()
                    if raw or timestamps:
                        raise CaptureFailure('incomplete_sample')
                    if returncode not in (None,0) or not self._recorded_file:
                        raise CaptureFailure('unexpected_source_termination')
                    return
        except CaptureFailure:
            raise
        except Exception:
            raise CaptureFailure('capture_failed') from None
        finally:
            selector.close()
            self._finish(process)

    def _finish(self,process):
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except Exception:
                    process.kill()
                    process.wait(timeout=2)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        finally:
            for pipe in (getattr(process,'stdout',None),getattr(process,'stderr',None)):
                if pipe:
                    try:
                        pipe.close()
                    except Exception:
                        pass

    def close(self):
        self._done.set()
        with self._lock:
            process=self._process
        self._finish(process)
