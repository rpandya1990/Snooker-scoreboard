"""Turn newly extracted dataset frames into reviewable 8-class labels and a review queue.

For each session not yet prepared:
  1. Ball boxes come from the YOLO ball detector (inside the calibrated table outline).
  2. Each box's colour comes from the companion's colour rules (ai_scoring box_label).
  3. Table checks flag frames with unknown colours, duplicates, >15 reds or >1 cue ball.
  4. A ball that has not moved keeps its colour from the previous frame (copy forward);
     a still ball that changes colour is flagged.
  5. Score check: the pots/respots implied by consecutive frames are scored with the clean-play
     rules and compared with each break entered in the app. Matching breaks confirm their frames.
  6. Confirmed frames are auto-accepted, except a random ~10% kept for a spot check; every other
     frame goes to the review queue.

Pre-labels and auto-accepted labels are not ground truth until reviewed or spot-checked.

  training/.venv/bin/python training/prepare_review.py [--dataset companion/data/dataset]
"""
import argparse
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import cv2
from ultralytics import YOLO
from ai_scoring.dao.session_snapshot import read_session_snapshot, SnapshotError
from ai_scoring.domain.ball_detection import box_label, table_polygon, REFERENCE_WIDTH
from ai_scoring.domain.scoring import SnookerAccumulator, interpretable_table
from ai_scoring.domain.visual_adapter import TimestampedFrame
from ai_scoring.services.dataset_builder import CLASSES

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parent
COLOURS=CLASSES[1:7]
STILL_PIXELS=4          # at 1280 px: same ball if it moved less than this
MIN_CONFIDENCE=.5


def inside(polygon,x,y):
    signs={(bx-ax)*(y-ay)-(by-ay)*(x-ax)>0 for (ax,ay),(bx,by) in zip(polygon,polygon[1:]+polygon[:1])}
    return len(signs)==1


def frame_time(entry):
    return datetime.fromisoformat(entry['segmentCaptureStartUtc'])+timedelta(seconds=entry['segmentOffsetSeconds'])


class Labeller:
    def __init__(self,weights,calibration):
        self.model=YOLO(str(weights))
        self.calibration=calibration

    def label(self,image_path):
        """Return [(class, x, y, w, h, confidence)] in image pixels."""
        image=cv2.imread(str(image_path))
        height,width=image.shape[:2]
        small=cv2.cvtColor(cv2.resize(image,(REFERENCE_WIDTH,round(REFERENCE_WIDTH*height/width)),interpolation=cv2.INTER_AREA),cv2.COLOR_BGR2RGB)
        frame=TimestampedFrame(small.tobytes(),'1970-01-01T00:00:00+00:00','dataset',0.0,0.0,small.shape[1],small.shape[0])
        scale=small.shape[1]/width
        polygon=table_polygon(self.calibration['pockets'],width,height)
        result=self.model.predict(str(image_path),imgsz=1280,conf=.25,device='mps',verbose=False)[0]
        balls=[]
        for (x0,y0,x1,y1),confidence in zip(result.boxes.xyxy.tolist(),result.boxes.conf.tolist()):
            x,y=(x0+x1)/2,(y0+y1)/2
            if not inside(polygon,x,y): continue
            colour,_=box_label(frame,x0*scale,y0*scale,x1*scale,y1*scale)
            balls.append([colour,x,y,x1-x0,y1-y0,confidence])
        return balls,width,height


def check(balls,previous):
    """Copy colours forward for still balls and return the table-check reasons."""
    reasons=set()
    for ball in balls:
        still=next((old for old in previous if math.dist(old[1:3],ball[1:3])<STILL_PIXELS),None)
        if still is not None and still[0] is not None:
            if ball[0] is None: ball[0]=still[0]
            elif ball[0]!=still[0]: reasons.add('colour_changed_while_still')
        if ball[0] is None: reasons.add('colour_unknown')
        if ball[5]<MIN_CONFIDENCE: reasons.add('low_confidence_box')
    labels=[ball[0] for ball in balls]
    if labels.count('red')>15: reasons.add('too_many_reds')
    if labels.count('white')>1: reasons.add('multiple_cue_balls')
    if any(labels.count(colour)>1 for colour in COLOURS): reasons.add('duplicate_colour')
    return reasons


def inventory(balls):
    labels=[ball[0] for ball in balls]
    return labels.count('red'),frozenset(label for label in labels if label in COLOURS)


