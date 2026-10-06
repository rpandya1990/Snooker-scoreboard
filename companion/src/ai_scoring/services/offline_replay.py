"""Replay only pre-input footage through score-free adapters; never live APIs."""
import hashlib
import importlib
import json
import math
import subprocess
import os
import selectors
import time
import uuid
from datetime import timedelta
from pathlib import Path
from ai_scoring.domain.scoring import SnookerAccumulator
from ai_scoring.domain.visual_adapter import TimestampedFrame, BoundaryContext, VisualResult
from ai_scoring.services.datasets import DatasetError, confined, utc, write_json, file_sha256, read_bytes_nofollow


class FFmpegFrameSource:
    """Decode RGB24 frames with original PTS, stopping at the permitted cutoff."""
    def __init__(self, max_frames=10000, decode_timeout=60, clock=None, sample_fps=None):
        if type(max_frames) is not int or max_frames <= 0:
            raise DatasetError('positive frame budget required')
        if type(decode_timeout) not in (int, float) or decode_timeout <= 0:
            raise DatasetError('positive decode timeout required')
        self.max_frames = max_frames
        self.decode_timeout = decode_timeout
        self.clock = clock or time.monotonic
        if sample_fps is not None and (type(sample_fps) not in (int,float) or not math.isfinite(sample_fps) or not 0<sample_fps<=60):
            raise DatasetError('finite positive bounded sampling rate required')
        self.sample_fps = sample_fps
        self.sampling_metadata = {'method':'original_pts_cadence' if sample_fps else 'all_original_frames',
                                  'sampleFps':sample_fps,'maxFrames':max_frames,'activeDecodeBudgetSeconds':decode_timeout}

    def frames(self, path, segment, cutoff):
        anchor = utc(segment['captureStartUtc'])
        uncertainty = segment['utcUncertaintyMs']
        limit = (cutoff - anchor).total_seconds() - uncertainty / 1000
        if limit < 0:
            return
        try:
            output = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                '-read_intervals', f'%+#{self.max_frames + 16}', '-show_frames', '-show_streams',
                '-show_entries', 'stream=width,height,start_time:frame=best_effort_timestamp_time', '-of', 'json', str(path)],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True, timeout=60)
            probe = json.loads(output.stdout)
            stream = probe['streams'][0]
            width, height = int(stream['width']), int(stream['height'])
            start_pts = float(stream.get('start_time', 0))
            all_times = [float(frame['best_effort_timestamp_time']) for frame in probe['frames']]
            eligible = [(index,t) for index,t in enumerate(all_times) if 0 <= t - start_pts <= limit]
            if self.sample_fps is not None:
                sampled=[]
                for index,timestamp in eligible:
                    if not sampled or timestamp-sampled[-1][1]>=1/self.sample_fps-1e-9:
                        sampled.append((index,timestamp))
                eligible=sampled
            times=[timestamp for _,timestamp in eligible]
            if width <= 0 or height <= 0 or width * height > 16777216 or len(times) > self.max_frames:
                raise DatasetError('decode exceeds configured frame budget')
            if any(b <= a for a, b in zip(times, times[1:])):
                raise DatasetError('nonmonotonic video presentation timestamps')
            selection = '+'.join(f'eq(n\\,{index})' for index,_ in eligible) if self.sample_fps is not None else fr'lte(t\,{times[-1] + 0.000001 if times else start_pts})'
            command = ['ffmpeg', '-nostdin', '-v', 'error', '-copyts', '-i', str(path),
                '-vf', 'select='+selection, '-fps_mode', 'passthrough',
                '-frames:v', str(len(times)), '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1']
            if not times:
                return
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            deadline = self.clock() + self.decode_timeout
            try:
                size = width * height * 3
                for pts in times:
                    data = bytearray()
                    while len(data) < size:
                        remaining = deadline - self.clock()
                        if remaining <= 0 or not selector.select(remaining):
                            raise DatasetError('media decode deadline exceeded')
                        part = os.read(process.stdout.fileno(), size - len(data))
                        if not part:
                            raise DatasetError('incomplete decoded frame')
                        data.extend(part)
                    relative = pts - start_pts
                    upper = anchor + timedelta(seconds=relative, milliseconds=uncertainty)
                    if upper > cutoff:
                        raise DatasetError('frame exceeds pre-input cutoff')
                    suspended_at = self.clock()
                    yield TimestampedFrame(bytes(data), upper.isoformat(), segment['assetId'],
                                           segment['mediaStart'] + relative, uncertainty, width, height, 'rgb24')
                    # Inference runs in the consumer while this generator is
                    # suspended. Backpressure during that time is not a decoder
                    # stall and must not consume the active decoding budget.
                    deadline += self.clock() - suspended_at
                if process.wait(timeout=max(0.001, deadline - self.clock())) != 0:
                    raise DatasetError('media decoder failed')
            finally:
                if process.poll() is None:
                    process.kill(); process.wait()
                selector.close()
                process.stdout.close()
        except (OSError, subprocess.SubprocessError, KeyError, ValueError):
            raise DatasetError('media decoding/timeline inspection failed') from None


