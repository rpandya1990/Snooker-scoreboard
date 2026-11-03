"""Build the ball-detection training dataset from finished recorded sessions."""
import argparse
import json
from pathlib import Path
from ai_scoring.services.dataset_builder import build_pending

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-directory',type=Path,required=True)
    parser.add_argument('--calibration-file',type=Path,required=True)
    parser.add_argument('--every-seconds',type=float,default=2.0,help='Sample one frame per this many seconds of video')
    args=parser.parse_args(argv)
    total=build_pending(args.data_directory,json.loads(args.calibration_file.read_text()),args.every_seconds)
    print(f'dataset: {total} new frames in {args.data_directory/"dataset"}')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
