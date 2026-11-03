import unittest
from ai_scoring.domain.ball_detection import BallDetector
from ai_scoring.domain.visual_adapter import TimestampedFrame

W,H=768,432
# Colours sampled from the target camera; the pink is pale under its lighting.
CLOTH=(51,194,78)
BALLS={'red':(194,35,15),'yellow':(255,227,18),'green':(0,113,64),'brown':(138,53,16),
       'blue':(0,89,184),'pink':(255,177,131),'black':(4,3,2),'white':(240,240,235)}
COLOURS_ALL=('yellow','green','brown','blue','pink','black')
CALIBRATION={'pockets':[[.02,.2],[.5,.2],[.98,.2],[.98,.8],[.5,.8],[.02,.8]],'pocketRadius':.025}

def table(balls,blocks=()):
    pixels=bytearray(bytes(CLOTH)*(W*H))
    def paint(x0,y0,x1,y1,colour):
        for y in range(y0,y1):
            for x in range(x0,x1):
                if 0<=x<W and 0<=y<H:pixels[(y*W+x)*3:(y*W+x)*3+3]=bytes(colour)
    # Backgrounds (shading, objects) first, balls on top.
    for x0,y0,x1,y1,colour in blocks:paint(x0,y0,x1,y1,colour)
    for label,x,y in balls:
        for dy in range(-4,5):
            for dx in range(-4,5):
                if dx*dx+dy*dy<=16:paint(x+dx,y+dy,x+dx+1,y+dy+1,BALLS[label])
    return TimestampedFrame(bytes(pixels),'2026-10-06T00:00:00+00:00','fixture',0.0,0.0,W,H)

def spread(reds=15,colours=('yellow','green','brown','blue','pink','black')):
    balls=[('red',150+i*25,200) for i in range(reds)]
    balls+=[(colour,200+i*60,300) for i,colour in enumerate(colours)]
    return balls+[('white',600,250)]

class BallDetectionTests(unittest.TestCase):
    def setUp(self):self.detector=BallDetector(CALIBRATION)
    def test_counts_reds_and_each_colour_including_pale_pink_and_dark_green(self):
        inventory=self.detector.detect(table(spread()))
        self.assertEqual((inventory.visibility,inventory.reds),('clear',15))
        self.assertEqual(inventory.colours,frozenset(('yellow','green','brown','blue','pink','black')))
    def test_missing_balls_are_reported_missing(self):
        inventory=self.detector.detect(table(spread(reds=13,colours=('yellow','blue','black'))))
        self.assertEqual((inventory.reds,inventory.colours),(13,frozenset(('yellow','blue','black'))))
    def test_touching_reds_are_counted_by_area(self):
        balls=spread(reds=10)+[('red',500+i*8,150) for i in range(3)]
        self.assertEqual(self.detector.detect(table(balls)).reds,13)
    def test_large_object_inside_cloth_is_occlusion_but_rail_clutter_is_ignored(self):
        arm=self.detector.detect(table(spread(),blocks=((300,230,360,260,(200,160,140)),)))
        self.assertEqual(arm.visibility,'occluded')
        rail=self.detector.detect(table(spread(),blocks=((300,342,380,346,(90,60,40)),)))
        self.assertEqual(rail.visibility,'clear')
    def test_balls_outside_table_or_in_pocket_mouths_are_ignored(self):
        balls=spread()+[('red',384,40),('pink',384,86)]
        inventory=self.detector.detect(table(balls))
        self.assertEqual((inventory.visibility,inventory.reds),('clear',15))
    def test_shaded_cloth_is_not_green_but_dark_green_ball_is(self):
        # Shaded cloth at the far end matches the green ball's colour; only local
        # contrast separates them. Ball colour sampled from recorded live video.
        BALLS['green_dim']=(0,95,40)
        try:
            balls=spread(colours=('yellow','brown','blue','pink','black'))+[('green_dim',500,300)]
            shade=(30,150,40,240,(8,114,34))
            inventory=self.detector.detect(table(balls,blocks=(shade,)))
            self.assertEqual((inventory.visibility,inventory.colours),('clear',frozenset(COLOURS_ALL)))
            missing=self.detector.detect(table(spread(colours=('yellow','brown','blue','pink','black')),blocks=(shade,)))
            self.assertNotIn('green',missing.colours)
        finally:
            del BALLS['green_dim']
    def test_duplicate_colour_is_uncertain(self):
        self.assertEqual(self.detector.detect(table(spread()+[('pink',650,320)])).visibility,'uncertain')
    def test_requires_pocket_calibration(self):
        with self.assertRaises(ValueError):BallDetector({'pockets':[[0,0]]*5,'pocketRadius':.02})

if __name__=='__main__':
    unittest.main()
