"""Admin-only CSV persistence helpers. UI must authorize admin before calling."""
import csv
import os
import tempfile
from pathlib import Path
from .access_control import _acquire_lock, _release_lock

FLAGS = {f'tab{i}_{suffix}' for i in range(1,7) for suffix in ('show','enable')} | {'settings_show'}

def read_access_csv(path):
    path=Path(path)
    with path.open('r',encoding='utf-8-sig',newline='') as handle:
        reader=csv.DictReader(handle)
        fields=list(reader.fieldnames or [])
        rows=list(reader)
    if not {'ip','name','status'}.issubset(set(fields)):
        raise ValueError('Access CSV is missing required headers')
    return fields,rows

def save_access_csv(path, fields, rows):
    path=Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    if len({r.get('ip','').strip() for r in rows})!=len(rows) or any(not r.get('ip','').strip() for r in rows):
        raise ValueError('IP must be nonempty and unique')
    for row in rows:
        for name in FLAGS.intersection(fields):
            if row.get(name) not in ('0','1'):
                raise ValueError(f'{name} must be 0 or 1')
    fd,lock=_acquire_lock(path)
    tmp=None
    try:
        current_fields,current_rows=read_access_csv(path)
        if current_fields!=list(fields):
            raise RuntimeError('Access CSV headers changed since open')
        if [r.get('ip') for r in current_rows] != [r.get('ip') for r in rows]:
            raise RuntimeError('Access CSV machine list changed since open')
        with tempfile.NamedTemporaryFile('w',encoding='utf-8-sig',newline='',dir=path.parent,prefix='.access-',suffix='.tmp',delete=False) as handle:
            tmp=Path(handle.name)
            writer=csv.DictWriter(handle,fieldnames=fields)
            writer.writeheader();writer.writerows(rows)
            handle.flush();os.fsync(handle.fileno())
        os.replace(tmp,path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
        _release_lock(fd,lock)
