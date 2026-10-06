"""Single process/session writer with durable acknowledgements and strict recovery."""
import copy
import fcntl
import json
import os
import stat
from pathlib import Path
from threading import RLock

class StorageFault(RuntimeError):
    pass

class IdentityConflict(ValueError):
    pass

class JsonlSessionStore:
    def __init__(self, data_directory, session_id):
        if not session_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in session_id):
            raise ValueError('invalid session ID')
        root=Path(data_directory).resolve()
        root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path=root/'sessions'/session_id/'session.jsonl'
        descriptors=[]
        log_descriptor=None
        try:
            flags=os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            directory_descriptor=os.open(root,flags)
            descriptors.append(directory_descriptor)
            for name in ('sessions',session_id):
                try:
                    os.mkdir(name,mode=0o700,dir_fd=directory_descriptor)
                except FileExistsError:
                    pass
                directory_descriptor=os.open(name,flags,dir_fd=directory_descriptor)
                descriptors.append(directory_descriptor)
                os.fchmod(directory_descriptor,0o700)
            log_descriptor=os.open('session.jsonl',os.O_CREAT | os.O_APPEND | os.O_RDWR | os.O_NOFOLLOW,
                mode=0o600,dir_fd=directory_descriptor)
            if not stat.S_ISREG(os.fstat(log_descriptor).st_mode):
                raise OSError('not a regular log')
            os.fchmod(log_descriptor,0o600)
            self._file=os.fdopen(log_descriptor,'a+b')
            log_descriptor=None
        except OSError:
            raise StorageFault('unsafe or inaccessible session storage') from None
        finally:
            if log_descriptor is not None:
                os.close(log_descriptor)
            for descriptor in reversed(descriptors):
                os.close(descriptor)
        try:
            fcntl.flock(self._file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._file.close()
            raise StorageFault('session already has a writer') from None
        self._lock = RLock()
        self._faulted = False
        self._records = []
        self._ids = {}
        try:
            self._recover()
        except Exception:
            self.close()
            raise

    def _recover(self):
        self._file.seek(0)
        data = self._file.read()
        complete_end = data.rfind(b'\n') + 1
        for line in data[:complete_end].splitlines():
            try:
                record = json.loads(line)
                if not isinstance(record, dict) or not isinstance(record.get('id'), str) or record['id'] in self._ids:
                    raise ValueError()
            except (ValueError, UnicodeError):
                raise StorageFault('malformed complete session record') from None
            self._records.append(record)
            self._ids[record['id']] = record
        if complete_end < len(data):
            self._file.seek(complete_end)
            self._file.truncate()
            self._file.flush()
            os.fsync(self._file.fileno())

    @property
    def records(self):
        return copy.deepcopy(self._records)

    def append(self, record):
        encoded = (json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
        record = json.loads(encoded)
        with self._lock:
            if self._faulted:
                raise StorageFault('writer faulted; reopen for recovery')
            existing = self._ids.get(record['id'])
            if existing is not None:
                if existing != record:
                    raise IdentityConflict('record ID reused with different payload')
                return copy.deepcopy(existing)
            try:
                self._file.seek(0, os.SEEK_END)
                self._file.write(encoded)
                self._file.flush()
                os.fsync(self._file.fileno())
            except OSError:
                self._faulted = True
                raise StorageFault('session write failed; collection stopped') from None
            self._records.append(record)
            self._ids[record['id']] = record
            return copy.deepcopy(record)

    def close(self):
        self._file.close()
