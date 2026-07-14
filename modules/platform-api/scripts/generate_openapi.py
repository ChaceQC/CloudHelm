"""从 FastAPI 应用生成共享 OpenAPI YAML。

该脚本只负责把 `app.openapi()` 的真实契约写入共享文件，避免手工维护导致
路由、DTO、错误响应或版本号漂移。生成后仍需运行精确一致性测试。
"""

from pathlib import Path

import yaml

from cloudhelm_platform_api.main import app


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_PATH = (
    REPOSITORY_ROOT
    / "packages"
    / "shared-contracts"
    / "openapi"
    / "cloudhelm.openapi.yaml"
)


def main() -> None:
    """以 UTF-8 和稳定字段顺序写出当前 FastAPI OpenAPI。"""

    content = yaml.safe_dump(
        app.openapi(),
        allow_unicode=True,
        sort_keys=False,
        width=120,
    )
    OUTPUT_PATH.write_text(content, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
