"""Inspect/export local JSONL and append explicit independent reviews."""
import argparse
import json
from pathlib import Path
from uuid import uuid4
from ai_scoring.dao.jsonl import JsonlSessionStore
from ai_scoring.services.evaluation import evaluate
from ai_scoring.services.scoring import utc_now

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-directory',type=Path,required=True)
    parser.add_argument('--session-id',required=True)
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('evaluate')
    commands.add_parser('export')
    review=commands.add_parser('review')
    review.add_argument('--entry-id',required=True)
    review.add_argument('--reviewer',required=True)
    review.add_argument('--actual-points',type=int)
    review.add_argument('--exclusion-reason')
    review.add_argument('--resolves-revision',action='store_true')
    review.add_argument('--evidence-reviewed',action='store_true',help='Attest sufficient independent evidence was inspected')
    review.add_argument('--evidence-reference',help='Local evidence path or record reference; never a credential URL')
    review.add_argument('--held-out',action='store_true',help='Only for a cohort designated before reviewing outcomes')
    args=parser.parse_args(argv)
    store=JsonlSessionStore(args.data_directory,args.session_id)
    try:
        if args.command=='review':
            if args.actual_points is None and not args.exclusion_reason:
                parser.error('provide independently established --actual-points or --exclusion-reason')
            if args.actual_points is not None and args.actual_points < 0:
                parser.error('actual points must be nonnegative')
            known={r['payload']['event']['entryId'] for r in store.records if r['type']=='event' and r['payload']['event']['type']=='break_committed'}
            if args.entry_id not in known:
                parser.error('unknown entry ID')
            store.append({'id':'review:'+str(uuid4()),'type':'review','timestamp':utc_now().isoformat(),
                'payload':{'entryId':args.entry_id,'reviewer':args.reviewer,'independent':True,
                           'eligible':args.exclusion_reason is None,'actualPoints':args.actual_points,
                           'exclusionReason':args.exclusion_reason,'resolvesRevision':args.resolves_revision,
                           'evidenceSufficient':args.evidence_reviewed,'evidenceReference':args.evidence_reference,'heldOut':args.held_out}})
        elif args.command=='evaluate':
            print(json.dumps(evaluate(store.records),indent=2))
        else:
            print(json.dumps(store.records,indent=2))
    finally:
        store.close()

if __name__=='__main__':
    main()
