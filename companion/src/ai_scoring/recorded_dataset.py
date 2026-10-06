"""Operator-only local dataset tooling. Never calls scoreboard/session endpoints."""
import argparse
import json
from pathlib import Path
from ai_scoring.services.datasets import DatasetStore, DatasetError
from ai_scoring.services.offline_replay import OfflineReplay, FFmpegFrameSource, load_adapter


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path, help='isolated dataset directory, outside live sessions')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('init')
    imp = sub.add_parser('import'); imp.add_argument('source', type=Path)
    cohort = sub.add_parser('cohort'); cohort.add_argument('dataset'); cohort.add_argument('assignment', choices=('tuning','held-out'))
    align = sub.add_parser('align'); align.add_argument('dataset'); align.add_argument('mapping', type=Path)
    blind = sub.add_parser('blind-review'); blind.add_argument('dataset')
    review = sub.add_parser('review'); review.add_argument('dataset'); review.add_argument('review', type=Path)
    evaluate = sub.add_parser('evaluate'); evaluate.add_argument('dataset'); evaluate.add_argument('replay_run')
    export = sub.add_parser('export'); export.add_argument('dataset'); export.add_argument('--replay-run')
    replay = sub.add_parser('replay'); replay.add_argument('dataset'); replay.add_argument('--adapter', help='explicit trusted local module:factory')
    replay.add_argument('--sample-fps',type=float,help='Optional original-PTS frame sampling rate; may miss pots and requires declared adapter continuity limits')
    replay.add_argument('--settings', type=Path); replay.add_argument('--max-frames', type=int, default=10000)
    args = parser.parse_args(argv)
    try:
        store = DatasetStore(args.root)
        if args.command == 'init': result = {'datasetRoot':str(store.root), 'liveScoringConnected':False}
        elif args.command == 'import': result = {'datasetId':store.import_session(args.source)}
        elif args.command == 'cohort':
            store.assign_cohort(args.dataset,args.assignment); result = store.metadata(args.dataset)
        elif args.command == 'align':
            result = {'alignmentId':store.align(args.dataset,json.loads(args.mapping.read_text()))}
        elif args.command == 'blind-review': result = store.blind_entries(args.dataset)
        elif args.command == 'review': result = {'reviewId':store.review(args.dataset,json.loads(args.review.read_text()))}
        elif args.command == 'evaluate': result = OfflineReplay(store).evaluate(args.dataset,args.replay_run)
        elif args.command == 'export':
            result = OfflineReplay(store).comparisons(args.dataset,args.replay_run) if args.replay_run else store.metadata(args.dataset)
        else:
            settings = json.loads(args.settings.read_text()) if args.settings else {}
            factory = (lambda: load_adapter(args.adapter,settings)) if args.adapter else None
            result = OfflineReplay(store,FFmpegFrameSource(args.max_frames,sample_fps=args.sample_fps)).run(args.dataset,factory)
        print(json.dumps(result,sort_keys=True,allow_nan=False))
        return 0
    except (DatasetError, OSError, ValueError, ImportError, AttributeError, KeyError, TypeError):
        # Avoid leaking source paths/secrets from operator plug-in/subprocess errors.
        parser.exit(2, 'dataset operation failed; check integrity, cohort, mapping and adapter configuration\n')


if __name__ == '__main__':
    raise SystemExit(main())
