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
