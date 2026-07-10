"""Event Timeline 与 SSE API 测试。"""

from fastapi.testclient import TestClient

from conftest import create_project, create_task


def test_event_timeline_and_sse_stream_return_real_events(client: TestClient) -> None:
    """验证 timeline 和 SSE 都读取真实 event_logs。"""

    project = create_project(client)
    task = create_task(client, project["id"])
    client.post(f"/api/tasks/{task['id']}/pause", json={"actor_id": "tester"})

    timeline = client.get(f"/api/tasks/{task['id']}/timeline?limit=10")
    assert timeline.status_code == 200
    event_types = [event["event_type"] for event in timeline.json()["items"]]
    assert event_types == ["TaskCreated", "TaskPaused"]

    stream = client.get(f"/api/tasks/{task['id']}/events/stream")
    assert stream.status_code == 200
    assert "event: TaskCreated" in stream.text
    assert "event: TaskPaused" in stream.text
    assert ": heartbeat" in stream.text


def test_timeline_small_page_keeps_latest_events_in_chronological_order(client: TestClient) -> None:
    """时间线分页不能因历史事件过多而永久漏掉最新状态。"""

    project = create_project(client)
    task = create_task(client, project["id"])
    client.post(f"/api/tasks/{task['id']}/pause")
    client.post(f"/api/tasks/{task['id']}/resume")
    client.post(f"/api/tasks/{task['id']}/pause")
    client.post(f"/api/tasks/{task['id']}/resume")
    client.post(f"/api/tasks/{task['id']}/cancel")

    latest = client.get(f"/api/tasks/{task['id']}/timeline?limit=2")
    assert latest.status_code == 200
    assert [item["event_type"] for item in latest.json()["items"]] == ["TaskResumed", "TaskCancelled"]
    assert latest.json()["page"]["next_cursor"] == "2"
