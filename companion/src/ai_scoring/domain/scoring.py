"""Clean-play rules; visual interpretation and foul detection are outside this module."""
from dataclasses import dataclass
from enum import StrEnum

class Ball(StrEnum):
    RED = 'red'
    YELLOW = 'yellow'
    GREEN = 'green'
    BROWN = 'brown'
    BLUE = 'blue'
    PINK = 'pink'
    BLACK = 'black'

VALUES = {ball: index for index, ball in enumerate(Ball, 1)}
CLEARANCE = tuple(Ball)[1:]

@dataclass(frozen=True)
class PotObservation:
    observation_id: str
    ball: Ball
    timestamp: str
    count: int = 1
    kind: str = 'pot'

class SnookerAccumulator:
    def __init__(self, reds=15):
        if type(reds) is not int or not 0 <= reds <= 15:
            raise ValueError('invalid red count')
        self.reds = reds
        self.points = 0
        self.clearance_index = 0
        self.ball_on = 'red' if reds else 'yellow'
        self.pending_respots = set()
        self.quality_reasons = set()

    def pot(self, ball, count=1):
        ball = Ball(ball)
        if type(count) is not int or count < 1 or (ball != Ball.RED and count != 1):
            raise ValueError('invalid pot count')
        valid = ((self.ball_on == 'red' and ball == Ball.RED and count <= self.reds)
                 or (self.ball_on == 'colour' and ball != Ball.RED)
                 or (self.ball_on == ball.value and ball != Ball.RED))
        if not valid or ball in self.pending_respots:
            self.quality_reasons.add('unsupported_sequence')
            return False
        self.points += VALUES[ball] * count
        if ball == Ball.RED:
            self.reds -= count
            self.ball_on = 'colour'
        elif self.ball_on == 'colour':
            self.pending_respots.add(ball)
            self.ball_on = 'red' if self.reds else 'yellow'
        else:
            self.clearance_index += 1
            self.ball_on = CLEARANCE[self.clearance_index].value if self.clearance_index < 6 else 'complete'
        return True

    def respot(self, ball):
        self.pending_respots.discard(Ball(ball))

    def new_visit(self):
        self.points = 0
        self.ball_on = 'red' if self.reds else (CLEARANCE[self.clearance_index].value if self.clearance_index < 6 else 'complete')
