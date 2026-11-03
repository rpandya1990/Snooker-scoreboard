"""Single adapter owner, bounded async inference, conservative coverage failures."""
from dataclasses import dataclass
from queue import Queue, Empty, Full
from threading import Event, Thread, Lock
import time
from ai_scoring.clients.live_capture import LiveFrameSource, CaptureFailure
from ai_scoring.services.scoring import utc_now, timestamp
from ai_scoring.domain.visual_adapter import VisualResult

@dataclass(frozen=True)
class InferenceJob:
    captured: object
    context: object
    epoch: str
    queued_monotonic: float
    work_id: str | None = None

class LiveObserver:
    def __init__(self,service,settings,source,recorded_file=False,adapter=None,
                 capture_factory=LiveFrameSource,clock=utc_now,monotonic=time.monotonic):
        self.service,self.settings=service,settings
        self._source,self._recorded_file=source,recorded_file
        self._adapter=adapter
        self._capture_factory=capture_factory
        self._clock,self._monotonic=clock,monotonic
        self._capture=None
        self._queue=Queue(settings.queue_size)
        self._done=Event()
        self._model_ready=Event()
        self._threads=[]
        self._status='disabled' if not settings.enabled else 'idle'
        self._reason=None
        self._last_media_time=None
        self._capture_epoch=None
        self._adapter_epoch=None
        self._unknown_flagged_frame=None
        self._state_lock=Lock()
        self._tracking=settings.inference_trigger=='shot'
        self._generation=None
        self._work_id=None
        self._last_event=None
        self._last_baseline_logged=None


    @property
    def health(self):
        health={'status':self._status,'reason':self._reason,'model':self.settings.model,
                'queuedJobs':self._queue.qsize()}
        if self._tracking:
            health.update(trackingState=self._last_event,changePending=self._work_id is not None)
        return health

    def start(self):
        if not self.settings.enabled or self._status!='idle':
            return
        self._status='starting'
        self._threads=[Thread(target=self._infer,name='visual-inference',daemon=True),
                       Thread(target=self._read,name='visual-capture',daemon=True)]
        for thread in self._threads:
            thread.start()

    def _failure(self,reason,discontinue=True):
        self._reason=reason
        try:
            self.service.visual_failure(reason,discontinue)
        except Exception:
            self._status='failed'

    def submit(self,captured):
        if self._done.is_set():
            return
        context=self.service.visual_context(captured.frame.timestamp)
        if context is None:
            return
        if self._capture_epoch is not None and self._capture_epoch != captured.capture_epoch:
            self._failure('capture_epoch_changed')
        if self._last_media_time is not None and (captured.frame.media_time<=self._last_media_time or captured.frame.media_time-self._last_media_time>self.settings.max_frame_gap_seconds):
            self._failure('sample_coverage_gap')
        self._last_media_time=captured.frame.media_time
        self._capture_epoch=captured.capture_epoch
        if captured.frame.utc_uncertainty_ms is None or captured.frame.utc_uncertainty_ms > self.settings.max_capture_uncertainty_ms:
            if self._unknown_flagged_frame != context[0].frame_id:
                self._failure('exposure_time_unresolved',discontinue=False)
                self._unknown_flagged_frame=context[0].frame_id
        # Failure may have advanced the epoch: bind to the current generation.
        context=self.service.visual_context(captured.frame.timestamp)
        if context is None:
            return
        if self._tracking:
            self._track(captured,context)
        else:
            self._enqueue(InferenceJob(captured,context[0],context[1],self._monotonic()))

    def _enqueue(self,job):
        try:
            self._queue.put_nowait(job)
            return True
        except Full:
            self._failure('inference_queue_dropped_window')
            jobs=[job]
            while True:
                try:jobs.append(self._queue.get_nowait())
                except Empty:break
            for pending in jobs:self._resolve_job(pending,False,'inference_queue_dropped_window')
            return False

    def _resolve_job(self,job,resolved,reason=None):
        if job.work_id:
            self.service.finish_inference_pending(job.work_id,job.context,job.epoch,resolved=resolved,reason=reason)

    def _track(self,captured,snapshot):
        """Read every sampled frame; the adapter accepts only stable clear changes."""
        context,epoch=snapshot
        adapter=self._adapter
        if adapter is None:
            return
        if (context.frame_id,context.run_id,epoch)!=self._generation:
            # A committed entry or failure moved the boundary; old work is void.
            self._work_id=None
            if self._generation is not None and self._generation[2]!=epoch:
                if self.service.baseline_initialized:
                    adapter.reset_epoch()
                else:
                    adapter.reset_baseline_attempt()
            self._generation=(context.frame_id,context.run_id,epoch)
        event,result=adapter.track(captured.frame,context)
        self._last_event=event
        summary=adapter.last_baseline_diagnostic
        if summary is not None:
            adapter.last_baseline_diagnostic=None
            # Log a rejected starting table once per distinct reading, not per frame.
            key=(summary.get('reds'),tuple(summary.get('coloursPresent',())))
            if key!=self._last_baseline_logged:
                self._last_baseline_logged=key
                self.service.visual_diagnostic(context,'baseline_check',summary,adapter.metadata)
        if event=='diverging' and self._work_id is None and self.service.baseline_initialized:
            # Hide the previous suggestion while a possible change settles.
            self._work_id=self.service.mark_inference_pending(context,epoch,'shot_in_progress')
        elif event=='steady':
            if self._work_id is not None:
                self.service.finish_inference_pending(self._work_id,context,epoch,resolved=True)
                self._work_id=None
            if self.service.baseline_initialized:
                self.service.advance_verified_quiet(context,epoch,captured.frame,self.settings.prediction_ttl_seconds)
        elif result is not None:
            work,self._work_id=self._work_id,None
            try:
                self.service.apply_visual_result(result,context,epoch,captured.frame,adapter.metadata,0,
                    self.settings.prediction_ttl_seconds,work_id=work)
            except Exception:
                self._failure('visual_result_rejected')

    def _read(self):
        try:
            while not self._done.is_set() and not self._model_ready.wait(.1):
                pass
            if self._done.is_set():
                return
            capture=self._capture_factory(self.settings,self._source,recorded_file=self._recorded_file,
                clock=self._clock,monotonic=self._monotonic)
            with self._state_lock:
                self._capture=capture
            if self._done.is_set():
                capture.close()
                return
            self._status='observing'
            for captured in self._capture.frames():
                if self._done.is_set():
                    break
                self.submit(captured)
            if not self._done.is_set():
                self._failure('capture_ended')
                self._status='stopped' if self._recorded_file else 'failed'
        except CaptureFailure as error:
            if not self._done.is_set():
                self._failure(str(error))
                self._status='failed'
        except Exception:
            if not self._done.is_set():
                self._failure('capture_failed')
                self._status='failed'
        finally:
            if self._capture:
                self._capture.close()

    def _infer(self):
        try:
            if self._adapter is None:
                if self._tracking:
                    from ai_scoring.services.inventory_adapter import create
                else:
                    from ai_scoring.services.ollama_adapter import create
                adapter=create({'model':self.settings.model,'endpoint':self.settings.endpoint,
                    'windowFrames':self.settings.window_frames,'maxFrameGapSeconds':self.settings.max_frame_gap_seconds,
                    'minConfidence':self.settings.min_confidence,'seed':0,'timeoutSeconds':self.settings.model_timeout_seconds,
                    'calibration':self.settings.calibration or {},'stableSeconds':self.settings.stable_seconds,'ballModel':self.settings.ball_model,
                    'debugFrameDirectory':str(self.service.store.path.parent/'inference-frames') if self.settings.save_inference_frames else None})
                with self._state_lock:
                    if not self._done.is_set():
                        self._adapter=adapter
                if self._done.is_set():
                    close=getattr(adapter,'close',None)
                    if close:
                        close()
                    return
            if self._done.is_set():
                return
            self._model_ready.set()
            while not self._done.is_set():
                try:
                    job=self._queue.get(timeout=.1)
                except Empty:
                    continue
                self.process(job)
        except Exception:
            if not self._done.is_set():
                self._failure('model_initialisation_failed')
                self._status='failed'
                self._done.set()
                if self._capture:
                    self._capture.close()

    def _current_job(self,job):
        snapshot=self.service.visual_context(job.captured.frame.timestamp)
        return bool(snapshot and snapshot[0].frame_id==job.context.frame_id and snapshot[0].run_id==job.context.run_id and snapshot[1]==job.epoch)

    def _diagnostic(self,job,reason):
        try:
            self.service.visual_diagnostic(job.context,reason)
        except Exception:
            pass

    def process(self,job):
        try:
            self._process(job)
        finally:
            # Accepted batches resolve atomically inside apply_visual_result. Every
            # remaining current token represents an unresolved observation window.
            if job.work_id:
                self._resolve_job(job,False,'shot_inference_unresolved')

    def _process(self,job):
        if self._done.is_set():
            return
        if not self._current_job(job):
            self._diagnostic(job,"late_or_changed_boundary")
            return
        started=self._monotonic()
        if started-job.queued_monotonic > self.settings.job_freshness_seconds:
            self._failure('inference_job_stale')
            return
        try:
            if self._adapter_epoch is not None and self._adapter_epoch != job.epoch:
                reset=getattr(self._adapter,'reset_epoch',None)
                if reset:
                    reset()
            self._adapter_epoch=job.epoch
            result=self._adapter.observe(job.captured.frame,job.context)
            if not isinstance(result,VisualResult):
                raise ValueError('invalid adapter result')
        except Exception:
            if self._current_job(job):
                self._failure('model_failed')
            else:
                self._diagnostic(job,'late_model_failure')
            return
        if self._done.is_set():
            return
        if not self._current_job(job):
            self._diagnostic(job,'late_or_changed_boundary')
            return
        ended=self._monotonic()
        if ended-job.queued_monotonic > self.settings.job_freshness_seconds:
            self._failure('inference_job_stale')
            return
        age=(self._clock()-timestamp(job.captured.frame.timestamp)).total_seconds()
        if age > self.settings.job_freshness_seconds or age < -self.settings.max_capture_uncertainty_ms/1000:
            self._failure('source_timestamp_stale')
            return
        try:
            baseline_summary=getattr(self._adapter,'last_baseline_diagnostic',None)
            if baseline_summary is not None:
                provenance=dict(self._adapter.metadata,inferenceLatencyMs=round((ended-started)*1000))
                self.service.visual_diagnostic(job.context,'baseline_check',baseline_summary,provenance)
            self.service.apply_visual_result(result,job.context,job.epoch,job.captured.frame,
                self._adapter.metadata,round((ended-started)*1000),self.settings.prediction_ttl_seconds,work_id=job.work_id)
        except Exception:
            self._failure('visual_result_rejected')

    def close(self,reason='shutdown'):
        self._done.set()
        if self._capture:
            self._capture.close()
        close=getattr(self._adapter,'close',None)
        if close:
            try:
                close()
            except Exception:
                pass
        for thread in self._threads:
            if thread is not __import__('threading').current_thread():
                thread.join(timeout=2)
        self._status='stopped'
