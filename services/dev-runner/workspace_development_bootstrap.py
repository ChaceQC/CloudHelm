"""Bounded extraction of a verified private venv into an exec-only container tmpfs."""

from __future__ import annotations

import json

from packages.contracts.p1.development_environment import MIGRATION_REVISION
from .toolchain import ProbeFailure


def bootstrap_command(action: str) -> str:
    if action not in {"serve", MIGRATION_REVISION}:
        raise ProbeFailure("workspace_development_bootstrap_action_invalid")
    argv = (["/environment/bin/python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0",
             "--port", "8000", "--reload", "--reload-dir", "/workspace/backend/app"]
            if action == "serve" else
            ["/environment/bin/python", "-m", "alembic", "upgrade", MIGRATION_REVISION])
    return """import hashlib, os, pathlib, posixpath, re, stat, tarfile
archive='/workspace-cache/dependencies.tar.gz'
expected=os.environ.get('WORKSPACE_SNAPSHOT_SHA256','')
if not re.fullmatch(r'[0-9a-f]{64}', expected): raise SystemExit(81)
archive_stat=os.stat(archive)
if not stat.S_ISREG(archive_stat.st_mode) or archive_stat.st_size>402653184: raise SystemExit(82)
h=hashlib.sha256()
with open(archive,'rb') as source:
    while True:
        block=source.read(1048576)
        if not block: break
        h.update(block)
if h.hexdigest()!=expected: raise SystemExit(83)
root=pathlib.Path('/environment')
members=[]; names=set(); total=0
with tarfile.open(archive,'r:*') as tar:
    for member in tar:
        if len(members)>=100000: raise SystemExit(84)
        name=member.name.rstrip('/')
        path=pathlib.PurePosixPath(name)
        if (not name or path.is_absolute() or any(part in ('','.','..') for part in name.split('/'))
            or len(name.encode('utf-8'))>1024 or any(ord(c)<32 or c=='\\' for c in name)
            or name in names): raise SystemExit(85)
        names.add(name)
        if member.isdir(): kind='dir'
        elif member.isfile():
            if member.mode & 0o7000 or member.mode & ~0o755 or member.mode & 0o111 not in (0,0o111): raise SystemExit(86)
            total+=member.size
            if total>536870912: raise SystemExit(87)
            kind='file'
        elif member.issym():
            target=member.linkname
            if not target or len(target.encode('utf-8'))>1024 or any(ord(c)<32 for c in target): raise SystemExit(88)
            if target.startswith('/'):
                if target not in ('/usr/local/bin/python','/usr/local/bin/python3','/usr/local/bin/python3.12'): raise SystemExit(89)
            else:
                resolved=posixpath.normpath(posixpath.join(posixpath.dirname(name),target))
                if resolved in ('..','.') or resolved.startswith('../') or resolved.startswith('/'): raise SystemExit(90)
            kind='link'
        else: raise SystemExit(91)
        members.append((member,name,kind))
    if not members: raise SystemExit(92)
    kinds={name:kind for _,name,kind in members}
    for _,name,kind in members:
        for parent in pathlib.PurePosixPath(name).parents:
            if str(parent)=='.': break
            if str(parent) in kinds and kinds[str(parent)]!='dir': raise SystemExit(93)
        if kind=='link' and any(other.startswith(name+'/') for _,other,_ in members): raise SystemExit(94)
    if any(root.iterdir()): raise SystemExit(95)
    for member,name,kind in sorted(members,key=lambda item:(item[2]!='dir',item[1])):
        destination=root.joinpath(*name.split('/'))
        if kind=='dir':
            destination.mkdir(mode=0o755,parents=True,exist_ok=True)
            if not stat.S_ISDIR(destination.lstat().st_mode): raise SystemExit(96)
        elif kind=='file':
            destination.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
            current=root
            for part in pathlib.PurePosixPath(name).parts[:-1]:
                current=current/part
                if not stat.S_ISDIR(current.lstat().st_mode): raise SystemExit(97)
            source=tar.extractfile(member)
            with open(destination,'xb') as output:
                while True:
                    block=source.read(65536)
                    if not block: break
                    output.write(block)
            os.chmod(destination,0o755 if member.mode & 0o111 else 0o644)
    for member,name,kind in members:
        if kind!='link': continue
        destination=root.joinpath(*name.split('/'))
        destination.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
        target=member.linkname
        if target.startswith('/'):
            allowed={'bin/python':'/usr/local/bin/python','bin/python3':'/usr/local/bin/python3','bin/python3.12':'/usr/local/bin/python3.12'}
            if allowed.get(name)!=target: raise SystemExit(98)
        os.symlink(target,destination)
os.execv('/environment/bin/python', """ + json.dumps(argv) + ")"""
