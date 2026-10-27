"""Fresh process for one archive step; no ledger or inherited network clients."""

import json
import sys

from .deadline import parent_death_signal


def main():
    parent_death_signal(int(sys.argv[1]))
    from packages.contracts.p1.remote_delivery import RemotePlan
    from . import archive_receipts, archives
    from .channel import Channel
    from .docker_io import Docker
    from .ledger import private_directory
    from .resources import Resources

    request = json.loads(sys.stdin.buffer.read(2_000_001))
    deployment = RemotePlan.model_validate(request["deployment"])
    channel = Channel(**request["channel"])
    try:
        docker = Docker(**request["docker"])
        resources = Resources(docker, **request["resources"])
        directory = private_directory(request["directory"])
        facts = archives.prepare(channel, docker, deployment, directory,
            check_resources=lambda: resources.verify(deployment.plan.configuration.resources))
        archive_receipts.record_completed(deployment, directory, facts)
        result = json.dumps({"ok": True, "value": facts}, separators=(",", ":")).encode("utf-8")
        if len(result) > 131072:
            raise ValueError("result too large")
        sys.stdout.buffer.write(result)
        sys.stdout.buffer.flush()
    finally:
        channel.close()


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        # A daemon, network, or validation error is reconciled under the original identity.
        raise SystemExit(1) from None
