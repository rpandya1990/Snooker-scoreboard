import json
import os
import tempfile
import unittest
from ai_scoring.domain.ball_detection import Inventory
from ai_scoring.domain.visual_adapter import TimestampedFrame, BoundaryContext
from ai_scoring.services.inventory_adapter import InventoryVisualAdapter, COLOURS

def context(physical='frame',run='run'):
    return BoundaryContext(physical,run,'2026-10-06T00:00:00+00:00','2026-10-06T00:00:00+00:00','2026-10-06T00:10:00+00:00')
def reading(reds=15,colours=COLOURS,visibility='clear'):
    return Inventory(visibility,reds,frozenset(colours),(('red',1,1,40),))

class InventoryAdapterTests(unittest.TestCase):
    def setUp(self):
        self.queue=[]
        def reader(frame):
            item=self.queue.pop(0)
            if isinstance(item,Exception):raise item
            return item
        self.reader=reader
        self.adapter=InventoryVisualAdapter({'stableSeconds':.5},reader=reader)
        self.second=0.
    def frame(self):
        self.second=round(self.second+.1,3)
        minutes,seconds=divmod(self.second,60)
        return TimestampedFrame(b'\x10\x20\x30'*16,f'2026-10-06T00:{int(minutes):02}:{seconds:06.3f}+00:00','video',self.second,0,4,4,'rgb24')
    def hold(self,item,seconds=.7,ctx=None):
        """Feed one reading for a duration; returns every (event, result)."""
        events=[]
        for _ in range(round(seconds*10)):
            self.queue.append(item)
            events.append(self.adapter.track(self.frame(),ctx or context()))
        return events
    def outcome(self,item,seconds=.7,ctx=None):
        results=[result for _,result in self.hold(item,seconds,ctx) if result is not None]
        self.assertLessEqual(len(results),1)
        return results[0] if results else None
    def ready(self,reds=15,colours=COLOURS):
        result=self.outcome(reading(reds,colours))
        self.assertEqual(result.baseline_reds,reds)
        self.assertEqual(set(result.baseline_colours),set(colours))
    def test_change_needs_stable_identical_clear_frames(self):
        events=[event for event,_ in self.hold(reading())]
        self.assertEqual(events[:2],['diverging','settling'])
        self.assertEqual(events[5],'baseline')
        self.assertEqual(events[6],'steady')
        self.assertEqual(self.adapter.metadata['externalInference'],False)
    def test_unclear_or_flickering_frames_restart_the_streak(self):
        self.ready()
        for _ in range(4):
            self.assertIsNone(self.outcome(reading(reds=14),.3))
            self.assertIsNone(self.outcome(reading(visibility='occluded'),.1))
        self.assertIsNone(self.outcome(reading(),.3))
        self.assertEqual(self.outcome(reading(reds=14)).observations[0].count,1)
    def test_midframe_and_clearance_tables_are_accepted_baselines(self):
        self.ready(reds=9)
        self.adapter=InventoryVisualAdapter({},reader=self.reader)
        self.ready(reds=0,colours=('blue','pink','black'))
    def test_uninterpretable_start_is_reported_not_accepted(self):
        self.assertIsNone(self.outcome(reading(reds=13,colours=COLOURS[:-1])))
        self.assertEqual(self.adapter.last_baseline_diagnostic['validationCauses'],['missing_colours'])
        self.assertIsNone(self.outcome(reading(reds=0,colours=('yellow','pink','black'))))
        self.ready()
    def test_red_and_colour_pots_then_respot_become_ordered_observations(self):
        self.ready()
        reds=self.outcome(reading(reds=13))
        self.assertEqual([(o.kind,o.ball.value,o.count) for o in reds.observations],[('pot','red',2)])
        black=self.outcome(reading(reds=13,colours=COLOURS[:-1]))
        self.assertEqual([(o.kind,o.ball.value) for o in black.observations],[('pot','black')])
        respot=self.outcome(reading(reds=13))
        self.assertEqual([(o.kind,o.ball.value) for o in respot.observations],[('respot','black')])
        self.assertIsNone(self.outcome(reading(reds=13)))
    def test_red_and_colour_between_clear_frames_are_both_observed(self):
        self.ready()
        result=self.outcome(reading(reds=14,colours=[c for c in COLOURS if c!='green']))
        self.assertEqual([(o.kind,o.ball.value,o.count) for o in result.observations],[('pot','red',1),('pot','green',1)])
        self.assertEqual(self.outcome(reading(reds=13)).quality_reasons,('inventory_change_ambiguous',))
    def test_impossible_change_abstains_once_then_tracks_from_the_new_reading(self):
        self.ready()
        result=self.outcome(reading(reds=14,colours=COLOURS[:-2]))
        self.assertEqual((result.observations,result.quality_reasons),((),('inventory_change_ambiguous',)))
        self.assertIsNone(self.outcome(reading(reds=14,colours=COLOURS[:-2]),2))
        self.assertEqual(self.outcome(reading(reds=15)).quality_reasons,('inventory_reds_increased',))
        self.assertIsNone(self.outcome(reading(reds=15),2))
    def test_ball_hidden_under_an_object_is_not_a_pot(self):
        cloth=bytes((51,194,78))*16;arm=bytes((90,70,60))*16
        def at(data):
            self.second=round(self.second+.1,3)
            return TimestampedFrame(data,f'2026-10-06T00:00:{self.second:06.3f}+00:00','video',self.second,0,4,4,'rgb24')
        def hold(item,data,seconds=.7):
            results=[]
            for _ in range(round(seconds*10)):
                self.queue.append(item);results.append(self.adapter.track(at(data),context()))
            return [result for _,result in results if result is not None]
        start=Inventory('clear',15,frozenset(COLOURS),(('red',1,1,40),('blue',2,2,40)))
        self.assertEqual(hold(start,cloth)[0].baseline_reds,15)
        moved_red=Inventory('clear',14,frozenset(COLOURS),(('blue',2,2,40),))
        self.assertEqual(hold(moved_red,arm),[])
        self.assertEqual([(o.kind,o.ball.value) for o in hold(moved_red,cloth)[0].observations],[('pot','red')])
    def test_discontinuity_blocks_until_new_baseline_attempt_or_frame(self):
        self.ready()
        self.adapter.reset_epoch()
        self.assertEqual(self.outcome(reading(reds=14)).quality_reasons,('capture_discontinuity',))
        self.adapter.reset_baseline_attempt()
        self.ready()
        self.adapter.reset_epoch()
        self.assertEqual(self.outcome(reading(),ctx=context(physical='next')).baseline_reds,15)
    def test_reader_failure_is_unclear(self):
        self.ready()
        self.assertIsNone(self.outcome(ValueError('bad frame'),.3))
        self.assertEqual(self.outcome(reading(reds=14)).observations[0].count,1)
    def test_optional_debug_frames_store_accepted_transitions_privately(self):
        with tempfile.TemporaryDirectory() as root:
            folder=os.path.join(root,'inference-frames')
            self.adapter=InventoryVisualAdapter({'debugFrameDirectory':folder},reader=self.reader)
            self.ready()
            self.hold(reading(),1)
            names=sorted(os.listdir(folder))
            self.assertEqual(len(names),4)
            self.assertEqual(os.stat(folder).st_mode&0o777,0o700)
            record=json.load(open(os.path.join(folder,[n for n in names if n.endswith('.json')][0])))
            self.assertEqual((record['reds'],record['visibility']),(15,'clear'))
            self.assertTrue(all(os.stat(os.path.join(folder,n)).st_mode&0o777==0o600 for n in names))

if __name__=='__main__':
    unittest.main()
