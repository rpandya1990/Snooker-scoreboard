"""Compare ball readers on held-out reviewed frames: ball recall/precision per class,
colour confusions, and whole-table (inventory) exact match.

Readers: a fine-tuned 8-class model, the public ball model + colour rules, and the
colour rules alone (the current live tracker).

  training/.venv/bin/python training/evaluate_reviewed.py runs/table-v8n/weights/best.pt
"""
import argparse
import collections
import json
import math
from pathlib import Path
import cv2
from ultralytics import YOLO
from prepare_review import Labeller, ROOT, REPO, inside
from ai_scoring.domain.ball_detection import BallDetector, REFERENCE_WIDTH, table_polygon
from ai_scoring.domain.visual_adapter import TimestampedFrame
from ai_scoring.services.dataset_builder import CLASSES

VAL=ROOT/'data/reviewed/val'
CALIBRATION=json.loads((REPO/'companion/data/calibration.json').read_text())


def truth(stem,width,height):
    rows=[line.split() for line in (VAL/'labels'/(stem+'.txt')).read_text().splitlines() if line]
    return [(CLASSES[int(c)],float(x)*width,float(y)*height,float(w)*width) for c,x,y,w,_ in rows]


class FineTuned:
    name='fine-tuned model'
    def __init__(self,weights):self.model=YOLO(str(weights))
    def read(self,image):
        result=self.model.predict(str(image),imgsz=1280,conf=.25,device='mps',verbose=False)[0]
        height,width=result.orig_shape
        polygon=table_polygon(CALIBRATION['pockets'],width,height)
        return [(CLASSES[int(c)],(x0+x1)/2,(y0+y1)/2) for (x0,y0,x1,y1),c in zip(result.boxes.xyxy.tolist(),result.boxes.cls.tolist())
                if inside(polygon,(x0+x1)/2,(y0+y1)/2)]


class PublicPlusRules:
    name='public model + colour rules'
    def __init__(self):self.labeller=Labeller(ROOT/'runs/gezi-v1/weights/best.pt',CALIBRATION)
    def read(self,image):
        balls,_,_=self.labeller.label(image)
        return [(c or 'unknown',x,y) for c,x,y,*_ in balls]


class ColourRules:
    name='colour rules (live today)'
    def __init__(self):self.detector=BallDetector(CALIBRATION)
    def read(self,image):
        img=cv2.imread(str(image));height,width=img.shape[:2]
        small=cv2.cvtColor(cv2.resize(img,(REFERENCE_WIDTH,round(REFERENCE_WIDTH*height/width)),interpolation=cv2.INTER_AREA),cv2.COLOR_BGR2RGB)
        inventory=self.detector.detect(TimestampedFrame(small.tobytes(),'1970-01-01T00:00:00+00:00','eval',0.0,0.0,small.shape[1],small.shape[0]))
        scale=width/small.shape[1]
        return [(label,x*scale,y*scale) for label,x,y,_ in inventory.balls]


def inventory(balls):
    labels=[b[0] for b in balls]
    return labels.count('red'),frozenset(l for l in labels if l in CLASSES[1:7]),labels.count('white')


def evaluate(reader,frames):
    found=collections.Counter();total=collections.Counter();predicted=collections.Counter();correct=collections.Counter()
    confusion=collections.Counter();exact=0;red_errors=[];missed_any=0
    for image in frames:
        img=cv2.imread(str(image));height,width=img.shape[:2]
        gold=truth(image.stem,width,height);guess=reader.read(image)
        unmatched=list(guess)
        for label,x,y,w in gold:
            total[label]+=1
            hit=min(unmatched,key=lambda p:math.dist(p[1:],(x,y)),default=None)
            if hit is not None and math.dist(hit[1:],(x,y))<=max(w,8):
                unmatched.remove(hit);found[label]+=1
                if hit[0]==label: correct[label]+=1
                else: confusion[(label,hit[0])]+=1
        for label,*_ in guess: predicted[label]+=1
        if inventory([(l,) for l,*_ in gold])==inventory([(l,) for l,*_ in guess]): exact+=1
        red_errors.append(abs(sum(l=='red' for l,*_ in gold)-sum(l=='red' for l,*_ in guess)))
    return found,total,predicted,correct,confusion,exact,red_errors


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('weights')
    args=parser.parse_args()
    frames=sorted(VAL.glob('images/*.jpg'))
    readers=[FineTuned(ROOT/args.weights if (ROOT/args.weights).exists() else args.weights),PublicPlusRules(),ColourRules()]
    print(f'{len(frames)} held-out reviewed frames\n')
    for reader in readers:
        found,total,predicted,correct,confusion,exact,red_errors=evaluate(reader,frames)
        balls=sum(total.values())
        print(f'== {reader.name}')
        print(f'   whole-table exact match: {exact}/{len(frames)} ({exact/len(frames):.0%})   red count error: mean {sum(red_errors)/len(red_errors):.2f}, max {max(red_errors)}')
        print(f'   balls found {sum(found.values())}/{balls} ({sum(found.values())/balls:.0%}), right colour {sum(correct.values())}/{balls} ({sum(correct.values())/balls:.0%}), extra detections {sum(predicted.values())-sum(found.values())}')
        print('   per class (right colour / truth):  '+'  '.join(f'{c} {correct[c]}/{total[c]}' for c in CLASSES if total[c]))
        if confusion: print('   colour mix-ups (truth -> read): '+', '.join(f'{a}->{b} x{n}' for (a,b),n in confusion.most_common(6)))
        print()


if __name__=='__main__':
    main()
