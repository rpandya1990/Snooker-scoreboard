from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

class Mode(StrEnum):
    OFF = 'off'
    DRY_RUN = 'dry-run'
    ASSIST = 'assist'

@dataclass(frozen=True)
class Config:
    data_directory: Path
    mode: Mode = Mode.OFF
    camera_url: str | None = field(default=None, repr=False, compare=False)
    recording: 'RecordingConfig' = field(default_factory=lambda: RecordingConfig())
    recorded_source: Path | None = field(default=None, repr=False, compare=False)
    inference: "InferenceConfig" = field(default_factory=lambda: InferenceConfig())
    # Seconds between extracted training frames; None disables dataset building.
    dataset_every_seconds: float | None = None

    def __post_init__(self):
        object.__setattr__(self, 'mode', Mode(self.mode))
        object.__setattr__(self, 'data_directory', Path(self.data_directory))
        if self.inference.enabled and self.mode == Mode.OFF:
            raise ValueError('inference requires active observer mode')
        if self.recording.enabled and self.mode == Mode.OFF:
            raise ValueError('recording requires active observer mode')
        if self.dataset_every_seconds is not None and (not self.recording.enabled or not self.inference.calibration):
            raise ValueError('dataset building requires recording and calibration')

@dataclass(frozen=True)
class RecordingConfig:
    enabled: bool = False
    retention_seconds: float | None = None
    total_bytes: int | None = None
    min_free_bytes: int | None = None
    segment_seconds: float | None = None

    def __post_init__(self):
        import math
        if type(self.enabled) is not bool:
            raise ValueError('recording enabled must be boolean')
        if self.enabled:
            for name in ('retention_seconds','total_bytes','min_free_bytes','segment_seconds'):
                value=getattr(self,name)
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value <= 0:
                    raise ValueError('recording requires explicit positive budgets and segment duration')
            if type(self.total_bytes) is not int or type(self.min_free_bytes) is not int:
                raise ValueError('recording byte budgets must be integers')

@dataclass(frozen=True)
class InferenceConfig:
    enabled: bool = False
    model: str | None = None
    endpoint: str = 'http://127.0.0.1:11434'
    sample_fps: float = 1.0
    inference_trigger: str = "periodic"
    stable_seconds: float = .5
    # Exported ONNX ball detector for shot mode; None keeps the colour rules.
    ball_model: str | None = None
    save_inference_frames: bool = False
    width: int = 768
    height: int = 432
    roi: tuple[float,float,float,float] | None = None
    capture_timeout_seconds: float = 10.0
    job_freshness_seconds: float = 5.0
    queue_size: int = 2
    prediction_ttl_seconds: float = 3.0
    max_frame_gap_seconds: float = 2.0
    min_confidence: float = .95
    model_timeout_seconds: float = 30.0
    window_frames: int = 3
    capture_uncertainty_ms: float | None = None
    max_capture_uncertainty_ms: float = 500.0
    calibration: dict | None = field(default=None,repr=False,compare=False)

    def __post_init__(self):
        import math
        from urllib.parse import urlsplit
        import ipaddress
        if type(self.enabled) is not bool:
            raise ValueError('inference enabled must be boolean')
        if self.inference_trigger not in ('periodic','shot'):
            raise ValueError('inference trigger must be periodic or shot')
        # Shot mode reads balls with local colour detection; only periodic mode uses a model.
        if self.enabled and self.inference_trigger=='periodic' and (not isinstance(self.model,str) or not self.model.strip()):
            raise ValueError('enabled periodic inference requires explicit model')
        try:
            parsed=urlsplit(self.endpoint)
            address=ipaddress.ip_address(parsed.hostname or '')
            port=parsed.port
            if parsed.scheme != 'http' or not address.is_loopback or not port or not 0 < port < 65536 or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
                raise ValueError()
        except (ValueError,TypeError):
            raise ValueError('inference endpoint must be numeric loopback HTTP with explicit port') from None
        for name in ('sample_fps','capture_timeout_seconds','job_freshness_seconds','prediction_ttl_seconds','max_frame_gap_seconds','min_confidence','model_timeout_seconds','max_capture_uncertainty_ms','stable_seconds'):
            value=getattr(self,name)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value <= 0:
                raise ValueError('inference limits must be positive finite numbers')
        if self.ball_model is not None and (self.inference_trigger!='shot' or not isinstance(self.ball_model,str) or not self.ball_model.endswith('.onnx')):
            raise ValueError('ball model requires shot mode and an .onnx file')
        if self.stable_seconds>10:
            raise ValueError('stable period must be at most ten seconds')
        if self.sample_fps > 30 or self.min_confidence > 1:
            raise ValueError('invalid sampling or confidence')
        for name in ('width','height','queue_size','window_frames'):
            if type(getattr(self,name)) is not int or getattr(self,name) <= 0:
                raise ValueError('inference sizes must be positive integers')
        if self.width*self.height > 4194304 or self.queue_size > 16 or self.window_frames < 3 or self.window_frames > 8:
            raise ValueError('inference allocation exceeds limits')
        if self.capture_uncertainty_ms is not None and (isinstance(self.capture_uncertainty_ms,bool) or not isinstance(self.capture_uncertainty_ms,(int,float)) or not math.isfinite(self.capture_uncertainty_ms) or self.capture_uncertainty_ms <= 0):
            raise ValueError('capture uncertainty requires a positive measured bound')
        if self.roi is not None:
            if len(self.roi)!=4 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in self.roi):
                raise ValueError('ROI requires four normalized finite numbers')
            x,y,width,height=self.roi
            if x<0 or y<0 or width<=0 or height<=0 or x+width>1 or y+height>1:
                raise ValueError('ROI outside source')
