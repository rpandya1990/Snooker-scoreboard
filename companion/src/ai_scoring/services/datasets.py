"""Immutable local recordings. Dataset files are never live session writers."""
import fcntl
import hashlib
import json
import math
import os
import shutil
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path, PurePosixPath


class DatasetError(ValueError):
    pass


def utc(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed
    except (AttributeError, TypeError, ValueError):
        raise DatasetError('invalid or timezone-free timestamp') from None


def confined(root, relative, *, require=True):
    """Reject symlinks too: resolving then checking containment alone is insufficient."""
    path = PurePosixPath(relative)
    if not relative or path.is_absolute() or '..' in path.parts or '\\' in relative:
        raise DatasetError('invalid relative asset path')
    candidate = Path(root)
    for part in path.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise DatasetError('symlink assets are not accepted')
    if require and not candidate.is_file():
        raise DatasetError('asset missing or unfinished')
    return candidate


def read_bytes_nofollow(path):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        return stream.read()


def file_sha256(path):
    digest = hashlib.sha256()
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read_records(path):
    data = read_bytes_nofollow(path)
    if data and not data.endswith(b'\n'):
        raise DatasetError('unfinished JSONL record')
    records, ids = [], set()
    try:
        for line in data.splitlines():
            record = json.loads(line)
            if not isinstance(record, dict) or not isinstance(record.get('payload'), dict):
                raise ValueError()
            if not isinstance(record.get('id'), str) or record['id'] in ids:
                raise ValueError()
            ids.add(record['id'])
            utc(record['timestamp'])
            records.append(record)
    except (ValueError, KeyError, UnicodeError):
        raise DatasetError('invalid JSONL record') from None
    return records


def private_open(path, mode):
    flags = os.O_NOFOLLOW | os.O_CREAT
    flags |= os.O_EXCL if 'x' in mode else (os.O_APPEND if 'a' in mode else os.O_TRUNC)
    flags |= os.O_RDWR if '+' in mode else os.O_WRONLY
    descriptor = os.open(path, flags, 0o600)
    return os.fdopen(descriptor, mode)


def write_json(path, data):
    with private_open(path, 'x') as stream:
        json.dump(data, stream, sort_keys=True, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


class DatasetStore:
    """Source/checksum identities lock cohorts across imports and segment reuse."""
    def __init__(self, root):
        self.root = Path(root).absolute()
        if any(parent.is_symlink() for parent in (self.root, *self.root.parents)):
            raise DatasetError('symlink dataset root is not accepted')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.registry = self.root / 'registry.jsonl'

    @contextmanager
    def _locked(self):
        with private_open(self.registry, 'a+') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            stream.seek(0)
            try:
                lines = stream.readlines()
                if any(not line.endswith('\n') for line in lines):
                    raise ValueError()
                records = [json.loads(line) for line in lines]
            except ValueError:
                raise DatasetError('dataset registry storage fault') from None
            yield stream, records

    def _append(self, stream, record):
        stream.seek(0, os.SEEK_END)
        stream.write(json.dumps(record, sort_keys=True, allow_nan=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())

    def path(self, dataset_id):
        if not dataset_id or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in dataset_id):
            raise DatasetError('invalid dataset ID')
        folder = self.root / dataset_id
        if folder.is_symlink() or not folder.is_dir():
            raise DatasetError('dataset missing')
        return folder

    def import_session(self, source):
        source = Path(source).absolute()
        if any(parent.is_symlink() for parent in (source, *source.parents)):
            raise DatasetError('symlink source directories are not accepted')
        log = confined(source, 'session.jsonl')
        with os.fdopen(os.open(log, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                raise DatasetError('source session still has an active writer') from None
            return self._import_snapshot(source, stream.read())

    def _import_snapshot(self, source, snapshot):
        source = Path(source)
        if source.is_symlink() or not source.is_dir():
            raise DatasetError('invalid source directory')
        log = confined(source, 'session.jsonl')
        records = read_records(log)
        sessions = {r['payload']['sessionId'] for r in records if r['type'] == 'session_opened'}
        if len(sessions) != 1:
            raise DatasetError('one original session identity required')
        reasons, segments, tokens = [], [], {'session:' + next(iter(sessions))}
        expired = {r['payload'].get('assetId') for r in records if r['type'] == 'asset_expired'}
        opened = {r['payload'].get('assetId') for r in records if r['type'] == 'segment_opened'}
        closed = set()
        paths = set()
        for record in records:
            if record['type'] == 'recording_started' and record['payload'].get('captureId'):
                tokens.add('capture:' + str(record['payload']['captureId']))
            if record['type'] == 'capture_gap':
                reasons.append('capture_gap')
            if record['type'] != 'segment_closed':
                continue
            segment = dict(record['payload'])
            closed.add(segment.get('assetId'))
            relative = segment.get('relativePath', '')
            if PurePosixPath(relative).parts and PurePosixPath(relative).parts[0] in ('session.jsonl','dataset.json','alignment.jsonl','reviews.jsonl','replays'):
                raise DatasetError('asset path conflicts with dataset metadata')
            if relative in paths:
                raise DatasetError('duplicate asset path')
            paths.add(relative)
            asset = confined(source, relative)
            digest = file_sha256(asset)
            if digest != segment.get('sha256'):
                raise DatasetError('asset checksum missing or mismatched')
            if segment.get('sizeBytes') != asset.stat().st_size:
                raise DatasetError('asset size mismatch')
            for key in ('mediaStart', 'mediaDuration'):
                value = segment.get(key)
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (key == 'mediaDuration' and value == 0):
                    raise DatasetError('invalid media timeline')
            utc(segment.get('captureStartUtc'))
            uncertainty = segment.get('utcUncertaintyMs')
            if segment.get('alignmentStatus') not in ('estimated', 'exact') or type(uncertainty) not in (int, float) or not math.isfinite(uncertainty) or uncertainty < 0:
                reasons.append('timeline_alignment_unknown')
            if segment.get('assetId') in expired:
                reasons.append('asset_expired')
            tokens.add('asset:' + digest)
            segments.append(segment)
        if not segments:
            reasons.append('no_recording_assets')
        if opened - closed:
            reasons.append('unfinished_assets')
        # Check overlapping media intervals within one observation epoch.
        by_epoch = {}
        for segment in segments:
            epoch = segment.get('observationEpoch', 'unknown')
            prior = by_epoch.setdefault(epoch, [])
            start, end = segment['mediaStart'], segment['mediaStart'] + segment['mediaDuration']
            if any(start < b and a < end for a, b in prior):
                reasons.append('timeline_overlap')
            prior.append((start, end))
        for record in records:
            if record['type'] == 'event' and record['payload'].get('event', {}).get('type') == 'break_committed':
                event = record['payload']['event']
                if utc(event['committedAt']) < utc(event['inputStartedAt']):
                    raise DatasetError('invalid entry timeline')
        dataset_id = str(uuid.uuid4())
        folder = self.root / dataset_id
        folder.mkdir(mode=0o700)
        try:
            with private_open(folder / 'session.jsonl', 'xb') as target_log:
                target_log.write(snapshot)
                target_log.flush(); os.fsync(target_log.fileno())
            for segment in segments:
                target = confined(folder, segment['relativePath'], require=False)
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with os.fdopen(os.open(confined(source, segment['relativePath']), os.O_RDONLY | os.O_NOFOLLOW), 'rb') as source_asset, private_open(target, 'xb') as target_asset:
                    shutil.copyfileobj(source_asset, target_asset, length=1024 * 1024)
                    target_asset.flush(); os.fsync(target_asset.fileno())
                if file_sha256(target) != segment['sha256']:
                    raise DatasetError('asset changed during import')
            metadata = {'datasetId': dataset_id, 'sourceSessionId': next(iter(sessions)),
                        'sourceLogSha256': hashlib.sha256(snapshot).hexdigest(),
                        'identityTokens': sorted(tokens), 'segments': segments,
                        'evidenceComplete': not reasons, 'qualityReasons': sorted(set(reasons)),
                        'containsReviews': any(r['type'] == 'review' for r in records)}
            write_json(folder / 'dataset.json', metadata)
            with self._locked() as (stream, _):
                self._append(stream, {'type':'import', 'datasetId':dataset_id, 'identityTokens':sorted(tokens)})
        except Exception:
            shutil.rmtree(folder)
            raise
        return dataset_id

    def metadata(self, dataset_id):
        data = json.loads(read_bytes_nofollow(confined(self.path(dataset_id), 'dataset.json')))
        with self._locked() as (_, records):
            assignments = [r for r in records if r['type'] == 'cohort' and r['datasetId'] == dataset_id]
        data['cohort'] = assignments[-1]['cohort'] if assignments else None
        return data

    def assign_cohort(self, dataset_id, cohort):
        if cohort not in ('tuning', 'held-out'):
            raise DatasetError('cohort must be tuning or held-out')
        metadata = self.metadata(dataset_id)
        if metadata['containsReviews'] and metadata['cohort'] is None:
            raise DatasetError('cohort must precede reviews')
        with self._locked() as (stream, records):
            tokens = set(metadata['identityTokens'])
            # Transitive overlaps keep a segment subset linked to the entire source.
            changed = True
            while changed:
                before = len(tokens)
                for record in records:
                    other = set(record.get('identityTokens', []))
                    if tokens & other:
                        tokens |= other
                changed = len(tokens) != before
            for record in records:
                if record['type'] == 'cohort' and tokens & set(record['identityTokens']):
                    if record['cohort'] != cohort:
                        raise DatasetError('related capture already assigned to other cohort')
            if any(r['type'] == 'cohort' and r['datasetId'] == dataset_id for r in records):
                return
            self._append(stream, {'type':'cohort', 'datasetId':dataset_id, 'cohort':cohort, 'identityTokens':sorted(tokens),
                                  'assignedAt': datetime.now().astimezone().isoformat()})

    def records(self, dataset_id):
        metadata = self.metadata(dataset_id)
        log = confined(self.path(dataset_id), 'session.jsonl')
        if file_sha256(log) != metadata['sourceLogSha256']:
            raise DatasetError('archived source integrity failed')
        return read_records(log)

    def align(self, dataset_id, mapping):
        """Append an explicit versioned operator mapping; never replace source times."""
        metadata = self.metadata(dataset_id)
        if not metadata['cohort']:
            raise DatasetError('assign cohort before alignment/replay/review')
        if not mapping.get('version') or not mapping.get('reviewer'):
            raise DatasetError('alignment version and reviewer required')
        assets = {segment['assetId'] for segment in metadata['segments']}
        entries = {r['payload']['event']['entryId'] for r in self.records(dataset_id)
                   if r['type'] == 'event' and r['payload'].get('event', {}).get('type') == 'break_committed'}
        frames = {r['payload']['event']['frameId'] for r in self.records(dataset_id)
                  if r['type'] == 'event' and r['payload'].get('event', {}).get('type') == 'frame_started'}
        for item in mapping.get('frames', []):
            if item.get('frameId') not in frames:
                raise DatasetError('unknown alignment frame')
            utc(item.get('frameStartedAt'))
            self._uncertainty(item.get('utcUncertaintyMs'))
        for item in mapping.get('assets', []):
            if item.get('assetId') not in assets:
                raise DatasetError('unknown alignment asset')
            utc(item.get('captureStartUtc'))
            self._uncertainty(item.get('utcUncertaintyMs'))
        for item in mapping.get('entries', []):
            if item.get('entryId') not in entries:
                raise DatasetError('unknown alignment entry')
            utc(item.get('inputStartedAt'))
            if item.get('committedAt'):
                if utc(item['committedAt']) < utc(item['inputStartedAt']):
                    raise DatasetError('invalid mapped entry timeline')
            self._uncertainty(item.get('utcUncertaintyMs'))
        if not mapping.get('assets') and not mapping.get('entries') and not mapping.get('frames'):
            raise DatasetError('empty alignment mapping')
        record = {'type': 'alignment', 'id': str(uuid.uuid4()), 'timestamp': datetime.now().astimezone().isoformat(), 'payload': mapping}
        path = self.path(dataset_id) / 'alignment.jsonl'
        with private_open(path, 'a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            stream.write(json.dumps(record, sort_keys=True, allow_nan=False) + '\n')
            stream.flush(); os.fsync(stream.fileno())
        return record['id']

    @staticmethod
    def _uncertainty(value):
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise DatasetError('explicit nonnegative clock uncertainty required')

    def mappings(self, dataset_id):
        path = self.path(dataset_id) / 'alignment.jsonl'
        return read_records(confined(self.path(dataset_id), path.name)) if path.exists() else []

    def blind_entries(self, dataset_id):
        metadata = self.metadata(dataset_id)
        if not metadata['cohort']:
            raise DatasetError('assign cohort before review')
        result = []
        for record in self.records(dataset_id):
            if record['type'] != 'event' or record['payload'].get('event', {}).get('type') != 'break_committed':
                continue
            event = record['payload']['event']
            result.append({'entryId': event['entryId'], 'frameId': event['frameId'], 'runId': event['runId'],
                           'inputStartedAt': event['inputStartedAt'], 'committedAt': event['committedAt'],
                           'assets': [{k: s.get(k) for k in ('assetId','relativePath','captureStartUtc','mediaDuration','utcUncertaintyMs','alignmentStatus')}
                                      for s in metadata['segments']],
                           'qualityReasons': metadata['qualityReasons']})
        return result

    def review(self, dataset_id, review):
        metadata = self.metadata(dataset_id)
        if not metadata['cohort']:
            raise DatasetError('assign cohort before review')
        entries = {row['entryId'] for row in self.blind_entries(dataset_id)}
        if review.get('entryId') not in entries or not review.get('reviewer') or review.get('independent') is not True:
            raise DatasetError('known entry and independent reviewer required')
        if review.get('eligible') is True:
            if type(review.get('actualPoints')) is not int or review['actualPoints'] < 0 or review.get('evidenceSufficient') is not True:
                raise DatasetError('eligible review requires independent points and sufficient evidence')
        elif not review.get('exclusionReason'):
            raise DatasetError('excluded review requires a reason')
        if 'heldOut' in review:
            raise DatasetError('cohort is persisted, not a reviewer choice')
        record = {'id': str(uuid.uuid4()), 'type':'review', 'timestamp':datetime.now().astimezone().isoformat(), 'payload':dict(review)}
        path = self.path(dataset_id) / 'reviews.jsonl'
        with private_open(path, 'a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            stream.write(json.dumps(record,sort_keys=True,allow_nan=False) + '\n')
            stream.flush(); os.fsync(stream.fileno())
        return record['id']

    def reviews(self, dataset_id):
        path = self.path(dataset_id) / 'reviews.jsonl'
        return read_records(confined(self.path(dataset_id), path.name)) if path.exists() else []
