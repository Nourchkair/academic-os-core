from __future__ import annotations

import json
from pathlib import Path

from academia_os.agent_sessions import AgentSessionStore
from tests.test_web import request, running_server


def post(server, path: str, value: dict) -> tuple[int, dict[str, str], bytes]:
    return request(server, "POST", path, body=json.dumps(value).encode("utf-8"), headers={"Content-Type": "application/json"})


def session_payload() -> dict:
    return {
        "id": "session-web-0001",
        "title": "Week plan",
        "courseId": "",
        "courseLabel": "All Academia",
        "messages": [{"role": "user", "content": "What is due this week?"}],
        "sourceIds": [],
        "excludedCourseSourceIds": [],
        "updatedAt": "2026-11-13T12:00:00+00:00",
    }


def test_agent_session_routes(tmp_path: Path) -> None:
    with running_server(tmp_path) as web:
        web.agent_sessions = AgentSessionStore(tmp_path / "agent_sessions")

        status, _, payload = request(web, "GET", "/api/v1/agent/sessions")
        assert status == 200
        assert json.loads(payload)["sessions"] == []

        status, _, payload = post(web, "/api/v1/agent/sessions/save", {"session": session_payload()})
        assert status == 200
        assert json.loads(payload)["session"]["id"] == "session-web-0001"

        status, _, payload = request(web, "GET", "/api/v1/agent/sessions")
        assert status == 200
        sessions = json.loads(payload)["sessions"]
        assert [item["id"] for item in sessions] == ["session-web-0001"]
        assert sessions[0]["preview"] == "What is due this week?"

        status, _, payload = request(web, "GET", "/api/v1/agent/sessions/load?id=session-web-0001")
        assert status == 200
        assert json.loads(payload)["session"]["messages"][0]["content"] == "What is due this week?"

        status, _, payload = post(web, "/api/v1/agent/sessions/delete", {"id": "session-web-0001"})
        assert status == 200
        assert json.loads(payload)["deleted"] is True
        assert request(web, "GET", "/api/v1/agent/sessions")[2]
        assert json.loads(request(web, "GET", "/api/v1/agent/sessions")[2])["sessions"] == []


def test_agent_session_routes_reject_bad_input(tmp_path: Path) -> None:
    with running_server(tmp_path) as web:
        web.agent_sessions = AgentSessionStore(tmp_path / "agent_sessions")

        status, _, payload = request(web, "GET", "/api/v1/agent/sessions/load?id=missing-session")
        assert status == 404

        status, _, payload = post(web, "/api/v1/agent/sessions/save", {"session": {**session_payload(), "id": "../escape"}})
        assert status == 400

        status, _, payload = post(web, "/api/v1/agent/sessions/save", {})
        assert status == 400

        status, _, payload = post(web, "/api/v1/agent/sessions/delete", {})
        assert status == 400
