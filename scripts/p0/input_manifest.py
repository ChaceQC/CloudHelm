"""Print hashes of public P0 inputs; never inspect machine configuration."""

import hashlib
import json
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    paths = [root / name for name in ("pyproject.toml", "uv.lock", ".python-version")]
    for directory in ("scripts/p0", "infra/p0", "packages/contracts/p0"):
        paths.extend(
            path for path in (root / directory).rglob("*")
            if path.is_file() and path.suffix in {".py", ".json", ".yaml"}
        )
    print(json.dumps({
        "input_set": "p0.1-public-inputs-r1",
        "scope": "probe sources, dependency lock and isolated contracts only",
        "sha256": {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
