"""Independent review labels drive metrics; accepted AI never supplies truth."""
import math

def evaluate(records):
    predictions, entries, reviews = {}, {}, {}
    invalidated = {}
    review_positions = {}
    for position, record in enumerate(records):
        payload=record['payload']
        if record['type']=='prediction':
            predictions[payload['predictionId']]=payload
        elif record['type']=='event':
            event=payload['event']
            if event['type']=='break_committed':
                entries[event['entryId']]=payload
                if event.get('correctionAffected') or payload['comparison'].get('labelStatus') == 'correction_affected':
                    invalidated[event['entryId']]=position
            elif event['type'] in ('undo','correction'):
                targets=event.get('affectedEntryIds') or ([event['entryId']] if event.get('entryId') else list(entries))
                for target in targets:
                    invalidated[target]=position
        elif record['type']=='review':
            reviews[payload['entryId']]=payload
            review_positions[payload['entryId']]=position
    eligible=correct=available=0
    heldout_eligible=heldout_correct=0
    errors=[]
    exclusions={}
    boundary=0
    for entry_id,payload in entries.items():
        review=reviews.get(entry_id)
        if payload['comparison'].get('boundaryUncertain'):
            boundary += 1
        if not review or not review.get('independent'):
            reason='not_independently_reviewed'
        elif not review.get('evidenceSufficient'):
            reason='insufficient_review_evidence'
        elif not review.get('eligible'):
            reason=review.get('exclusionReason','unsupported')
        elif entry_id in invalidated and (not review.get('resolvesRevision') or review_positions[entry_id] <= invalidated[entry_id]):
            reason='unresolved_revision'
        else:
            reason=None
        if reason:
            exclusions[reason]=exclusions.get(reason,0)+1
            continue
        if type(review.get('actualPoints')) is not int or review['actualPoints'] < 0:
            raise ValueError('eligible review requires actualPoints')
        eligible += 1
        if review.get("heldOut"):
            heldout_eligible += 1
        event=payload['event']
        prediction=predictions.get(event.get('predictionId'))
        if prediction and prediction['status']=='available':
            available += 1
            error=prediction['points']-review['actualPoints']
            errors.append(error)
            correct += error == 0
            if review.get("heldOut"):
                heldout_correct += error == 0
    accuracy=correct/eligible if eligible else None
    coverage=available/eligible if eligible else None
    interval=None
    if eligible:
        z=1.96
        centre=(accuracy+z*z/(2*eligible))/(1+z*z/eligible)
        radius=z*math.sqrt(accuracy*(1-accuracy)/eligible+z*z/(4*eligible*eligible))/(1+z*z/eligible)
        interval=[centre-radius,centre+radius]
    return {'entries':len(entries),'eligibleReviewed':eligible,'correct':correct,'exactAccuracy':accuracy,
            'suggestionCoverage':coverage,'missingPredictions':eligible-available,'errorPoints':errors,
            'accuracy95WilsonInterval':interval,'exclusions':exclusions,'boundaryViolations':boundary,
            'passesPointEstimate90Percent':accuracy is not None and accuracy > .9,
            'heldOutReviewed':heldout_eligible,'heldOutCorrect':heldout_correct,
            'heldOutExactAccuracy':heldout_correct/heldout_eligible if heldout_eligible else None,
            'rolloutApproved':False}
