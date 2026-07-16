"""M7 ProjectRepositoryBinding 配置、幂等更新与漂移失效服务。"""

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.project_repository_binding import (
    ProjectRepositoryBinding,
)
from cloudhelm_platform_api.providers.repository_profile_provider import (
    RepositoryProfileProvider,
)
from cloudhelm_platform_api.repositories.project_repository import (
    ProjectRepository,
)
from cloudhelm_platform_api.repositories.project_repository_binding_repository import (
    ProjectRepositoryBindingRepository,
)
from cloudhelm_platform_api.schemas.repository_binding import (
    RepositoryBindingPut,
    RepositoryBindingRead,
)
from cloudhelm_platform_api.services.base import BaseService
from cloudhelm_platform_api.services.database_errors import (
    database_write_error,
    integrity_constraint_name,
)
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.exceptions import ServiceError
from cloudhelm_platform_api.services.release_candidate_freshness import (
    ReleaseCandidateFreshnessService,
)
from cloudhelm_platform_api.services.repository_binding_snapshot import (
    build_repository_binding_public_snapshot,
    internal_snapshot_hash_from_binding,
    repository_binding_internal_snapshot_hash,
)

_BINDING_CONFLICT_CONSTRAINTS = {
    "uq_project_repository_bindings_external",
    "ux_project_repository_bindings_owner_name",
}
class ProjectRepositoryBindingService(BaseService):
    """物化服务端 RepositoryProfile，并同步处理配置漂移。"""

    def __init__(
        self,
        session: Session,
        *,
        profiles: RepositoryProfileProvider | None = None,
    ) -> None:
        super().__init__(session)
        self.profiles = profiles or RepositoryProfileProvider()
        self.projects = ProjectRepository(session)
        self.bindings = ProjectRepositoryBindingRepository(session)
        self.freshness = ReleaseCandidateFreshnessService(session)
        self.events = EventService(session)

    def put_binding(
        self,
        project_id: UUID,
        data: RepositoryBindingPut,
    ) -> RepositoryBindingRead:
        """创建或幂等更新项目绑定，并使漂移候选与审批原子失效。"""

        if self.projects.get(project_id) is None:
            raise ServiceError(
                "project_not_found",
                "Project 不存在。",
                404,
            )

        profile = self.profiles.get_profile(data.profile_key)
        self.profiles.get_credential(profile.credential_ref)
        clone_url = str(profile.clone_url)
        public_snapshot = build_repository_binding_public_snapshot(
            provider=profile.provider,
            repository_external_id=profile.repository_external_id,
            repository_owner=profile.repository_owner,
            repository_name=profile.repository_name,
            default_branch=profile.default_branch,
            workflow_id=profile.workflow_id,
            release_ref_prefix=profile.release_ref_prefix,
        )
        new_snapshot_hash = repository_binding_internal_snapshot_hash(
            public_snapshot=public_snapshot,
            profile_key=data.profile_key,
            clone_url=clone_url,
            credential_ref=profile.credential_ref,
        )

        self.bindings.lock_configuration_namespace()
        binding = self.bindings.get_by_project(
            project_id,
            for_update=True,
        )
        if binding is None:
            if self.projects.get(project_id, for_update=True) is None:
                raise ServiceError(
                    "project_not_found",
                    "Project 不存在。",
                    404,
                )
            binding = self.bindings.get_by_project(
                project_id,
                for_update=True,
            )

        created = binding is None
        old_snapshot_hash = (
            None
            if binding is None
            else internal_snapshot_hash_from_binding(binding)
        )
        old_status = None if binding is None else binding.status
        if (
            binding is not None
            and binding.status == "active"
            and old_snapshot_hash == new_snapshot_hash
        ):
            response = RepositoryBindingRead.model_validate(binding)
            self.session.rollback()
            return response

        if binding is None:
            binding = ProjectRepositoryBinding(
                project_id=project_id,
                provider=profile.provider,
                profile_key=data.profile_key,
                repository_external_id=profile.repository_external_id,
                repository_owner=profile.repository_owner,
                repository_name=profile.repository_name,
                clone_url=clone_url,
                default_branch=profile.default_branch,
                credential_ref=profile.credential_ref,
                workflow_id=profile.workflow_id,
                release_ref_prefix=profile.release_ref_prefix,
                status="active",
            )
        else:
            binding.provider = profile.provider
            binding.profile_key = data.profile_key
            binding.repository_external_id = profile.repository_external_id
            binding.repository_owner = profile.repository_owner
            binding.repository_name = profile.repository_name
            binding.clone_url = clone_url
            binding.default_branch = profile.default_branch
            binding.credential_ref = profile.credential_ref
            binding.workflow_id = profile.workflow_id
            binding.release_ref_prefix = profile.release_ref_prefix
            binding.status = "active"

        try:
            if created:
                self.bindings.create(binding)
            else:
                self.bindings.save(binding)
        except IntegrityError as exc:
            self.session.rollback()
            if integrity_constraint_name(exc) in _BINDING_CONFLICT_CONSTRAINTS:
                raise ServiceError(
                    "repository_binding_conflict",
                    "Repository 已绑定到其他 Project。",
                    409,
                ) from None
            raise database_write_error(exc) from exc

        drifted = (
            not created
            and (
                old_snapshot_hash != new_snapshot_hash
                or old_status != "active"
            )
        )
        stale_candidate_ids: list[str] = []
        expired_approval_ids: list[str] = []
        if drifted:
            (
                stale_candidate_ids,
                expired_approval_ids,
            ) = self.freshness.invalidate_by_binding(
                binding.id,
                reason="repository_binding_changed",
            )

        self.events.record(
            event_type="RepositoryBindingConfigured",
            actor_type="system",
            actor_id="repository-profile",
            payload={
                "project_id": str(project_id),
                "repository_binding_id": str(binding.id),
                "profile_key": binding.profile_key,
                "provider": binding.provider,
                "repository_external_id": binding.repository_external_id,
                "repository_owner": binding.repository_owner,
                "repository_name": binding.repository_name,
                "default_branch": binding.default_branch,
                "workflow_id": binding.workflow_id,
                "release_ref_prefix": binding.release_ref_prefix,
                "status": binding.status,
                "created": created,
                "configuration_changed": drifted,
                "stale_candidate_ids": stale_candidate_ids,
                "expired_approval_ids": expired_approval_ids,
            },
        )
        self.commit()
        return RepositoryBindingRead.model_validate(binding)

    def get_binding(self, project_id: UUID) -> RepositoryBindingRead:
        """只从数据库读取已物化 Binding，不重新加载 profile/credential。"""

        if self.projects.get(project_id) is None:
            raise ServiceError(
                "project_not_found",
                "Project 不存在。",
                404,
            )
        binding = self.bindings.get_by_project(project_id)
        if binding is None:
            raise ServiceError(
                "repository_binding_not_found",
                "ProjectRepositoryBinding 不存在。",
                404,
            )
        return RepositoryBindingRead.model_validate(binding)
