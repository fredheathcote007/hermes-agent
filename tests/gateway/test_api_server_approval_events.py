"""Contracts for approval events emitted by the API server adapter."""

from gateway.platforms.api_server import _approval_request_event


def test_api_approval_event_keeps_complete_mcp_payload_and_cost_notice():
    command = ('MCP untrusted call {"server":"srv","tool":"paid_render",'
               '"arguments":{"target":"/production/database","operation":"delete"}}')
    description = (
        "MCP untrusted call; approve once only after reviewing the complete payload. "
        "Costs about 40 credits. This chat has used about 80 credits on 'srv' (limit 100)."
    )
    event = _approval_request_event("run-1", {"command": command, "description": description})

    assert event["event"] == "approval.request"
    assert event["command"] == command
    assert '"target":"/production/database"' in event["command"]
    assert '"operation":"delete"' in event["command"]
    assert "Costs about 40 credits." in event["description"]
    assert "used about 80 credits" in event["description"]
