"""Transport translation only; no camera or scoring rules here."""
import hmac
import json
from http.server import BaseHTTPRequestHandler
from ai_scoring.dao.jsonl import IdentityConflict, StorageFault
from ai_scoring.services.scoring import EventConflict

MAX_BODY = 64 * 1024

def handler_for(manager, bearer_token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # Requests/headers/payloads can contain secrets; retain no default access log.
            pass

        def _reply(self, status, payload):
            encoded = json.dumps(payload, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _handle(self, method):
            expected = 'Bearer ' + bearer_token
            if not hmac.compare_digest(self.headers.get('Authorization', '').encode('utf-8'), expected.encode('utf-8')):
                return self._reply(401, {'error': 'unauthorized'})
            try:
                parts = self.path.split('?')[0].strip('/').split('/')
                payload = {}
                if method == 'POST':
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= MAX_BODY:
                        return self._reply(413, {'error': 'invalid_body_size'})
                    payload = json.loads(self.rfile.read(length))
                    if not isinstance(payload, dict):
                        raise ValueError('object required')
                if parts == ['v1', 'sessions'] and method == 'POST':
                    return self._reply(200, manager.open(payload))
                if len(parts) == 4 and parts[:2] == ['v1', 'sessions']:
                    session_id, action = parts[2:]
                    if method == 'POST' and action == 'heartbeat':
                        return self._reply(200, manager.heartbeat(session_id))
                    if method == 'POST' and action == 'events':
                        return self._reply(200, manager.event(session_id, payload))
                    if method == 'GET' and action == 'prediction':
                        return self._reply(200, manager.get(session_id).latest_prediction())
                return self._reply(404, {'error': 'not_found'})
            except (IdentityConflict, EventConflict):
                return self._reply(409, {'error': 'state_conflict'})
            except (ValueError, KeyError, TypeError, UnicodeError):
                return self._reply(400, {'error': 'invalid_request'})
            except (StorageFault, OSError):
                return self._reply(503, {'error': 'storage_unavailable'})

        def do_POST(self):
            self._handle('POST')
        def do_GET(self):
            self._handle('GET')
    return Handler
