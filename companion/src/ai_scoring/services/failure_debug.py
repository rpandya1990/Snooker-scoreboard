"""Read-only debugging against provisional submissions, independent of accuracy."""
import math
import re
from ai_scoring.dao.read_helpers import utc, confined, ReadError

ID=re.compile(r'[A-Za-z0-9_.:-]{1,160}\Z')
REASON=re.compile(r'[a-z][a-z0-9_]{0,100}\Z')

def safe_id(value):
    return value if isinstance(value,str) and ID.fullmatch(value) else None

def safe_reason(value):
    return value if isinstance(value,str) and REASON.fullmatch(value) else 'redacted_reason'

def number(value):
    return value if type(value) in (int,float) and math.isfinite(value) else None

def safe_time(value):
    try:
        return utc(value).isoformat()
    except ReadError:
        return None

class FailureReport:
    def __init__(self,records,session_directory):
        self.records=records
        self.session_directory=session_directory
        if session_directory.is_symlink() or session_directory.parent.is_symlink():
            raise ReadError("unsafe session snapshot directory")

    def entries(self,entry_id=None):
        predictions={r['payload'].get('predictionId'):r['payload'] for r in self.records if r.get('type')=='prediction' and isinstance(r['payload'].get('predictionId'),str)}
        starts={}
        entries=[]
        revisions=[]
        for record in self.records:
            if record.get('type')!='event':
                continue
            payload=record['payload']
            event=payload.get('event',{})
            if event.get('type')=='frame_started':
                starts[event.get('runId')]=safe_time(record.get('timestamp'))
            elif event.get('type')=='break_committed':
                entries.append((record,event,payload.get('comparison',{}),starts.get(event.get('runId'))))
                starts[event.get('nextRunId')]=safe_time(event.get('committedAt'))
            elif event.get('type') in ('correction','undo'):
                targets=event.get('affectedEntryIds') or ([event['entryId']] if event.get('entryId') else [item[1].get('entryId') for item in entries])
                revisions.append((record,event,targets))
        reports=[]
        for record,event,comparison,run_start in entries:
            if entry_id is not None and event.get('entryId')!=entry_id:
                continue
            predicted=predictions.get(event.get('predictionId'))
            expected=event.get('submittedPoints') if type(event.get('submittedPoints')) is int else None
            points=predicted.get('points') if predicted and type(predicted.get('points')) is int else None
            source=event.get('source') if event.get('source') in ('manual','ai_selected','ai_selected_edited') else 'unknown'
            reasons=[]
            frozen_availability=event.get('predictionAvailability')
            available=bool(predicted and predicted.get('status')=='available' and points is not None and frozen_availability in (None,'available'))
            if not predicted:
                classification='missing_prediction'
                reasons.append(safe_reason(frozen_availability) if frozen_availability not in (None,'available') else 'missing_prediction')
            elif not available:
                classification='unavailable_prediction'
                reasons.extend(safe_reason(value) for value in predicted.get('qualityReasons',[]) if isinstance(value,str))
                if frozen_availability not in (None,'available'):
                    reasons.append(safe_reason(frozen_availability))
                if not reasons:
                    reasons.append('prediction_unavailable')
            else:
                classification='match' if expected==points else 'mismatch'
            if entry_id is None and classification=='match':
                continue
            correction_affected=bool(event.get('correctionAffected') or comparison.get('labelStatus')=='correction_affected')
            undo=False
            revision_info=[]
            for revision,change,targets in revisions:
                if event.get('entryId') in targets:
                    undo |= change.get('type')=='undo'
                    correction_affected |= change.get('type')=='correction'
                    revision_info.append({'type':change['type'],'eventId':safe_id(change.get('eventId')),'timestamp':safe_time(revision.get('timestamp'))})
            start=safe_time(event.get('inputStartedAt'))
            commit=safe_time(event.get('committedAt'))
            timing={'runStartedAt':run_start,'inputStartedAt':start,'committedAt':commit,
                'clockUncertaintyMs':number(event.get('clockUncertaintyMs'))}
            report={'entryId':safe_id(event.get('entryId')),'eventId':safe_id(event.get('eventId')),
                'frameId':safe_id(event.get('frameId')),'runId':safe_id(event.get('runId')),'predictionId':safe_id(event.get('predictionId')),
                'classification':classification,'source':source,'aiInfluenced':source in ('ai_selected','ai_selected_edited'),
                'expectedPoints':expected,'expectedBasis':'submitted_points_provisional_debug_label','submittedPoints':expected,
                'predictedPoints':points,'errorPoints':points-expected if available and expected is not None else None,
                'predictionReasons':sorted(set(reasons)),'corrected':correction_affected,'undone':undo,
                'boundaryUncertain':bool(comparison.get('boundaryUncertain')),'revisions':revision_info,'timing':timing,
                'diagnostics':self._diagnostics(event,run_start,commit),
                'segments':self._segments(timing,comparison)}
            reports.append(report)
        return reports

    def _diagnostics(self,event,start,end):
        result=[]
        kinds={'capture_gap','discontinuity','visual_diagnostic','visual_quality','recording_stopped'}
        for record in self.records:
            if record.get('type') not in kinds:
                continue
            payload=record['payload']
            if payload.get('runId') is not None:
                relevant=payload['runId']==event.get('runId')
            elif payload.get('frameId') is not None:
                relevant=payload['frameId']==event.get('frameId')
            else:
                when=safe_time(record.get('timestamp'))
                relevant=not(start and end and when) or utc(start)<=utc(when)<=utc(end)
            if relevant:
                result.append({'type':record['type'],'reason':safe_reason(payload.get('reason')),
                    'timestamp':safe_time(record.get('timestamp')),'frameId':safe_id(payload.get('frameId')),'runId':safe_id(payload.get('runId'))})
        return result

    def _segments(self,timing,comparison):
        result=[]
        expired={r['payload'].get('assetId') for r in self.records if r.get('type')=='asset_expired'}
        closed_ids={r['payload'].get('assetId') for r in self.records if r.get('type')=='segment_closed'}
        for record in self.records:
            if record.get('type') not in ('segment_closed','segment_opened'):
                continue
            segment=record['payload']
            if record['type']=='segment_opened' and segment.get('assetId') in closed_ids:
                continue
            relative=segment.get('relativePath')
            path=None
            status='missing'
            if isinstance(relative,str):
                try:
                    path=confined(self.session_directory,relative,require=False)
                    # Only session-owned video paths are relevant, never arbitrary log/config files.
                    if not re.fullmatch(r'video/[A-Za-z0-9_.-]+',relative):
                        raise ReadError('invalid video reference')
                    status='expired' if segment.get('assetId') in expired else ('unfinished' if record['type']=='segment_opened' else ('available' if path.is_file() else 'missing'))
                except (ReadError,OSError):
                    path=None
                    status='unsafe_path'
            anchor=safe_time(segment.get('captureStartUtc'))
            uncertainty=number(segment.get('utcUncertaintyMs'))
            duration=number(segment.get('mediaDuration'))
            media_start=number(segment.get('mediaStart'))
            entry_uncertainty=timing['clockUncertaintyMs']
            justified=bool(anchor and uncertainty is not None and uncertainty>=0 and duration is not None and duration>=0
                and media_start is not None and media_start>=0 and segment.get('alignmentStatus') in ('estimated','measured','aligned')
                and entry_uncertainty is not None and entry_uncertainty>=0 and timing['runStartedAt'] and timing['committedAt']
                and not comparison.get('boundaryUncertain'))
            offsets=None
            if justified:
                lower=(utc(timing['runStartedAt'])-utc(anchor)).total_seconds()-(uncertainty+entry_uncertainty)/1000
                upper=(utc(timing['committedAt'])-utc(anchor)).total_seconds()+(uncertainty+entry_uncertainty)/1000
                if upper<0 or lower>duration:
                    continue
                if upper>=lower:
                    offsets={'fileStart':max(0,lower),'fileEnd':min(duration,upper),
                        'sessionMediaStart':media_start+max(0,lower),'sessionMediaEnd':media_start+min(duration,upper)}
            # Unknown alignment cannot justify excluding even apparently distant assets.
            result.append({'assetId':safe_id(segment.get('assetId')),'relativePath':relative if path is not None else None,
                'localPath':str(path) if path is not None else None,'assetStatus':status,
                'alignment':'estimated_candidate' if justified else 'unknown_candidate_not_exact',
                'mediaOffsetsSeconds':offsets,'captureStartUtc':anchor,'utcUncertaintyMs':uncertainty})
        return result
