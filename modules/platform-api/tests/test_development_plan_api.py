"""DevelopmentPlan API 查询测试。"""

from fastapi.testclient import TestClient

from conftest import create_project, create_task


def test_get_development_plan_by_id(client: TestClient) -> None:
    """验证 DevelopmentPlan 可通过任务列表和 ID 查询。"""

    project = create_project(client)
    task = create_task(client, project["id"], title="查询开发计划")

    assert client.post(f"/api/tasks/{task['id']}/start", json={"actor_id": "tester"}).status_code == 200
    assert client.post(f"/api/tasks/{task['id']}/run-next", json={"actor_id": "tester"}).status_code == 200
    design = client.post(f"/api/tasks/{task['id']}/run-next", json={"actor_id": "tester"}).json()
    assert client.post(
        f"/api/technical-designs/{design['technical_design']['id']}/approve",
        json={"actor_id": "architect"},
    ).status_code == 200
    assert client.post(f"/api/tasks/{task['id']}/run-next", json={"actor_id": "tester"}).status_code == 200
    plan = client.post(f"/api/tasks/{task['id']}/run-next", json={"actor_id": "tester"}).json()["development_plan"]

    response = client.get(f"/api/development-plans/{plan['id']}")
    assert response.status_code == 200
    assert response.json()["summary"] == plan["summary"]

    missing = client.get("/api/development-plans/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404
    assert missing.json()["code"] == "development_plan_not_found"
