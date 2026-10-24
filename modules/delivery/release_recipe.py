"""One versioned archive recipe; it cannot select caller commands or images."""

import json
import hashlib

import rfc8785

from modules.delivery.compose import parse_release_source
from packages.contracts.p1.build_records import build_digest
from packages.contracts.p1.workspace_git import content_digest

RECIPE_REVISION = "reference-notes-archive-linux-amd64-r1"


def parameter_contract_digest(runtime):
    return delivery_digest({"recipe": RECIPE_REVISION,
        "parameters": {key: slot.model_dump(mode="json") for key, slot in runtime.parameter_contract.items()},
        "secrets": {key: slot.model_dump(mode="json") for key, slot in runtime.secret_reference_contract.items()}})


def delivery_digest(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def archive_runtime(artifacts):
    images = {item.role: f"cloudhelm-{item.role}@{item.manifest_digest}" for item in artifacts}
    services = {role: {"image": image, "networks": ["application"], "restart": "unless-stopped"}
                for role, image in images.items()}
    services["postgres"].update(
        environment={"POSTGRES_DB": "reference_notes", "POSTGRES_USER": "reference_owner",
                     "POSTGRES_PASSWORD": "__CH_SECRET_REF:POSTGRES_PASSWORD__"},
        volumes=[{"type": "volume", "source": "database", "target": "/var/lib/postgresql/data"}],
        healthcheck={"test": ["CMD", "pg_isready", "-U", "reference_owner", "-d", "reference_notes"]},
    )
    services["backend"].update(
        environment={"DATABASE_URL": "__CH_SECRET_REF:DATABASE_URL__"},
        healthcheck={"test": ["CMD", "python", "-c",
            "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=2)"]},
    )
    services["frontend"].update(
        environment={"NGINX_WORKER_PROCESSES": "__CH_PARAMETER:NGINX_WORKER_PROCESSES__"},
        ports=[{"host_ip": "127.0.0.1", "published": 58080, "target": 80}],
        healthcheck={"test": ["CMD", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1/"]},
    )
    source = {"name": "cloudhelm-notes-archive", "services": services,
              "networks": {"application": {"internal": True}}, "volumes": {"database": {}},
              "x-cloudhelm": {"contract": "cloudhelm.p1.compose-r1", "parameters": {
                  "NGINX_WORKER_PROCESSES": {"service": "frontend", "target": "environment.NGINX_WORKER_PROCESSES",
                                             "kind": "enum", "allowed_values": ["1", "2"]}},
                  "secret_refs": {name: {"service": service, "target": "environment." + name}
                                  for name, service in (("POSTGRES_PASSWORD", "postgres"), ("DATABASE_URL", "backend"))}}}
    return parse_release_source(json.dumps(source, ensure_ascii=False, sort_keys=True))


def variant_digest(record):
    return content_digest((RECIPE_REVISION + ":" + build_digest(record.fixed_inputs.definition)).encode("utf-8"))


def runtime_verification_digest(record, artifacts, configuration):
    return delivery_digest({"recipe": RECIPE_REVISION, "build_operation_id": record.operation_id,
        "build_input_digest": record.build_input_digest,
        "artifacts": [item.model_dump(mode="json") for item in sorted(artifacts, key=lambda item: item.role)],
        "runtime_digest": archive_runtime(artifacts).release_digest,
        "test_configuration": configuration.model_dump(mode="json")})
