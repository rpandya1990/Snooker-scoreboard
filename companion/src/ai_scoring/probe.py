"""Opt-in, read-only ffprobe diagnostic. Does not record or start AI scoring."""
import argparse
import json
import os
from ai_scoring.clients.probe import MediaProbe
from ai_scoring.config import Mode

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=list(Mode),default='off')
    parser.add_argument('--recorded-file',help='Probe an existing local file instead of the configured camera')
    parser.add_argument('--timeout-seconds',type=float,default=10)
    args=parser.parse_args(argv)
    try:
        probe=MediaProbe(timeout_seconds=args.timeout_seconds)
    except ValueError:
        parser.error('timeout must be positive and finite')
    source=args.recorded_file if args.recorded_file is not None else os.environ.get('AI_SCORING_CAMERA_URL')
    result=probe.inspect(source,mode=args.mode,recorded_file=args.recorded_file is not None)
    print(json.dumps(result.to_dict(),sort_keys=True))
    return 0 if result.status in ('available','disabled') else 1

if __name__=='__main__':
    raise SystemExit(main())