def score_runs(frames,records):
    """Mark frames whose break total matches the score entered in the app."""
    entries=[record['payload']['event'] for record in records
             if record['type']=='event' and record['payload']['event']['type']=='break_committed']
    if not entries: return
    # A player over the table hides balls, which would read as pots; only clear
    # views (per the extraction's occlusion check) can confirm a break.
    usable=[f for f in frames if not f['reasons'] and f['entry']['prelabel']['visibility']=='clear']
    rules=None;state=None;start=None
    run_frames=[];ambiguous=False
    def close_run(entry):
        nonlocal run_frames,ambiguous
        if rules is not None and not ambiguous and not rules.quality_reasons and rules.points==entry['submittedPoints']:
            for frame in run_frames: frame['scoreConfirmed']=True
        if rules is not None: rules.new_visit();rules.quality_reasons.clear()
        run_frames=[];ambiguous=False
    pending=sorted(entries,key=lambda e:e['inputStartedAt'])
    for frame in usable:
        while pending and frame['time']>datetime.fromisoformat(pending[0]['inputStartedAt']):
            close_run(pending.pop(0))
        key=inventory(frame['balls'])
        if rules is None:
            if interpretable_table(*key):
                rules=SnookerAccumulator(key[0])
                if key[0]==0: rules.clearance_index=6-len(key[1]);rules.new_visit()
                state=key
            continue
        run_frames.append(frame)
        reds,colours=state
        removed,added=colours-key[1],key[1]-colours
        if key[0]>reds or (added and (key[0]<reds or removed)) or len(removed)>1:
            ambiguous=True
        else:
            if key[0]<reds: rules.pot('red',reds-key[0])
            for ball in removed: rules.pot(ball)
            for ball in added: rules.respot(ball)
        state=key
    while pending: close_run(pending.pop(0))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,default=REPO/'companion/data/dataset')
    parser.add_argument('--data-directory',type=Path,default=REPO/'companion/data')
    parser.add_argument('--weights',type=Path,default=ROOT/'runs/gezi-v1/weights/best.pt')
    parser.add_argument('--spot-check',type=float,default=.1)
    args=parser.parse_args()
    manifest_path=args.dataset/'manifest.jsonl'
    if not manifest_path.exists():
        print('prepare: no extracted frames yet');return 0
    manifest=[json.loads(line) for line in manifest_path.read_text().splitlines()]
    state_path=args.dataset/'review-state.json'
    prepared=set(json.loads(state_path.read_text())) if state_path.exists() else set()
    sessions=sorted({entry['session'] for entry in manifest}-prepared)
    if not sessions:
        print('prepare: nothing new');return 0
    labeller=Labeller(args.weights,json.loads((args.data_directory/'calibration.json').read_text()))
    for session in sessions:
        try:
            records,_=read_session_snapshot(args.data_directory,session)
        except SnapshotError as error:
            print(f'prepare: skipping {session}: {error}');continue
        frames=[]
        previous=[]
        for entry in sorted((e for e in manifest if e['session']==session),key=frame_time):
            balls,width,height=labeller.label(args.dataset/entry['image'])
            reasons=check(balls,previous)
            previous=balls
            frames.append({'entry':entry,'balls':balls,'reasons':reasons,'time':frame_time(entry),'width':width,'height':height,'scoreConfirmed':False})
        score_runs(frames,records)
        for frame in frames:
            entry=frame['entry']
            lines=[f"{CLASSES.index(c)} {x/frame['width']:.6f} {y/frame['height']:.6f} {w/frame['width']:.6f} {h/frame['height']:.6f}"
                   for c,x,y,w,h,_ in frame['balls'] if c is not None]
            (args.dataset/'labels'/(Path(entry['image']).stem+'.txt')).write_text('\n'.join(lines)+('\n' if lines else ''))
            reasons=sorted(frame['reasons'])
            if not reasons and entry['prelabel']['visibility']!='clear': reasons=['view_blocked']
            if not reasons and not frame['scoreConfirmed']: reasons=['not_score_confirmed']
            sample=int(hashlib.sha256(entry['image'].encode()).hexdigest(),16)%1000<args.spot_check*1000
            entry.update(labelSource=f'yolo:{args.weights.parent.parent.name}+colour-rules',reasons=reasons,
                status='needs_review' if reasons else ('spot_check' if sample else 'auto_accepted'))
        prepared.add(session)
        counts={status:sum(1 for f in frames if f['entry']['status']==status) for status in ('auto_accepted','spot_check','needs_review')}
        print(f'prepare: {session}: {len(frames)} frames {counts}')
    manifest_path.write_text(''.join(json.dumps(entry,sort_keys=True)+'\n' for entry in manifest))
    state_path.write_text(json.dumps(sorted(prepared)))
    queue=[entry['image'] for entry in manifest if entry.get('status') in ('needs_review','spot_check') and not entry.get('reviewed')]
    (args.dataset/'review-queue.txt').write_text(''.join(image+'\n' for image in queue))
    print(f'prepare: {len(queue)} frames to review listed in {args.dataset/"review-queue.txt"}')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
