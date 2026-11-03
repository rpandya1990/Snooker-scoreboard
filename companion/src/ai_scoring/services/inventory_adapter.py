"""Continuous table inventory tracking with local colour-blob ball detection; no model, no totals.

Every sampled frame is read. Frames with a person, cue or object over the cloth are
skipped. A new inventory is accepted only after it is read identically on clear frames
for a stable period; the difference between consecutive accepted inventories becomes
pot/respot observations for the rules accumulator. Impossible changes abstain.
"""
import hashlib
import json
from ai_scoring.domain.ball_detection import BallDetector, bare_cloth, REFERENCE_WIDTH
from ai_scoring.domain.scoring import Ball, PotObservation, interpretable_table as interpretable
from ai_scoring.domain.visual_adapter import VisualResult, TimestampedFrame
from ai_scoring.services.ollama_adapter import rgb_png

DETECTOR_VERSION='colour-blob-v1'
COLOURS=tuple(ball.value for ball in Ball if ball!=Ball.RED)
MARKERS={'red':(255,255,255),'white':(255,0,255),'black':(255,255,255)}

# track() events
UNCLEAR,STEADY,DIVERGING,SETTLING,BASELINE,CHANGE='unclear','steady','diverging','settling','baseline','change'


class InventoryVisualAdapter:
    def __init__(self,settings,reader=None):
        self.settings=json.loads(json.dumps(settings,allow_nan=False))
        self.stable_seconds=self.settings.get('stableSeconds',.5)
        if type(self.stable_seconds) not in (int,float) or not 0<self.stable_seconds<=10:
            raise ValueError('bounded stable period required')
        model=self.settings.get('ballModel')
        if reader is None and model:
            from ai_scoring.services.ball_model import BallModel
            reader=BallModel(model,self.settings.get('calibration') or {}).detect
        self.reader=reader or BallDetector(self.settings.get('calibration') or {}).detect
        self.metadata={'adapterVersion':'local-colour-tracking-v1','modelVersion':__import__('os').path.basename(model) if model else DETECTOR_VERSION,'promptVersion':'none',
            'sampling':{'stableSeconds':self.stable_seconds},'calibration':self.settings.get('calibration'),'externalInference':False}
        self.debug_directory=self.settings.get('debugFrameDirectory')
        self.closed=False
        self.frame_id=None
        self.state=None
        self.discontinuous=False
        self.candidate=None   # (reds, colours, first frame, first inventory)
        self.balls=()         # ball positions of the accepted inventory
        self.last_baseline_diagnostic=None

    def track(self,frame,context):
        """Feed one chronological sampled frame; returns (event, VisualResult or None)."""
        if self.closed: return UNCLEAR,None
        if context.frame_id!=self.frame_id:
            self.frame_id=context.frame_id;self.state=None;self.discontinuous=False;self.candidate=None
        try:
            reading=self.reader(frame)
        except Exception:
            self.candidate=None
            return UNCLEAR,None
        if reading.visibility!='clear':
            # Hidden balls cannot confirm or refute a change; restart the streak.
            self.candidate=None
            return UNCLEAR,None
        key=(reading.reds,reading.colours)
        if self.state is not None and key==self.state:
            self.candidate=None
            return STEADY,None
        if self.candidate is None or self.candidate[:2]!=key:
            self.candidate=(*key,frame,reading)
            return DIVERGING,None
        first,first_reading=self.candidate[2],self.candidate[3]
        if frame.media_time-first.media_time<self.stable_seconds:
            return SETTLING,None
        self.candidate=None
        if self.state is None:
            if not interpretable(*key):
                self.last_baseline_diagnostic={'reds':reading.reds,'coloursPresent':sorted(reading.colours),'confidence':1.0,'settled':True,
                    'phase':'unknown','visibility':'clear','witnessCount':2,'minimumConfidence':1.0,'baselineFrameReferenceValid':True,
                    'baselineAccepted':False,'validationCauses':['missing_colours']}
                return SETTLING,None
            self.state=key;self.balls=reading.balls
            self._save_debug(((first,first_reading),(frame,reading)))
            return BASELINE,VisualResult(baseline_reds=reading.reds,baseline_colours=tuple(sorted(reading.colours)),processed_through=frame.timestamp)
        if self.discontinuous:
            return CHANGE,VisualResult(quality_reasons=('capture_discontinuity',),processed_through=frame.timestamp)
        if not self._vanished_onto_cloth(frame,reading):
            # A ball "gone" from under a person, cue or shadow is hidden, not potted.
            return UNCLEAR,None
        self._save_debug(((first,first_reading),(frame,reading)))
        result=self._diff(key,first.timestamp,frame.timestamp,context)
        # Abstentions already disable the frame; adopt the reading so the same
        # impossible change is not re-reported every stable period.
        self.state=key;self.balls=reading.balls
        return CHANGE,result

    def _vanished_onto_cloth(self,frame,reading):
        scale=frame.width/REFERENCE_WIDTH
        near,radius=8*scale,4*scale
        for label,x,y,_ in self.balls:
            if label=='white': continue
            if any(other==label and (ox-x)**2+(oy-y)**2<=near*near for other,ox,oy,_ in reading.balls): continue
            if bare_cloth(frame,x,y,radius)<.7: return False
        return True

    def _diff(self,key,observed_at,through,context):
        reds,colours=self.state
        new_reds,new_colours=key
        removed,added=colours-new_colours,new_colours-colours
        if new_reds>reds: return VisualResult(quality_reasons=('inventory_reds_increased',),processed_through=through)
        # Reds then one colour can merge between clear frames (same points in either
        # order; the rules accumulator checks sequence). Respots are separate hand
        # motion, and two missing colours imply a skipped respot.
        if (added and (new_reds<reds or removed)) or len(removed)>1:
            return VisualResult(quality_reasons=('inventory_change_ambiguous',),processed_through=through)
        def observation(kind,ball,count=1):
            identity=hashlib.sha256(json.dumps([context.frame_id,observed_at,kind,ball],sort_keys=True).encode()).hexdigest()
            return PotObservation(identity,Ball(ball),observed_at,count,kind)
        observations=[]
        if new_reds<reds: observations.append(observation('pot','red',reds-new_reds))
        observations+=[observation('pot',ball) for ball in removed]
        observations+=[observation('respot',ball) for ball in COLOURS if ball in added]
        return VisualResult(tuple(observations),processed_through=through)

    def _save_debug(self,pairs):
        # Opt-in local diagnostics of accepted transitions only; failures never affect scoring.
        if not self.debug_directory: return
        import os
        from pathlib import Path
        try:
            folder=Path(self.debug_directory)
            folder.mkdir(mode=0o700,parents=True,exist_ok=True)
            for frame,inventory in pairs:
                pixels=bytearray(frame.data)
                for label,x,y,_ in inventory.balls:
                    colour=bytes(MARKERS.get(label,(0,0,0)))
                    for step in range(-7,8):
                        for px,py in ((x+step,y-7),(x+step,y+7),(x-7,y+step),(x+7,y+step)):
                            if 0<=px<frame.width and 0<=py<frame.height:
                                offset=(py*frame.width+px)*3;pixels[offset:offset+3]=colour
                png=rgb_png(TimestampedFrame(bytes(pixels),frame.timestamp,frame.asset_id,frame.media_time,frame.utc_uncertainty_ms,frame.width,frame.height),frame.width)
                record={'timestamp':frame.timestamp,'mediaTime':frame.media_time,'visibility':inventory.visibility,'reds':inventory.reds,
                    'colours':sorted(inventory.colours),'causes':list(inventory.causes),'balls':[list(ball) for ball in inventory.balls]}
                stem=hashlib.sha256(frame.timestamp.encode()).hexdigest()[:8]
                name=frame.timestamp.replace(':','').replace('+0000','Z')[:22]+'-'+stem
                for suffix,data in (('.png',png),('.json',json.dumps(record,sort_keys=True).encode())):
                    descriptor=os.open(folder/(name+suffix),os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
                    with os.fdopen(descriptor,'wb') as handle:handle.write(data)
        except Exception:
            pass

    def reset_baseline_attempt(self):
        # Called only while the service baseline is unconfirmed: a fresh
        # interpretable reading re-establishes physical state, so gaps clear.
        self.state=None;self.balls=();self.discontinuous=False;self.candidate=None;self.last_baseline_diagnostic=None

    def reset_epoch(self):
        # Unseen capture may hide a pot/respot pair; accepted state is unusable.
        self.discontinuous=self.state is not None
        self.candidate=None

    def close(self):
        self.closed=True


def create(settings):
    return InventoryVisualAdapter(settings)
