import unittest
from ai_scoring.domain.scoring import SnookerAccumulator
class RulesTests(unittest.TestCase):
    def test_clean_break(self):
        rules = SnookerAccumulator()
        for ball in ('red', 'black', 'red', 'pink'):
            rules.pot(ball)
        self.assertEqual(rules.points, 15)

    def test_multiple_reds_and_respot(self):
        rules = SnookerAccumulator()
        rules.pot('red', 2)
        rules.pot('black')
        rules.respot('black')
        self.assertEqual(rules.points, 9)
        self.assertEqual(rules.reds, 13)

    def test_last_red_and_clearance(self):
        rules = SnookerAccumulator(1)
        rules.pot('red')
        rules.pot('black')
        rules.respot('black')
        for ball in ('yellow', 'green', 'brown', 'blue', 'pink', 'black'):
            self.assertTrue(rules.pot(ball))
        self.assertEqual(rules.points, 35)
        self.assertEqual(rules.ball_on, 'complete')

    def test_new_visit_preserves_physical_state(self):
        rules = SnookerAccumulator(2)
        rules.pot('red')
        rules.new_visit()
        self.assertEqual(rules.ball_on, 'red')
        rules.pot('red')
        rules.new_visit()
        self.assertEqual(rules.ball_on, 'yellow')
        rules.pot('yellow')
        rules.new_visit()
        self.assertEqual(rules.ball_on, 'green')
        self.assertEqual(rules.points, 0)

    def test_unsupported_sequence_suppresses(self):
        rules = SnookerAccumulator()
        self.assertFalse(rules.pot('black'))
        self.assertIn('unsupported_sequence', rules.quality_reasons)

    def test_brown_next_after_yellow_green_across_visits(self):
        rules=SnookerAccumulator(1)
        rules.pot('red')
        rules.pot('black')
        rules.respot('black')
        rules.pot('yellow')
        rules.new_visit()
        self.assertEqual(rules.ball_on,'green')
        self.assertTrue(rules.pot('green'))
        rules.new_visit()
        self.assertEqual(rules.ball_on,'brown')
        self.assertEqual(rules.reds,0)
        self.assertEqual(rules.points,0)
        self.assertTrue(rules.pot('brown'))
        self.assertEqual(rules.points,4)
        self.assertEqual(rules.ball_on,'blue')
