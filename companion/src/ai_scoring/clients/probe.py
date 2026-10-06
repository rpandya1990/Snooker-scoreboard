"""Read-only, explicitly enabled metadata probe; no recording or inference.

The subprocess receives the original source as one argument. Never include its
command, stderr, raw metadata or exceptions in logs or persisted records.
"""
from dataclasses import asdict, dataclass
from fractions import Fraction
import json
import math
from pathlib import Path
import re
import subprocess
import time
from ai_scoring.config import Mode

KNOWN_CODECS = frozenset(('h264','hevc','mjpeg','mpeg4','av1','vp8','vp9',
    'mpeg2video','rawvideo','prores','ffv1','h263','theora','jpeg2000','png'))

@dataclass(frozen=True)
class ProbeResult:
    status: str
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    elapsed_ms: int | None = None
    reason: str | None = None

    def to_dict(self):
        return asdict(self)

class MediaProbe:
    def __init__(self, runner=None, monotonic=None, executable='ffprobe', timeout_seconds=10):
        if not isinstance(timeout_seconds,(int,float)) or isinstance(timeout_seconds,bool) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError('probe timeout must be positive and finite')
        self._runner = runner if runner is not None else subprocess.run
        self._monotonic = monotonic if monotonic is not None else time.monotonic
        self._executable = executable
        self._timeout = timeout_seconds

    def inspect(self, source, mode=Mode.OFF, recorded_file=False):
        if Mode(mode) == Mode.OFF:
            return ProbeResult('disabled',reason='off')
        if not isinstance(source,str) or not source or any(character in source for character in ('\n','\r','\x00')):
            return ProbeResult('unavailable',reason='invalid_source')
        if recorded_file:
            try:
                if not Path(source).is_file():
                    return ProbeResult('unavailable',reason='missing_recorded_file')
                # Absolute local path prevents an option or URL from being interpreted.
                target = str(Path(source).resolve())
            except (OSError,ValueError):
                return ProbeResult('unavailable',reason='invalid_source')
            transport=[]
        else:
            # Do not split authority/userinfo: passwords may contain reserved @.
            if not source.lower().startswith(('rtsp://','rtsps://')):
                return ProbeResult('unavailable',reason='invalid_source')
            target=source
            transport=['-rtsp_transport','tcp']
        command=[self._executable,'-v','error',*transport,'-select_streams','v:0',
            '-show_entries','stream=codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate',
            '-of','json',target]
        started=self._monotonic()
        def failed(reason):
            return ProbeResult('unavailable',elapsed_ms=max(0,round((self._monotonic()-started)*1000)),reason=reason)
        try:
            process=self._runner(command,capture_output=True,text=True,shell=False,timeout=self._timeout,check=False)
        except subprocess.TimeoutExpired:
            return failed('probe_timeout')
        except FileNotFoundError:
            return failed('ffprobe_missing')
        except (OSError,ValueError,UnicodeError):
            return failed('probe_failed')
        if process.returncode != 0:
            return failed('probe_failed')
        try:
            if not isinstance(process.stdout,str) or len(process.stdout)>65536:
                raise ValueError()
            metadata=json.loads(process.stdout)
            streams=metadata.get('streams') if isinstance(metadata,dict) else None
            if not isinstance(streams,list):
                raise ValueError()
            video=next((stream for stream in streams if isinstance(stream,dict) and stream.get('codec_type')=='video'),None)
            if video is None:
                return failed('no_video_stream')
            width,height=video.get('width'),video.get('height')
            if any(type(dimension) is not int or not 0 < dimension <= 65536 for dimension in (width,height)):
                raise ValueError()
            raw_codec=video.get('codec_name')
            codec=raw_codec if isinstance(raw_codec,str) and raw_codec in KNOWN_CODECS else 'unknown'
            fps=None
            for key in ('avg_frame_rate','r_frame_rate'):
                raw_rate=video.get(key)
                if not isinstance(raw_rate,str) or len(raw_rate)>32 or not re.fullmatch(r'\d+(?:/\d+)?',raw_rate):
                    continue
                try:
                    candidate=float(Fraction(raw_rate))
                except (ValueError,ZeroDivisionError,OverflowError):
                    continue
                if math.isfinite(candidate) and 0 < candidate <= 1000:
                    fps=candidate
                    break
        except (ValueError,TypeError,KeyError):
            return failed('invalid_probe_metadata')
        return ProbeResult('available',codec,width,height,fps,max(0,round((self._monotonic()-started)*1000)))