def load_adapter(specification, settings):
    """Explicit local operator plug-in; no model, network or deployment selected."""
    if not specification:
        return None
    module, separator, factory = specification.partition(':')
    if not separator or not module or not factory:
        raise DatasetError('adapter must use module:factory')
    return getattr(importlib.import_module(module), factory)(settings)


def adapter_metadata(adapter):
    if adapter is None:
        return {'adapterVersion': 'none', 'modelVersion': 'none', 'promptVersion': 'none',
                'sampling': {}, 'calibration': {}, 'runtime': {}, 'externalInference': False}
    metadata = json.loads(json.dumps(adapter.metadata, allow_nan=False))
    for key in ('adapterVersion', 'modelVersion', 'promptVersion', 'sampling', 'calibration', 'runtime'):
        value = metadata.get(key)
        if (key.endswith('Version') and (not isinstance(value, str) or not value.strip())) or (not key.endswith('Version') and not isinstance(value, dict)):
            raise DatasetError('adapter identity/settings incomplete')
    if metadata.get('externalInference') is not False:
        raise DatasetError('external inference not authorised')
    return metadata


class OfflineReplay:
    def __init__(self, store, frame_source=None):
        self.store = store
        self.frame_source = frame_source or FFmpegFrameSource()

    def run(self, dataset_id, adapter_factory=None):
        metadata = self.store.metadata(dataset_id)
        if not metadata['cohort']:
            raise DatasetError('assign cohort before replay or inspecting outcomes')
        records = self.store.records(dataset_id)
        mappings = self.store.mappings(dataset_id)
        asset_mapping, entry_mapping, frame_mapping = {}, {}, {}
        for record in mappings:
            asset_mapping.update({x['assetId']: x for x in record['payload'].get('assets', [])})
            entry_mapping.update({x['entryId']: x for x in record['payload'].get('entries', [])})
            frame_mapping.update({x['frameId']: x for x in record['payload'].get('frames', [])})
        segments = []
        for original in metadata['segments']:
            segment = {**original, **asset_mapping.get(original['assetId'], {})}
            segments.append(segment)
        events = [{**r['payload']['event'], '_receiptTimestamp': r['timestamp']} for r in records if r['type'] == 'event']
        for event in events:
            mapping = entry_mapping.get(event.get('entryId'), {})
            if mapping.get('committedAt'):
                event['committedAt'] = mapping['committedAt']
                event['clockUncertaintyMs'] = mapping['utcUncertaintyMs']
        entries = [event for event in events if event['type'] == 'break_committed']
        run_id = str(uuid.uuid4())
        results = []
        identities = []
        for entry in entries:
            adapter = adapter_factory() if adapter_factory else None
            identity = adapter_metadata(adapter)
            identities.append(identity)
            reasons = set(metadata['qualityReasons']) - {'timeline_alignment_unknown', 'capture_gap', 'timeline_overlap', 'asset_expired', 'unfinished_assets'}
            resolved_entry = entry_mapping.get(entry['entryId'], {})
            uncertainty = resolved_entry.get('utcUncertaintyMs', entry.get('clockUncertaintyMs'))
            if type(uncertainty) not in (int, float) or not math.isfinite(uncertainty) or uncertainty < 0:
                reasons.add('input_clock_alignment_unknown')
                uncertainty = 0
            cutoff = utc(resolved_entry.get('inputStartedAt', entry['inputStartedAt'])) - timedelta(milliseconds=uncertainty)
            relevant_segments = [segment for segment in segments if utc(segment['captureStartUtc']) <= cutoff]
            for record in records:
                if record['type'] == 'capture_gap' and utc(record['payload'].get('gapStartUtc', record['timestamp'])) <= cutoff:
                    reasons.add('capture_gap')
            for segment in relevant_segments:
                try:
                    path = confined(self.store.path(dataset_id),segment['relativePath'])
                    if file_sha256(path) != segment['sha256']:
                        reasons.add('asset_integrity_failure')
                except (DatasetError,OSError):
                    reasons.add('asset_missing')
                value = segment.get('utcUncertaintyMs')
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (
                        segment['assetId'] not in asset_mapping and segment.get('alignmentStatus') not in ('estimated', 'exact')):
                    reasons.add('timeline_alignment_unknown')
            _, structural_reasons = self._coverage(entry, cutoff, relevant_segments, events, frame_mapping)
            reasons.update(structural_reasons)
            evidence_reasons = reasons - {'adapter_not_configured'}
            if adapter is None:
                reasons.add('adapter_not_configured')
            points, watermark = None, None
            if not reasons:
                try:
                    points, watermark, adapter_reasons = self._predict(dataset_id, entry, cutoff, relevant_segments, events, adapter, frame_mapping)
                    reasons.update(adapter_reasons)
                except Exception:
                    reasons.add('adapter_or_media_failure')
            results.append({'entryId': entry['entryId'], 'replayPredictionId': str(uuid.uuid4()),
                'inputCutoff': cutoff.isoformat(), 'status': 'unavailable' if reasons else 'available',
                'points': None if reasons else points, 'qualityReasons': sorted(reasons),
                'evidenceQualityReasons': sorted(evidence_reasons),
                'evidenceAssetIds': [segment['assetId'] for segment in relevant_segments],
                'processedThrough': watermark, 'originalPredictionId': entry.get('predictionId'),
                'alignmentRecordIds': [r['id'] for r in mappings]})
        if identities and any(identity != identities[0] for identity in identities):
            raise DatasetError('adapter settings changed within replay run')
        parent = self.store.path(dataset_id) / 'replays'
        if parent.is_symlink():
            raise DatasetError('symlink replay directory not accepted')
        parent.mkdir(exist_ok=True, mode=0o700)
        folder = parent / run_id
        folder.mkdir(mode=0o700)
        result = {'replayRunId': run_id, 'datasetId': dataset_id, 'cohort': metadata['cohort'],
                  'adapter': identities[0] if identities else adapter_metadata(None),
                  'frameSourceSampling':getattr(self.frame_source,'sampling_metadata',{'method':'injected_source'}), 'results': results,
                  'originalLivePredictionsChanged': False, 'rolloutApproved': False}
        write_json(folder / 'replay.json', result)
        return result

    def _coverage(self, entry, cutoff, segments, events, frame_mapping):
        frame_starts = [event for event in events if event['type'] == 'frame_started' and event.get('frameId') == entry['frameId']]
        if not frame_starts:
            return None, {'frame_boundary_missing'}
        mapped = frame_mapping.get(entry['frameId'])
        boundary_uncertainty = mapped.get('utcUncertaintyMs') if mapped else frame_starts[-1].get('clockUncertaintyMs')
        if type(boundary_uncertainty) not in (int, float) or boundary_uncertainty < 0:
            return None, {'frame_clock_alignment_unknown'}
        frame_start = utc(mapped['frameStartedAt'] if mapped else frame_starts[-1].get('timestamp', frame_starts[-1]['_receiptTimestamp'])) - timedelta(milliseconds=boundary_uncertainty)
        intervals = sorted((utc(segment['captureStartUtc']), utc(segment['captureStartUtc']) + timedelta(seconds=segment['mediaDuration'])) for segment in segments)
        covered_until = frame_start
        for start, end in intervals:
            if covered_until >= cutoff:
                break
            if end <= covered_until:
                continue
            if start > covered_until:
                return None, {'recording_timeline_gap'}
            covered_until = max(covered_until, end)
        if covered_until < cutoff:
            return None, {'recording_tail_missing'}
        return frame_start, set()

    def _predict(self, dataset_id, entry, cutoff, segments, events, adapter, frame_mapping):
        frame_start, coverage_reasons = self._coverage(entry, cutoff, segments, events, frame_mapping)
        if coverage_reasons:
            return None, None, coverage_reasons
        frame_starts = [event for event in events if event['type'] == 'frame_started' and event.get('frameId') == entry['frameId']]
        max_gap = adapter.metadata.get('sampling', {}).get('maxFrameGapSeconds')
        if type(max_gap) not in (int, float) or not math.isfinite(max_gap) or max_gap <= 0:
            return None, None, {'sampling_continuity_not_configured'}
        previous = [event for event in events if event['type'] == 'break_committed' and event.get('frameId') == entry['frameId']
                    and utc(event['committedAt']) <= cutoff and event['entryId'] != entry['entryId']]
        if any(type(event.get('clockUncertaintyMs')) not in (int, float) or not math.isfinite(event['clockUncertaintyMs']) or event['clockUncertaintyMs'] < 0 for event in previous):
            return None, None, {'boundary_clock_alignment_unknown'}
        previous.sort(key=lambda event: utc(event['committedAt']))
        context = BoundaryContext(entry['frameId'], frame_starts[-1]['runId'], frame_start.isoformat(), frame_start.isoformat(), cutoff.isoformat())
        rules, seen, reasons = None, set(), set()
        watermark = None
        boundary_index = 0
        last_time = None
        last_observation = None
        previous_watermark = None
        for segment in sorted(segments, key=lambda s: utc(s['captureStartUtc'])):
            for frame in self.frame_source.frames(confined(self.store.path(dataset_id), segment['relativePath']), segment, cutoff):
                timestamp = utc(frame.timestamp)
                if timestamp > cutoff:
                    raise DatasetError('frame exceeds cutoff')
                if timestamp < frame_start:
                    continue
                if last_time is not None and timestamp <= last_time:
                    raise DatasetError('frame order or overlap invalid')
                if (timestamp - (last_time or frame_start)).total_seconds() > max_gap:
                    reasons.add('sampled_frame_gap')
                last_time = timestamp
                while boundary_index < len(previous):
                    boundary = previous[boundary_index]
                    centre = utc(boundary['committedAt'])
                    radius = timedelta(milliseconds=boundary['clockUncertaintyMs'])
                    frame_lower = timestamp - timedelta(milliseconds=2 * frame.utc_uncertainty_ms)
                    if (radius.total_seconds() > 0 or frame.utc_uncertainty_ms > 0) and frame_lower <= centre + radius and timestamp >= centre - radius:
                        reasons.add('boundary_time_ambiguous')
                    if frame_lower < centre + radius:
                        break
                    if rules: rules.new_visit()
                    context = BoundaryContext(entry['frameId'], boundary['nextRunId'], frame_start.isoformat(), boundary['committedAt'], cutoff.isoformat())
                    boundary_index += 1
                result = adapter.observe(frame, context)
                if not isinstance(result, VisualResult):
                    raise DatasetError('adapter returned incompatible visual result')
                if result.baseline_reds is not None:
                    if rules is not None:
                        raise DatasetError('adapter attempted repeated baseline')
                    rules = SnookerAccumulator(result.baseline_reds)
                reasons.update(result.quality_reasons)
                if result.processed_through is None or utc(result.processed_through) > timestamp:
                    reasons.add('invalid_processed_watermark')
                else:
                    if previous_watermark is not None and utc(result.processed_through) < previous_watermark:
                        reasons.add('nonmonotonic_processed_watermark')
                    previous_watermark = utc(result.processed_through)
                    watermark = result.processed_through
                for observation in result.observations:
                    if rules is None:
                        reasons.add('table_not_initialised'); continue
                    if utc(observation.timestamp) > timestamp or utc(observation.timestamp) > cutoff:
                        raise DatasetError('observation after available frame')
                    if utc(observation.timestamp) < utc(context.run_started_at):
                        reasons.add('late_cross_boundary_observation')
                        continue
                    if last_observation is not None and utc(observation.timestamp) < last_observation:
                        reasons.add('nonmonotonic_observation')
                        continue
                    last_observation = utc(observation.timestamp)
                    if observation.observation_id in seen: continue
                    seen.add(observation.observation_id)
                    if observation.kind == 'respot': rules.respot(observation.ball)
                    elif observation.kind == 'pot': rules.pot(observation.ball, observation.count)
                    else: reasons.add('unsupported_observation')
        if watermark is not None and (cutoff - utc(watermark)).total_seconds() > max_gap:
            reasons.add('processed_tail_missing')
        if rules is None or watermark is None:
            reasons.add('table_not_initialised')
        if boundary_index < len(previous):
            reasons.add('boundary_not_observed')
        if rules: reasons.update(rules.quality_reasons)
        return rules.points if rules else None, watermark, reasons

    def comparisons(self, dataset_id, replay_run_id):
        if not self.store.metadata(dataset_id)['cohort']:
            raise DatasetError('cohort required')
        if not replay_run_id or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in replay_run_id):
            raise DatasetError('invalid replay run ID')
        result = json.loads(read_bytes_nofollow(confined(self.store.path(dataset_id), f'replays/{replay_run_id}/replay.json')))
        originals = {r['payload']['predictionId']: r['payload'] for r in self.store.records(dataset_id) if r['type'] == 'prediction'}
        # This export runs only after inference and never feeds the adapter.
        return [{'entryId': row['entryId'], 'original': originals.get(row['originalPredictionId']),
                 'replay': row, 'replayRunId': replay_run_id, 'cohort': result['cohort']} for row in result['results']]

    def evaluate(self, dataset_id, replay_run_id):
        """Separate post-inference phase; independent reviews never reach adapters."""
        from ai_scoring.services.evaluation import evaluate
        comparisons = self.comparisons(dataset_id,replay_run_id)
        replay_predictions = {row['entryId']: row['replay'] for row in comparisons}
        source = self.store.records(dataset_id)
        evaluation_records = []
        for entry_id, prediction in replay_predictions.items():
            evaluation_records.append({'type':'prediction', 'payload':{
                'predictionId':prediction['replayPredictionId'],'status':prediction['status'],'points':prediction['points']}})
        for record in source:
            if record['type'] != 'event': continue
            copied = json.loads(json.dumps(record))
            event = copied['payload']['event']
            if event['type'] == 'break_committed':
                replay = replay_predictions.get(event['entryId'])
                event['predictionId'] = replay['replayPredictionId'] if replay else None
                copied['payload'].setdefault('comparison', {})
            evaluation_records.append(copied)
        metadata = self.store.metadata(dataset_id)
        scoped_evidence_issues = {}
        for record in self.store.reviews(dataset_id):
            copied = json.loads(json.dumps(record))
            copied['payload']['heldOut'] = metadata['cohort'] == 'held-out'
            entry_id = copied['payload']['entryId']
            prediction = replay_predictions.get(entry_id)
            issues = set(prediction.get('evidenceQualityReasons', [])) if prediction else {'missing_replay_entry'}
            cutoff = utc(prediction['inputCutoff']) if prediction else None
            for segment in metadata['segments']:
                if cutoff is not None and utc(segment['captureStartUtc']) > cutoff:
                    continue
                try:
                    path = confined(self.store.path(dataset_id),segment['relativePath'])
                    if file_sha256(path) != segment['sha256']: issues.add('asset_integrity_failure')
                except (DatasetError,OSError): issues.add('asset_missing')
            if issues:
                copied['payload']['evidenceSufficient'] = False
                scoped_evidence_issues[entry_id] = sorted(issues)
            evaluation_records.append(copied)
        metrics = evaluate(evaluation_records)
        return {'datasetId':dataset_id,'replayRunId':replay_run_id,'cohort':metadata['cohort'],
                'provenance':'offline_replay_independent_reviews','evidenceIssues':scoped_evidence_issues, 'collectionIssues':metadata['qualityReasons'],
                'metrics':metrics,'originalLiveMetricsChanged':False,'rolloutApproved':False}
