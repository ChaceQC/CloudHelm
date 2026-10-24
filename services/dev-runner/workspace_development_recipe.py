"""Stateless recipe for the single supported notes development profile.

Only fixed values and pure request/response transformations live here. Execution,
authorization, credential injection and persistent state belong to the caller.
"""

from __future__ import annotations

import json

from packages.contracts.p1.development_environment import (
    DATA_REVISION, MIGRATION_REVISION, POSTGRES_REFERENCE,
    WORKSPACE_DEVELOPMENT_PROFILE as PROFILE,
)

from .offline_images import SOURCE_DIGEST as PYTHON_IMAGE_DIGEST, SOURCE_REFERENCE as PYTHON_REFERENCE
from .toolchain import ProbeFailure

POSTGRES_IMAGE_DIGEST = POSTGRES_REFERENCE.rsplit("@", 1)[1]
DATABASE_NAME = "reference_notes"
DATABASE_OWNER = "reference_owner"
DATABASE_APPLICATION_USER = "reference_app"
WORKING_DIRECTORY = "/workspace/backend"
BACKEND_PORT = "8000/tcp"
DATABASE_ENVIRONMENT = (
    "POSTGRES_DB=" + DATABASE_NAME, "POSTGRES_USER=" + DATABASE_OWNER,
    "POSTGRES_PASSWORD_FILE=/run/cloudhelm-secrets/owner",
    "POSTGRES_INITDB_ARGS=--auth-host=scram-sha-256 --auth-local=scram-sha-256",
)
DATABASE_COMMAND = (
    "postgres", "-c", "max_connections=30", "-c", "shared_buffers=32MB",
    "-c", "log_min_messages=panic", "-c", "log_statement=none",
)
DATABASE_SQL_COMMAND = (
    "psql", "--no-psqlrc", "--quiet", "--tuples-only", "--no-align",
    "--host=localhost", "--username=" + DATABASE_OWNER, "--dbname=" + DATABASE_NAME,
    "--set=ON_ERROR_STOP=1",
)
MIGRATION_HEAD_QUERY = "SELECT version_num FROM alembic_version;"
DATASET_SEEDS = {
    "reference-synthetic-r1": (
        "CloudHelm synthetic seed reference-synthetic-r1",
        "Deterministic disposable seed note for reference-synthetic-r1",
    ),
    "reference-synthetic-r2": (
        "CloudHelm synthetic seed reference-synthetic-r2",
        "Deterministic disposable seed note for reference-synthetic-r2",
    ),
}
DATASET_REVISIONS = frozenset(DATASET_SEEDS)


def application_command(action: str) -> list[str]:
    if action == "serve":
        return ["/environment/bin/python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0",
                "--port", "8000", "--reload", "--reload-dir", "/workspace/backend/app"]
    if action == MIGRATION_REVISION:
        return ["/environment/bin/python", "-m", "alembic", "upgrade", MIGRATION_REVISION]
    raise ProbeFailure("workspace_development_bootstrap_action_invalid")


def seed_count_statement(revision: str) -> str:
    if revision not in DATASET_REVISIONS:
        raise ProbeFailure("workspace_development_data_revision_unsupported")
    title, body = DATASET_SEEDS[revision]
    return f"SELECT count(*) FROM notes WHERE title='{title}' AND body='{body}';"


def data_statements(revision: str) -> tuple[str, str, str, str]:
    """Return fixed SQL; the caller replaces the password placeholder privately."""
    seed = seed_count_statement(revision)
    title, body = DATASET_SEEDS[revision]
    initialize = (
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='reference_app') THEN "
        "CREATE ROLE reference_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION; END IF; END $$;\n"
        "ALTER ROLE reference_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '{password}';\n"
        "GRANT CONNECT ON DATABASE reference_notes TO reference_app; "
        "GRANT USAGE ON SCHEMA public TO reference_app; "
        "GRANT SELECT,INSERT,UPDATE,DELETE ON notes TO reference_app; "
        "GRANT SELECT ON alembic_version TO reference_app; "
        "GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO reference_app;\n"
        f"INSERT INTO notes(title,body,created_at,updated_at) SELECT '{title}','{body}',"
        "'2026-01-01T00:00:00Z','2026-01-01T00:00:00Z' WHERE NOT EXISTS "
        f"(SELECT 1 FROM notes WHERE title='{title}' AND body='{body}');"
    )
    other = (
        f"SELECT count(*) FROM notes WHERE title IN ({','.join(repr(value[0]) for value in DATASET_SEEDS.values())}) "
        f"AND title <> '{title}';"
    )
    security = (
        "SELECT (SELECT count(*)=0 FROM pg_hba_file_rules WHERE error IS NOT NULL OR auth_method='trust') "
        "AND (SELECT NOT (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication) "
        "FROM pg_roles WHERE rolname='reference_app');"
    )
    return initialize, seed, other, security


HTTP_PROBE = r'''import hashlib,json,urllib.error,urllib.request
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
seeds=''' + repr(DATASET_SEEDS) + r'''
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


def parse_backend_probe(output: bytes) -> dict:
    try:
        value = json.loads(output)
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
