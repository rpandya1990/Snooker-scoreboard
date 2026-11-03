"""Colour-blob ball inventory for a fixed camera over green cloth; no model or score knowledge.

Thresholds were tuned on one camera/lighting setup and must be revalidated when either
changes. Anything that does not look like a clean set of separate balls reports
visibility other than clear, so callers abstain.
"""
import math
from dataclasses import dataclass, field

COLOURS=('yellow','green','brown','blue','pink','black')
REFERENCE_WIDTH=768
# Single-ball pixel area at the reference width; scaled by (width/768)^2.
MIN_BALL_AREA,MAX_BALL_AREA=20,160
# Green-ball pixels must be this much darker (green channel) than nearby cloth.
GREEN_CONTRAST,GREEN_RING=1.25,7
# Oversized blobs centred this close to the pocket outline are rail/cushion clutter.
EDGE_MARGIN=15

@dataclass(frozen=True)
class Inventory:
    visibility: str
    reds: int
    colours: frozenset
    balls: tuple = field(default=())   # (label, x, y, area) in pixels, for diagnostics
    causes: tuple = field(default=())

def pixel_label(r,g,b):
    # Candidate only: shaded cloth can match this colour, so detect() also
    # requires the pixel to be clearly darker than the cloth around it.
    if r<15 and 60<g<160 and 0.3*g<b<g: return 'green'
    if g>r+25 and g>=b: return None   # cloth, lit or shaded
    if max(r,g,b)<70: return 'dark'
    if b>r+40 and b>g: return 'blue'
    if r>200 and g>200 and b>190: return 'white'
    if r>200 and g>190 and b<120: return 'yellow'
    if r>200 and g>130 and b>90: return 'pink'
    if r>120 and g<0.42*r and b<0.30*r: return 'brown' if r<170 and g>0.33*r else 'red'
    if r>120 and g<0.6*r: return 'orange'
    return 'other'

def bare_cloth(frame,x,y,radius):
    """Fraction of pixels around (x, y) that look like uncovered cloth."""
    total=cloth=0
    for py in range(round(y-radius),round(y+radius)+1):
        for px in range(round(x-radius),round(x+radius)+1):
            if 0<=px<frame.width and 0<=py<frame.height:
                offset=(py*frame.width+px)*3
                total+=1
                cloth+=pixel_label(frame.data[offset],frame.data[offset+1],frame.data[offset+2]) is None
    return cloth/total if total else 0.0

def table_polygon(pockets,width,height):
    points=[(x*width,y*height) for x,y in pockets]
    cx=sum(x for x,_ in points)/len(points);cy=sum(y for _,y in points)/len(points)
    return sorted(points,key=lambda p:math.atan2(p[1]-cy,p[0]-cx))

def edge_distance(x,y,polygon):
    best=math.inf
    for (ax,ay),(bx,by) in zip(polygon,polygon[1:]+polygon[:1]):
        dx,dy=bx-ax,by-ay
        t=max(0,min(1,((x-ax)*dx+(y-ay)*dy)/(dx*dx+dy*dy)))
        best=min(best,math.hypot(x-ax-t*dx,y-ay-t*dy))
    return best

def _mask(width,height,calibration):
    polygon=table_polygon(calibration['pockets'],width,height)
    radius=calibration['pocketRadius']*width
    edges=list(zip(polygon,polygon[1:]+polygon[:1]))
    rows=[]
    for y in range(height):
        row=[]
        for x in range(width):
            signs={(bx-ax)*(y-ay)-(by-ay)*(x-ax)>0 for (ax,ay),(bx,by) in edges}
            # Pocket mouths and leathers are excluded; the camera is oblique so
            # the exclusion is elliptical.
            if len(signs)==1 and all((x-px)**2+((y-py)*1.6)**2>=radius*radius for px,py in polygon):
                row.append(x)
        rows.append(row)
    return rows

def contrast_label(data,width,height,x,y,ring):
    """Pixel colour label; green candidates must be darker than nearby cloth."""
    offset=(y*width+x)*3
    label=pixel_label(data[offset],data[offset+1],data[offset+2])
    if label=='green':
        around=max(data[((y+dy)*width+x+dx)*3+1] for dx,dy in ((ring,0),(-ring,0),(0,ring),(0,-ring))
            if 0<=x+dx<width and 0<=y+dy<height)
        if around<GREEN_CONTRAST*data[offset+1]: label=None
    return label

def blob_label(votes,w,h,linear):
    """Ball label from pixel votes of one blob or box, or None."""
    votes=dict(votes);votes.pop('other',None);dark=votes.pop('dark',0)
    label=max(votes,key=votes.get) if votes else None
    if label=='orange':
        # Orange is ambiguous between red and brown; its votes join the winner.
        orange=votes.pop('orange')
        label='brown' if votes.get('brown',0)>=votes.get('red',0) else 'red'
        votes[label]=votes.get(label,0)+orange
    if label and votes[label]<4: label=None
    # A few tinted edge pixels on a dark blob are cloth bleed, not a colour.
    if label and dark>=12 and dark>3*votes[label]: label=None
    if label=='green' and max(w,h)>3*min(w,h): label=None   # cushion lines
    if label is None and dark>=12 and max(w,h)<=14*linear and abs(w-h)<=5*linear:
        label='black'
    return label

