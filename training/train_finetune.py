"""Fine-tune a ball detector into the 8-class table model on reviewed frames.

  training/.venv/bin/python training/train_finetune.py --base runs/gezi-v1/weights/best.pt --name table-v8n
"""
import argparse
from pathlib import Path
from ultralytics import YOLO

ROOT=Path(__file__).resolve().parent

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',required=True,help='Starting weights (a trained ball detector or a stock .pt)')
    parser.add_argument('--name',required=True)
    parser.add_argument('--imgsz',type=int,default=1280)
    parser.add_argument('--epochs',type=int,default=150)
    parser.add_argument('--batch',type=int,default=8)
    args=parser.parse_args()
    base=Path(args.base)
    model=YOLO(str(ROOT/base) if (ROOT/base).exists() else args.base)
    # Colour identity is the label: keep hue jitter tiny; brightness/saturation jitter
    # still covers lighting changes.
    model.train(data=str(ROOT/'data/reviewed/data.yaml'),imgsz=args.imgsz,epochs=args.epochs,patience=30,batch=args.batch,
        device='mps',project=str(ROOT/'runs'),name=args.name,exist_ok=True,seed=0,verbose=False,
        hsv_h=.003,hsv_s=.4,hsv_v=.4,fliplr=.5,degrees=0,mosaic=1.0,close_mosaic=20)
