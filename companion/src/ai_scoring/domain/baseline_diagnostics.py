"""Bounded, answer-free baseline diagnostics; never raw model responses."""
import math
from ai_scoring.domain.scoring import Ball

COLOURS=tuple(ball.value for ball in Ball if ball!=Ball.RED)
CAUSES=frozenset(('baseline_missing','baseline_schema_invalid','invalid_red_count','reds_not_15',
    'missing_colours','duplicate_colours','invalid_colours','baseline_not_settled','baseline_low_confidence',
    'baseline_confidence_invalid','baseline_phase_not_red_colour','baseline_frame_not_in_window',
    'witness_count_invalid','witness_reds_not_15','witness_missing_colours','witness_not_settled',
    'witness_low_confidence','witness_confidence_invalid','witness_frame_not_in_window',
    'witnesses_not_chronological','baseline_not_latest_witness','baseline_not_latest_window','visibility_not_clear',
    'model_reported_uncertainty','window_incomplete','schema_validation_failed'))

def bounded_int(value,limit):
    return value if type(value) is int and 0<=value<=limit else None

def confidence(value):
    return value if type(value) in (int,float) and math.isfinite(value) and 0<=value<=1 else None

def colour_list(value):
    return [colour for colour in COLOURS if isinstance(value,list) and colour in value]

def summarize_baseline(output,window_ids,threshold):
    output=output if isinstance(output,dict) else {}
    candidate=output.get('baseline')
    causes=set()
    visibility=output.get('visibility') if output.get('visibility') in ('clear','occluded','uncertain') else 'invalid'
    if visibility!='clear': causes.add('visibility_not_clear')
    if output.get('uncertainty'): causes.add('model_reported_uncertainty')
    if not isinstance(candidate,dict):
        candidate={}
        causes.add('baseline_missing')
    reds=bounded_int(candidate.get('reds'),15)
    colours=colour_list(candidate.get('coloursPresent'))
    certainty=confidence(candidate.get('confidence'))
    settled=candidate.get('settled') if type(candidate.get('settled')) is bool else None
    phase=candidate.get('phase') if candidate.get('phase') in ('red_colour','clearance','unknown') else 'invalid'
    indices={identifier:index for index,identifier in enumerate(window_ids)}
    reference=candidate.get('frameId')
    reference_valid=isinstance(reference,str) and reference in indices
    if candidate:
        if reds is None: causes.add('invalid_red_count')
        elif reds!=15: causes.add('reds_not_15')
        if len(colours)!=6: causes.add('missing_colours')
        raw_colours=candidate.get('coloursPresent')
        if not isinstance(raw_colours,list) or any(not isinstance(colour,str) or colour not in COLOURS for colour in raw_colours): causes.add('invalid_colours')
        elif len(set(raw_colours))!=len(raw_colours): causes.add('duplicate_colours')
        if settled is not True: causes.add('baseline_not_settled')
        if certainty is None: causes.add('baseline_confidence_invalid')
        elif certainty<threshold: causes.add('baseline_low_confidence')
        if phase!='red_colour': causes.add('baseline_phase_not_red_colour')
        if not reference_valid: causes.add('baseline_frame_not_in_window')
        elif window_ids and reference!=window_ids[-1]: causes.add('baseline_not_latest_window')
    raw_witnesses=candidate.get('witnesses')
    count=min(len(raw_witnesses),9) if isinstance(raw_witnesses,list) else 0
    if candidate and not 3<=count<=8: causes.add('witness_count_invalid')
    witnesses=[]
    witness_indices=[]
    for raw in raw_witnesses[:8] if isinstance(raw_witnesses,list) else []:
        witness=raw if isinstance(raw,dict) else {}
        red_count=bounded_int(witness.get('reds'),15)
        present=colour_list(witness.get('coloursPresent'))
        certain=confidence(witness.get('confidence'))
        still=witness.get('settled') if type(witness.get('settled')) is bool else None
        identifier=witness.get('frameId')
        position=indices.get(identifier) if isinstance(identifier,str) else None
        if red_count!=15: causes.add('witness_reds_not_15')
        if len(present)!=6 or not isinstance(witness.get('coloursPresent'),list) or len(witness['coloursPresent'])!=6: causes.add('witness_missing_colours')
        if still is not True: causes.add('witness_not_settled')
        if certain is None: causes.add('witness_confidence_invalid')
        elif certain<threshold: causes.add('witness_low_confidence')
        if position is None: causes.add('witness_frame_not_in_window')
        witness_indices.append(position)
        witnesses.append({'reds':red_count,'coloursPresent':present,'colourCount':len(present),
            'confidence':certain,'settled':still,'frameIndex':position})
    if witnesses:
        valid=[position for position in witness_indices if position is not None]
        if len(valid)!=len(witness_indices) or valid!=sorted(set(valid)):
            causes.add('witnesses_not_chronological')
        if not reference_valid or witness_indices[-1]!=indices.get(reference):
            causes.add('baseline_not_latest_witness')
    return sanitize_summary({'reds':reds,'coloursPresent':colours,'confidence':certainty,'settled':settled,'phase':phase,
        'visibility':visibility,'witnessCount':count,'witnesses':witnesses,'validationCauses':sorted(causes),
        'minimumConfidence':threshold,'baselineFrameReferenceValid':reference_valid})

def sanitize_summary(value):
    """Also validate adapter-supplied diagnostics at the persistence boundary."""
    value=value if isinstance(value,dict) else {}
    colours=colour_list(value.get('coloursPresent'))
    result={'reds':bounded_int(value.get('reds'),15),'coloursPresent':colours,'colourCount':len(colours),
        'confidence':confidence(value.get('confidence')),'settled':value.get('settled') if type(value.get('settled')) is bool else None,
        'phase':value.get('phase') if value.get('phase') in ('red_colour','clearance','unknown') else 'invalid',
        'visibility':value.get('visibility') if value.get('visibility') in ('clear','occluded','uncertain') else 'invalid',
        'witnessCount':bounded_int(value.get('witnessCount'),9),'witnesses':[],
        'minimumConfidence':confidence(value.get('minimumConfidence')),
        'baselineFrameReferenceValid':value.get('baselineFrameReferenceValid') is True,
        'baselineAccepted':value.get('baselineAccepted') is True,
        'baselineAlreadyEstablished':value.get('baselineAlreadyEstablished') is True,
        'validationCauses':sorted(set(cause for cause in value.get('validationCauses',[]) if isinstance(cause,str) and cause in CAUSES)) if isinstance(value.get('validationCauses'),list) else []}
    witnesses=value.get('witnesses')
    for witness in witnesses[:8] if isinstance(witnesses,list) else []:
        if not isinstance(witness,dict):continue
        present=colour_list(witness.get('coloursPresent'))
        result['witnesses'].append({'reds':bounded_int(witness.get('reds'),15),'coloursPresent':present,'colourCount':len(present),
            'confidence':confidence(witness.get('confidence')),'settled':witness.get('settled') if type(witness.get('settled')) is bool else None,
            'frameIndex':bounded_int(witness.get('frameIndex'),7)})
    return result
