"""Read-only scoring failure inspection; submitted points are debugging labels."""
import argparse
import json
from pathlib import Path
import sys
from ai_scoring.dao.session_snapshot import read_session_snapshot,SnapshotError
from ai_scoring.services.failure_debug import FailureReport

class DebugError(ValueError):
    pass

def load_report(data_directory,session_id,entry_id=None):
    try:
        records,folder=read_session_snapshot(data_directory,session_id)
        entries=FailureReport(records,folder).entries(entry_id)
        if entry_id is not None and not entries:
            raise DebugError('entry not found')
        return {'sessionId':session_id,'labelNotice':'Submitted points are provisional debugging expectations; AI-selected entries are influenced. This is not accuracy evaluation.',
            'entryCount':len(entries),'entries':entries}
    except SnapshotError as error:
        raise DebugError(str(error)) from None
    except (OSError,ValueError,TypeError,KeyError,AttributeError):
        raise DebugError('session snapshot unavailable or malformed; no files were changed') from None

def render_text(report):
    lines=[f"Session {report['sessionId']}: {report['entryCount']} failure/selected entries",report['labelNotice']]
    for entry in report['entries']:
        lines += ['',f"{entry['entryId']} — {entry['classification']}: expected/submitted {entry['expectedPoints']}, prediction {entry['predictedPoints']}, error {entry['errorPoints']}",
            f"  source={entry['source']} AI-influenced={entry['aiInfluenced']} corrected={entry['corrected']} undone={entry['undone']}",
            f"  frame={entry['frameId']} run={entry['runId']} prediction={entry['predictionId']}",
            f"  run start={entry['timing']['runStartedAt']} input={entry['timing']['inputStartedAt']} commit={entry['timing']['committedAt']}",
            f"  reasons={','.join(entry['predictionReasons']) or 'none'} boundary-uncertain={entry['boundaryUncertain']}"]
        for diagnostic in entry['diagnostics']:
            lines.append(f"  diagnostic {diagnostic['type']}: {diagnostic['reason']} at {diagnostic['timestamp']}")
        for segment in entry['segments']:
            lines.append(f"  video {segment['assetStatus']} {segment['localPath'] or '(unsafe/unavailable path)'}; {segment['alignment']}; offsets={segment['mediaOffsetsSeconds']}")
    return '\n'.join(lines)

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-directory',type=Path,required=True)
    parser.add_argument('--session-id',required=True)
    parser.add_argument('--entry-id')
    parser.add_argument('--json',action='store_true')
    args=parser.parse_args(argv)
    try:
        report=load_report(args.data_directory,args.session_id,args.entry_id)
    except DebugError as error:
        print(f'Inspection unavailable: {error}',file=sys.stderr)
        return 1
    print(json.dumps(report,indent=2,allow_nan=False) if args.json else render_text(report))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
