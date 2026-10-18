"""Fixed in-container HTTP and reload-process probes for the notes profile."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from modules.workspaces.candidate_writers import process_start_ticks

from .toolchain import DockerClient, ProbeFailure

_HTTP_PROBE = r'''import hashlib,json,urllib.error,urllib.request
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def get(path):
    try:
        with opener.open('http://127.0.0.1:8000'+path,timeout=2) as response:
            return response.status,response.read(2097153)
    except urllib.error.HTTPError as error:
        return error.code,error.read(2097153)
    except Exception:
        raise SystemExit(80)
def digest(data):
    if len(data)>2097152: raise SystemExit(81)
    return 'sha256:'+hashlib.sha256(data).hexdigest()
revision=__import__('os').environ.get('CLOUDHELM_DATA_REVISION','')
seeds={
 'reference-synthetic-r1':('CloudHelm synthetic seed reference-synthetic-r1','Deterministic disposable seed note for reference-synthetic-r1'),
 'reference-synthetic-r2':('CloudHelm synthetic seed reference-synthetic-r2','Deterministic disposable seed note for reference-synthetic-r2'),
}
if revision not in seeds: raise SystemExit(82)
hs,hb=get('/health'); rs,rb=get('/ready'); ns,nb=get('/api/notes'); ms,mb=get('/devmarker')
try:
    health=json.loads(hb.decode('utf-8')); ready=json.loads(rb.decode('utf-8'))
    notes=json.loads(nb.decode('utf-8'))
except Exception:
    raise SystemExit(83)
if hs!=200 or health!={'status':'ok'} or rs!=200 or ready!={'status':'ready'} or ns!=200 or not isinstance(notes,list) or len(notes)>256:
    raise SystemExit(84)
title,body=seeds[revision]
summary=[]; matching=0
for item in notes:
    if not isinstance(item,dict) or type(item.get('id')) is not int or not isinstance(item.get('title'),str) or not isinstance(item.get('body'),str):
        raise SystemExit(85)
    if len(item['title'])>120 or len(item['body'])>4000: raise SystemExit(86)
    matching+=item['title']==title and item['body']==body
    summary.append({'id':item['id'],'title_digest':digest(item['title'].encode()),'body_digest':digest(item['body'].encode())})
if matching!=1: raise SystemExit(87)
print(json.dumps({'health_status':hs,'health_digest':digest(hb),'ready_status':rs,'ready_digest':digest(rb),
    'notes_status':ns,'notes_digest':digest(nb),'notes':summary,'seed_verified':True,
    'devmarker_status':ms,'devmarker_digest':digest(mb)},sort_keys=True,separators=(',',':')))
'''


def probe_workspace_backend(client: DockerClient, container_id: str) -> dict:
    result = client.run("exec", container_id, "/environment/bin/python", "-B", "-I", "-c", _HTTP_PROBE,
        timeout=8, required=False)
    if result.returncode:
        raise ProbeFailure("workspace_development_http_probe_not_ready")
    try:
        value = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise ProbeFailure("workspace_development_http_probe_invalid") from None
    required = {"health_status", "health_digest", "ready_status", "ready_digest", "notes_status",
        "notes_digest", "notes", "seed_verified", "devmarker_status", "devmarker_digest"}
    if (set(value) != required or value["health_status"] != 200 or value["ready_status"] != 200
            or value["notes_status"] != 200 or value["seed_verified"] is not True
            or any(not isinstance(value[name], str) or not value[name].startswith("sha256:")
                   for name in ("health_digest", "ready_digest", "notes_digest", "devmarker_digest"))
            or type(value["devmarker_status"]) is not int or not isinstance(value["notes"], list)
            or len(value["notes"]) > 256):
        raise ProbeFailure("workspace_development_http_probe_contract_mismatch")
    return value


def workspace_server_process_id(client: DockerClient, container_id: str, cgroup_path: Path) -> str:
    result = client.run("top", container_id, "-eo", "pid,args", timeout=10)
    candidates = []
    for line in result.stdout.splitlines()[1:]:
        fields = line.strip().split(None, 1)
        if len(fields) != 2 or not fields[0].isdigit():
            continue
        if "multiprocessing.spawn" in fields[1] or "spawn_main" in fields[1]:
            candidates.append(int(fields[0]))
    if len(candidates) != 1:
        raise ProbeFailure("workspace_development_server_process_identity_unconfirmed")
    pid = candidates[0]
    try:
        cgroups = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8").splitlines()
        selected = next((Path("/sys/fs/cgroup") / line[3:].lstrip("/")
                         for line in cgroups if line.startswith("0::/")), None)
        if selected is None or not selected.is_relative_to(cgroup_path):
            raise ProbeFailure("workspace_development_server_process_outside_parent")
        ticks = process_start_ticks(pid)
    except ProbeFailure:
        raise
    except (OSError, ValueError, IndexError):
        raise ProbeFailure("workspace_development_server_process_identity_unconfirmed") from None
    return f"{container_id[:16]}:{pid}:{ticks}"
