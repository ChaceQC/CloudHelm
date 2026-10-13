#!/usr/bin/env python3
"""Independent HTTP checks for the CloudHelm reference slice, revision r1.0."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


METHOD_REVISION = "reference-http-r1.1"
REQUIREMENT_REVISION = "reference-requirements-r1"
NOTE_FIELDS = {"id", "title", "body", "created_at", "updated_at"}
TITLE_120 = "__cloudhelm_ref_r1_title_120__" + "_" * (120 - len("__cloudhelm_ref_r1_title_120__"))
TITLE_1 = "\ue000"
BASELINE_TITLES = {
    "__cloudhelm_ref_r1_sort_z__",
    "__cloudhelm_ref_r1_sort_a__",
    "__cloudhelm_ref_r1_trim__",
    "__cloudhelm_ref_r1_patch__",
    "__cloudhelm_ref_r1_patch_updated__",
    TITLE_1,
    TITLE_120,
    "__cloudhelm_ref_r1_body_4000__",
    "__cloudhelm_ref_r1_body_default__",
}
PERSISTED_TITLE = "__cloudhelm_ref_r1_persisted_marker__"
PERSISTED_BODY = "cloudhelm-reference-http-r1-persistence-marker"
SECRET_SHAPES = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"\b(?:sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b"),
    re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|redis)://[^\s/@:]+:[^\s/@]+@"),
    re.compile(r'(?i)"(?:password|secret|token|authorization|api[_-]?key)"\s*:\s*"[^"\r\n]{8,}"'),
)


class CheckFailure(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


class ScriptSourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "script":
            source = dict(attrs).get("src")
            if source:
                self.sources.append(source)


class HttpClient:
    def __init__(self, base_url: str) -> None:
        try:
            parsed = urlsplit(base_url)
            hostname = parsed.hostname
            port = parsed.port
        except ValueError as error:
            raise CheckFailure("invalid local HTTP origin") from error
        if (parsed.scheme != "http" or hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username is not None or parsed.password is not None or "@" in parsed.netloc
                or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment or port is None):
            raise CheckFailure("base-url must be a local HTTP origin with an explicit port")
        self.base_url = f"http://{parsed.netloc}"
        self.origin = (parsed.scheme, parsed.netloc.lower())
        self.opener = build_opener(NoRedirect())

    def request(self, method: str, path: str, payload: object | None = None):
        headers = {"Accept": "application/json, text/html, application/javascript, text/javascript"}
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = Request(self.base_url + path, data=body, headers=headers, method=method)
        try:
            response = self.opener.open(req, timeout=8)
        except HTTPError as error:
            response = error
        except (URLError, TimeoutError, OSError) as error:
            raise CheckFailure("HTTP request did not complete") from error
        try:
            final = urlsplit(response.geturl())
            if (final.scheme, final.netloc.lower()) != self.origin:
                raise CheckFailure("response origin changed")
            data = response.read(8 * 1024 * 1024 + 1)
            if len(data) > 8 * 1024 * 1024:
                raise CheckFailure("response exceeded the method size limit")
            if any(pattern.search(data.decode("latin-1")) for pattern in SECRET_SHAPES):
                raise CheckFailure("response matched a credential-shaped literal check")
            return response.status, data, response.headers
        finally:
            response.close()


class Results:
    def __init__(self) -> None:
        self.passed: list[str] = []
        self.failed: list[str] = []

    def run(self, name: str, check):
        try:
            value = check()
        except Exception:
            self.failed.append(name)
            return None
        self.passed.append(name)
        return value

    def output(self, phase: str) -> int:
        result = {
            "method_revision": METHOD_REVISION,
            "requirement_revision": REQUIREMENT_REVISION,
            "phase": phase,
            "case_counts": {
                "total": len(self.passed) + len(self.failed),
                "passed": len(self.passed),
                "failed": len(self.failed),
            },
            "passed": not self.failed,
            "passed_cases": self.passed,
            "failed_cases": self.failed,
        }
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0 if not self.failed else 1


def require(condition: bool) -> None:
    if not condition:
        raise CheckFailure("assertion failed")


def json_value(response) -> object:
    try:
        return json.loads(response[1].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CheckFailure("response was not valid UTF-8 JSON") from error


def check_utc_iso8601(value: object) -> bool:
    if not isinstance(value, str) or "T" not in value or value.endswith("-00:00"):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)


def note_object(value: object) -> dict:
    require(isinstance(value, dict) and NOTE_FIELDS <= set(value))
    require(isinstance(value["id"], int) and not isinstance(value["id"], bool))
    require(isinstance(value["title"], str) and isinstance(value["body"], str))
    require(check_utc_iso8601(value["created_at"]) and check_utc_iso8601(value["updated_at"]))
    return value


def note_list(client: HttpClient) -> list[dict]:
    response = client.request("GET", "/api/notes")
    require(response[0] == 200)
    value = json_value(response)
    require(isinstance(value, list))
    notes = [note_object(item) for item in value]
    ids = [item["id"] for item in notes]
    require(ids == sorted(ids) and len(ids) == len(set(ids)))
    return notes


def expect_status(client: HttpClient, method: str, path: str, expected: int, payload=None):
    response = client.request(method, path, payload)
    require(response[0] == expected)
    return response


def create_note(client: HttpClient, title: str, body: str | None = "", owned_ids: set[int] | None = None) -> dict:
    payload = {"title": title}
    if body is not None:
        payload["body"] = body
    response = expect_status(client, "POST", "/api/notes", 201, payload)
    note = note_object(json_value(response))
    if owned_ids is not None:
        owned_ids.add(note["id"])
    return note


def cleanup_titles(client: HttpClient, titles: set[str], owned_ids: set[int]) -> None:
    ids = set(owned_ids)
    listing_error: Exception | None = None
    try:
        ids.update(item["id"] for item in note_list(client) if item["title"] in titles)
    except Exception as error:
        listing_error = error
    for note_id in sorted(ids):
        response = client.request("DELETE", f"/api/notes/{note_id}")
        require(response[0] in {204, 404})
    if listing_error is not None:
        raise listing_error


def run_baseline(client: HttpClient, result: Results) -> None:
    owned_ids: set[int] = set()
    result.run("REF-02-04.marker_cleanup_before", lambda: cleanup_titles(client, BASELINE_TITLES | {PERSISTED_TITLE}, set()))
    result.run("REF-06.health_200", lambda: expect_status(client, "GET", "/health", 200))
    result.run("REF-06.ready_200", lambda: expect_status(client, "GET", "/ready", 200))

    initial = result.run("REF-02-04.list_json_array_sorted_utc", lambda: note_list(client))
    known_ids = {item["id"] for item in initial} if initial else set()
    missing_id = 2_147_483_647
    while missing_id in known_ids:
        missing_id -= 1

    core = result.run(
        "REF-02-03.create_201_server_integer_id",
        lambda: create_note(client, "__cloudhelm_ref_r1_sort_z__", "crud body", owned_ids),
    )
    reverse = result.run(
        "REF-04.create_reverse_lexical_order_record",
        lambda: create_note(client, "__cloudhelm_ref_r1_sort_a__", "sort order", owned_ids),
    )
    if core and reverse:
        pair_list = result.run("REF-04.reverse_lexical_pair_list_sorted_by_id", lambda: note_list(client))
        if pair_list is not None:
            positions = {item["id"]: index for index, item in enumerate(pair_list)}
            ordered_pair_ids = sorted((core["id"], reverse["id"]))
            result.run("REF-04.reverse_lexical_pair_order", lambda: require(
                len(set(ordered_pair_ids)) == 2
                and all(note_id in positions for note_id in ordered_pair_ids)
                and positions[ordered_pair_ids[0]] < positions[ordered_pair_ids[1]]
            ))
    if core:
        result.run("REF-03.create_returns_title_body_utc_timestamps", lambda: require(
            core["title"] == "__cloudhelm_ref_r1_sort_z__" and core["body"] == "crud body"
        ))
        original = result.run(
            "REF-02.read_200_and_values",
            lambda: note_object(json_value(expect_status(client, "GET", f"/api/notes/{core['id']}", 200))),
        )
        if original:
            result.run("REF-02.read_values", lambda: require(
                original["title"] == "__cloudhelm_ref_r1_sort_z__" and original["body"] == "crud body"
            ))
        patch = result.run(
            "REF-02.patch_single_field_accepted",
            lambda: _patch_one_field(client, core["id"]),
        )
        if patch is not None:
            if patch[0] == 200:
                result.run("REF-02.patch_response_object", lambda: note_object(json_value(patch)))
        updated = result.run(
            "REF-02.patch_persisted_values_read_200",
            lambda: note_object(json_value(expect_status(client, "GET", f"/api/notes/{core['id']}", 200))),
        )
        if updated:
            result.run("REF-02.patch_values", lambda: require(
                updated["title"] == "__cloudhelm_ref_r1_patch_updated__" and updated["body"] == "crud body"
            ))
        result.run("REF-02.patch_empty_rejected_422", lambda: expect_status(
            client, "PATCH", f"/api/notes/{core['id']}", 422, {}
        ))
        result.run("REF-02.patch_unknown_field_rejected_422", lambda: expect_status(
            client, "PATCH", f"/api/notes/{core['id']}", 422, {"unknown": "x"}
        ))
        result.run("REF-02.patch_null_rejected_422", lambda: expect_status(
            client, "PATCH", f"/api/notes/{core['id']}", 422, {"title": None}
        ))
        result.run("REF-02.delete_204", lambda: expect_status(client, "DELETE", f"/api/notes/{core['id']}", 204))
        result.run("REF-02.deleted_read_404", lambda: expect_status(client, "GET", f"/api/notes/{core['id']}", 404))

    trim_input = " \t__cloudhelm_ref_r1_trim__\n "
    trimmed = result.run(
        "REF-03.title_trimmed_on_create",
        lambda: create_note(client, trim_input, "trim body", owned_ids),
    )
    if trimmed:
        result.run("REF-03.title_trimmed_value", lambda: require(trimmed["title"] == "__cloudhelm_ref_r1_trim__"))
        saved = result.run(
            "REF-03.trimmed_title_read_back",
            lambda: note_object(json_value(expect_status(client, "GET", f"/api/notes/{trimmed['id']}", 200))),
        )
        if saved:
            result.run("REF-03.trimmed_title_persisted", lambda: require(saved["title"] == "__cloudhelm_ref_r1_trim__"))

    for size, actual_title in ((1, TITLE_1), (120, TITLE_120)):
        created = result.run(
            f"REF-03.title_{size}_accepted",
            lambda actual_title=actual_title: create_note(client, actual_title, "", owned_ids),
        )
        if created:
            result.run(f"REF-03.title_{size}_accepted_length", lambda: require(
                len(created["title"]) == size and isinstance(created["id"], int)
            ))
    result.run("REF-03.title_121_rejected_422", lambda: expect_status(
        client, "POST", "/api/notes", 422, {"title": "t" * 121, "body": ""}
    ))
    result.run("REF-03.empty_title_rejected_422", lambda: expect_status(
        client, "POST", "/api/notes", 422, {"title": " \t ", "body": ""}
    ))
    result.run("REF-03.missing_post_title_rejected_422", lambda: expect_status(
        client, "POST", "/api/notes", 422, {"body": ""}
    ))

    body_4000 = result.run(
        "REF-03.body_4000_accepted",
        lambda: create_note(client, "__cloudhelm_ref_r1_body_4000__", "b" * 4000, owned_ids),
    )
    if body_4000:
        result.run("REF-03.body_4000_retained", lambda: require(len(body_4000["body"]) == 4000))
    result.run("REF-03.body_4001_rejected_422", lambda: expect_status(
        client, "POST", "/api/notes", 422, {"title": "body too long", "body": "b" * 4001}
    ))
    result.run("REF-03.post_body_defaults_empty", lambda: require(
        create_note(client, "__cloudhelm_ref_r1_body_default__", None, owned_ids)["body"] == ""
    ))

    result.run("REF-02.missing_get_404", lambda: expect_status(client, "GET", f"/api/notes/{missing_id}", 404))
    result.run("REF-02.missing_patch_404", lambda: expect_status(
        client, "PATCH", f"/api/notes/{missing_id}", 404, {"title": "ghost"}
    ))
    result.run("REF-02.missing_delete_404", lambda: expect_status(client, "DELETE", f"/api/notes/{missing_id}", 404))

    listed = result.run("REF-04.list_sorted_after_writes", lambda: note_list(client))
    if listed is not None:
        titles = {item["title"] for item in listed}
        # sort_z was intentionally deleted above; the remaining reserved records must be present.
        result.run("REF-04.list_contains_live_boundary_records", lambda: require(
            {"__cloudhelm_ref_r1_sort_a__", "__cloudhelm_ref_r1_trim__", TITLE_1, TITLE_120,
             "__cloudhelm_ref_r1_body_4000__", "__cloudhelm_ref_r1_body_default__"} <= titles
        ))

    html = result.run("REF-01.static_root_html_200", lambda: _read_root_html(client))
    if html is not None:
        result.run("REF-01.same_origin_javascript_bundle_200", lambda: _check_script_bundle(client, html))
    result.run(
        "REF-02-04.marker_cleanup_after",
        lambda: cleanup_titles(client, BASELINE_TITLES | {PERSISTED_TITLE}, owned_ids),
    )


def _read_root_html(client: HttpClient) -> tuple[str, str]:
    response = client.request("GET", "/")
    require(response[0] == 200 and response[1]
            and "text/html" in response[2].get("Content-Type", "").lower())
    return response[1].decode("utf-8"), response[2].get("Content-Type", "")


def _patch_one_field(client: HttpClient, note_id: int):
    response = client.request("PATCH", f"/api/notes/{note_id}", {"title": "__cloudhelm_ref_r1_patch_updated__"})
    require(response[0] in {200, 204})
    return response


def _check_script_bundle(client: HttpClient, html: tuple[str, str]) -> None:
    parser = ScriptSourceParser()
    parser.feed(html[0])
    for source in parser.sources:
        absolute = urljoin(client.base_url + "/", source)
        parsed = urlsplit(absolute)
        if (parsed.scheme, parsed.netloc.lower()) != client.origin:
            continue
        response = client.request("GET", parsed.path + ("?" + parsed.query if parsed.query else ""))
        mime = response[2].get("Content-Type", "").lower()
        if response[0] == 200 and response[1] and any(x in mime for x in ("javascript", "ecmascript")):
            return
    raise CheckFailure("no same-origin JavaScript bundle responded successfully")


def run_seed(client: HttpClient, result: Results) -> None:
    result.run("REF-04.seed_ready_200", lambda: expect_status(client, "GET", "/ready", 200))
    result.run("REF-04.seed_clear_exact_reserved_marker", lambda: cleanup_titles(client, {PERSISTED_TITLE}, set()))

    def create_seed() -> dict:
        note = create_note(client, PERSISTED_TITLE, PERSISTED_BODY)
        require(note["title"] == PERSISTED_TITLE and note["body"] == PERSISTED_BODY)
        return note

    result.run("REF-04.seed_create_fixed_persistence_marker", create_seed)


def run_verify_persisted(client: HttpClient, result: Results) -> None:
    marker: dict | None = None

    def verify() -> dict:
        notes = note_list(client)
        matches = [item for item in notes if item["title"] == PERSISTED_TITLE]
        require(len(matches) == 1 and matches[0]["body"] == PERSISTED_BODY)
        return matches[0]

    marker = result.run("REF-04.persisted_marker_present_after_api_restart", verify)
    result.run("REF-04.persisted_marker_cleanup_exact", lambda: cleanup_titles(
        client, {PERSISTED_TITLE}, {marker["id"]} if marker else set()
    ))


def run_not_ready(client: HttpClient, result: Results) -> None:
    result.run("REF-06.health_200_while_dependency_unavailable", lambda: expect_status(client, "GET", "/health", 200))
    result.run("REF-06.ready_503_while_dependency_unavailable", lambda: expect_status(client, "GET", "/ready", 503))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run independent reference HTTP checks.")
    parser.add_argument("--base-url", required=True, help="Local HTTP origin, for example http://127.0.0.1:8000")
    parser.add_argument("--phase", choices=("baseline", "seed", "verify-persisted", "not-ready"), default="baseline")
    args = parser.parse_args()
    result = Results()
    try:
        client = HttpClient(args.base_url)
    except CheckFailure:
        print(json.dumps({
            "method_revision": METHOD_REVISION,
            "requirement_revision": REQUIREMENT_REVISION,
            "phase": args.phase,
            "case_counts": {"total": 1, "passed": 0, "failed": 1},
            "passed": False,
            "passed_cases": [],
            "failed_cases": ["CLI.base_url_local_http_origin"],
        }, separators=(",", ":")))
        return 2
    if args.phase == "baseline":
        run_baseline(client, result)
    elif args.phase == "seed":
        run_seed(client, result)
    elif args.phase == "verify-persisted":
        run_verify_persisted(client, result)
    else:
        run_not_ready(client, result)
    return result.output(args.phase)


if __name__ == "__main__":
    sys.exit(main())
