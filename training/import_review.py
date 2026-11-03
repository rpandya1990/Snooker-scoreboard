"""Import reviewed Label Studio annotations into the dataset and build a training split.

Reads a backup copy of Label Studio's local database (never the live file), writes the
reviewed YOLO labels into dataset/labels/, marks the frames `reviewed` in the manifest,
and builds training/data/reviewed/ (image symlinks + labels) with a time-ordered split:
the last frames of each session are held out for validation, so near-duplicate frames
seconds apart never straddle train and validation.

  training/.venv/bin/python training/import_review.py --validation-share 0.2
"""
import argparse
import collections
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from prepare_review import REPO, ROOT, frame_time
from ai_scoring.services.dataset_builder import CLASSES

GROUND_TRUTH=REPO/'datasets/ground-truth'
LABEL_STUDIO_DB=Path.home()/'Library/Application Support/label-studio/label_studio.sqlite3'


def annotations(project):
    with tempfile.TemporaryDirectory() as scratch:
        copy=Path(scratch)/'ls.sqlite3'
        source=sqlite3.connect(f'file:{LABEL_STUDIO_DB}?mode=ro',uri=True)
        target=sqlite3.connect(copy)
        source.backup(target);source.close()
        rows=target.execute('''select t.data,c.result,c.updated_at from task t join task_completion c on c.task_id=t.id
            where t.project_id=? and c.was_cancelled=0 order by c.updated_at''',(project,)).fetchall()
        target.close()
    latest={}
    for data,result,updated in rows:
        latest[json.loads(data)['image'].split('d=',1)[1]]=json.loads(result)
    return latest


def yolo_lines(result):
    lines=[];problems=[]
    for region in result:
        if region.get('type')!='rectanglelabels': continue
        value=region['value'];label=value['rectanglelabels'][0]
        if label not in CLASSES: problems.append(label);continue
        x,y,w,h=value['x']/100,value['y']/100,value['width']/100,value['height']/100
        lines.append(f'{CLASSES.index(label)} {x+w/2:.6f} {y+h/2:.6f} {w:.6f} {h:.6f}')
    return lines,problems


def export_ground_truth(dataset,reviewed):
    """Copy reviewed frames into the repository, one folder per local session date."""
    from datetime import datetime
    GROUND_TRUTH.mkdir(parents=True,exist_ok=True)
    (GROUND_TRUTH/'classes.txt').write_text('\n'.join(CLASSES)+'\n')
    dates=collections.defaultdict(list)
    for entry in reviewed:
        dates[frame_time(entry).astimezone().date().isoformat()].append(entry)
    for date,entries in sorted(dates.items()):
        folder=GROUND_TRUTH/date
        for part in ('images','labels'): (folder/part).mkdir(parents=True,exist_ok=True)
        for entry in entries:
            stem=Path(entry['image']).stem
            shutil.copy(dataset/entry['image'],folder/'images'/(stem+'.jpg'))
            shutil.copy(dataset/'labels'/(stem+'.txt'),folder/'labels'/(stem+'.txt'))
        entries=sorted(entries,key=frame_time)
        (folder/'manifest.jsonl').write_text(''.join(json.dumps(e,sort_keys=True)+'\n' for e in entries))
        counts=collections.Counter()
        for entry in entries:
            for line in (folder/'labels'/(Path(entry['image']).stem+'.txt')).read_text().split('\n'):
                if line: counts[CLASSES[int(line.split()[0])]]+=1
        sessions=sorted({e['session'] for e in entries})
        (folder/'README.md').write_text(f'# Ground truth — {date}\n\n'
            f'{len(entries)} human-reviewed frames from {len(sessions)} session(s): {", ".join(sessions)}.\n\n'
            '| Class | Boxes |\n| --- | --- |\n'+''.join(f'| {name} | {counts[name]} |\n' for name in CLASSES)+
            f'\nViews: {dict(collections.Counter(e["prelabel"]["visibility"] for e in entries))}; '
            f'frames with touching reds: {sum(e["prelabel"]["touchingReds"] for e in entries)}.\n')
    return sorted(dates)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,default=REPO/'companion/data/dataset')
    parser.add_argument('--project',type=int,default=1)
    parser.add_argument('--validation-share',type=float,default=.2)
    args=parser.parse_args()
    manifest_path=args.dataset/'manifest.jsonl'
    manifest=[json.loads(line) for line in manifest_path.read_text().splitlines()]
    by_image={entry['image']:entry for entry in manifest}
    imported=0
    for image,result in annotations(args.project).items():
        lines,problems=yolo_lines(result)
        counts=collections.Counter(line.split()[0] for line in lines)
        if problems or int(counts.get('0',0))>15 or any(counts.get(str(i),0)>1 for i in range(1,8)):
            raise SystemExit(f'{image}: fails table checks ({problems or dict(counts)}); fix it in Label Studio first')
        (args.dataset/'labels'/(Path(image).stem+'.txt')).write_text('\n'.join(lines)+'\n')
        by_image[image].update(reviewed=True,status='reviewed',labelSource=f'label-studio:project-{args.project}',reasons=[])
        imported+=1
    manifest_path.write_text(''.join(json.dumps(entry,sort_keys=True)+'\n' for entry in manifest))
    reviewed=[entry for entry in manifest if entry.get('reviewed')]
    dates=export_ground_truth(args.dataset,reviewed)
    split={}
    for session in {entry['session'] for entry in reviewed}:
        frames=sorted((e for e in reviewed if e['session']==session),key=frame_time)
        held=max(1,round(len(frames)*args.validation_share))
        for entry in frames[:-held]: split[entry['image']]='train'
        for entry in frames[-held:]: split[entry['image']]='val'
    out=ROOT/'data/reviewed'
    shutil.rmtree(out,ignore_errors=True)
    for part in ('train','val'):
        (out/part/'images').mkdir(parents=True);(out/part/'labels').mkdir(parents=True)
    for image,part in split.items():
        stem=Path(image).stem
        (out/part/'images'/(stem+'.jpg')).symlink_to(args.dataset/image)
        shutil.copy(args.dataset/'labels'/(stem+'.txt'),out/part/'labels'/(stem+'.txt'))
    (out/'data.yaml').write_text(f'path: {out}\ntrain: train/images\nval: val/images\nnames: {list(CLASSES)}\n')
    parts=collections.Counter(split.values())
    print(f'ground truth stored in {GROUND_TRUTH} for {", ".join(dates)}')
    print(f'imported {imported} reviewed frames; split train={parts["train"]} val={parts["val"]} -> {out/"data.yaml"}')


if __name__=='__main__':
    main()
