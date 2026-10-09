"""Small validation helpers shared by local observation and read-only inspection."""
from datetime import datetime
from pathlib import Path,PurePosixPath

class ReadError(ValueError):
    pass

def utc(value):
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed
    except (AttributeError,TypeError,ValueError):
        raise ReadError('invalid or timezone-free timestamp') from None

def confined(root,relative,*,require=True):
    path=PurePosixPath(relative)
    if not relative or path.is_absolute() or '..' in path.parts or '\\' in relative:
        raise ReadError('invalid relative asset path')
    candidate=Path(root)
    if candidate.is_symlink():
        raise ReadError('symlink roots are not accepted')
    for part in path.parts:
        candidate=candidate/part
        if candidate.is_symlink():
            raise ReadError('symlink assets are not accepted')
    if require and not candidate.is_file():
        raise ReadError('asset missing or unfinished')
    return candidate
