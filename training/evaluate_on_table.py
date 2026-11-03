"""Compare a trained ball detector with colour-blob pre-labels on our own table frames.

Pre-labels are not ground truth: a "missed" ball may be a pre-label error, and an
"extra" detection may be a ball the pre-labels missed. Saved overlays show which.

  training/.venv/bin/python training/evaluate_on_table.py WEIGHTS [--imgsz 1280] [--limit 133]
"""
import argparse
import json
import math
from pathlib import Path
from ultralytics import YOLO

ROOT=Path(__file__).resolve().parent
DATASET=ROOT.parent/'companion/data/dataset-trial'
CLASSES=(DATASET/'classes.txt').read_text().split()
CALIBRATION=json.loads((ROOT.parent/'companion/data/calibration.json').read_text())


def on_table(x,y,width,height):
    """Inside the pocket outline the companion already uses to ignore the room."""
    import math as m
    points=CALIBRATION['pockets'];cx=sum(p[0] for p in points)/6;cy=sum(p[1] for p in points)/6
    polygon=sorted(points,key=lambda p:m.atan2(p[1]-cy,p[0]-cx))
    u,v=x/width,y/height
    signs={(bx-ax)*(v-ay)-(by-ay)*(u-ax)>0 for (ax,ay),(bx,by) in zip(polygon,polygon[1:]+polygon[:1])}
    return len(signs)==1


def prelabels(stem,width,height):
    path=DATASET/'labels'/(stem+'.txt')
    return [(CLASSES[int(c)],float(x)*width,float(y)*height,float(w)*width) for c,x,y,w,_ in (line.split() for line in path.read_text().splitlines())]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('weights')
    parser.add_argument('--imgsz',type=int,default=1280)
    parser.add_argument('--conf',type=float,default=.25)
    parser.add_argument('--overlays',type=int,default=6)
    args=parser.parse_args()
    model=YOLO(args.weights)
    manifest=[json.loads(line) for line in (DATASET/'manifest.jsonl').read_text().splitlines()]
    out=ROOT/'runs'/'table-eval'/f'{Path(args.weights).parent.parent.name}-{args.imgsz}'
    out.mkdir(parents=True,exist_ok=True)
    totals={}
    worst=[]
    for entry in manifest:
        image=DATASET/entry['image']
        result=model.predict(str(image),imgsz=args.imgsz,conf=args.conf,device='mps',verbose=False)[0]
        height,width=result.orig_shape
        predicted=[((x1+x2)/2,(y1+y2)/2) for x1,y1,x2,y2 in result.boxes.xyxy.tolist()]
        off_table=sum(1 for x,y in predicted if not on_table(x,y,width,height))
        predicted=[(x,y) for x,y in predicted if on_table(x,y,width,height)]
        reference=prelabels(image.stem,width,height)
        unmatched=list(predicted)
        matched=0
        for _,x,y,size in reference:
            hit=min(unmatched,key=lambda p:math.dist(p,(x,y)),default=None)
            if hit is not None and math.dist(hit,(x,y))<=max(size,8):
                unmatched.remove(hit);matched+=1
        group=entry['prelabel']['visibility']
        bucket=totals.setdefault(group,{'frames':0,'prelabelled':0,'matched':0,'extra':0,'offTable':0})
        bucket['frames']+=1;bucket['offTable']+=off_table;bucket['prelabelled']+=len(reference);bucket['matched']+=matched;bucket['extra']+=len(unmatched)
        worst.append((len(reference)-matched+len(unmatched),image,result))
    for group,bucket in sorted(totals.items()):
        recall=bucket['matched']/bucket['prelabelled'] if bucket['prelabelled'] else 0
        print(f"{group:9s} frames={bucket['frames']:3d} pre-labelled balls={bucket['prelabelled']:4d} "
              f"found={bucket['matched']:4d} ({recall:.0%}) extra on table={bucket['extra']} ignored off table={bucket['offTable']}")
    worst.sort(key=lambda item:-item[0])
    for disagreement,image,result in worst[:args.overlays]:
        result.save(filename=str(out/f'{disagreement:02d}-{image.stem}.jpg'))
    print(f'overlays of the {args.overlays} biggest disagreements: {out}')


if __name__=='__main__':
    main()
