from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from academia_os.web import DashboardServer
from tests.test_action_service import workspace
from tests.test_web import request


@contextmanager
def server_for(profile: Path, tmp_path: Path) -> Iterator[DashboardServer]:
    server = DashboardServer(port=0, profile=profile, dist_dir=tmp_path / "dist")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def post(server, path: str, value: dict) -> tuple[int, dict[str, str], bytes]:
    return request(server, "POST", path, body=json.dumps(value).encode("utf-8"), headers={"Content-Type": "application/json"})


def test_action_routes_propose_list_execute_and_discard(tmp_path: Path) -> None:
    profile, course = workspace(tmp_path)
    with server_for(profile, tmp_path) as web:
        status, _, payload = request(web, "GET", "/api/v1/actions/pending")
        assert status == 200
        assert json.loads(payload)["actions"] == []

        status, _, payload = post(web, "/api/v1/actions/propose", {
            "action_type": "grade_record",
            "details": {"course_id": course.name, "values": {"kind": "essay", "title": "First Essay", "status": "graded", "grade": "82%"}},
        })
        assert status == 200
        inline = json.loads(payload)
        assert inline["tier"] == "inline"

        status, _, payload = request(web, "GET", "/api/v1/actions/pending")
        assert [item["proposal_id"] for item in json.loads(payload)["actions"]] == [inline["proposal_id"]]

        status, _, payload = post(web, "/api/v1/actions/execute", {"proposal_id": inline["proposal_id"]})
        assert status == 200
        assert json.loads(payload)["status"] == "verified"

        root = tmp_path / "University"
        file = (course / "04_READINGS" / "week1.md").relative_to(root).as_posix()
        status, _, payload = post(web, "/api/v1/actions/propose", {"action_type": "file_trash", "details": {"path": file}})
        assert status == 200
        review = json.loads(payload)
        assert review["tier"] == "review"

        refused, _, _ = post(web, "/api/v1/actions/execute", {"proposal_id": review["proposal_id"]})
        assert refused == 403
        assert (course / "04_READINGS" / "week1.md").is_file()

        discarded, _, _ = post(web, "/api/v1/actions/discard", {"proposal_id": review["proposal_id"]})
        assert discarded == 200


def test_action_routes_reject_bad_input(tmp_path: Path) -> None:
    profile, _ = workspace(tmp_path)
    with server_for(profile, tmp_path) as web:
        status, _, _ = post(web, "/api/v1/actions/propose", {"action_type": "file_trash"})
        assert status == 400
        status, _, _ = post(web, "/api/v1/actions/propose", {"action_type": "not_an_action", "details": {}})
        assert status == 422
        status, _, _ = post(web, "/api/v1/actions/execute", {})
        assert status == 400
        status, _, _ = post(web, "/api/v1/actions/execute", {"proposal_id": "missing-action"})
        assert status == 404
