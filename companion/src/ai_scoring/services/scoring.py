"""Durable session orchestration; entered points never alter rules/inference."""
import copy
from datetime import datetime, timedelta, timezone
from threading import RLock
from uuid import uuid4
from ai_scoring.config import Mode
from ai_scoring.dao.jsonl import IdentityConflict
from ai_scoring.domain.scoring import SnookerAccumulator, PotObservation

def utc_now():
    return datetime.now(timezone.utc)

def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('timestamp must be a string')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timestamp requires timezone')
    return parsed

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
        self.activity_version = 0
        self.epoch = str(uuid4())
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
            self.reasons.add(payload['reason'])
            self.epoch = payload['epoch']

    def _apply(self, event):
        kind = event['type']
        if kind == 'frame_started':
            self.frame_id, self.run_id = event['frameId'], event['runId']
            self.rules = SnookerAccumulator(event.get('reds', 15))
            self.reasons = {'table_not_initialised'}
            self.observed_through = None
            self._last_scoring_at = None
            self.stopped = False
        elif kind == 'baseline_confirmed':
            self.reasons.discard('table_not_initialised')
            self.observed_through = event['observedThrough']
        elif kind == 'break_committed':
            self.entries[event['entryId']] = copy.deepcopy(event)
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
                boundary_uncertain = (('clockUncertaintyMs' in event and (event['clockUncertaintyMs'] is None or event['clockUncertaintyMs'] > 500))
                                      or bool(self._last_scoring_at and timestamp(self._last_scoring_at) > timestamp(event['inputStartedAt'])))
                payload['comparison'] = {'predictionId': event.get('predictionId'), 'predictedPoints': pred['points'] if pred else None,
                    'submittedPoints': event['submittedPoints'], 'agreement': pred['points'] == event['submittedPoints'] if available else None,
                    'labelStatus': 'correction_affected' if event.get('correctionAffected') else ('provisional' if event['source'] == 'manual' else 'ai_influenced'),
                    'boundaryUncertain': boundary_uncertain, 'reviewRequired': boundary_uncertain or (available and pred['points'] != event['submittedPoints'])}
            record = self._record('event', 'event:' + event['eventId'], payload)
            self.store.append(record)
            self._replay(record)
            return ack

    def confirm_baseline(self, observed_through):
        timestamp(observed_through)
        with self._lock:
            if self.mode == Mode.OFF or not self.rules:
                raise EventConflict('no observing frame')
            # Internal adapter command, never accepted as a public client event.
            event = {'eventId': str(uuid4()), 'sequence': self.sequence, 'type': 'baseline_confirmed', 'observedThrough': observed_through}
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
            reasons = sorted(self.reasons | self.rules.quality_reasons)
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
                        'lastAppliedEventSequence': self.sequence, 'activityVersion': self.activity_version, 'qualityReasons': sorted(self.reasons or {'no_prediction'})}
            payload = copy.deepcopy(matching[-1])
            reasons = self.reasons | (self.rules.quality_reasons if self.rules else set())
            if timestamp(payload['expiresAt']) <= self.clock():
                reasons = reasons | {'stale'}
            if payload['observedThrough'] != self.observed_through:
                reasons = reasons | {'new_activity'}
            if reasons:
                payload.update(status='unavailable', points=None, qualityReasons=sorted(reasons))
            return payload

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

    def apply_visual_result(self, result, context, epoch, frame, metadata, latency_ms, ttl_seconds):
        """Accept one ordered adapter result atomically against its capture generation."""
        with self._lock:
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
                if result.baseline_reds == 15 and self.rules.reds == 15 and self.rules.points == 0:
                    self.confirm_baseline(frame.timestamp)
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
            self.publish_prediction(metadata.get('modelVersion','unconfigured'),ttl_seconds,metadata,latency_ms)
            return True

    def visual_diagnostic(self, context, reason):
        with self._lock:
            self.store.append(self._record('visual_diagnostic','diagnostic:'+str(uuid4()),
                {'reason':reason,'frameId':context.frame_id,'runId':context.run_id}))
