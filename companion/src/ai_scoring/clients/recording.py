"""Opted-in local FFmpeg segments with an auditable single-writer manifest."""
import csv
from datetime import timedelta
import hashlib
import json
from fractions import Fraction
from ai_scoring.clients.probe import KNOWN_CODECS
import os
from pathlib import Path
import shutil
import subprocess
from threading import Event, RLock, Thread
import time
from uuid import uuid4
from ai_scoring.services.scoring import utc_now, timestamp

class RecordingWorker:
    def __init__(self, store, config, source, recorded_file=False, clock=utc_now,
                 monotonic=time.monotonic, process_factory=subprocess.Popen,
                 disk_usage=shutil.disk_usage, poll_seconds=.25, metadata_runner=subprocess.run):
        self.store,self.config=store,config
        self._source=source
        self._recorded_file=recorded_file
        self._clock,self._monotonic=clock,monotonic
        self._factory,self._disk_usage=process_factory,disk_usage
        self._metadata_runner=metadata_runner
        self._poll_seconds=poll_seconds
        self._process=None
        self._thread=None
        self._done=Event()
        self._lock=RLock()
        self._opened={}
        self._closed={}
        self._expired=set()
        self._state='disabled' if not config.enabled else 'idle'
        self._reason=None
        self._directory=store.path.parent/'video'
        self._epoch=str(uuid4())
        self._anchor_utc=None
        self._anchor_mono=None
        self._prefix='segment-'+self._epoch+'-'
        self._list_path=self._directory/('segments-'+self._epoch+'.csv')
        for record in store.records:
            payload=record['payload']
            if record['type']=='segment_opened':
                self._opened[payload['relativePath']]=payload
            elif record['type']=='segment_closed':
                self._closed[payload['relativePath']]=payload
            elif record['type']=='asset_expired':
                self._expired.add(payload['relativePath'])

    def _record(self, kind, payload):
        self.store.append({'id':kind+':'+str(uuid4()),'type':kind,'timestamp':self._clock().isoformat(),'payload':payload})

    @property
    def health(self):
        return {'status':self._state,'reason':self._reason,'observationEpoch':self._epoch}

    def _safe_path(self, relative):
        if not isinstance(relative,str) or not relative.startswith('video/'):
            raise ValueError('invalid recording path')
        path=self.store.path.parent/relative
        if self._directory.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(self._directory.resolve()) or path.parent.resolve()!=self._directory.resolve():
            raise ValueError('recording path escapes session')
        return path

    def _limits_ok(self):
        if self._disk_usage(self.store.path.parent).free < self.config.min_free_bytes:
            return False
        sessions=self.store.path.parent.parent
        total=0
        for path in sessions.glob('*/video/*'):
            if path.parent.is_symlink() or path.parent.parent.is_symlink() or not path.resolve().is_relative_to(sessions.resolve()):
                continue
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
        return total < self.config.total_bytes

    def start(self, background=True):
        with self._lock:
            if not self.config.enabled or self._state != 'idle':
                return
            try:
                if self._directory.is_symlink():
                    raise ValueError('unsafe recording directory')
                self._directory.mkdir(exist_ok=True)
                for path in self._directory.glob('segment-*.mkv'):
                    relative='video/'+path.name
                    self._safe_path(relative)
                    if relative not in self._opened and relative not in self._closed:
                        opened={'assetId':str(uuid4()),'relativePath':relative,'observationEpoch':None,'alignmentStatus':'incomplete'}
                        self._record('segment_opened',opened)
                        self._opened[relative]=opened
                for relative,opened in list(self._opened.items()):
                    if relative not in self._closed:
                        self._record('capture_gap',{'reason':'unfinished_segment_after_restart','assetId':opened['assetId'],
                            'relativePath':relative,'observationEpoch':self._epoch,'alignmentStatus':'incomplete'})
                self.cleanup()
                if not self._limits_ok():
                    return self._fail('storage_limits')
                if not isinstance(self._source,str) or not self._source or any(c in self._source for c in ('\n','\r','\x00')):
                    return self._fail('invalid_source')
                if self._recorded_file:
                    path=Path(self._source)
                    if not path.is_file():
                        return self._fail('missing_recorded_file')
                    source=str(path.resolve())
                    transport=['-readrate','1']
                elif self._source.lower().startswith(('rtsp://','rtsps://')):
                    source=self._source
                    transport=['-rtsp_transport','tcp']
                else:
                    return self._fail('invalid_source')
                command=['ffmpeg','-hide_banner','-loglevel','error',*transport,'-i',source,
                    '-map','0:v:0','-an','-c','copy','-f','segment','-segment_time',str(self.config.segment_seconds),
                    '-segment_list',str(self._list_path),'-segment_list_type','csv','-reset_timestamps','1',
                    str(self._directory/(self._prefix+'%06d.mkv'))]
                self._anchor_utc,self._anchor_mono=self._clock(),self._monotonic()
                self._process=self._factory(command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,shell=False)
                self._state='recording'
                self._record('recording_started',{'observationEpoch':self._epoch,'anchorUtc':self._anchor_utc.isoformat(),
                    'anchorMonotonic':self._anchor_mono,'utcUncertaintyMs':None,'alignmentStatus':'unknown',
                    'captureId':self.store.path.parent.name,'sessionId':self.store.path.parent.name,
                    'sourceKind':'recorded_file' if self._recorded_file else 'rtsp','segmentSeconds':self.config.segment_seconds})
                if background:
                    self._thread=Thread(target=self._run,daemon=True,name='recording-watchdog')
                    self._thread.start()
            except Exception:
                if self._process is not None:
                    try:
                        self._process.terminate()
                        self._process.wait(timeout=2)
                    except Exception:
                        try:
                            self._process.kill()
                        except Exception:
                            pass
                self._fail('capture_start_failed')

    def _fail(self, reason):
        self._state,self._reason='failed',reason
        try:
            self._record('capture_gap',{'reason':reason,'observationEpoch':self._epoch,'alignmentStatus':'unknown'})
        except Exception:
            pass

    def _run(self):
        while not self._done.wait(self._poll_seconds):
            self.tick()
            if self._state != 'recording':
                break

    def _media_metadata(self, path):
        try:
            result=self._metadata_runner(["ffprobe","-v","error","-select_streams","v:0",
                "-show_entries","stream=codec_name,time_base,start_time","-of","json",str(path)],
                capture_output=True,text=True,shell=False,timeout=5,check=False)
            if result.returncode != 0 or len(result.stdout)>65536:
                return {}
            streams=json.loads(result.stdout).get("streams",[])
            stream=streams[0] if streams else {}
            codec=stream.get("codec_name")
            timebase=stream.get("time_base")
            if not isinstance(timebase,str) or len(timebase)>32 or Fraction(timebase)<=0:
                timebase=None
            return {"codec":codec if codec in KNOWN_CODECS else None,"timeBase":timebase}
        except (ValueError,TypeError,KeyError,IndexError,AttributeError,OSError,subprocess.TimeoutExpired,ZeroDivisionError):
            return {}

    def _scan(self):
        for path in sorted(self._directory.glob(self._prefix+'*.mkv')):
            relative='video/'+path.name
            self._safe_path(relative)
            if relative not in self._opened:
                payload={'assetId':str(uuid4()),'relativePath':relative,'observationEpoch':self._epoch,
                         'alignmentStatus':'unknown'}
                self._record('segment_opened',payload)
                self._opened[relative]=payload
        if not self._list_path.exists():
            return
        if self._list_path.is_symlink():
            raise ValueError('unsafe segment manifest')
        # FFmpeg emits list entries when a segment closes. An incomplete final row is not trusted.
        data=self._list_path.read_text()
        for row in csv.reader(data[:data.rfind('\n')+1].splitlines()):
            if len(row)!=3:
                continue
            name=Path(row[0]).name
            if name != row[0] or not name.startswith(self._prefix):
                raise ValueError('unsafe segment name')
            relative='video/'+name
            if relative in self._closed:
                continue
            path=self._safe_path(relative)
            if not path.is_file() or relative not in self._opened:
                self._record('capture_gap',{'reason':'missing_segment','relativePath':relative,'observationEpoch':self._epoch})
                continue
            start,end=float(row[1]),float(row[2])
            import math
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start:
                raise ValueError('invalid segment times')
            checksum=hashlib.sha256()
            with path.open('rb') as stream:
                os.fsync(stream.fileno())
                for chunk in iter(lambda:stream.read(1024*1024),b''):
                    checksum.update(chunk)
            payload=dict(self._opened[relative],sha256=checksum.hexdigest(),sizeBytes=path.stat().st_size,
                mediaStart=start,mediaDuration=end-start,anchorUtc=self._anchor_utc.isoformat(),
                anchorMonotonic=self._anchor_mono,captureStartUtc=(self._anchor_utc+timedelta(seconds=start)).isoformat(),
                utcUncertaintyMs=None,alignmentStatus='unknown',codec=None,timeBase=None,closedAt=self._clock().isoformat())
            payload.update(self._media_metadata(path))
            self._record('segment_closed',payload)
            self._closed[relative]=payload

    def tick(self):
        with self._lock:
            if self._state != 'recording':
                return
            try:
                self._scan()
                self.cleanup()
                if not self._limits_ok():
                    self.stop('storage_limits')
                    self._fail('storage_limits')
                else:
                    returncode=self._process.poll()
                    if returncode is not None:
                        if self._recorded_file and returncode == 0:
                            self.stop('source_ended')
                        else:
                            self.stop('unexpected_source_termination')
                            self._fail('unexpected_source_termination')
            except Exception:
                self.stop('capture_failed')
                self._fail('capture_failed')

    def cleanup(self):
        with self._lock:
            self._cleanup()

    def _cleanup(self):
        if not self.config.enabled:
            return
        for relative,payload in list(self._closed.items()):
            if relative in self._expired:
                continue
            if (self._clock()-timestamp(payload['closedAt'])).total_seconds() < self.config.retention_seconds:
                continue
            path=self._safe_path(relative)
            if path.exists():
                self._record('asset_expiration_requested',{'assetId':payload['assetId'],'relativePath':relative,'reason':'retention'})
                path.unlink()
            self._record('asset_expired',{'assetId':payload['assetId'],'relativePath':relative,'reason':'retention',
                'observationEpoch':payload['observationEpoch']})
            self._expired.add(relative)

    def _finish_process(self):
        if self._process is None:
            return True
        try:
            if self._process.poll() is not None:
                return True
            self._process.communicate(input=b'q\n',timeout=3)
            return True
        except Exception:
            pass
        try:
            self._process.terminate()
        except Exception:
            pass
        try:
            self._process.wait(timeout=2)
            return True
        except Exception:
            pass
        try:
            self._process.kill()
        except Exception:
            pass
        try:
            self._process.wait(timeout=2)
            return True
        except Exception:
            return False

    def stop(self, reason='session_stopped'):
        with self._lock:
            if self._state != 'recording':
                return
            self._done.set()
            finalised=self._finish_process()
            if not finalised:
                self._reason='capture_process_stop_failed'
            try:
                self._scan()
                for relative,opened in self._opened.items():
                    if relative not in self._closed:
                        self._record('capture_gap',{'reason':'unfinished_segment','assetId':opened['assetId'],
                            'relativePath':relative,'observationEpoch':self._epoch,'alignmentStatus':'incomplete'})
                self._record('recording_stopped',{'reason':reason,'observationEpoch':self._epoch})
            except Exception:
                self._reason='capture_finalisation_failed'
            self._state='stopped'

    def close(self, reason='shutdown'):
        self.stop(reason)
        if self._thread and self._thread is not __import__('threading').current_thread():
            self._thread.join(timeout=6)


def purge_expired_sessions(data_directory, config, clock=utc_now):
    """Clean closed assets in idle sessions; active logs remain exclusively owned."""
    from ai_scoring.dao.jsonl import JsonlSessionStore, StorageFault
    root=Path(data_directory)/'sessions'
    if not root.exists() or root.is_symlink():
        return
    for session in root.iterdir():
        if not session.is_dir() or session.is_symlink() or not session.resolve().is_relative_to(root.resolve()):
            continue
        if not (session/'session.jsonl').is_file() or (session/'session.jsonl').is_symlink():
            continue
        store=None
        try:
            store=JsonlSessionStore(data_directory,session.name)
            worker=RecordingWorker(store,config,None,clock=clock)
            worker.cleanup()
        except (StorageFault,OSError,ValueError,KeyError,TypeError):
            # Locked active sessions and malformed manifests require their owner/operator.
            pass
        finally:
            if store is not None:
                store.close()