def box_label(frame,x0,y0,x1,y1):
    """Colour of a ball inside a detector box (pixel coordinates), using the same rules."""
    ring=max(1,round(GREEN_RING*frame.width/REFERENCE_WIDTH))
    votes={}
    xs=range(max(0,int(x0)),min(frame.width,int(math.ceil(x1))+1))
    ys=range(max(0,int(y0)),min(frame.height,int(math.ceil(y1))+1))
    for y in ys:
        for x in xs:
            label=contrast_label(frame.data,frame.width,frame.height,x,y,ring)
            if label: votes[label]=votes.get(label,0)+1
    return blob_label(votes,len(xs),len(ys),frame.width/REFERENCE_WIDTH),votes

class BallDetector:
    def __init__(self,calibration):
        pockets=calibration.get('pockets') if isinstance(calibration,dict) else None
        radius=calibration.get('pocketRadius') if isinstance(calibration,dict) else None
        if not isinstance(pockets,list) or len(pockets)!=6 or type(radius) not in (int,float) or not 0<radius<=.25:
            raise ValueError('ball detection requires six calibrated pockets and a pocket radius')
        self.calibration={'pockets':[list(point) for point in pockets],'pocketRadius':radius}
        self._masks={}

    def detect(self,frame):
        width,height=frame.width,frame.height
        if frame.pixel_format!='rgb24' or len(frame.data)!=width*height*3:
            raise ValueError('invalid RGB frame')
        if (width,height) not in self._masks:
            self._masks[(width,height)]=_mask(width,height,self.calibration)
        scale=(width/REFERENCE_WIDTH)**2
        low,high=MIN_BALL_AREA*scale,MAX_BALL_AREA*scale
        data=frame.data
        ring=max(1,round(GREEN_RING*width/REFERENCE_WIDTH))
        labels={}
        for y,row in enumerate(self._masks[(width,height)]):
            base=y*width
            for x in row:
                label=contrast_label(data,width,height,x,y,ring)
                if label: labels[(x,y)]=label
        blobs=[]
        seen=set()
        for start in labels:
            if start in seen: continue
            seen.add(start);stack=[start];pixels=[]
            while stack:
                point=stack.pop();pixels.append(point)
                for dx in (-1,0,1):
                    for dy in (-1,0,1):
                        near=(point[0]+dx,point[1]+dy)
                        if near in labels and near not in seen:
                            seen.add(near);stack.append(near)
            if len(pixels)<low: continue
            votes={}
            for point in pixels: votes[labels[point]]=votes.get(labels[point],0)+1
            xs=[x for x,_ in pixels];ys=[y for _,y in pixels]
            blobs.append({'area':len(pixels),'x':sum(xs)/len(xs),'y':sum(ys)/len(ys),
                'w':max(xs)-min(xs)+1,'h':max(ys)-min(ys)+1,'votes':votes})
        return self._inventory(blobs,high,math.sqrt(scale),table_polygon(self.calibration['pockets'],width,height))

    def _inventory(self,blobs,high,linear,polygon):
        causes=set();balls=[];reds=0;colours=[]
        singles=[]
        for blob in blobs:
            label=blob['label']=blob_label(blob['votes'],blob['w'],blob['h'],linear)
            if label=='red' and blob['area']<=high: singles.append(blob['area'])
        typical=sorted(singles)[len(singles)//2] if singles else 75*linear*linear
        for blob in blobs:
            label=blob['label']
            if label=='red' and blob['area']>=1.6*typical:
                # Touching reds (e.g. the opening pack) are counted by area.
                estimate=blob['area']/typical
                if abs(estimate-round(estimate))>.3: causes.add('red_cluster_count_uncertain')
                reds+=round(estimate)
                balls.append(('red',round(blob['x']),round(blob['y']),blob['area']))
                continue
            if blob['area']>high:
                # Any other oversized blob is a person, cue or object over the
                # cloth, unless it sits on the rail at the cloth edge.
                if edge_distance(blob['x'],blob['y'],polygon)>EDGE_MARGIN*linear:
                    causes.add('large_object_on_table')
                continue
            if label is None: continue
            balls.append((label,round(blob['x']),round(blob['y']),blob['area']))
            if label=='red': reds+=1
            elif label in COLOURS: colours.append(label)
        if len(colours)!=len(set(colours)): causes.add('duplicate_colour')
        if reds>15: causes.add('too_many_reds')
        if causes: visibility='occluded' if 'large_object_on_table' in causes else 'uncertain'
        else: visibility='clear'
        return Inventory(visibility,min(reds,15),frozenset(colours),tuple(balls),tuple(sorted(causes)))
