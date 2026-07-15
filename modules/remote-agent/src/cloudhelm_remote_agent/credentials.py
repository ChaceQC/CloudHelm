"""machine secret 的受控文件读取。"""

import errno
import os
from pathlib import Path
import stat

from cloudhelm_remote_agent.exceptions import CredentialError

_MAX_CREDENTIAL_BYTES = 4096


def read_machine_secret(path: Path) -> bytes:
    """读取 machine secret，并拒绝空文件、符号链接和明显宽松权限。

    Linux/POSIX 上要求 group/other 无任何权限。Windows 的 POSIX mode 位
    不能准确表达 ACL，因此这里只执行文件类型、symlink、大小和可读性检查；
    部署时仍需由专用服务账号 ACL 或 systemd credential 目录限制访问。
    """

    try:
        initial_metadata = path.lstat()
    except FileNotFoundError as exc:
        raise CredentialError(
            "credential_file_missing",
            "machine credential 文件不存在。",
        ) from exc
    except OSError as exc:
        raise CredentialError(
            "credential_file_unavailable",
            "machine credential 文件不可访问。",
        ) from exc

    if stat.S_ISLNK(initial_metadata.st_mode):
        raise CredentialError(
            "credential_file_symlink",
            "machine credential 文件不得是符号链接。",
        )
    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError as exc:
        raise CredentialError(
            "credential_file_missing",
            "machine credential 文件不存在。",
        ) from exc
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise CredentialError(
                "credential_file_symlink",
                "machine credential 文件不得是符号链接。",
            ) from exc
        raise CredentialError(
            "credential_file_unreadable",
            "machine credential 文件读取失败。",
        ) from exc

    try:
        metadata = os.fstat(descriptor)
        if (
            initial_metadata.st_dev != metadata.st_dev
            or initial_metadata.st_ino != metadata.st_ino
        ):
            raise CredentialError(
                "credential_file_changed",
                "machine credential 文件在读取前发生变化。",
            )
        if not stat.S_ISREG(metadata.st_mode):
            raise CredentialError(
                "credential_file_invalid",
                "machine credential 路径不是普通文件。",
            )
        if metadata.st_size > _MAX_CREDENTIAL_BYTES:
            raise CredentialError(
                "credential_file_too_large",
                "machine credential 文件超过大小限制。",
            )
        if os.name != "nt" and stat.S_IMODE(metadata.st_mode) & 0o077:
            raise CredentialError(
                "credential_file_insecure_permissions",
                "machine credential 文件权限过于宽松。",
            )

        chunks: list[bytes] = []
        received = 0
        while True:
            chunk = os.read(
                descriptor,
                min(1024, _MAX_CREDENTIAL_BYTES + 1 - received),
            )
            if not chunk:
                break
            chunks.append(chunk)
            received += len(chunk)
            if received > _MAX_CREDENTIAL_BYTES:
                raise CredentialError(
                    "credential_file_too_large",
                    "machine credential 文件超过大小限制。",
                )
        secret = b"".join(chunks).strip()
    except CredentialError:
        raise
    except OSError as exc:
        raise CredentialError(
            "credential_file_unreadable",
            "machine credential 文件读取失败。",
        ) from exc
    finally:
        os.close(descriptor)

    if not secret:
        raise CredentialError(
            "credential_file_empty",
            "machine credential 文件为空。",
        )
    return secret
