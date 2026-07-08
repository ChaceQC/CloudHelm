"""Project API 黑盒与白盒结合测试。"""

from fastapi.testclient import TestClient

from conftest import create_project


def test_create_list_and_get_project_use_database(client: TestClient) -> None:
    """验证 Project API 真实写入、列表分页和详情读取。"""

    project = create_project(client)

    list_response = client.get("/api/projects?limit=10")
    assert list_response.status_code == 200
    items = list_response.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == project["id"]

    get_response = client.get(f"/api/projects/{project['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "演示项目"


def test_get_missing_project_returns_standard_error(client: TestClient) -> None:
    """验证不存在项目返回统一错误结构和 trace_id。"""

    response = client.get("/api/projects/00000000-0000-0000-0000-000000000001")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "project_not_found"
    assert body["trace_id"]
