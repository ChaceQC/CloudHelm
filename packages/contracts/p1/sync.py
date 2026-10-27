"""Project-scoped snapshots and invalidations; domain APIs own authoritative detail."""

from typing import Literal

from pydantic import Field

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision
from packages.contracts.p0.engineering_contracts import UtcTimestamp
from packages.contracts.p0.identity_contracts import Action
from packages.contracts.p1.identity_contracts import ProjectView
from packages.contracts.p1.task_results import TaskView

SYNC_SCHEMA = "p1-sync-r1"


class SyncObject(Contract):
    kind: Literal["release", "configuration", "environment", "plan"]
    object_id: Identifier
    digest: Digest
    revision: Revision = 0
    release_id: Identifier | None = None
    target_id: Identifier | None = None
    config_revision_id: Identifier | None = None
    operation_id: Identifier | None = None
    approved: bool = False


class SyncSnapshot(Contract):
    schema_revision: Literal["p1-sync-r1"] = SYNC_SCHEMA
    stream_id: Identifier
    cursor: Revision
    captured_at: UtcTimestamp
    project: ProjectView
    available_actions: tuple[Action, ...] = Field(max_length=20)
    tasks: tuple[TaskView, ...] = Field(max_length=100)
    objects: tuple[SyncObject, ...] = Field(max_length=400)
    # P1 has no public hard-delete commands. Future deletion must populate these.
    tombstones: tuple[Identifier, ...] = Field(default=(), max_length=100)


class SyncEvent(Contract):
    cursor: Revision
    event_id: Identifier
    project_id: Identifier
    aggregate_kind: Identifier
    aggregate_id: Identifier
    aggregate_version: Revision
    event_type: Identifier
    schema_version: Identifier


class SyncBatch(Contract):
    schema_revision: Literal["p1-sync-r1"] = SYNC_SCHEMA
    stream_id: Identifier
    cursor: Revision
    events: tuple[SyncEvent, ...] = Field(max_length=32)
