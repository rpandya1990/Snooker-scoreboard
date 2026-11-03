import unittest
try:
    import numpy
except ImportError:   # the [model] extra is optional
    numpy=None
from ai_scoring.config import InferenceConfig
from ai_scoring.domain.visual_adapter import TimestampedFrame

W,H=1280,720
CLOTH=(51,194,78);PINK=(255,177,131)
CALIBRATION={'pockets':[[.02,.2],[.5,.2],[.98,.2],[.98,.8],[.5,.8],[.02,.8]],'pocketRadius':.025}
NAMES="{0: 'red', 1: 'yellow', 2: 'green', 3: 'brown', 4: 'blue', 5: 'pink', 6: 'black', 7: 'white'}"


def frame(balls=()):
    pixels=numpy.empty((H,W,3),numpy.uint8);pixels[:]=CLOTH
    for x,y,colour in balls:
        yy,xx=numpy.ogrid[:H,:W]
        pixels[(xx-x)**2+(yy-y)**2<=49]=colour
    return TimestampedFrame(pixels.tobytes(),'2026-01-01T00:00:00+00:00','fixture',0.0,0.0,W,H)


class FakeSession:
    """ONNX session stand-in: each box is (cx, cy, w, h, class, score) in frame pixels."""
    def __init__(self,boxes,names=NAMES):
        self.boxes=boxes;self.names=names
    def get_modelmeta(self):
        return type('Meta',(),{'custom_metadata_map':{'names':self.names}})()
    def get_inputs(self):
        return [type('Input',(),{'name':'images','shape':[1,3,1280,1280]})()]
    def run(self,_,feeds):
        tensor=feeds['images']
        assert tensor.shape==(1,3,1280,1280) and tensor.dtype==numpy.float32
        out=numpy.zeros((1,12,len(self.boxes)),numpy.float32)
        top=(1280-H)//2   # letterbox pads the 720-high frame vertically
        for i,(cx,cy,w,h,cls,score) in enumerate(self.boxes):
            out[0,:4,i]=(cx,cy+top,w,h);out[0,4+cls,i]=score
        return [out]


@unittest.skipIf(numpy is None,'model extra not installed')
class BallModelTests(unittest.TestCase):
    def model(self,boxes,**kwargs):
        from ai_scoring.services.ball_model import BallModel
        return BallModel('unused.onnx',CALIBRATION,session=FakeSession(boxes,**kwargs))
    def test_boxes_are_unpadded_and_one_box_kept_per_ball(self):
        boxes=self.model([(400,300,14,14,0,.9),(401,301,14,14,0,.6),(800,400,14,14,4,.2)]).boxes(numpy.zeros((H,W,3),numpy.uint8))
        self.assertEqual(len(boxes),1)
        label,confidence,x0,y0,x1,y1=boxes[0]
        self.assertEqual((label,confidence),('red',.8999999761581421))
        self.assertAlmostEqual((x0+x1)/2,400,places=3);self.assertAlmostEqual((y0+y1)/2,300,places=3)
    def test_colour_rules_label_boxes_and_model_colour_is_the_fallback(self):
        inventory=self.model([(500,360,14,14,0,.9),(700,360,14,14,2,.9)]).detect(frame([(500,360,PINK)]))
        labels={(x,y):label for label,x,y,_ in inventory.balls}
        self.assertEqual(labels[(500,360)],'pink')    # rules see pink where the model said red
        self.assertEqual(labels[(700,360)],'green')   # plain cloth: rules undecided, model colour kept
        self.assertEqual((inventory.visibility,inventory.reds,inventory.colours),('clear',0,frozenset({'pink','green'})))
    def test_boxes_off_the_table_are_ignored(self):
        inventory=self.model([(640,40,14,14,0,.9),(640,360,14,14,0,.9)]).detect(frame())
        self.assertEqual(inventory.reds,1)
    def test_duplicate_colour_is_uncertain(self):
        inventory=self.model([(500,360,14,14,5,.9),(700,360,14,14,5,.9)]).detect(frame())
        self.assertEqual(inventory.visibility,'uncertain');self.assertIn('duplicate_colour',inventory.causes)
    def test_model_with_unknown_classes_is_rejected(self):
        with self.assertRaises(ValueError):self.model([],names="{0: 'ball'}")


class BallModelConfigTests(unittest.TestCase):
    def test_ball_model_requires_shot_mode_and_onnx(self):
        InferenceConfig(inference_trigger='shot',ball_model='/models/ball.onnx')
        for kwargs in ({'ball_model':'/models/ball.onnx'},{'inference_trigger':'shot','ball_model':'/models/ball.pt'}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):InferenceConfig(**kwargs)


if __name__=='__main__':
    unittest.main()
