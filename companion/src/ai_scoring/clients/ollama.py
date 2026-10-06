"""Local numeric-loopback Ollama only. No proxies, redirects or model pulls."""
import ipaddress
import json
import re
import threading
import socket
import time
from urllib import request, error
from urllib.parse import urlsplit

class OllamaError(ValueError):
    pass

class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise OllamaError('local model redirect refused')

class OllamaClient:
    def __init__(self, model, endpoint='http://127.0.0.1:11434', *, timeout=60, transport=None):
        if not isinstance(model,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}',model) or 'cloud' in model.lower() or '//' in model or '..' in model:
            raise OllamaError('explicit installed local model required')
        try:
            url=urlsplit(endpoint)
            address=ipaddress.ip_address(url.hostname)
            if url.scheme!='http' or not address.is_loopback or url.username or url.password or url.path not in ('','/') or url.query or url.fragment or not url.port:
                raise ValueError()
        except (TypeError,ValueError):
            raise OllamaError('numeric loopback endpoint required') from None
        if type(timeout) not in (int,float) or not 0 < timeout <= 600:
            raise OllamaError('bounded local request timeout required')
        self.closed=False; self._response=None; self._lock=threading.Lock()
        self.model=model; self.endpoint=endpoint.rstrip('/'); self.timeout=timeout
        self._opener=request.build_opener(request.ProxyHandler({}),_NoRedirect())
        self._transport=transport or self._request
        try:
            version=self._transport('GET','/api/version',None)
            if not isinstance(version.get('version'),str) or not version['version']:
                raise OllamaError('local runtime version required')
            tags=self._transport('GET','/api/tags',None)
            matches=[item for item in tags.get('models',[]) if item.get('name')==model or item.get('model')==model]
            if len(matches)!=1 or not isinstance(matches[0].get('digest'),str) or not matches[0]['digest']:
                raise OllamaError('local model not installed with known digest')
            shown=self._transport('POST','/api/show',{'model':model})
            if 'vision' not in shown.get('capabilities',[]) or any(shown.get(key) for key in ('remote_model','remote_host','cloud')):
                raise OllamaError('installed local vision model required')
            self.identity={'engineVersion':version['version'],'name':model,'digest':matches[0]['digest'],'family':shown.get('details',{}).get('family'),'capabilities':shown['capabilities']}
        except OllamaError: raise
        except Exception:
            raise OllamaError('local model verification unavailable') from None

    def _request(self, method, path, body):
        if self.closed: raise OllamaError('local adapter stopped')
        if path not in ('/api/version','/api/tags','/api/show','/api/chat'):
            raise OllamaError('unsupported local model operation')
        data=json.dumps(body,allow_nan=False).encode() if body is not None else None
        req=request.Request(self.endpoint+path,data=data,method=method,headers={'Content-Type':'application/json'})
        try:
            with self._opener.open(req,timeout=self.timeout) as response:
                with self._lock:
                    if self.closed: raise OllamaError('local adapter stopped')
                    self._response=response
                if response.status!=200: raise OllamaError('local model unavailable')
                deadline=time.monotonic()+self.timeout
                chunks=[]; size=0
                while size<=2*1024*1024:
                    if self.closed or time.monotonic()>deadline: raise OllamaError('local adapter stopped or timed out')
                    part=response.read1(min(65536,2*1024*1024+1-size))
                    if not part: break
                    chunks.append(part); size+=len(part)
                raw=b''.join(chunks)
                if len(raw)>2*1024*1024: raise OllamaError('local model response too large')
                result=json.loads(raw)
                if not isinstance(result,dict): raise OllamaError('invalid local model response')
                return result
        except OllamaError: raise
        except (OSError,error.URLError,ValueError):
            raise OllamaError('local model request failed') from None
        finally:
            with self._lock: self._response=None

    def close(self):
        self.closed=True
        with self._lock:
            response=self._response
        if response is not None:
            # Interrupt reads without waiting on the BufferedReader lock held by
            # the model worker. Header waits remain bounded by request timeout.
            try:
                response.fp.raw._sock.shutdown(socket.SHUT_RDWR)
            except (AttributeError,OSError):
                pass

    def describe(self, images, prompt, schema, *, seed=0, num_predict=None, num_ctx=None):
        if self.closed: raise OllamaError('local adapter stopped')
        options={'temperature':0,'seed':seed}
        for key,value,maximum in (('num_predict',num_predict,4096),('num_ctx',num_ctx,65536)):
            if value is not None:
                if type(value) is not int or not 128<=value<=maximum: raise OllamaError('bounded model token options required')
                options[key]=value
        try:
            result=self._transport('POST','/api/chat',{'model':self.model,'stream':False,'format':schema,
                'messages':[{'role':'user','content':prompt,'images':images}],
                'options':options})
            if self.closed: raise OllamaError('local adapter stopped')
            if result.get('done') is not True or result.get('message',{}).get('role')!='assistant':
                raise OllamaError('incomplete local model output')
            parsed=json.loads(result['message']['content'])
            if not isinstance(parsed,dict): raise OllamaError('invalid structured visual output')
            return parsed
        except OllamaError: raise
        except Exception:
            raise OllamaError('invalid structured visual output') from None
