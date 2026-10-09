"""One camera lease; session metadata and accepted events survive process restarts."""
from datetime import timedelta
from threading import RLock, Event, Thread
from ai_scoring.config import Mode
from ai_scoring.clients.recording import RecordingWorker, purge_expired_sessions
from ai_scoring.services.live_observer import LiveObserver
import time
from uuid import uuid4
from ai_scoring.dao.jsonl import JsonlSessionStore, IdentityConflict
from ai_scoring.services.scoring import ScoringService, EventConflict, utc_now

class SessionManager:
    def __init__(self, config, clock=utc_now, lease_seconds=30, recording_factory=RecordingWorker, watchdog_seconds=.25, inference_factory=LiveObserver):
        self.config = config
        self.clock = clock
        self.lease_seconds = lease_seconds
        self._sessions = {}
        self._active = None
        self._expires = None
        self._lock = RLock()
        self._recording_factory=recording_factory
        self._recorders={}
        self._recording_attempted=set()
        self._recording_failures={}
        self._inference_factory=inference_factory
        self._observers={}
        self._inference_attempted=set()
        self._inference_failures={}
        self._shutdown=Event()
        self._watchdog=None
        self._last_purge=0.0
        if config.recording.enabled or config.inference.enabled:
            self._watchdog=Thread(target=self._watch, args=(watchdog_seconds,),daemon=True,name="session-lease-watchdog")
            self._watchdog.start()

    def _watch(self, interval):
        while not self._shutdown.wait(interval):
            with self._lock:
                try:
                    self._expire()
                    for recorder in self._recorders.values():
                        recorder.cleanup()
                    if time.monotonic()-self._last_purge > 30:
                        purge_expired_sessions(self.config.data_directory,self.config.recording,clock=self.clock)
                        self._last_purge=time.monotonic()
                except Exception:
                    if self._active in self._recorders:
                        try:
                            self._recorders[self._active].close("lease_storage_failure")
                        except Exception:
                            pass
                    self._active=None

    def _expire(self):
        if self._active and self.clock() >= self._expires:
            session_id=self._active
            self._active=None
            if session_id in self._recorders:
                try:
                    self._recorders[session_id].close('lease_expired')
                except Exception:
                    pass
            # A later explicit lease claim may resume capture in a new epoch.
            # Ordinary duplicate opens while this lease is active never retry it.
            self._recording_attempted.discard(session_id)
            self._recording_failures.pop(session_id,None)
            if session_id in self._observers:
                try:
                    self._observers[session_id].close('lease_expired')
                except Exception:
                    pass
            self._inference_attempted.discard(session_id)
            self._inference_failures.pop(session_id,None)
            self._sessions[session_id].discontinuity('lease_expired')

    def open(self, request):
        session_id = request.get('sessionId')
        mode = Mode(request.get('mode', 'off'))
        if self.config.mode == Mode.OFF or mode == Mode.OFF:
            raise EventConflict('observer is off')
        if self.config.mode == Mode.DRY_RUN and mode == Mode.ASSIST:
            raise EventConflict('assist is not enabled by server configuration')
        metadata = {'sessionId': session_id, 'mode': mode.value}
        with self._lock:
            self._expire()
            if self._active and self._active != session_id and not (session_id in self._sessions and self._sessions[session_id].stopped):
                raise EventConflict('camera already leased by another session')
            if session_id not in self._sessions:
                store = JsonlSessionStore(self.config.data_directory, session_id)
                records = store.records
                previous = next((r for r in records if r['type'] == 'session_opened'), None)
                if previous and {key:previous['payload'].get(key) for key in metadata} != metadata:
                    store.close()
                    raise IdentityConflict('session ID reused with different configuration')
                if not previous:
                    store.append({'id':'session-opened', 'type':'session_opened', 'timestamp':self.clock().isoformat(), 'payload':metadata})
                self._sessions[session_id] = ScoringService(store, mode, self.clock)
            service = self._sessions[session_id]
            if service.mode != mode:
                raise IdentityConflict('session ID reused with different mode')
            if service.stopped:
                return dict(metadata, serverTimestamp=self.clock().isoformat(), leaseSeconds=0, stopped=True)
            self._active = session_id
            self._expires = self.clock() + timedelta(seconds=self.lease_seconds)
            if self.config.recording.enabled and session_id not in self._recording_attempted:
                self._recording_attempted.add(session_id)
                try:
                    recorder=self._recording_factory(service.store,self.config.recording,
                        str(self.config.recorded_source) if self.config.recorded_source is not None else self.config.camera_url,
                        recorded_file=self.config.recorded_source is not None,clock=self.clock)
                    self._recorders[session_id]=recorder
                    recorder.start()
                except Exception:
                    # Capture is optional: never reject already accepted scoring ownership.
                    self._recording_failures[session_id]={"status":"failed","reason":"capture_start_failed"}
                    try:
                        service.store.append({"id":"capture_gap:"+str(uuid4()),"type":"capture_gap",
                            "timestamp":self.clock().isoformat(),"payload":{"reason":"capture_start_failed","alignmentStatus":"unknown"}})
                    except Exception:
                        pass
            if self.config.inference.enabled and session_id not in self._inference_attempted:
                self._inference_attempted.add(session_id)
                try:
                    observer=self._inference_factory(service,self.config.inference,
                        str(self.config.recorded_source) if self.config.recorded_source is not None else self.config.camera_url,
                        recorded_file=self.config.recorded_source is not None,clock=self.clock)
                    self._observers[session_id]=observer
                    observer.start()
                except Exception:
                    self._inference_failures[session_id]={'status':'failed','reason':'observer_start_failed'}
                    try:
                        service.visual_failure('observer_start_failed')
                    except Exception:
                        pass
            recorder=self._recorders.get(session_id)
            observer=self._observers.get(session_id)
            return dict(metadata, serverTimestamp=self.clock().isoformat(), leaseSeconds=self.lease_seconds,
                recordingHealth=getattr(recorder,'health',self._recording_failures.get(session_id,{'status':'disabled' if not self.config.recording.enabled else 'unavailable'})),
                inferenceHealth=getattr(observer,'health',self._inference_failures.get(session_id,{'status':'disabled' if not self.config.inference.enabled else 'unavailable'})))

    def get(self, session_id):
        with self._lock:
            self._expire()
            if session_id != self._active:
                raise EventConflict('session lease is inactive')
            return self._sessions[session_id]

    def heartbeat(self, session_id):
        with self._lock:
            self.get(session_id)
            self._expires = self.clock() + timedelta(seconds=self.lease_seconds)
            recorder=self._recorders.get(session_id)
            return {'sessionId': session_id, 'serverTimestamp': self.clock().isoformat(), 'leaseSeconds': self.lease_seconds,
                'recordingHealth':getattr(recorder,'health',self._recording_failures.get(session_id,{'status':'disabled' if not self.config.recording.enabled else 'unavailable'}))}

    def event(self, session_id, event):
        with self._lock:
            service = self._sessions.get(session_id)
            if service and event.get('eventId') in service.events:
                return service.apply_event(event)
            service = self.get(session_id)
            result = service.apply_event(event)
            if service.stopped:
                if session_id in self._observers:
                    try:
                        self._observers[session_id].close('session_stopped')
                    except Exception:
                        pass
                if session_id in self._recorders:
                    try:
                        self._recorders[session_id].close('session_stopped')
                    except Exception:
                        pass
                self._active = None
            return result

    def close(self):
        self._shutdown.set()
        if self._watchdog:
            self._watchdog.join(timeout=7)
        for recorder in self._recorders.values():
            try:
                recorder.close("shutdown")
            except Exception:
                pass
        for observer in self._observers.values():
            try:
                observer.close("shutdown")
            except Exception:
                pass
        for service in self._sessions.values():
            service.store.close()
