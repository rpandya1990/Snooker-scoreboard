"""Live ball reading with an exported YOLO detector (ONNX), colours from the colour rules.

The model finds balls (and proposes a colour); the colour rules label each box and keep
the blocked-view check, using a half-size copy of the frame close to the scale their
thresholds were tuned at. The model's own colour is used only when the rules cannot
decide. Requires the optional `model` extra (onnxruntime, numpy).
"""
import ast
from ai_scoring.domain.ball_detection import BallDetector, Inventory, box_label, table_polygon, COLOURS
from ai_scoring.domain.visual_adapter import TimestampedFrame
from ai_scoring.services.dataset_builder import CLASSES

PAD=114   # YOLO letterbox padding value


def inside(polygon,x,y):
    signs={(bx-ax)*(y-ay)-(by-ay)*(x-ax)>0 for (ax,ay),(bx,by) in zip(polygon,polygon[1:]+polygon[:1])}
    return len(signs)==1


class BallModel:
    def __init__(self,path,calibration,confidence=.35,iou=.5,session=None):
        import numpy
        self.np=numpy
        if session is None:
            import onnxruntime
            session=onnxruntime.InferenceSession(str(path),providers=['CoreMLExecutionProvider','CPUExecutionProvider'])
        self.session=session
        names=ast.literal_eval(session.get_modelmeta().custom_metadata_map.get('names','{}'))
        self.classes=[names[index] for index in sorted(names)]
        if not set(self.classes)<=set(CLASSES):
            raise ValueError('ball model classes do not match the ball labels')
        shape=session.get_inputs()[0].shape
        self.size=int(shape[2])
        self.input=session.get_inputs()[0].name
        self.confidence,self.iou=confidence,iou
        self.calibration=calibration
        self.rules=BallDetector(calibration)

    def _letterbox(self,image):
        np=self.np
        height,width=image.shape[:2]
        scale=min(self.size/width,self.size/height)
        if scale!=1:
            # Nearest resize; run the capture at the model's width to avoid it.
            rows=(np.arange(round(height*scale))/scale).astype(int).clip(0,height-1)
            cols=(np.arange(round(width*scale))/scale).astype(int).clip(0,width-1)
            image=image[rows][:,cols]
        canvas=np.full((self.size,self.size,3),PAD,np.uint8)
        top,left=(self.size-image.shape[0])//2,(self.size-image.shape[1])//2
        canvas[top:top+image.shape[0],left:left+image.shape[1]]=image
        tensor=canvas.transpose(2,0,1)[None].astype(np.float32)/255
        return tensor,scale,left,top

    def boxes(self,image):
        """[(class, confidence, x0, y0, x1, y1)] in frame pixels, after NMS."""
        np=self.np
        tensor,scale,left,top=self._letterbox(image)
        output=self.session.run(None,{self.input:tensor})[0][0].T   # (candidates, 4 + classes)
        scores=output[:,4:]
        best=scores.argmax(1);confidence=scores.max(1)
        keep=confidence>=self.confidence
        cx,cy,w,h=(output[keep,i] for i in range(4))
        boxes=np.stack([(cx-w/2-left)/scale,(cy-h/2-top)/scale,(cx+w/2-left)/scale,(cy+h/2-top)/scale],1)
        order=np.argsort(-confidence[keep])
        boxes,classes,confidence=boxes[order],best[keep][order],confidence[keep][order]
        chosen=[]
        for index in range(len(boxes)):
            # Class-agnostic NMS: one ball, one box.
            if all(self._overlap(boxes[index],boxes[other])<self.iou for other in chosen): chosen.append(index)
        return [(self.classes[int(classes[i])],float(confidence[i]),*map(float,boxes[i])) for i in chosen]

    @staticmethod
    def _overlap(a,b):
        inter=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
        union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter
        return inter/union if union>0 else 0

    def detect(self,frame):
        np=self.np
        if frame.pixel_format!='rgb24' or len(frame.data)!=frame.width*frame.height*3:
            raise ValueError('invalid RGB frame')
        image=np.frombuffer(frame.data,np.uint8).reshape(frame.height,frame.width,3)
        half=image[:frame.height//2*2,:frame.width//2*2].reshape(frame.height//2,2,frame.width//2,2,3).mean((1,3)).astype(np.uint8)
        small=TimestampedFrame(half.tobytes(),frame.timestamp,frame.asset_id,frame.media_time,frame.utc_uncertainty_ms,half.shape[1],half.shape[0])
        causes=set(cause for cause in self.rules.detect(small).causes if cause=='large_object_on_table')
        polygon=table_polygon(self.calibration['pockets'],frame.width,frame.height)
        balls=[]
        for model_label,_,x0,y0,x1,y1 in self.boxes(image):
            x,y=(x0+x1)/2,(y0+y1)/2
            if not inside(polygon,x,y): continue
            rule_label,_=box_label(small,x0/2,y0/2,x1/2,y1/2)
            balls.append((rule_label or model_label,round(x),round(y),round((x1-x0)*(y1-y0))))
        labels=[ball[0] for ball in balls]
        reds=labels.count('red')
        colours=[label for label in labels if label in COLOURS]
        if len(colours)!=len(set(colours)): causes.add('duplicate_colour')
        if reds>15: causes.add('too_many_reds')
        visibility='occluded' if 'large_object_on_table' in causes else ('uncertain' if causes else 'clear')
        return Inventory(visibility,min(reds,15),frozenset(colours),tuple(balls),tuple(sorted(causes)))
