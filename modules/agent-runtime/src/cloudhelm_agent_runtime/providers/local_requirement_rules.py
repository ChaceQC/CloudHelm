"""本地 Requirement/Architect/Planner 共用的文本规则。"""

import re

from cloudhelm_agent_runtime.schemas.requirement import AcceptanceCriterion


def split_sentences(text: str) -> list[str]:
    """按中英文标点拆分短句，过滤空白片段。"""

    return [
        part.strip()
        for part in re.split(r"[。！？!?；;\n]+", text)
        if part.strip()
    ]


def contains_any(text: str, keywords: list[str]) -> bool:
    """大小写不敏感关键字匹配。"""

    lower = text.lower()
    return any(keyword.lower() in lower for keyword in keywords)


def extract_acceptance_criteria(
    description: str,
) -> list[AcceptanceCriterion]:
    """从 demo issue Markdown 保留领域 AC ID、标题和完整说明。"""

    pattern = re.compile(
        r"(?ms)^-\s+\*\*"
        r"(?P<id>AC-[A-Z0-9]+(?:-[A-Z0-9]+)*)"
        r"\s+(?P<title>[^*]+)\*\*[：:]\s*"
        r"(?P<body>.*?)(?=^-\s+\*\*AC-|\Z)"
    )
    criteria = []
    for match in pattern.finditer(description):
        body = " ".join(
            line.strip()
            for line in match.group("body").splitlines()
            if line.strip()
        )
        description_text = (
            f"{match.group('title').strip()}：{body}".strip("：")
        )
        verification = (
            "pytest"
            if contains_any(
                description_text,
                ["测试", "pytest", "状态码", "返回", "持久化", "鉴权"],
            )
            else "api"
        )
        criteria.append(
            AcceptanceCriterion(
                id=match.group("id"),
                description=description_text,
                verification=verification,
            )
        )
    return criteria
