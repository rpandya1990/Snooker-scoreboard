"""Authenticated API bootstrap with opt-in recording and local visual inference."""
import argparse
import os
import ssl
from http.server import ThreadingHTTPServer
from pathlib import Path
from ai_scoring.activity.http import handler_for
from ai_scoring.config import Config, Mode, RecordingConfig, InferenceConfig
from ai_scoring.services.sessions import SessionManager

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-directory', type=Path, required=True)
    parser.add_argument('--mode', choices=list(Mode), default='off')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8443)
    parser.add_argument('--cert', type=Path)
    parser.add_argument('--key', type=Path)
    parser.add_argument('--inference-enabled', action='store_true')
    parser.add_argument('--model')
    parser.add_argument('--ollama-endpoint', default='http://127.0.0.1:11434')
    parser.add_argument('--sample-fps', type=float, default=1.0)
    parser.add_argument('--inference-width', type=int, default=768)
    parser.add_argument('--inference-height', type=int, default=432)
    parser.add_argument('--capture-timeout-seconds', type=float, default=10)
    parser.add_argument('--job-freshness-seconds', type=float, default=5)
    parser.add_argument('--inference-queue-size', type=int, default=2)
    parser.add_argument('--prediction-ttl-seconds', type=float, default=3)
    parser.add_argument('--max-frame-gap-seconds', type=float, default=2)
    parser.add_argument('--model-timeout-seconds', type=float, default=30)
    parser.add_argument('--window-frames', type=int, default=3)
    parser.add_argument('--min-confidence', type=float, default=.95)
    parser.add_argument('--capture-uncertainty-ms', type=float, help='Measured exposure mapping bound; absent means unavailable diagnostics')
    parser.add_argument('--max-capture-uncertainty-ms', type=float, default=500)
    parser.add_argument('--roi', type=float, nargs=4, metavar=('X','Y','WIDTH','HEIGHT'))
    parser.add_argument('--calibration-file', type=Path, help='Protected local JSON table/pocket calibration')
    parser.add_argument('--recording-enabled', action='store_true')
    parser.add_argument('--retention-seconds', type=float)
    parser.add_argument('--recording-total-bytes', type=int)
    parser.add_argument('--recording-min-free-bytes', type=int)
    parser.add_argument('--segment-seconds', type=float)
    parser.add_argument('--recorded-source', type=Path, help='Explicit local-file recording input for development; no camera')
    args = parser.parse_args(argv)
    if args.mode == Mode.OFF:
        print('Observer off: no service or camera processing started.')
        return
    token = os.environ.get('AI_SCORING_API_TOKEN')
    if not token or len(token) < 16:
        parser.error('set AI_SCORING_API_TOKEN to a protected token of at least 16 characters')
    if bool(args.cert) != bool(args.key):
        parser.error('optional HTTPS requires both --cert and --key')
    try:
        recording=RecordingConfig(args.recording_enabled,args.retention_seconds,args.recording_total_bytes,args.recording_min_free_bytes,args.segment_seconds)
        import json
        calibration=json.loads(args.calibration_file.read_text()) if args.calibration_file else None
        inference=InferenceConfig(enabled=args.inference_enabled,model=args.model,endpoint=args.ollama_endpoint,
            sample_fps=args.sample_fps,width=args.inference_width,height=args.inference_height,roi=tuple(args.roi) if args.roi else None,
            capture_timeout_seconds=args.capture_timeout_seconds,job_freshness_seconds=args.job_freshness_seconds,queue_size=args.inference_queue_size,
            prediction_ttl_seconds=args.prediction_ttl_seconds,max_frame_gap_seconds=args.max_frame_gap_seconds,
            model_timeout_seconds=args.model_timeout_seconds,window_frames=args.window_frames,min_confidence=args.min_confidence,
            capture_uncertainty_ms=args.capture_uncertainty_ms,max_capture_uncertainty_ms=args.max_capture_uncertainty_ms,calibration=calibration)
        config = Config(args.data_directory, Mode(args.mode),
            camera_url=os.environ.get("AI_SCORING_CAMERA_URL"),recording=recording,recorded_source=args.recorded_source,inference=inference)
    except (ValueError,OSError):
        parser.error("invalid recording/inference configuration; check explicit model, budgets, local endpoint and calibration")
    context=None
    if args.cert:
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version=ssl.TLSVersion.TLSv1_2
        try:
            context.load_cert_chain(args.cert,args.key)
        except (OSError,ssl.SSLError):
            parser.error('unable to load optional HTTPS certificate/key')
    manager = SessionManager(config)
    server=None
    try:
        server=ThreadingHTTPServer((args.host,args.port),handler_for(manager,token))
        if context:
            server.socket=context.wrap_socket(server.socket,server_side=True)
    except Exception:
        if server:
            server.server_close()
        manager.close()
        raise
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        manager.close()

if __name__ == '__main__':
    main()
