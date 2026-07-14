"""M6 Artifact 与本地等价 PR record 查询 API 黑盒测试。"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from m6_evidence_fixture import seed_m6_evidence


def test_artifact_api_lists_filters_pages_and_isolates_tasks(
    client: TestClient,
) -> None:
    """Artifact 列表只返回所属 Task，并支持类型、状态和 cursor。"""

    primary = seed_m6_evidence("primary", pull_request_count=2)
    secondary = seed_m6_evidence("secondary", pull_request_count=1)

    first_page = client.get(
        f"/api/tasks/{primary.task_id}/artifacts",
        params={"limit": 2},
    )
    assert first_page.status_code == 200, first_page.text
    first_body = first_page.json()
    assert len(first_body["items"]) == 2
    assert first_body["page"]["next_cursor"] == "2"
    assert {
        item["task_id"] for item in first_body["items"]
    } == {str(primary.task_id)}

    second_page = client.get(
        f"/api/tasks/{primary.task_id}/artifacts",
        params={
            "limit": 100,
            "cursor": first_body["page"]["next_cursor"],
        },
    )
    assert second_page.status_code == 200, second_page.text
    all_ids = {
        item["id"]
        for item in [*first_body["items"], *second_page.json()["items"]]
    }
    assert str(secondary.preview_artifact_id) not in all_ids

    test_reports = client.get(
        f"/api/tasks/{primary.task_id}/artifacts",
        params={"artifact_type": "test_report"},
    )
    assert test_reports.status_code == 200, test_reports.text
    assert [
        item["artifact_type"] for item in test_reports.json()["items"]
    ] == ["test_report"]

    invalidated = client.get(
        f"/api/tasks/{primary.task_id}/artifacts",
        params={"status": "invalidated"},
    )
    assert invalidated.status_code == 200, invalidated.text
    assert [item["id"] for item in invalidated.json()["items"]] == [
        str(primary.invalidated_artifact_id)
    ]

    invalid_status = client.get(
        f"/api/tasks/{primary.task_id}/artifacts",
        params={"status": "unknown"},
    )
    assert invalid_status.status_code == 422


def test_artifact_detail_returns_safe_preview_and_stable_404(
    client: TestClient,
) -> None:
    """Artifact 详情验证文件后仅返回受限、脱敏预览。"""

    fixture = seed_m6_evidence("preview", pull_request_count=1)

    response = client.get(
        f"/api/artifacts/{fixture.preview_artifact_id}"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["uri"] == f"artifact://{fixture.preview_artifact_id}"
    assert "storage_key" not in body
    assert "workspace_root" not in body["metadata_json"]
    assert body["metadata_json"]["report_path"] == (
        "<redacted-local-path>"
    )
    assert body["preview"]["kind"] == "text"
    assert "D:\\private" not in body["preview"]["text"]
    assert "<redacted-local-path>" in body["preview"]["text"]
    assert body["preview"]["truncated"] is True
    assert body["preview"]["bytes_returned"] == 65536

    missing = client.get(f"/api/artifacts/{uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["code"] == "artifact_not_found"

    missing_task = client.get(f"/api/tasks/{uuid4()}/artifacts")
    assert missing_task.status_code == 404
    assert missing_task.json()["code"] == "task_not_found"


def test_pull_request_record_api_lists_filters_pages_and_details(
    client: TestClient,
) -> None:
    """PR record 列表支持状态/cursor，详情不构造本地伪 URL。"""

    primary = seed_m6_evidence("pull-request", pull_request_count=2)
    secondary = seed_m6_evidence("other-task", pull_request_count=1)

    first_page = client.get(
        f"/api/tasks/{primary.task_id}/pull-request-records",
        params={"limit": 1},
    )
    assert first_page.status_code == 200, first_page.text
    first_body = first_page.json()
    assert len(first_body["items"]) == 1
    assert first_body["page"]["next_cursor"] == "1"

    second_page = client.get(
        f"/api/tasks/{primary.task_id}/pull-request-records",
        params={"limit": 10, "cursor": "1"},
    )
    assert second_page.status_code == 200, second_page.text
    records = [*first_body["items"], *second_page.json()["items"]]
    assert {item["task_id"] for item in records} == {
        str(primary.task_id)
    }
    assert str(secondary.pull_request_record_ids[0]) not in {
        item["id"] for item in records
    }
    assert {item["status"] for item in records} == {
        "open",
        "superseded",
    }

    open_records = client.get(
        f"/api/tasks/{primary.task_id}/pull-request-records",
        params={"status": "open"},
    )
    assert open_records.status_code == 200, open_records.text
    assert len(open_records.json()["items"]) == 1
    open_record = open_records.json()["items"][0]
    assert open_record["url"] is None
    assert all(
        not changed["path"].startswith(("/", "\\"))
        for changed in open_record["changed_files_json"]
    )

    detail = client.get(
        f"/api/pull-request-records/{open_record['id']}"
    )
    assert detail.status_code == 200, detail.text
    assert detail.json() == open_record

    invalid_status = client.get(
        f"/api/tasks/{primary.task_id}/pull-request-records",
        params={"status": "unknown"},
    )
    assert invalid_status.status_code == 422

    missing = client.get(f"/api/pull-request-records/{uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["code"] == "pull_request_record_not_found"

    missing_task = client.get(
        f"/api/tasks/{uuid4()}/pull-request-records"
    )
    assert missing_task.status_code == 404
    assert missing_task.json()["code"] == "task_not_found"
