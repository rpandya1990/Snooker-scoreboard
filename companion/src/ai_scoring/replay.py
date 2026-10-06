"""Synthetic domain demonstration only: never claims camera accuracy."""
import argparse
from datetime import timedelta
from pathlib import Path
from uuid import uuid4
from ai_scoring.dao.jsonl import JsonlSessionStore
from ai_scoring.domain.scoring import Ball, PotObservation
from ai_scoring.services.scoring import ScoringService, utc_now

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-directory',type=Path,required=True)
    args=parser.parse_args(argv)
    session_id='synthetic-'+str(uuid4())
    store=JsonlSessionStore(args.data_directory,session_id)
    now=utc_now()
    service=ScoringService(store,clock=lambda:now)
    try:
        service.apply_event({'eventId':'frame','sequence':1,'type':'frame_started','frameId':'frame','runId':'run'})
        service.confirm_baseline(now.isoformat())
        for index,ball in enumerate((Ball.RED,Ball.BLACK,Ball.RED,Ball.PINK)):
            now+=timedelta(seconds=1)
            service.observe(PotObservation(str(index),ball,now.isoformat()))
            if ball!=Ball.RED:
                service.observe(PotObservation('respot-'+str(index),ball,now.isoformat(),kind='respot'))
        prediction=service.publish_prediction(model_version='synthetic-fixture-only')
        service.apply_event({'eventId':'entry','sequence':2,'type':'break_committed','frameId':'frame','runId':'run','nextRunId':'next',
            'entryId':'entry','attemptId':'attempt','inputStartedAt':now.isoformat(),'committedAt':now.isoformat(),
            'predictionId':prediction['predictionId'],'submittedPoints':12,'appliedScoreDelta':12,'source':'manual'})
        print(f'Synthetic expected prediction: {prediction["points"]}; manual mismatch: 12. Not camera evidence.')
        print(store.path)
    finally:
        store.close()

if __name__=='__main__':
    main()
