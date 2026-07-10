"""Requirement / Design API 与事件测试。"""

from fastapi.testclient import TestClient

from conftest import create_project, create_task


def test_requirement_lifecycle_persists_json_and_events(client: TestClient) -> None:
    """验证需求规格保存 JSON 字段并写入审批事件。"""

    project = create_project(client)
    task = create_task(client, project["id"])

    create_response = client.post(
        f"/api/tasks/{task['id']}/requirements",
        json={
            "source_type": "manual",
            "raw_input": "新增任务看板。",
            "user_story": "作为用户，我希望看到任务状态。",
            "constraints_json": [{"name": "MVP", "value": "不接入真实 Agent"}],
            "acceptance_criteria_json": ["可以创建任务", "可以查看时间线"],
        },
    )
    assert create_response.status_code == 201, create_response.text
    requirement = create_response.json()
    assert requirement["status"] == "draft"
    assert requirement["acceptance_criteria_json"] == ["可以创建任务", "可以查看时间线"]

    approve_response = client.post(
        f"/api/requirements/{requirement['id']}/approve",
        json={"actor_id": "reviewer", "reason": "满足 M2 范围"},
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"

    changes_response = client.post(
        f"/api/requirements/{requirement['id']}/request-changes",
        json={"actor_id": "reviewer", "reason": "补充验收标准"},
    )
    assert changes_response.status_code == 200
    assert changes_response.json()["status"] == "changes_requested"

    event_types = [event["event_type"] for event in client.get(f"/api/tasks/{task['id']}/timeline").json()["items"]]
    assert "RequirementSpecCreated" in event_types
    assert "RequirementSpecApproved" in event_types
    assert "RequirementSpecChangesRequested" in event_types


def test_design_lifecycle_requires_requirement_and_writes_events(client: TestClient) -> None:
    """验证技术设计与需求关联、JSON 字段和审批事件。"""

    project = create_project(client)
    task = create_task(client, project["id"])
    requirement = client.post(
        f"/api/tasks/{task['id']}/requirements",
        json={"raw_input": "实现 API 底座。"},
    ).json()
    approve_requirement = client.post(f"/api/requirements/{requirement['id']}/approve")
    assert approve_requirement.status_code == 200, approve_requirement.text

    create_response = client.post(
        f"/api/tasks/{task['id']}/technical-designs",
        json={
            "requirement_spec_id": requirement["id"],
            "design_type": "mvp",
            "content_markdown": "## API 设计\n\n使用 FastAPI + SQLAlchemy。",
            "openapi_json": {"paths": {"/api/tasks": {"get": {}}}},
            "db_schema_json": {"tables": ["tasks", "event_logs"]},
            "risk_level": "L1",
        },
    )
    assert create_response.status_code == 201, create_response.text
    design = create_response.json()
    assert design["status"] == "draft"
    assert design["openapi_json"]["paths"]["/api/tasks"]["get"] == {}

    approve = client.post(f"/api/technical-designs/{design['id']}/approve", json={"actor_id": "architect"})
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"

    changes = client.post(
        f"/api/technical-designs/{design['id']}/request-changes",
        json={"actor_id": "architect", "reason": "补充错误码"},
    )
    assert changes.status_code == 200
    assert changes.json()["status"] == "changes_requested"

    event_types = [event["event_type"] for event in client.get(f"/api/tasks/{task['id']}/timeline").json()["items"]]
    assert "TechnicalDesignCreated" in event_types
    assert "TechnicalDesignApproved" in event_types
    assert "TechnicalDesignChangesRequested" in event_types


def test_review_transitions_reject_duplicates_and_reset_task_phase(client: TestClient) -> None:
    """评审要求修改应回退任务阶段，重复决策应返回 409。"""

    project = create_project(client)
    task = create_task(client, project["id"])
    requirement = client.post(f"/api/tasks/{task['id']}/requirements", json={"raw_input": "需要重新评审。"}).json()
    first = client.post(f"/api/requirements/{requirement['id']}/request-changes", json={"actor_id": "reviewer"})
    assert first.status_code == 200
    duplicate = client.post(f"/api/requirements/{requirement['id']}/request-changes", json={"actor_id": "reviewer"})
    assert duplicate.status_code == 409
    assert client.get(f"/api/tasks/{task['id']}").json()["current_phase"] == "RequirementClarifying"


def test_design_rejects_agent_run_from_other_task(client: TestClient) -> None:
    """TechnicalDesign 的 created_by_agent_run_id 必须属于当前任务。"""

    project = create_project(client)
    task = create_task(client, project["id"], "任务一")
    other = create_task(client, project["id"], "任务二")
    requirement = client.post(f"/api/tasks/{task['id']}/requirements", json={"raw_input": "归属校验"}).json()
    assert client.post(f"/api/requirements/{requirement['id']}/approve").status_code == 200
    other_run = client.post(f"/api/tasks/{other['id']}/agent-runs", json={"agent_type": "architect"}).json()
    response = client.post(
        f"/api/tasks/{task['id']}/technical-designs",
        json={
            "requirement_spec_id": requirement["id"],
            "content_markdown": "# design",
            "created_by_agent_run_id": other_run["id"],
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == "agent_run_task_mismatch"


def test_requirement_and_design_versions_reject_stale_reviews(client: TestClient) -> None:
    """新版本必须递增，并禁止旧需求或旧设计再次改变当前任务。"""

    project = create_project(client)
    task = create_task(client, project["id"], "版本一致性")

    requirement_v1 = client.post(
        f"/api/tasks/{task['id']}/requirements",
        json={"raw_input": "第一版需求"},
    ).json()
    assert requirement_v1["version"] == 1
    approved_v1 = client.post(f"/api/requirements/{requirement_v1['id']}/approve")
    assert approved_v1.status_code == 200
    assert client.get(f"/api/tasks/{task['id']}").json()["current_phase"] == "Designing"

    design_v1 = client.post(
        f"/api/tasks/{task['id']}/technical-designs",
        json={"requirement_spec_id": requirement_v1["id"], "content_markdown": "# 第一版设计"},
    ).json()
    assert design_v1["version"] == 1
    assert client.post(f"/api/technical-designs/{design_v1['id']}/approve").status_code == 200
    assert client.get(f"/api/tasks/{task['id']}").json()["current_phase"] == "Planning"

    requirement_v2 = client.post(
        f"/api/tasks/{task['id']}/requirements",
        json={"raw_input": "第二版需求"},
    )
    assert requirement_v2.status_code == 201, requirement_v2.text
    assert requirement_v2.json()["version"] == 2
    assert client.get(f"/api/technical-designs/{design_v1['id']}").json()["status"] == "changes_requested"

    stale_requirement = client.post(f"/api/requirements/{requirement_v1['id']}/request-changes")
    assert stale_requirement.status_code == 409
    assert stale_requirement.json()["code"] == "stale_requirement"

    assert client.post(f"/api/requirements/{requirement_v2.json()['id']}/approve").status_code == 200
    design_v2 = client.post(
        f"/api/tasks/{task['id']}/technical-designs",
        json={"requirement_spec_id": requirement_v2.json()["id"], "content_markdown": "# 第二版设计"},
    )
    assert design_v2.status_code == 201, design_v2.text
    assert design_v2.json()["version"] == 2

    stale_design = client.post(f"/api/technical-designs/{design_v1['id']}/approve")
    assert stale_design.status_code == 409
    assert stale_design.json()["code"] == "stale_technical_design"


def test_design_creation_requires_latest_approved_requirement(client: TestClient) -> None:
    """设计不能基于未批准或已过期的 RequirementSpec。"""

    project = create_project(client)
    task = create_task(client, project["id"], "设计前置条件")
    first = client.post(f"/api/tasks/{task['id']}/requirements", json={"raw_input": "第一版"}).json()

    draft_response = client.post(
        f"/api/tasks/{task['id']}/technical-designs",
        json={"requirement_spec_id": first["id"], "content_markdown": "# draft"},
    )
    assert draft_response.status_code == 409
    assert draft_response.json()["code"] == "requirement_not_approved"

    assert client.post(f"/api/requirements/{first['id']}/approve").status_code == 200
    second = client.post(f"/api/tasks/{task['id']}/requirements", json={"raw_input": "第二版"}).json()
    stale_response = client.post(
        f"/api/tasks/{task['id']}/technical-designs",
        json={"requirement_spec_id": first["id"], "content_markdown": "# stale"},
    )
    assert stale_response.status_code == 409
    assert stale_response.json()["code"] == "stale_requirement"
    assert second["version"] == 2
