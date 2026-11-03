"""Durable session orchestration; entered points never alter rules/inference."""
import copy
import math
from datetime import datetime, timedelta, timezone
from threading import RLock
from uuid import uuid4
from ai_scoring.config import Mode
from ai_scoring.dao.jsonl import IdentityConflict
from ai_scoring.domain.scoring import SnookerAccumulator, PotObservation, CLEARANCE, interpretable_table

def utc_now():
    return datetime.now(timezone.utc)

def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('timestamp must be a string')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timestamp requires timezone')
    return parsed

PERSISTENT_REASONS = frozenset({'exposure_time_unresolved'})

class EventConflict(ValueError):
    pass

class ScoringService:
    def __init__(self, store, mode=Mode.DRY_RUN, clock=utc_now):
        self.store = store
        self.mode = Mode(mode)
        self.clock = clock
        self._lock = RLock()
        self.sequence = 0
        self.frame_id = None
        self.run_id = None
        self._frame_started_at = None
        self._run_started_at = None
        self.rules = None
        self.stopped = False
        self.predictions = {}
        self.entries = {}
        self.events = {}
        self.observed_through = None
        self._last_scoring_at = None
        self._last_activity_started_at = None
        self.activity_version = 0
        self.epoch = str(uuid4())
        self._pending_work = {}
        self.reasons = {'table_not_initialised'}
        records = store.records
        for record in records:
            self._replay(record)
        if self.frame_id:
            self.discontinuity('restart')

    def _record(self, kind, identifier, payload):
        return {'id': identifier, 'type': kind, 'timestamp': self.clock().isoformat(), 'payload': payload}

    def _replay(self, record):
        kind, payload = record['type'], record['payload']
        if kind == 'event':
            event = payload['event']
            if event['type']=='frame_started':
                self._frame_started_at=record['timestamp']
                self._run_started_at=record['timestamp']
            self.events[event['eventId']] = copy.deepcopy(payload)
            self.sequence = event['sequence']
            self._apply(event)
            if payload.get('comparison', {}).get('boundaryUncertain'):
                self.reasons.add('boundary_unsynchronised')
        elif kind == 'baseline':
            self._apply(payload)
        elif kind == 'prediction':
            self.predictions[payload['predictionId']] = copy.deepcopy(payload)
        elif kind == 'observation':
            if self.rules:
                if payload['kind'] == 'respot':
                    self.rules.respot(payload['ball'])
                else:
                    self.rules.pot(payload['ball'], payload['count'])
                    self._last_scoring_at=payload['timestamp']
                self.observed_through = payload['timestamp']
                self.activity_version += 1
        elif kind == 'visual_quality':
            self.reasons.add(payload['reason'])
        elif kind == 'visual_watermark':
            self.observed_through=payload['observedThrough']
        elif kind == 'discontinuity':
            self._pending_work.clear()
            self.reasons.add(payload['reason'])
            self.epoch = payload['epoch']

    def _apply(self, event):
        kind = event['type']
        if kind == 'frame_started':
            self._pending_work.clear()
            self.frame_id, self.run_id = event['frameId'], event['runId']
            self.rules = SnookerAccumulator(event.get('reds', 15))
            self.reasons = {'table_not_initialised'}
            self.observed_through = None
            self._last_scoring_at = None
            self._last_activity_started_at = None
            self.stopped = False
        elif kind == 'baseline_confirmed':
            # A settled interpretable table fixes physical state from what is visible,
            # so earlier observation failures clear; ongoing conditions remain.
            self.reasons &= PERSISTENT_REASONS
            if 'reds' in event:
                self.rules = SnookerAccumulator(event['reds'])
                self.rules.clearance_index = event['clearanceIndex']
                self.rules.new_visit()
            if event.get('midFrame'):
                # Points scored earlier in this visit were never observed.
                self.reasons.add('run_started_before_baseline')
            self.observed_through = event['observedThrough']
        elif kind == 'break_committed':
            if self._pending_work:
                self.reasons.add('boundary_unsynchronised')
                self._pending_work.clear()
            self.entries[event['entryId']] = copy.deepcopy(event)
            self.reasons.discard('run_started_before_baseline')
            self.run_id = event['nextRunId']
            self._run_started_at=event['committedAt']
            self.rules.new_visit()
            # Frame-wide uncertainty cannot be repaired by a entered score.
        elif kind in ('correction', 'undo'):
            targets = event.get('affectedEntryIds') or ([event['entryId']] if event.get('entryId') else [])
            if targets:
                for target in targets:
                    if target in self.entries:
                        self.entries[target]['labelStatus'] = 'invalidated' if kind == 'undo' else 'correction_affected'
            else:
                for entry in self.entries.values():
                    entry['labelStatus'] = 'correction_affected'
        elif kind in ('frame_ended', 'session_stopped'):
            self._pending_work.clear()
            self.frame_id = self.run_id = None
            self.rules = None
            if kind == 'session_stopped':
                self.stopped = True

    def _validate(self, event):
        if self.mode == Mode.OFF:
            raise EventConflict('observer is off')
        if self.stopped:
            raise EventConflict('session is stopped')
        if type(event.get('sequence')) is not int or event['sequence'] != self.sequence + 1:
            raise EventConflict('missing or out-of-order sequence')
        if not isinstance(event.get('eventId'), str) or not event['eventId']:
            raise ValueError('eventId required')
        kind = event.get('type')
        if kind not in ('frame_started', 'frame_ended', 'session_stopped', 'break_committed', 'correction', 'undo'):
            raise ValueError('unsupported client event')
        if kind == 'frame_started':
            for key in ('frameId', 'runId'):
                if not isinstance(event.get(key), str) or not event[key]:
                    raise ValueError(key + ' required')
            SnookerAccumulator(event.get('reds', 15))
        elif kind != 'session_stopped':
            if not self.frame_id or event.get('frameId') != self.frame_id:
                raise EventConflict('frame mismatch')
        if kind == 'break_committed':
            if event.get('runId') != self.run_id:
                raise EventConflict('run mismatch')
            for key in ('entryId', 'attemptId', 'nextRunId'):
                if not isinstance(event.get(key), str) or not event[key]:
                    raise ValueError(key + ' required')
            used_runs = {r['payload']['event'].get('runId') for r in self.store.records if r['type'] == 'event'}
            if event['entryId'] in self.entries or event['nextRunId'] in used_runs:
                raise EventConflict('entry or run ID already used')
            for key in ('submittedPoints', 'appliedScoreDelta'):
                if type(event.get(key)) is not int or event[key] < 0:
                    raise ValueError(key + ' must be a nonnegative integer')
            if event.get('source') not in ('manual', 'ai_selected', 'ai_selected_edited'):
                raise ValueError('invalid entry source')
            started = timestamp(event['inputStartedAt'])
            if timestamp(event['committedAt']) < started:
                raise ValueError('commit predates input')
            prediction = self.predictions.get(event.get('predictionId'))
            if event.get('predictionId') and prediction is None:
                raise EventConflict('unknown prediction')
            if prediction and (prediction['runId'] != self.run_id or prediction['frameId'] != self.frame_id or timestamp(prediction['createdAt']) > started):
                raise EventConflict('prediction was not available before input in this run')

    def apply_event(self, event):
        event = copy.deepcopy(event)
        with self._lock:
            previous = self.events.get(event.get('eventId'))
            if previous is not None:
                if previous['event'] != event:
                    raise IdentityConflict('event ID reused with changed payload')
                return copy.deepcopy(previous['ack'])
            self._validate(event)
            ack = {'eventId': event['eventId'], 'sequence': event['sequence'], 'status': 'accepted'}
            payload = {'event': event, 'ack': ack}
            if event['type'] == 'break_committed':
                pred = self.predictions.get(event.get('predictionId'))
                available = bool(pred and pred['status'] == 'available')
                boundary_uncertain = (bool(self._pending_work)
                                      or bool(pred and pred.get('activityVersion')!=self.activity_version)
                                      or bool(self._last_activity_started_at and timestamp(self._last_activity_started_at)>timestamp(event['inputStartedAt']))
                                      or ('clockUncertaintyMs' in event and (event['clockUncertaintyMs'] is None or event['clockUncertaintyMs'] > 500))
                                      or bool(self._last_scoring_at and timestamp(self._last_scoring_at) > timestamp(event['inputStartedAt'])))
                payload['comparison'] = {'predictionId': event.get('predictionId'), 'predictedPoints': pred['points'] if pred else None,
                    'submittedPoints': event['submittedPoints'], 'agreement': pred['points'] == event['submittedPoints'] if available else None,
                    'labelStatus': 'correction_affected' if event.get('correctionAffected') else ('provisional' if event['source'] == 'manual' else 'ai_influenced'),
                    'boundaryUncertain': boundary_uncertain, 'reviewRequired': boundary_uncertain or (available and pred['points'] != event['submittedPoints'])}
            record = self._record('event', 'event:' + event['eventId'], payload)
            self.store.append(record)
            self._replay(record)
            return ack

    def confirm_baseline(self, observed_through, reds=15, colours=CLEARANCE):
        timestamp(observed_through)
        colours = frozenset(colours)
        if not interpretable_table(reds, colours):
            raise ValueError('uninterpretable baseline table')
        with self._lock:
            if self.mode == Mode.OFF or not self.rules:
                raise EventConflict('no observing frame')
            # Internal adapter command, never accepted as a public client event.
            event = {'eventId': str(uuid4()), 'sequence': self.sequence, 'type': 'baseline_confirmed', 'observedThrough': observed_through,
                     'reds': reds, 'clearanceIndex': 0 if reds else len(CLEARANCE) - len(colours),
                     'midFrame': not (reds == 15 and len(colours) == len(CLEARANCE))}
            record = self._record('baseline', 'baseline:' + event['eventId'], event)
            self.store.append(record)
            self._apply(event)

    def observe(self, observation: PotObservation):
        with self._lock:
            if self.mode == Mode.OFF or not self.rules:
                raise EventConflict('no observing frame')
            timestamp(observation.timestamp)
            if self.observed_through and timestamp(observation.timestamp) < timestamp(self.observed_through):
                self.discontinuity('out_of_order_observation')
                raise EventConflict('out-of-order observation')
            if observation.kind not in ('pot', 'respot'):
                raise ValueError('invalid observation kind')
            payload = {'observationId': observation.observation_id, 'ball': observation.ball.value,
                       'timestamp': observation.timestamp, 'count': observation.count, 'kind': observation.kind,
                       'frameId': self.frame_id, 'runId': self.run_id}
            # Validate counts and ball types before durable write.
            if type(observation.count) is not int or observation.count < 1 or (observation.ball.value != 'red' and observation.count != 1):
                raise ValueError('invalid observation count')
            identifier = 'observation:' + observation.observation_id
            existing = next((r for r in self.store.records if r['id'] == identifier), None)
            if existing:
                if existing['payload'] != payload:
                    raise IdentityConflict('observation ID reused')
                return
            record = self._record('observation', identifier, payload)
            self.store.append(record)
            self._replay(record)

    def discontinuity(self, reason='feed_gap'):
        with self._lock:
            record = self._record('discontinuity', 'gap:' + str(uuid4()), {'reason': reason, 'epoch': str(uuid4())})
            self.store.append(record)
            self._replay(record)

    def publish_prediction(self, model_version='unconfigured', ttl_seconds=3, visual_metadata=None, inference_latency_ms=None):
        with self._lock:
            if self.mode == Mode.OFF or not self.rules:
                raise EventConflict('no observing frame')
            now = self.clock()
            reasons = sorted(self.reasons | self.rules.quality_reasons | self._pending_reasons())
            payload = {'predictionId': str(uuid4()), 'frameId': self.frame_id, 'runId': self.run_id,
                'status': 'unavailable' if reasons else 'available', 'points': None if reasons else self.rules.points,
                'createdAt': now.isoformat(), 'observedThrough': self.observed_through,
                'observationEpoch': self.epoch, 'activityVersion': self.activity_version, 'lastAppliedEventSequence': self.sequence,
                'expiresAt': (now + timedelta(seconds=ttl_seconds)).isoformat(),
                'modelVersion': model_version, 'rulesVersion': 'clean-play-v1', 'qualityReasons': reasons}
            if visual_metadata is not None:
                payload.update(promptVersion=visual_metadata.get('promptVersion','unconfigured'),
                    adapterVersion=visual_metadata.get('adapterVersion','unconfigured'),inferenceLatencyMs=inference_latency_ms)
            record = self._record('prediction', 'prediction:' + payload['predictionId'], payload)
            self.store.append(record)
            self._replay(record)
            return copy.deepcopy(payload)

    def latest_prediction(self):
        with self._lock:
            matching = [p for p in self.predictions.values() if p['frameId'] == self.frame_id and p['runId'] == self.run_id]
            if not matching:
                return {'status': 'unavailable', 'points': None, 'frameId': self.frame_id, 'runId': self.run_id,
                        'lastAppliedEventSequence': self.sequence, 'activityVersion': self.activity_version, 'qualityReasons': sorted((self.reasons | self._pending_reasons()) or {'no_prediction'})}
            payload = copy.deepcopy(matching[-1])
            reasons = self.reasons | self._pending_reasons() | (self.rules.quality_reasons if self.rules else set())
            if timestamp(payload['expiresAt']) <= self.clock():
                reasons = reasons | {'stale'}
            if payload.get('activityVersion') != self.activity_version:
                reasons = reasons | {'new_activity'}
            if payload['observedThrough'] != self.observed_through:
                reasons = reasons | {'new_activity'}
            if reasons:
                payload.update(status='unavailable', points=None, qualityReasons=sorted(reasons))
            return payload

    def _pending_reasons(self):
        return {work['reason'] for work in self._pending_work.values()}

    def _context_matches(self,context,epoch):
        return bool(self.rules and not self.stopped and self.frame_id==context.frame_id and self.run_id==context.run_id and self.epoch==epoch)

    def _work_matches(self,work_id,context,epoch):
        work=self._pending_work.get(work_id)
        return bool(work and self._context_matches(context,epoch) and
                    (work['frameId'],work['runId'],work['epoch'])==(context.frame_id,context.run_id,epoch))

    @property
    def baseline_initialized(self):
        with self._lock:
            return bool(self.rules and 'table_not_initialised' not in self.reasons)

    def is_inference_pending(self,work_id,context,epoch):
        with self._lock:
            return self._work_matches(work_id,context,epoch)

    def cancel_unconfirmed_baseline(self,context,epoch,work_id=None):
        """Atomic startup-motion cancellation; never resets confirmed rules state."""
        with self._lock:
            if not self._context_matches(context,epoch) or self.baseline_initialized:
                return False
            if work_id and self._work_matches(work_id,context,epoch):
                del self._pending_work[work_id]
            return True

    def mark_inference_pending(self,context,epoch,reason='shot_in_progress',work_id=None):
        """Immediately suppress cached suggestions before capture/model work starts."""
        if reason not in ('shot_in_progress','inference_pending','baseline_inference_pending'):
            raise ValueError('unsupported pending reason')
        with self._lock:
            if not self._context_matches(context,epoch): return None
            if work_id is not None:
                return work_id if self._work_matches(work_id,context,epoch) else None
            token=str(uuid4())
            self._pending_work[token]={'frameId':context.frame_id,'runId':context.run_id,'epoch':epoch,'reason':reason}
            self.activity_version+=1
            self._last_activity_started_at=self.clock().isoformat()
            return token

    def finish_inference_pending(self,work_id,context,epoch,resolved=True,reason=None):
        with self._lock:
            if not self._work_matches(work_id,context,epoch): return False
            del self._pending_work[work_id]
            if not resolved:
                self.visual_failure(reason or 'unresolved_visual_work',discontinue=False)
            return True

    def advance_verified_quiet(self,context,epoch,frame,ttl_seconds=3):
        """Controller-only renewal from continuously captured, verified quiet frames."""
        with self._lock:
            if not self._context_matches(context,epoch) or self._pending_work or self.reasons or self.rules.quality_reasons:
                return False
            uncertainty=frame.utc_uncertainty_ms
            if type(uncertainty) not in (int,float) or not math.isfinite(uncertainty) or uncertainty<0:
                return False
            through=timestamp(frame.timestamp)
            if through>timestamp(context.cutoff) or (self.observed_through and through<=timestamp(self.observed_through)):
                return False
            if (self.clock()-through).total_seconds()>ttl_seconds or (through-self.clock()).total_seconds()>uncertainty/1000:
                return False
            latest=next((p for p in reversed(list(self.predictions.values())) if p['frameId']==self.frame_id and p['runId']==self.run_id),None)
            if latest is None:
                # A clean committed visit preserves physical table/rules state.
                # Reuse only model provenance, never the prior run's point total.
                latest=next((p for p in reversed(list(self.predictions.values())) if p['frameId']==self.frame_id),None)
            if latest is None: return False
            if latest['runId']==self.run_id and latest.get('activityVersion')==self.activity_version and latest.get('status')=='available' and (timestamp(latest['expiresAt'])-self.clock()).total_seconds()>ttl_seconds/2:
                return True
            record=self._record('visual_watermark','quiet:'+str(uuid4()),{
                'observedThrough':frame.timestamp,'frameId':self.frame_id,'runId':self.run_id,
                'observationEpoch':epoch,'source':'continuously_verified_quiet_capture',
                'modelReferencePredictionId':latest['predictionId'],
                'mediaTime':frame.media_time,'utcUncertaintyMs':uncertainty})
            self.store.append(record)
            self.observed_through=frame.timestamp
            self.publish_prediction(latest['modelVersion'],ttl_seconds,latest,None)
            return True

    def visual_context(self, cutoff):
        """Score-free snapshot tagged with the currently owned observation epoch."""
        from ai_scoring.domain.visual_adapter import BoundaryContext
        with self._lock:
            if not self.rules or self.stopped:
                return None
            return BoundaryContext(self.frame_id,self.run_id,self._frame_started_at,self._run_started_at,cutoff),self.epoch

    def visual_failure(self, reason, discontinue=True):
        with self._lock:
            if discontinue:
                self.discontinuity(reason)
            else:
                record=self._record('visual_quality','quality:'+str(uuid4()),{'reason':reason})
                self.store.append(record)
                self.reasons.add(reason)

    def apply_visual_result(self, result, context, epoch, frame, metadata, latency_ms, ttl_seconds, work_id=None):
        """Accept one ordered adapter result atomically against its capture generation."""
        with self._lock:
            if work_id is not None and not self._work_matches(work_id,context,epoch):
                self.visual_diagnostic(context,'late_or_resolved_inference_work')
                return False
            if self.frame_id!=context.frame_id or self.run_id!=context.run_id or self.epoch!=epoch:
                self.store.append(self._record('visual_diagnostic','diagnostic:'+str(uuid4()),
                    {'reason':'late_or_changed_boundary','frameId':context.frame_id,'runId':context.run_id,
                     'processedThrough':result.processed_through,'modelVersion':metadata.get('modelVersion','unconfigured')}))
                return False
            if result.processed_through is not None and timestamp(result.processed_through)!=timestamp(frame.timestamp):
                self.visual_failure('invalid_processed_watermark')
                return False
            for observation in result.observations:
                if timestamp(observation.timestamp)<timestamp(context.run_started_at) or timestamp(observation.timestamp)>timestamp(frame.timestamp):
                    self.visual_failure('visual_observation_outside_run')
                    return False
            if result.quality_reasons:
                for reason in result.quality_reasons:
                    if reason not in ('window_incomplete','table_not_initialised'):
                        self.visual_failure(reason,discontinue=False)
            if result.baseline_reds is not None and 'table_not_initialised' in self.reasons:
                # Adapters without a colour inventory may only confirm a fresh full table.
                colours = result.baseline_colours
                if colours is None and result.baseline_reds == 15:
                    colours = CLEARANCE
                if colours is not None and self.rules.points == 0 and interpretable_table(result.baseline_reds, colours):
                    self.confirm_baseline(frame.timestamp, result.baseline_reds, colours)
                else:
                    self.visual_failure('physical_baseline_unresolved',discontinue=False)
            for observation in result.observations:
                if timestamp(observation.timestamp)>timestamp(frame.timestamp):
                    self.visual_failure('future_visual_observation')
                    return False
                self.observe(observation)
            if result.processed_through:
                if timestamp(result.processed_through)!=timestamp(frame.timestamp):
                    self.visual_failure('invalid_processed_watermark')
                    return False
                record=self._record('visual_watermark','watermark:'+str(uuid4()),
                    {'observedThrough':result.processed_through,'frameId':self.frame_id,'runId':self.run_id,
                     'observationEpoch':epoch,'mediaTime':frame.media_time,'utcUncertaintyMs':frame.utc_uncertainty_ms,
                     'modelVersion':metadata.get('modelVersion','unconfigured'),'promptVersion':metadata.get('promptVersion','unconfigured'),
                     'adapterVersion':metadata.get('adapterVersion','unconfigured'),'inferenceLatencyMs':latency_ms})
                self.store.append(record)
                self.observed_through=result.processed_through
            else:
                self.visual_failure('missing_processed_watermark',discontinue=False)
            if work_id is not None:
                self.finish_inference_pending(work_id,context,epoch)
            self.publish_prediction(metadata.get('modelVersion','unconfigured'),ttl_seconds,metadata,latency_ms)
            return True

    def visual_diagnostic(self, context, reason, baseline_summary=None, provenance=None):
        with self._lock:
            payload={'reason':reason,'frameId':context.frame_id,'runId':context.run_id}
            if baseline_summary is not None:
                from ai_scoring.domain.baseline_diagnostics import sanitize_summary
                import re
                payload['baselineSummary']=sanitize_summary(baseline_summary)
                provenance=provenance or {}
                for key in ('modelVersion','promptVersion','adapterVersion'):
                    value=provenance.get(key)
                    if isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}',value):
                        payload[key]=value
                latency=provenance.get('inferenceLatencyMs')
                if type(latency) is int and 0<=latency<=86400000:
                    payload['inferenceLatencyMs']=latency
                payload['observationEpoch']=self.epoch
            self.store.append(self._record('visual_diagnostic','diagnostic:'+str(uuid4()),payload))
