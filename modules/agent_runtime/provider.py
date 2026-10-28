"""Fixed worker-side provider binding; credentials never enter durable arguments."""

import os
import stat
from dataclasses import dataclass

from pydantic import SecretStr

from modules.collaboration.errors import TaskBoundaryError


@dataclass(frozen=True, repr=False)
class RuntimeProvider:
    base_url: str
    key_file: str
    config_id: str = "default-responses"
    config_revision: str = "1"
    model_name: str = "gpt-6-luna"

    def check(self, policy):
        secret = policy.secret_version_ref
        if (policy.model_config_id != self.config_id or policy.model_config_revision != self.config_revision
                or policy.model_name != self.model_name or policy.max_output_tokens > 128000
                or secret is not None and (secret.object_id != self.config_id or secret.revision != self.config_revision)):
            raise TaskBoundaryError("agent_model_configuration_unsupported")

    def api_key(self):
        descriptor = os.open(self.key_file, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(descriptor, "r", encoding="utf-8") as source:
            info = os.fstat(source.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077 or info.st_size > 4096):
                raise TaskBoundaryError("agent_credential_file_invalid")
            return SecretStr(source.read().strip())


def configured_provider():
    path = os.environ.get("CLOUDHELM_AGENT_MODEL_KEY_FILE")
    if path is None:
        return None
    return RuntimeProvider(os.environ.get("CLOUDHELM_AGENT_MODEL_BASE_URL", "https://api.openai.com/v1"), path)
