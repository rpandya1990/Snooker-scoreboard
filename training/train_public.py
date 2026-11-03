"""Train a YOLOv8-nano ball detector on the public broadcast dataset (one 'ball' class).

Run with the training environment, from the repository root:
  training/.venv/bin/python training/train_public.py
"""
from pathlib import Path
from ultralytics import YOLO

ROOT=Path(__file__).resolve().parent
DATA=ROOT.parent/'companion/data/external/gezi-v1/data-local.yaml'

if __name__=='__main__':
    model=YOLO('yolov8n.pt')   # Ultralytics' COCO-pretrained starting weights
    model.train(data=str(DATA),imgsz=640,epochs=60,patience=15,batch=16,device='mps',
        project=str(ROOT/'runs'),name='gezi-v1',exist_ok=True,seed=0,verbose=False)
