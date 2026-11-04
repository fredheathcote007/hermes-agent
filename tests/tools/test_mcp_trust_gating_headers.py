"""Header-preview regressions for the MCP untrusted-call approval gate."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools import mcp_tool
from tools import mcp_tool_handlers as _mcp_handlers


class _FakeContentBlock:
    def __init__(self, text: str, block_type: str = "text"):
        self.text = text
        self.type = block_type


class _FakeCallToolResult:
    def __init__(self, content, is_error=False, structuredContent=None):
        self.content = content
        self.isError = is_error
        self.structuredContent = structuredContent


def _fake_run_on_mcp_loop(coro_or_factory, timeout=30):
    coro = coro_or_factory() if callable(coro_or_factory) else coro_or_factory
    loop = asyncio.new_event_loop()
    try:
        async def _install_lock_and_run():
            for srv in list(mcp_tool._servers.values()):
                if getattr(srv, "_rpc_lock", None) is None:
                    srv._rpc_lock = asyncio.Lock()
            return await coro

        return loop.run_until_complete(_install_lock_and_run())
    finally:
        loop.close()


@pytest.fixture
def fake_session():
    session = MagicMock()
    session.call_tool = AsyncMock(
        return_value=_FakeCallToolResult(content=[_FakeContentBlock("ok")])
    )
    server = SimpleNamespace(session=session, _rpc_lock=None)
    with patch.dict(mcp_tool._servers, {"srv": server}), \
         patch("tools.mcp_tool_loop._run_on_mcp_loop", side_effect=_fake_run_on_mcp_loop), \
         patch.dict(mcp_tool._server_error_counts, {}, clear=True):
        yield session


@pytest.fixture(autouse=True)
def _clean_trust_state():
    with patch.dict(mcp_tool._server_trust_levels, {}, clear=True), \
         patch.dict(mcp_tool._tool_read_only_hints, {}, clear=True):
        yield


def _set_trust(server: str, trust: str):
    mcp_tool._server_trust_levels[server] = trust


@pytest.mark.parametrize(
    ("args", "secret"),
    [
        (["Cookie", "synthetic-cookie-A", 1, 2, "Authorization", "synthetic-auth-B"],
         "synthetic-auth-B"),
        (["Accept", "abc", None, None, "Cookie", "synthetic-cookie-A"],
         "synthetic-cookie-A"),
        (["Accept", "abc", "x", "Cookie", "synthetic-cookie-A"],
         "synthetic-cookie-A"),
        ({"x": "https://e.org/?x=1&Cookie: synthetic-cookie-A"}, "synthetic-cookie-A"),
        ({"x": "https://e.org/b;Cookie: synthetic-cookie-A"}, "synthetic-cookie-A"),
        ({"x": "https://e.org/b,Cookie: synthetic-cookie-A"}, "synthetic-cookie-A"),
    ],
    ids=[
        "dirty-flat-metadata",
        "dirty-flat-null",
        "dirty-flat-odd-offset",
        "url-query-punctuation",
        "url-semicolon-punctuation",
        "url-comma-punctuation",
    ],
)
def test_credential_disclosures_are_denied_before_trust_preview(args, secret):
    """Ambiguous flat headers and URL path suffixes cannot enter either preview surface."""
    cli_preview = _mcp_handlers._format_trust_gate_arguments(args)
    gateway_preview = _mcp_handlers._format_gateway_trust_gate_command("srv", "write_file", args)

    assert cli_preview is None
    assert gateway_preview is None
    assert secret not in (cli_preview or "")
    assert secret not in (gateway_preview or "")


@pytest.mark.parametrize(
    "text",
    [
        "https://auth.example.org:8443/path",
        "https://[2001:db8::1]:8443/path",
        r"C:\\Users\\Alice\\auth.txt",
        "ghcr.io/myorg/auth-service:v1.0.0",
        "long prose about authorization: this is not a header",
    ],
    ids=["url-port", "url-ipv6", "windows-path", "container-registry", "benign-prose"],
)
def test_valid_uri_ports_paths_and_benign_text_remain_previewable(text):
    args = {"x": text}
    assert _mcp_handlers._format_trust_gate_arguments(args) is not None
    assert _mcp_handlers._format_gateway_trust_gate_command("srv", "write_file", args) is not None


@pytest.mark.parametrize(
    ("args", "secret", "expected"),
    [
        ({"data": "https://example.org/\nCookie: synthetic-cookie-value"},
         "synthetic-cookie-value", None),
        ({"data": "https://example.org/\nX-Amz-Security-Token: synthetic-token-value"},
         "synthetic-token-value", None),
        ({"data": "https://example.org/foo Cookie: synthetic-cookie-value"},
         "synthetic-cookie-value", None),
        ({"name": "x_auth_data", "value": "synthetic-secret-value"},
         "synthetic-secret-value", "dict"),
        (["x_auth_data", "synthetic-secret-value"], "synthetic-secret-value", "list"),
    ],
    ids=["url-newline-cookie", "url-newline-token", "url-space-cookie", "snake-pair-dict", "snake-pair-list"],
)
def test_bugbot_credential_values_never_enter_trust_preview(args, secret, expected):
    preview = _mcp_handlers._format_trust_gate_arguments(args)
    assert secret not in (preview or "")
    if expected is None:
        assert preview is None
    elif expected == "dict":
        assert json.loads(preview)["value"] == "***"
    else:
        assert json.loads(preview)[1] == "***"


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ({"headers": ["Cookie", "synthetic-cookie-A", "Authorization", "synthetic-auth-B"]}, "masked"),
        (["Cookie", "synthetic-cookie-A", "Authorization", "synthetic-auth-B"], "masked"),
        ({"name": "Cookie", "content": ["synthetic-cookie-A", "synthetic-cookie-B"]}, "denied"),
        ({"name": "Authorization", "payload": ["synthetic-auth-A"]}, "denied"),
        ({"name": "Cookie", "body": ("synthetic-cookie-A", "synthetic-cookie-B")}, "denied"),
    ],
    ids=["nested-header-list", "header-list", "content-list", "payload-list", "body-tuple"],
)
def test_ambiguous_secret_sequences_do_not_leak_before_consent_rpc_and_cost(
    fake_session, args, expected
):
    from tools import mcp_tool_costs

    preview = _mcp_handlers._format_trust_gate_arguments(args)
    gateway_preview = _mcp_handlers._format_gateway_trust_gate_command("srv", "write_file", args)
    if expected == "masked":
        assert preview is not None
        assert gateway_preview is not None
        for secret in ("synthetic-cookie-A", "synthetic-auth-B"):
            assert secret not in preview
            assert secret not in gateway_preview
        return

    _set_trust("srv", "untrusted")
    policy = mcp_tool_costs.parse_cost_policy({"write_file": 40}, 100, None, where="test MCP server")
    assert preview is None
    assert gateway_preview is None

    with patch.dict(mcp_tool._server_cost_policies, {"srv": policy}, clear=True), \
         patch.dict(mcp_tool_costs._spent, {}, clear=True), \
         patch("tools.approval_prompt.request_elicitation_consent", return_value="accept") as consent:
        raw = _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

    consent.assert_not_called()
    fake_session.call_tool.assert_not_awaited()
    assert mcp_tool_costs._spent == {}
    assert "synthetic-" not in raw
    assert "error" in json.loads(raw)


def test_generic_auth_payload_sequence_control_stays_visible():
    args = {"name": "auth", "payload": {"target": "/prod", "op": "delete"}}
    preview = _mcp_handlers._format_trust_gate_arguments(args)
    assert preview is not None
    assert json.loads(preview) == args


def test_credential_header_sibling_shapes_mask_opaque_values():
    secret_cases = (
        {"k": "Cookie", "v": "synthetic-kv"},
        {"name": "Set-Cookie", "values": ["synthetic-values"]},
        {"name": "Cookie", "payload": "synthetic-payload"},
        {"name": "Cookie", "text": "synthetic-text"},
        {"name": "Cookie", "body": "synthetic-body"},
        {"name": "Cookie", "raw": "synthetic-raw"},
        {"name": "Cookie", "contents": "synthetic-contents"},
        {"name": "Cookie", "valueString": "synthetic-value-string"},
        {"label": "Authorization", "value": "synthetic-label-value"},
        {"field": "Authorization", "value": "synthetic-field-value"},
        ["Cookie", "synthetic-array-value", "Path=/synthetic-path"],
    )
    for args in secret_cases:
        cli_preview = _mcp_handlers._format_trust_gate_arguments(args)
        gateway_preview = _mcp_handlers._format_gateway_trust_gate_command("srv", "do", args)
        assert cli_preview is not None
        assert gateway_preview is not None
        assert all(secret not in cli_preview and secret not in gateway_preview for secret in (
            "synthetic-kv", "synthetic-values", "synthetic-payload", "synthetic-text",
            "synthetic-body", "synthetic-raw", "synthetic-contents", "synthetic-value-string",
            "synthetic-label-value", "synthetic-field-value", "synthetic-array-value",
        ))
        if isinstance(args, list):
            assert "Path=/synthetic-path" in cli_preview
            assert "Path=/synthetic-path" in gateway_preview


def test_authorization_and_cookie_header_shapes_are_masked(fake_session):
    _set_trust("srv", "untrusted")
    args = {
        "headers": {
            "Proxy-Authorization": "Basic proxy-opaque-secret",
            "X-Authorization": "Bearer x-opaque-secret",
            "X-Authentication": "x-authentication-secret",
            "x-auth-data": "x-auth-data-secret",
            "X-Auth-Token": "x-auth-token-secret",
            "Proxy-Authentication": "proxy-authentication-secret",
            "Cookie": "session=cookie-opaque-secret",
            "Set-Cookie": "sid=set-cookie-opaque-secret; HttpOnly",
            "X-Custom-Auth": "custom-opaque-secret",
            "X-Request-Id": "request-visible",
        },
        "header_list": [
            {"name": "Proxy-Authorization", "value": "Basic pair-proxy-secret"},
            {"name": "X-Authorization", "value": "Bearer pair-x-secret"},
            {"name": "X-Authentication", "value": "pair-authentication-secret"},
            {"name": "x-auth-data", "value": "pair-auth-data-secret"},
            {"name": "X-Auth-Token", "value": "pair-auth-token-secret"},
            {"name": "Proxy-Authentication", "value": "pair-proxy-authentication-secret"},
            {"name": "Cookie", "value": "pair-cookie-secret"},
            {"name": "Set-Cookie", "value": "pair-set-cookie-secret"},
            {"name": "X-Request-Id", "value": "pair-visible"},
        ],
        "cookie_metadata": {"name": "session", "domain": "example.test", "cookie_value": "cookie-value-secret"},
    }
    with patch("tools.approval_prompt.request_elicitation_consent", return_value="decline") as consent:
        _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

    consent.assert_called_once()
    message = consent.call_args.args[0]
    assert all(secret not in message for secret in (
        "proxy-opaque-secret", "x-opaque-secret", "x-authentication-secret", "x-auth-data-secret",
        "x-auth-token-secret", "proxy-authentication-secret", "cookie-opaque-secret",
        "set-cookie-opaque-secret", "custom-opaque-secret", "pair-proxy-secret", "pair-x-secret",
        "pair-authentication-secret", "pair-auth-data-secret", "pair-auth-token-secret",
        "pair-proxy-authentication-secret", "pair-cookie-secret", "pair-set-cookie-secret",
        "cookie-value-secret",
    ))
    assert '"X-Request-Id": "request-visible"' in message
    assert '"value": "pair-visible"' in message
    assert '"domain": "example.test"' in message
    fake_session.call_tool.assert_not_awaited()


def test_authorization_variant_values_are_masked_in_structured_headers(fake_session):
    _set_trust("srv", "untrusted")
    args = {
        "headers": {
            "X-Authorization-Data": "x-authorization-data-secret",
            "Authorization-Header": "authorization-header-secret",
            "authorization_code": "authorization-code-secret",
            "author": "Alice",
        },
        "header_list": [{"name": "Authorization-Header", "value": "pair-authorization-header-secret"}],
    }
    with patch("tools.approval_prompt.request_elicitation_consent", return_value="decline") as consent:
        _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

    consent.assert_called_once()
    message = consent.call_args.args[0]
    assert all(secret not in message for secret in (
        "x-authorization-data-secret", "authorization-header-secret",
        "authorization-code-secret", "pair-authorization-header-secret",
    ))
    assert '"author": "Alice"' in message
    fake_session.call_tool.assert_not_awaited()


def test_mixed_case_header_pair_keys_mask_credentials(fake_session):
    _set_trust("srv", "untrusted")
    args = {
        "header_list": [
            {"Name": "Authorization", "Value": "pascal-bearer-secret"},
            {"NAME": "Cookie", "VALUE": "upper-cookie-secret"},
            {"NaMe": "Authorisation", "vAlUe": "uk-auth-secret"},
            {"header_name": "X-Auth-Data", "value": "header-name-secret"},
            {"key": "X-Author", "value": "Alice"},
        ]
    }
    with patch("tools.approval_prompt.request_elicitation_consent", return_value="decline") as consent:
        _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

    consent.assert_called_once()
    message = consent.call_args.args[0]
    assert all(secret not in message for secret in (
        "pascal-bearer-secret", "upper-cookie-secret", "uk-auth-secret", "header-name-secret",
    ))
    assert '"value": "Alice"' in message
    fake_session.call_tool.assert_not_awaited()
