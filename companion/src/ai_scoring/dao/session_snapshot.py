"""Read-only shared-lock session snapshots, with no create/recovery side effects."""
import fcntl
import json
import os
from pathlib import Path
import re
import stat
from ai_scoring.dao.read_helpers import utc,ReadError

class SnapshotError(ValueError):
    pass

def read_session_snapshot(data_directory,session_id):
    if not isinstance(session_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',session_id):
        raise SnapshotError('invalid session ID')
    requested_root=Path(data_directory)
    if '..' in requested_root.parts or requested_root.is_symlink():
        raise SnapshotError('unsafe data directory')
    root=requested_root.resolve()
    folder=root/'sessions'/session_id
    descriptors=[]
    try:
        flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
        descriptor=os.open(root,flags)
        descriptors.append(descriptor)
        for child in ('sessions',session_id):
            descriptor=os.open(child,flags,dir_fd=descriptor)
            descriptors.append(descriptor)
        log_descriptor=os.open('session.jsonl',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=descriptor)
        with os.fdopen(log_descriptor,'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise SnapshotError('session log is not a regular file')
            try:
                fcntl.flock(stream,fcntl.LOCK_SH|fcntl.LOCK_NB)
            except BlockingIOError:
                raise SnapshotError('session has an active writer; stop the companion before inspecting') from None
            data=stream.read()
            if data and not data.endswith(b'\n'):
                raise SnapshotError('session has an incomplete final record; no recovery was performed')
            records=[]
            ids=set()
            for line in data.splitlines():
                record=json.loads(line)
                if not isinstance(record,dict) or not isinstance(record.get('id'),str) or record['id'] in ids or not isinstance(record.get('payload'),dict) or not isinstance(record.get('type'),str):
                    raise ValueError()
                utc(record['timestamp'])
                ids.add(record['id'])
                records.append(record)
            return records,folder
    except SnapshotError:
        raise
    except (OSError,ValueError,TypeError,KeyError,UnicodeError):
        raise SnapshotError('session snapshot unavailable or malformed; no files were changed') from None
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
