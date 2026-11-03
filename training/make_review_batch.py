"""Select a varied batch of dataset frames and write Label Studio tasks with pre-labels.

Frames are spread over time within view-condition groups (clear / player in the way /
uncertain), favouring frames with touching reds. Pre-labels come from the YOLO ball
detector plus the colour rules, with duplicate boxes on one ball removed; a ball whose
colour is unknown is labelled "unknown" so the reviewer must fix it.

  training/.venv/bin/python training/make_review_batch.py --name batch-1 --size 150
"""
import argparse
import json
from pathlib import Path
import cv2
from prepare_review import Labeller, ROOT, REPO, frame_time
from ai_scoring.services.dataset_builder import CLASSES

LABELS=(*CLASSES,'unknown')
QUOTAS={'clear':.4,'occluded':.37,'uncertain':.23}
COLOURS={'red':'#e53935','yellow':'#fdd835','green':'#2e7d32','brown':'#795548','blue':'#1e88e5',
         'pink':'#f48fb1','black':'#212121','white':'#e0e0e0','unknown':'#9c27b0'}


def spread(items,count):
    """Evenly spaced picks over a time-ordered list."""
    if count>=len(items): return list(items)
    return [items[round(i*(len(items)-1)/max(1,count-1))] for i in range(count)]


def select(manifest,size,exclude):
    chosen=[]
    for visibility,share in QUOTAS.items():
        group=sorted((e for e in manifest if e['prelabel']['visibility']==visibility and e['image'] not in exclude),key=frame_time)
        quota=round(size*share)
        packed=[e for e in group if e['prelabel']['touchingReds']]
        loose=[e for e in group if not e['prelabel']['touchingReds']]
        take_packed=min(len(packed),max(round(quota*.4),quota-len(loose)))
        chosen+=spread(packed,take_packed)+spread(loose,quota-take_packed)
    return sorted({e['image']:e for e in chosen}.values(),key=frame_time)[:size]


def overlap(a,b):
    ax0,ay0,ax1,ay1=a[1]-a[3]/2,a[2]-a[4]/2,a[1]+a[3]/2,a[2]+a[4]/2
    bx0,by0,bx1,by1=b[1]-b[3]/2,b[2]-b[4]/2,b[1]+b[3]/2,b[2]+b[4]/2
    inter=max(0,min(ax1,bx1)-max(ax0,bx0))*max(0,min(ay1,by1)-max(ay0,by0))
    union=a[3]*a[4]+b[3]*b[4]-inter
    return inter/union if union else 0


def dedupe(balls):
    kept=[]
    for ball in sorted(balls,key=lambda b:-b[5]):
        if all(overlap(ball,other)<.5 for other in kept): kept.append(ball)
    return kept


def task(entry,balls,width,height):
    result=[]
    for colour,x,y,w,h,confidence in balls:
        result.append({'from_name':'label','to_name':'image','type':'rectanglelabels','original_width':width,'original_height':height,
            'score':round(confidence,3),'value':{'x':100*(x-w/2)/width,'y':100*(y-h/2)/height,'width':100*w/width,'height':100*h/height,
            'rotation':0,'rectanglelabels':[colour or 'unknown']}})
    return {'data':{'image':'/data/local-files/?d='+entry['image'],'session':entry['session'],
                    'visibility':entry['prelabel']['visibility'],'reasons':', '.join(entry.get('reasons',[]))},
            'predictions':[{'model_version':'yolo-gezi-v1+colour-rules','score':round(min((b[5] for b in balls),default=1),3),'result':result}]}


def config():
    labels=''.join(f'<Label value="{name}" background="{COLOURS[name]}"/>' for name in LABELS)
    return ('<View>\n  <Header value="One tight box per ball on the cloth (not its shadow). Fix colours; replace every unknown."/>\n'
            '  <Image name="image" value="$image" zoom="true" zoomControl="true" rotateControl="false"/>\n'
            f'  <RectangleLabels name="label" toName="image">{labels}</RectangleLabels>\n</View>\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,default=REPO/'companion/data/dataset')
    parser.add_argument('--name',default='batch-1')
    parser.add_argument('--size',type=int,default=150)
    parser.add_argument('--weights',type=Path,default=ROOT/'runs/gezi-v1/weights/best.pt')
    args=parser.parse_args()
    manifest=[json.loads(line) for line in (args.dataset/'manifest.jsonl').read_text().splitlines()]
    batches=args.dataset/'review-batches'
    used={line for path in batches.glob('*/frames.txt') for line in path.read_text().split()} if batches.exists() else set()
    frames=select(manifest,args.size,used)
    labeller=Labeller(args.weights,json.loads((REPO/'companion/data/calibration.json').read_text()))
    tasks=[]
    for entry in frames:
        balls,width,height=labeller.label(args.dataset/entry['image'])
        tasks.append(task(entry,dedupe(balls),width,height))
    out=batches/args.name
    out.mkdir(parents=True,exist_ok=True)
    (out/'tasks.json').write_text(json.dumps(tasks))
    (out/'labeling-config.xml').write_text(config())
    (out/'frames.txt').write_text(''.join(entry['image']+'\n' for entry in frames))
    counts={v:sum(1 for e in frames if e['prelabel']['visibility']==v) for v in QUOTAS}
    unknown=sum(1 for t in tasks for r in t['predictions'][0]['result'] if r['value']['rectanglelabels']==['unknown'])
    print(f'{args.name}: {len(tasks)} frames {counts}, {sum(e["prelabel"]["touchingReds"] for e in frames)} with touching reds, '
          f'{sum(len(t["predictions"][0]["result"]) for t in tasks)} pre-labelled balls ({unknown} unknown) -> {out}')


if __name__=='__main__':
    main()
