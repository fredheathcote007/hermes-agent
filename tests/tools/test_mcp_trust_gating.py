"""Tests for MCP tool trust-tier gating and transport replay safety.

Security boundary under test: native MCP tools on servers configured
``trust: untrusted`` must route through the existing dangerous-approval
path before the RPC fires. Full-trust tools retain their existing behavior;
an untrusted server's annotation cannot relax that gate.

Adversarial notes encoded in these tests:
- ``readOnlyHint`` is a HINT supplied by the (potentially hostile) server and
  never relaxes gating for an untrusted server.
- Missing annotations ⇒ not replay-safe (fail closed).
- Unknown/garbage ``trust`` values ⇒ treated as untrusted (fail closed).
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools import mcp_tool
from tools import mcp_tool_handlers as _mcp_handlers
from tools import mcp_tool_registration as _mcp_registration


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
    """Patch a fake connected server + MCP loop; yield its session mock."""
    session = MagicMock()
    session.call_tool = AsyncMock(
        return_value=_FakeCallToolResult(content=[_FakeContentBlock("ok")])
    )
    server = SimpleNamespace(session=session, _rpc_lock=None)
    with patch.dict(mcp_tool._servers, {"srv": server}), \
         patch("tools.mcp_tool_loop._run_on_mcp_loop",
               side_effect=_fake_run_on_mcp_loop), \
         patch.dict(mcp_tool._server_error_counts, {}, clear=True):
        yield session


@pytest.fixture(autouse=True)
def _clean_trust_state():
    """Isolate the module-level trust metadata between tests."""
    with patch.dict(mcp_tool._server_trust_levels, {}, clear=True), \
         patch.dict(mcp_tool._tool_read_only_hints, {}, clear=True):
        yield


def _set_trust(server: str, trust: str):
    mcp_tool._server_trust_levels[server] = trust


def _set_read_only(server: str, tool: str, value: bool):
    mcp_tool._tool_read_only_hints.setdefault(server, {})[tool] = value


def _escape_header_blob_layers(text: str, layers: int) -> str:
    for _ in range(layers):
        text = text.replace("\\", "\\\\").replace('"', '\\"')
    return text


_ESCAPED_HEADER_CASES = []
for _header_name, _encoded_name, _encoded_colon in (
    ("Cookie", r"\u0043ookie", r"\u003a"),
    ("Authorization", r"\u0041uthorization", r"\x3a"),
    ("Authorisation", r"\x41uthorisation", ":"),
    ("secretkey", r"s\u0065cretkey", r"\u003a"),
    ("X-Auth-Data", r"\u0058-Auth-Data", r"\x3a"),
):
    for _separator in (" ", "\n", "\r", "\t", "\r\n", r"\u0020", r"\u000a", r"\x20"):
        for _layers in range(6):
            _header_blob = (
                f'{{"{_encoded_name}"{_separator}{_encoded_colon} '
                f'"synthetic-{_header_name}-{_layers}"}}'
            )
            _ESCAPED_HEADER_CASES.append(
                pytest.param(
                    _escape_header_blob_layers(_header_blob, _layers),
                    id=f"{_header_name}-{_layers}-{_separator.encode().hex()}",
                )
            )


_INVISIBLE_SECRET_NAME_MARKS = (
    "\u200b",  # ZERO WIDTH SPACE
    "\u200e",  # LEFT-TO-RIGHT MARK
    "\u2060",  # WORD JOINER
    "\ufeff",  # ZERO WIDTH NO-BREAK SPACE
    "\ufe0f",  # VARIATION SELECTOR-16
    "\u034f",  # COMBINING GRAPHEME JOINER
    "\u3164",  # HANGUL FILLER
    "\u115f",  # HANGUL CHOSEONG FILLER
    "\u1160",  # HANGUL JUNGSEONG FILLER
    "\uffa0",  # HALFWIDTH HANGUL FILLER
    "\u180b",  # MONGOLIAN FREE VARIATION SELECTOR THREE
    "\x00",    # NUL
    "\x08",    # BACKSPACE
    "\u2800",  # BRAILLE PATTERN BLANK
)


_UNSTRUCTURED_SECRET_HEADER_NAME_FORMS = []
for _raw_name, _escaped_name in (
    ("Authorization\u2065", r"Authorization\u2065"),
    ("Authorization\ufff0", r"Authorization\ufff0"),
    ("Authorization\U000e0000", r"Authorization\U000e0000"),
    ("api\u2011key", r"api\u2011key"),
    ("api\u2010key", r"api\u2010key"),
    ("api\u2013key", r"api\u2013key"),
    ("api\u203fkey", r"api\u203fkey"),
    ("api\uff0dkey", r"api\uff0dkey"),
    ("api/key", r"api\/key"),
):
    for _name_form in (_raw_name, _escaped_name):
        for _layers in (0, 2):
            _UNSTRUCTURED_SECRET_HEADER_NAME_FORMS.append(
                pytest.param(
                    _escape_header_blob_layers(
                        f'{{"{_name_form}": "synthetic-header-secret"}}', _layers
                    ),
                    id=f"{ord(_raw_name[3]) if _raw_name.startswith('api') else ord(_raw_name[-1]):x}-layers-{_layers}",
                )
            )


_RFC7230_HEADER_NAME_SEPARATORS = "!#$%&'*+-.^_`|~"
_UNICODE_HEADER_NAME_SEPARATORS = (
    "\u00b7",  # Po MIDDLE DOT
    "\u2011",  # Pd NON-BREAKING HYPHEN
    "\u203f",  # Pc UNDERTIE
    "\u2205",  # Sm EMPTY SET
    "\u20ac",  # Sc EURO SIGN
    "\u02c2",  # Sk MODIFIER LETTER LEFT ARROWHEAD
    "\u2605",  # So BLACK STAR
    "\u2065",  # Cn (NFKC classification ignores it)
    "=", "[", "]",
)


@pytest.mark.parametrize(
    "separator",
    _RFC7230_HEADER_NAME_SEPARATORS + "".join(_UNICODE_HEADER_NAME_SEPARATORS),
)
def test_unstructured_header_name_separator_parity_before_consent_and_cost(
    fake_session, separator
):
    """Every classifier-sensitive api{separator}key header is denied before approval."""
    from tools import mcp_tool_costs

    _set_trust("srv", "untrusted")
    header_name = f"api{separator}key"
    assert _mcp_handlers._is_secret_argument_name(header_name)
    secret = f"SYNTHSECRETvalue-{ord(separator):x}"
    args = {"header_block": f'{{"{header_name}": "{secret}"}}'}
    policy = mcp_tool_costs.parse_cost_policy(
        {"write_file": 40}, 100, None, where="test MCP server"
    )
    assert _mcp_handlers._format_trust_gate_arguments(args) is None
    assert _mcp_handlers._format_gateway_trust_gate_command("srv", "write_file", args) is None
    with patch.dict(mcp_tool._server_cost_policies, {"srv": policy}, clear=True), \
         patch.dict(mcp_tool_costs._spent, {}, clear=True), \
         patch("tools.approval_prompt.request_elicitation_consent", return_value="accept") as consent:
        result = _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

    consent.assert_not_called()
    fake_session.call_tool.assert_not_awaited()
    assert mcp_tool_costs._spent == {}
    assert secret not in result


@pytest.mark.parametrize(
    "header_blob",
    [
        '{"api\\u002bkey": "nested-plus-secret"}',
        '{"api\\u005cu002bkey": "nested-double-encoded-secret"}',
        '{"api\\uff0bkey": "fullwidth-plus-secret"}',
        '{"api\\u2011key": "nonbreaking-hyphen-secret"}',
        '{"api\\u2065key": "invisible-mark-secret"}',
    ],
)
def test_nested_encoded_unstructured_header_names_fail_closed_before_consent_and_cost(
    fake_session, header_blob
):
    """Escape decoding and NFKC classification keep raw header previews in parity."""
    from tools import mcp_tool_costs

    _set_trust("srv", "untrusted")
    policy = mcp_tool_costs.parse_cost_policy(
        {"write_file": 40}, 100, None, where="test MCP server"
    )
    args = {"header_block": header_blob}
    assert _mcp_handlers._format_trust_gate_arguments(args) is None
    assert _mcp_handlers._format_gateway_trust_gate_command("srv", "write_file", args) is None
    with patch.dict(mcp_tool._server_cost_policies, {"srv": policy}, clear=True), \
         patch.dict(mcp_tool_costs._spent, {}, clear=True), \
         patch("tools.approval_prompt.request_elicitation_consent", return_value="accept") as consent:
        result = _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

    consent.assert_not_called()
    fake_session.call_tool.assert_not_awaited()
    assert mcp_tool_costs._spent == {}
    assert "secret" not in result


@pytest.mark.parametrize(
    "text",
    [
        "author_key: Alice",
        "authority_key: example.test",
        "capital_key: Paris; semicolon is ordinary text",
        "ssh_public_key: ssh-ed25519 AAAA",
        "café: résumé::normal Unicode::still readable",
        "a:" * 300,
    ],
)
def test_benign_colon_rich_text_remains_previewable(text):
    """Benign labels and repeated delimiters stay readable within the bounded preview."""
    args = {"description": text}
    cli_preview = _mcp_handlers._format_trust_gate_arguments(args)
    gateway_preview = _mcp_handlers._format_gateway_trust_gate_command("srv", "write_file", args)

    assert cli_preview is not None
    assert json.loads(cli_preview) == args
    if len(text) < 600:
        assert gateway_preview is not None
        assert json.loads(gateway_preview.removeprefix("MCP untrusted call "))["arguments"] == args


def test_pathological_header_name_span_fails_closed():
    """A candidate name beyond the bounded scan cannot reach an approval preview."""
    long_name = "a" * (_mcp_handlers._HEADER_NAME_CANDIDATE_MAX_CHARS + 1)
    args = {"header_block": f"{long_name}: opaque"}

    assert _mcp_handlers._format_trust_gate_arguments(args) is None
    assert _mcp_handlers._format_gateway_trust_gate_command("srv", "write_file", args) is None


def test_header_scanner_stops_at_prose_boundaries_but_finds_embedded_credentials():
    """Whitespace is prose structure, not part of the header name."""
    assert _mcp_handlers._format_trust_gate_arguments({
        "description": "A long authorization discussion: this is benign prose.",
    }) is not None
    assert _mcp_handlers._format_trust_gate_arguments({
        "description": "unrelated prose\nCookie: opaque-cookie",
    }) is None


@pytest.mark.parametrize(
    "text",
    [
        "Please send Cookie: sessionid=synthetic-cookie-1",
        "a/b Cookie: sessionid=synthetic-cookie-2",
        "1. Cookie: sid=synthetic-cookie-3",
        'He said "Cookie: sid=synthetic-cookie-4"',
        "GET / HTTP/1.1 Host: x Cookie: sid=synthetic-cookie-5",
    ],
)
def test_prose_prefixed_cookie_headers_fail_before_consent_rpc_and_cost(fake_session, text):
    """Cookie credentials remain blocked even when prose precedes the header token."""
    from tools import mcp_tool_costs

    _set_trust("srv", "untrusted")
    policy = mcp_tool_costs.parse_cost_policy(
        {"write_file": 40}, 100, None, where="test MCP server"
    )
    args = {"description": text}
    assert _mcp_handlers._format_trust_gate_arguments(args) is None
    assert _mcp_handlers._format_gateway_trust_gate_command("srv", "write_file", args) is None

    with patch.dict(mcp_tool._server_cost_policies, {"srv": policy}, clear=True), \
         patch.dict(mcp_tool_costs._spent, {}, clear=True), \
         patch("tools.approval_prompt.request_elicitation_consent", return_value="accept") as consent:
        raw = _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

    consent.assert_not_called()
    fake_session.call_tool.assert_not_awaited()
    assert mcp_tool_costs._spent == {}
    assert "synthetic-cookie" not in raw
    assert "error" in json.loads(raw)


@pytest.mark.parametrize(
    "text",
    [
        "Please send Cookie: secret",
        "Please send Cookie: secret; ok",
        "Please send Cookie: abcdef123456opaque",
        "Please send X-Amz-Security-Token: opaque123456",
    ],
)
def test_prose_prefixed_opaque_secret_headers_fail_before_consent_rpc_and_cost(fake_session, text):
    """Opaque prose-prefixed credential headers never reach consent, RPC, or cost booking."""
    from tools import mcp_tool_costs

    _set_trust("srv", "untrusted")
    policy = mcp_tool_costs.parse_cost_policy(
        {"write_file": 40}, 100, None, where="test MCP server"
    )
    args = {"x": text}
    assert _mcp_handlers._format_trust_gate_arguments(args) is None
    assert _mcp_handlers._format_gateway_trust_gate_command("srv", "write_file", args) is None

    with patch.dict(mcp_tool._server_cost_policies, {"srv": policy}, clear=True), \
         patch.dict(mcp_tool_costs._spent, {}, clear=True), \
         patch("tools.approval_prompt.request_elicitation_consent", return_value="accept") as consent:
        raw = _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

    consent.assert_not_called()
    fake_session.call_tool.assert_not_awaited()
    assert mcp_tool_costs._spent == {}
    assert text not in raw
    assert "error" in json.loads(raw)


@pytest.mark.parametrize(
    ("args", "path"),
    [
        ({"name": "X-Api-Key", "value": "opaque123456"}, ("value",)),
        ({"name": "X-Amz-Security-Token", "value": "opaque123456"}, ("value",)),
        ({"name": "password", "value": "opaque123456"}, ("value",)),
        ({"name": "API_TOKEN", "value": "opaque123456"}, ("value",)),
        (
            {"requestHeaders": [{"name": "X-Api-Key", "value": "opaque123456"}]},
            ("requestHeaders", 0, "value"),
        ),
        ({"extra_headers": [["X-Api-Key", "opaque123456"]]}, ("extra_headers", 0, 1)),
    ],
)
def test_secret_shaped_header_name_value_pairs_are_masked_in_cli_and_gateway(args, path):
    """Header-shaped name/value entries mask only their scalar credential value."""
    cli_preview = _mcp_handlers._format_trust_gate_arguments(args)
    gateway_command = _mcp_handlers._format_gateway_trust_gate_command("srv", "write_file", args)

    assert cli_preview is not None
    assert gateway_command is not None
    cli_rendered = json.loads(cli_preview)
    gateway_rendered = json.loads(gateway_command.removeprefix("MCP untrusted call "))["arguments"]
    for rendered in (cli_rendered, gateway_rendered):
        current = rendered
        for component in path:
            current = current[component]
        assert current == "***"
    assert "opaque123456" not in cli_preview
    assert "opaque123456" not in gateway_command


@pytest.mark.parametrize(
    "args",
    [
        {"name": "auth", "payload": {"cmd": "destructive synthetic command"}},
        {"name": "auth", "body": "DROP TABLE synthetic_users"},
        {"name": "Authorization", "data": {"target": "/prod", "op": "delete"}},
    ],
)
def test_generic_rpc_name_payload_fields_stay_visible_or_fail_closed(args):
    """Generic RPC data is never silently collapsed as a header credential value."""
    cli_preview = _mcp_handlers._format_trust_gate_arguments(args)
    gateway_command = _mcp_handlers._format_gateway_trust_gate_command("srv", "write_file", args)

    assert (cli_preview is None) == (gateway_command is None)
    if cli_preview is not None:
        assert json.loads(cli_preview) == args
        assert json.loads(gateway_command.removeprefix("MCP untrusted call "))["arguments"] == args


def test_concurrent_untrusted_declines_prompt_independently_without_rpc_or_double_booking(fake_session):
    """Two simultaneous untrusted calls each ask once; declines dispatch nothing or spend nothing."""
    from concurrent.futures import ThreadPoolExecutor
    from tools import mcp_tool_costs

    _set_trust("srv", "untrusted")
    policy = mcp_tool_costs.parse_cost_policy(
        {"write_file": 40}, 100, None, where="test MCP server"
    )
    prompted = []

    def decline(message, *_args, **_kwargs):
        prompted.append(message)
        return "decline"

    handler = _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)
    with patch.dict(mcp_tool._server_cost_policies, {"srv": policy}, clear=True), \
         patch.dict(mcp_tool_costs._spent, {}, clear=True), \
         patch.dict(mcp_tool_costs._ask_locks, {}, clear=True), \
         patch("tools.approval_prompt.request_elicitation_consent", side_effect=decline):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(handler, ({"repo": "synthetic-a"}, {"repo": "synthetic-b"})))

    assert len(prompted) == 2
    assert any("synthetic-a" in message for message in prompted)
    assert any("synthetic-b" in message for message in prompted)
    assert all("Costs about 40 credits." in message for message in prompted)
    assert all("error" in json.loads(result) for result in results)
    fake_session.call_tool.assert_not_awaited()
    assert mcp_tool_costs._spent == {}


def test_header_masking_preserves_unrelated_siblings_and_validates_masked_subtrees():
    """Only the declared header value is masked; every subtree is still inspected."""
    args = {
        "name": "Authorization",
        "value": "opaque-authorization",
        "author": "Alice",
        "public_key": "ssh-ed25519 AAAA-visible",
        "target": "production",
    }
    preview = _mcp_handlers._format_trust_gate_arguments(args)
    assert preview is not None
    rendered = json.loads(preview)
    assert rendered["value"] == "***"
    assert rendered["author"] == "Alice"
    assert rendered["public_key"] == "ssh-ed25519 AAAA-visible"
    assert rendered["target"] == "production"

    assert _mcp_handlers._format_trust_gate_arguments({
        "name": "Authorization",
        "value": {"nested": "Cookie: opaque-cookie"},
    }) is None


@pytest.mark.parametrize("name", ["privateKey", r"private\u004bey", "Authorization"])
def test_structured_name_canonicalisation_masks_equivalent_forms(name):
    preview = _mcp_handlers._format_trust_gate_arguments({name: "opaque-secret"})
    assert preview is not None
    assert json.loads(preview)[name] == "***"


def test_lone_surrogate_in_structured_name_fails_closed():
    assert _mcp_handlers._format_trust_gate_arguments({"private\ud800Key": "opaque-secret"}) is None


def test_lone_surrogate_in_argument_value_fails_closed():
    assert _mcp_handlers._format_trust_gate_arguments({"text": "visible\ud800"}) is None


def test_surrogate_pair_in_structured_name_uses_the_same_secret_classification():
    name = "Authorization\ud83d\ude00"
    preview = _mcp_handlers._format_trust_gate_arguments({name: "opaque-secret"})
    assert preview is not None
    assert list(json.loads(preview).values()) == ["***"]
    assert "\\ud83d\\ude00" in preview


@pytest.mark.parametrize(
    "header_blob",
    [
        "Cookie\u00b7: synthetic-cookie",
        "Cookie=: synthetic-cookie",
        "Authorization]: synthetic-auth",
        "Cookie\U0001f600: synthetic-cookie",
        'C"ookie": synthetic-cookie',
        r'Co\"okie\": synthetic-cookie',
        "author=1;X-Auth=Data: synthetic-auth",
        "author.X-Custom-Auth: synthetic-auth",
        r"Cookie\udb40\udc20\u003a synthetic-cookie",
    ],
)
def test_reviewer_header_obfuscations_fail_closed_in_cli_and_gateway(header_blob):
    args = {"header_block": header_blob}
    assert _mcp_handlers._format_trust_gate_arguments(args) is None
    assert _mcp_handlers._format_gateway_trust_gate_command("srv", "write_file", args) is None


@pytest.mark.parametrize(
    "text",
    [
        "https://auth.example.com:8443/v1/status",
        "ghcr.io/myorg/auth-service:v1.0.0",
        r"C:\\Users\\Alice\\auth.txt",
        "host.ssh_public_key descriptor",
        "long prose about authorization: this is not a header",
    ],
)
def test_reviewer_benign_uri_path_labels_and_prose_remain_previewable(text):
    args = {"description": text}
    cli_preview = _mcp_handlers._format_trust_gate_arguments(args)
    gateway_preview = _mcp_handlers._format_gateway_trust_gate_command("srv", "write_file", args)
    assert cli_preview is not None
    assert gateway_preview is not None


def test_generic_rpc_payload_is_not_collapsed_as_a_header_value():
    args = {
        "name": "auth_check",
        "payload": {
            "target": "/production/database",
            "operation": "drop_all_tables",
            "author": "Alice",
            "public_key": "ssh-ed25519 AAAA-visible",
        },
    }
    rendered = json.loads(_mcp_handlers._format_trust_gate_arguments(args))
    assert rendered["payload"]["target"] == "/production/database"
    assert rendered["payload"]["operation"] == "drop_all_tables"
    assert rendered["payload"]["author"] == "Alice"
    assert rendered["payload"]["public_key"] == "ssh-ed25519 AAAA-visible"

    oversized = {"name": "auth_check", "payload": {"padding": "x" * 3_000}}
    assert _mcp_handlers._format_trust_gate_arguments(oversized) is None


def test_secret_scalar_is_validated_before_masking():
    assert _mcp_handlers._format_trust_gate_arguments({"api_key": 10 ** 5_000}) is None
    assert _mcp_handlers._format_trust_gate_arguments({"api_key": float("inf")}) is None
    cyclic = {}
    cyclic["api_key"] = cyclic
    assert _mcp_handlers._format_trust_gate_arguments(cyclic) is None


@pytest.mark.parametrize(
    "name",
    ["secretValue", "secretInput", "keyMaterial", "pass-wd", "cre-dentials",
     "author_oauth", "author_authentication"],
)
def test_camel_and_hyphenated_secret_names_are_masked(name):
    preview = _mcp_handlers._format_trust_gate_arguments({name: "synthetic-secret"})
    assert preview is not None
    assert json.loads(preview)[name] == "***"


def test_public_and_descriptive_key_names_are_not_blanket_masked():
    args = {
        "client_public_key": "visible-client-key",
        "signing_public_key": "visible-signing-key",
        "commit_author_key": "visible-author-key",
        "state_capital_key": "visible-capital-key",
    }
    assert json.loads(_mcp_handlers._format_trust_gate_arguments(args)) == args


def test_escaped_control_structured_name_fails_closed():
    assert _mcp_handlers._format_trust_gate_arguments({r"secret\tkey": "synthetic-secret"}) is None


class TestTrustGateAtCallTime:
    """The handler preamble consults the approval path when required."""

    @pytest.mark.parametrize("bypass", ["session_yolo", "global_yolo", "mode_off"])
    def test_generic_approval_bypass_never_grants_mcp_trust(
        self, fake_session, monkeypatch, bypass
    ):
        """The MCP trust/effect gate remains mandatory under every generic bypass.

        Regression for upstream #143787: the generic command-approval bypass is
        user-consent policy, not operator trust for a mutating MCP server.
        """
        from tools import approval
        from tools.approval_context import reset_current_session_key, set_current_session_key

        _set_trust("srv", "untrusted")
        _set_read_only("srv", "delete_repo", True)  # hostile server annotation
        session_key = f"mcp-bypass-{bypass}"
        key_token = set_current_session_key(session_key)
        try:
            if bypass == "session_yolo":
                approval.enable_session_yolo(session_key)
            elif bypass == "global_yolo":
                monkeypatch.setattr(approval, "_YOLO_MODE_FROZEN", True)
            else:
                monkeypatch.setattr(
                    "tools.approval_context._get_approval_mode", lambda: "off"
                )
            assert approval.is_approval_bypass_active()

            handler = _mcp_handlers._make_tool_handler("srv", "delete_repo", 30.0)
            with patch(
                "tools.approval_prompt.request_elicitation_consent",
                return_value="decline",
            ) as consent:
                raw = handler({"repo": "x"})
        finally:
            if bypass == "session_yolo":
                approval.disable_session_yolo(session_key)
            reset_current_session_key(key_token)

        consent.assert_called_once()
        fake_session.call_tool.assert_not_awaited()
        assert "error" in json.loads(raw)

    @pytest.mark.parametrize("bypass", ["session_yolo", "global_yolo", "mode_off"])
    def test_real_consent_routing_declines_unattended_bypass(self, fake_session, monkeypatch, bypass):
        """YOLO and approval-off policy never grant the separate MCP trust gate."""
        from gateway.session_context import clear_session_vars, set_session_vars
        from tools import approval
        from tools.approval_context import reset_current_session_key, set_current_session_key

        _set_trust("srv", "untrusted")
        session_key = f"mcp-real-consent-{bypass}"
        session_tokens = set_session_vars(platform="webhook", session_key=session_key)
        key_token = set_current_session_key(session_key)
        try:
            if bypass == "session_yolo":
                approval.enable_session_yolo(session_key)
            elif bypass == "global_yolo":
                monkeypatch.setattr(approval, "_YOLO_MODE_FROZEN", True)
            else:
                monkeypatch.setattr("tools.approval_context._get_approval_mode", lambda: "off")
            raw = _mcp_handlers._make_tool_handler("srv", "delete_repo", 30.0)({})
        finally:
            if bypass == "session_yolo":
                approval.disable_session_yolo(session_key)
            reset_current_session_key(key_token)
            clear_session_vars(session_tokens)

        fake_session.call_tool.assert_not_awaited()
        assert "error" in json.loads(raw)

    def test_session_yolo_does_not_cross_session_trust_boundary(self, fake_session):
        """A session YOLO bit cannot authorize another session's MCP write."""
        from tools import approval
        from tools.approval_context import reset_current_session_key, set_current_session_key

        _set_trust("srv", "untrusted")
        approval.enable_session_yolo("mcp-authorized-session")
        asked = []

        def decline(*_args, **_kwargs):
            asked.append(True)
            return "decline"

        try:
            with patch(
                "tools.approval_prompt.request_elicitation_consent", side_effect=decline
            ):
                for session_key in ("mcp-authorized-session", "mcp-other-session"):
                    key_token = set_current_session_key(session_key)
                    try:
                        _mcp_handlers._make_tool_handler("srv", "delete_repo", 30.0)({})
                    finally:
                        reset_current_session_key(key_token)
        finally:
            approval.disable_session_yolo("mcp-authorized-session")

        assert len(asked) == 2
        fake_session.call_tool.assert_not_awaited()

    @pytest.mark.parametrize("hint", [1, "true", object()])
    def test_malformed_read_only_hint_is_write_capable(self, fake_session, hint):
        """Malformed annotations remain write-capable on an untrusted server."""
        _set_trust("srv", "untrusted")
        _set_read_only("srv", "delete_repo", hint)
        handler = _mcp_handlers._make_tool_handler("srv", "delete_repo", 30.0)
        with patch(
            "tools.approval_prompt.request_elicitation_consent",
            return_value="decline",
        ) as consent:
            raw = handler({"repo": "x"})

        consent.assert_called_once()
        fake_session.call_tool.assert_not_awaited()
        assert "error" in json.loads(raw)

    def test_denial_blocks_before_lazy_transport_or_rpc(self, fake_session):
        """A denied untrusted write cannot reach lazy connection or RPC code."""
        _set_trust("srv", "untrusted")
        handler = _mcp_handlers._make_tool_handler("srv", "delete_repo", 30.0)
        with patch(
            "tools.approval_prompt.request_elicitation_consent", return_value="decline"
        ), patch.object(
            _mcp_handlers, "_check_circuit_breaker", side_effect=AssertionError("trust gate was bypassed")
        ), patch.object(
            _mcp_handlers, "_acquire_call_server", side_effect=AssertionError("lazy transport was reached")
        ):
            raw = handler({"repo": "x"})

        fake_session.call_tool.assert_not_awaited()
        assert "error" in json.loads(raw)

    def test_cron_cannot_use_yolo_to_run_untrusted_write(self, fake_session):
        """Unattended cron remains fail-closed even when its session has YOLO state."""
        from gateway.session_context import clear_session_vars, set_session_vars
        from tools import approval
        from tools.approval_context import reset_current_session_key, set_current_session_key

        _set_trust("srv", "untrusted")
        _set_read_only("srv", "delete_repo", True)  # hostile server annotation
        session_key = "cron:mcp-trust"
        approval.enable_session_yolo(session_key)
        session_tokens = set_session_vars(cron_session="1")
        key_token = set_current_session_key(session_key)
        try:
            with patch.object(
                _mcp_handlers, "_acquire_call_server", side_effect=AssertionError("cron trust bypassed")
            ):
                raw = _mcp_handlers._make_tool_handler("srv", "delete_repo", 30.0)({})
        finally:
            reset_current_session_key(key_token)
            clear_session_vars(session_tokens)
            approval.disable_session_yolo(session_key)

        fake_session.call_tool.assert_not_awaited()
        assert "error" in json.loads(raw)

    def test_write_capable_on_untrusted_server_requires_approval(
        self, fake_session
    ):
        """Approval consulted; 'accept' lets the RPC through."""
        _set_trust("srv", "untrusted")
        # No readOnlyHint recorded for delete_repo → write-capable.
        handler = _mcp_handlers._make_tool_handler("srv", "delete_repo", 30.0)
        with patch(
            "tools.approval_prompt.request_elicitation_consent",
            return_value="accept",
        ) as consent:
            raw = handler({"repo": "x"})
        consent.assert_called_once()
        assert json.loads(raw) == {"result": "ok"}
        fake_session.call_tool.assert_awaited_once()

    def test_gateway_prompt_contains_complete_compact_payload(self, fake_session, monkeypatch):
        """The real gateway consent route receives the whole MCP payload, not a clipped prefix."""
        from gateway.session_context import clear_session_vars, set_session_vars
        from tools import approval, approval_prompt
        from tools.approval_context import reset_current_session_key, set_current_session_key

        _set_trust("srv", "untrusted")
        session_key = "gateway-mcp-complete"
        session_tokens = set_session_vars(platform="telegram", session_key=session_key)
        key_token = set_current_session_key(session_key)
        seen = []

        def capture(_session_key, _notify, approval_data, **_kwargs):
            seen.append(dict(approval_data))
            return {"resolved": True, "choice": "deny"}

        approval.register_gateway_notify(session_key, lambda _data: None)
        monkeypatch.setattr(approval_prompt._gw, "_await_gateway_decision", capture)
        try:
            raw = _mcp_handlers._make_tool_handler("srv", "mutate", 30.0)(
                {"target": "/production/database", "operation": "delete"}
            )
        finally:
            approval.unregister_gateway_notify(session_key)
            reset_current_session_key(key_token)
            clear_session_vars(session_tokens)

        assert "error" in json.loads(raw)
        assert len(seen) == 1
        command = seen[0]["command"]
        assert len(command) <= 200
        assert '"server":"srv"' in command
        assert '"tool":"mutate"' in command
        assert '"target":"/production/database"' in command
        assert '"operation":"delete"' in command

        from gateway.run import _format_exec_approval_fallback
        rendered = _format_exec_approval_fallback(command, "review", "/")
        assert command in rendered
        for fragment in ('"server":"srv"', '"tool":"mutate"',
                         '"target":"/production/database"', '"operation":"delete"'):
            assert fragment in rendered

    def test_gateway_payload_preserves_escaped_invisible_and_non_bmp_arguments(
        self, fake_session
    ):
        """The operator card is safe while its parsed payload retains exact argument identity."""
        import unicodedata

        args = {
            "tag": "release\U000e0001\U000e0061",
            "direction": "prod\u202e",
            "line": "first\nsecond\r\x00",
            "zero_width": "a\u200bb",
        }
        command = _mcp_handlers._format_gateway_trust_gate_command(
            "srv\u202e", "tool\u200b", args
        )

        assert command is not None
        payload = json.loads(command.removeprefix("MCP untrusted call "))
        assert payload["server"] == "srv\u202e"
        assert payload["tool"] == "tool\u200b"
        assert payload["arguments"] == args
        assert not any(unicodedata.category(char) in {"Cc", "Cf"} for char in command)
        assert "\\udb40\\udc01" in command
        assert "\\u202e" in command


    def test_cli_preview_keeps_normal_unicode_and_round_trips_invisible_codepoints(self):
        import unicodedata

        args = {"text": "\u00e9" * 170, "emoji": "\U0001f642" * 70,
                "tag": "\U000e0061", "direction": "\u202e"}
        preview = _mcp_handlers._format_trust_gate_arguments(args, compact=False)

        assert preview is not None
        assert json.loads(preview) == args
        assert "\u00e9" * 170 in preview
        assert "\U0001f642" * 70 in preview
        assert "\\udb40\\udc61" in preview
        assert not any(unicodedata.category(c) == "Cf" for c in preview)

    def test_gateway_oversized_payload_denies_before_consent_and_rpc(self, fake_session):
        """A late mutating argument cannot hide beyond the gateway's 200-character command budget."""
        from gateway.session_context import clear_session_vars, set_session_vars
        from tools import approval_prompt
        from tools.approval_context import reset_current_session_key, set_current_session_key

        _set_trust("srv", "untrusted")
        session_tokens = set_session_vars(platform="telegram", session_key="gateway-mcp-large")
        key_token = set_current_session_key("gateway-mcp-large")
        args = {"benign_prefix": "x" * 180, "late_mutating_target": "/production/database"}
        try:
            with patch("tools.approval_prompt.request_elicitation_consent", return_value="accept") as consent:
                raw = _mcp_handlers._make_tool_handler("srv", "mutate", 30.0)(args)
        finally:
            reset_current_session_key(key_token)
            clear_session_vars(session_tokens)

        consent.assert_not_called()
        fake_session.call_tool.assert_not_awaited()
        parsed = json.loads(raw)
        assert "error" in parsed
        assert "gateway display limit" in parsed["error"]
        assert "/production/database" not in parsed["error"]

    def test_approval_card_shows_bounded_force_redacted_arguments(self, fake_session, monkeypatch):
        """The operator sees useful arguments without secrets or invisible controls."""
        import agent.redact

        monkeypatch.setattr(agent.redact, "_REDACT_ENABLED", False)
        _set_trust("srv", "untrusted")
        handler = _mcp_handlers._make_tool_handler("srv", "trigger_build", 30.0)
        args = {
            "job": "release",
            "api_key": "sk-supersecretcredential123456",
            "nested": {
                "headers": {
                    "Authorization": "Bearer opaque-authorization-value",
                    "x-api-key": "opaque-header-value",
                },
                "credentials": ["opaque-credential-value"],
            },
            "target": "prod\u202e",
            "command": "printf '$(touch /srv/scratch/pwned)'\x1b[31m",
            "notes": "x" * 5_000,
        }

        with patch(
            "tools.approval_prompt.request_elicitation_consent",
            return_value="decline",
        ) as consent:
            raw = handler(args)

        # The complete redacted arguments exceed the approval-card budget. A partial card
        # must never be shown as authoritative, so the call is refused before consent.
        consent.assert_not_called()
        fake_session.call_tool.assert_not_awaited()
        parsed = json.loads(raw)
        assert "error" in parsed
        assert "Reduce the payload" in parsed["error"]

    @pytest.mark.parametrize("author_key", ["AUTHOR", "Author"])
    def test_author_metadata_remains_visible_in_plain_and_header_arguments(
        self, fake_session, author_key
    ):
        """The auth suffix rule must not classify normal author metadata as a secret."""
        _set_trust("srv", "untrusted")
        args = {
            author_key: "Alice",
            "header": {"name": author_key, "value": "Alice"},
            "nested": [{author_key: "Bob"}],
        }
        with patch("tools.approval_prompt.request_elicitation_consent", return_value="decline") as consent:
            _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

        message = consent.call_args.args[0]
        assert f'"{author_key}": "Alice"' in message
        assert f'"name": "{author_key}"' in message
        assert '"value": "Alice"' in message
        assert f'"{author_key}": "Bob"' in message
        fake_session.call_tool.assert_not_awaited()

    @pytest.mark.parametrize(
        ("key", "is_secret"),
        [
            ("auth", True),
            ("AUTH", True),
            ("Custom-Auth", True),
            ("custom-auth", True),
            ("Proxy-Auth", True),
            ("api_auth", True),
            ("oauth", True),
            ("OAuth", True),
            ("Proxy-Authorization", True),
            ("X-Authorization", True),
            ("X-Authentication", True),
            ("x-auth-data", True),
            ("X-Auth-Token", True),
            ("Proxy-Authentication", True),
            ("X-Authorization-Data", True),
            ("Authorization-Header", True),
            ("Proxy-Authorization-Info", True),
            ("authorization_code", True),
            ("secret_key", True),
            ("aws_secret_access_key", True),
            ("secretAccessKey", True),
            ("privateKey", True),
            ("rsa_private_key", True),
            ("client_key", True),
            ("signing_key", True),
            ("api_access_key", True),
            ("aws_access_key_id", True),
            ("secretkey", True),
            ("accesskey", True),
            ("accesskeyid", True),
            ("clientkey", True),
            ("SECRETKEY", True),
            ("sec\u200bret_key", True),
            ("priv\u00adate_key", True),
            ("se-cret-key", True),
            ("api2_key", True),
            ("api2key", True),
            ("Ocp-Apim-Subscription-Key", True),
            ("SecRetKey", True),
            ("authorisation_key", True),
            ("public_key", False),
            ("ssh_public_key", False),
            ("object_key", False),
            ("idempotency_key", False),
            ("author_key", False),
            ("authority_key", False),
            ("capital_key", False),
            ("rapid_key", False),
            ("Cookie", True),
            ("Set-Cookie", True),
            ("author", False),
            ("Author", False),
            ("AUTHOR", False),
            ("authority", False),
            ("authorisation", True),
            ("Authorisation", True),
            ("X-Authorisation", True),
            ("Proxy-Authorisation", True),
            ("authorisation_code", True),
            ("X-Request-Id", False),
            ("X-Author", False),
            ("X-Authority", False),
        ],
    )
    def test_secret_argument_classifier_table(self, key, is_secret):
        """Classify credential-shaped names without hiding descriptive metadata."""
        assert _mcp_handlers._is_secret_argument_name(key) is is_secret

    @pytest.mark.parametrize(
        ("field_name", "is_secret"),
        [
            ("author_key", False),
            ("authority_key", False),
            ("capital_key", False),
            ("rapid_key", False),
            ("ssh_public_key", False),
            ("AuthorityKey", False),
            ("CAPITAL_KEY", False),
            ("SshPublicKey", False),
            ("secret_key", True),
            ("SecretAccessKey", True),
            ("aws_access_key_id", True),
            ("privateKey", True),
            ("secretkey", True),
            ("accesskey", True),
            ("accesskeyid", True),
            ("SECRETKEY", True),
            ("clientkey", True),
            ("sec\u200bret_key", True),
            ("priv\u00adate_key", True),
            ("se-cret-key", True),
            ("api2_key", True),
            ("Ocp-Apim-Subscription-Key", True),
            ("SecRetKey", True),
            ("authorisation_key", True),
            ("Authorization", True),
            ("Authorisation", True),
            ("Cookie", True),
            ("x-auth-data", True),
        ],
    )
    def test_key_name_boundaries_apply_to_nested_and_paired_headers(
        self, fake_session, field_name, is_secret
    ):
        """Credential segments mask values without hiding descriptive key identifiers."""
        _set_trust("srv", "untrusted")
        value = f"synthetic-{field_name}-value"
        args = {
            field_name: value,
            "nested": {field_name: value},
            "header": {"name": field_name, "value": value},
            "pairs": [[field_name, value]],
        }
        with patch("tools.approval_prompt.request_elicitation_consent", return_value="decline") as consent:
            _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

        consent.assert_called_once()
        message = consent.call_args.args[0]
        preview = _mcp_handlers._format_trust_gate_arguments(args)
        assert preview is not None
        rendered = json.loads(preview)
        if is_secret:
            escaped_value = _mcp_handlers._escape_trust_gate_controls(value)
            assert escaped_value not in message
            assert rendered[field_name] == "***"
            assert rendered["nested"][field_name] == "***"
            assert rendered["header"]["value"] == "***"
            assert rendered["pairs"][0][1] == "***"
        else:
            assert value in message
            assert rendered[field_name] == value
            assert rendered["nested"][field_name] == value
            assert rendered["header"]["value"] == value
            assert rendered["pairs"][0][1] == value
        fake_session.call_tool.assert_not_awaited()

    def test_unstructured_compact_secret_key_fails_closed(self, fake_session):
        """Compact credential headers in free text cannot be safely previewed."""
        _set_trust("srv", "untrusted")
        args = {"header_block": "secretkey: value"}
        with patch("tools.approval_prompt.request_elicitation_consent", return_value="accept") as consent:
            raw = _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

        consent.assert_not_called()
        fake_session.call_tool.assert_not_awaited()
        assert "error" in json.loads(raw)

    @pytest.mark.parametrize(
        "header_blob",
        [
            "Coo\u200bkie: synthetic-cookie",
            "C" + "\u200b" * 70 + "ookie: synthetic-cookie",
            "Cookie\uff1a synthetic-cookie",
            "Authorisation\u2236 synthetic-authorisation",
            "Authorisation\ufe55 synthetic-authorisation",
            "Cookie\u02d0 synthetic-cookie",
            "Cookie\u0703 synthetic-cookie",
        ],
    )
    def test_unicode_obfuscated_credential_headers_fail_closed(
        self, fake_session, header_blob
    ):
        """Format characters and colon lookalikes cannot leave an opaque header visible."""
        _set_trust("srv", "untrusted")
        args = {"header_block": header_blob}

        assert _mcp_handlers._format_trust_gate_arguments(args) is None
        assert _mcp_handlers._format_gateway_trust_gate_command("srv", "write_file", args) is None
        with patch("tools.approval_prompt.request_elicitation_consent", return_value="accept") as consent:
            raw = _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

        consent.assert_not_called()
        fake_session.call_tool.assert_not_awaited()
        assert "error" in json.loads(raw)

    @pytest.mark.parametrize(
        "command",
        [
            "echo $TOKEN; ls",
            "export API_TOKEN; run",
            "SELECT password; FROM t",
            "const secret; x",
            "Use the access token; then continue",
        ],
    )
    def test_semicolon_delimiters_do_not_hide_ordinary_text(self, fake_session, command):
        """Semicolons remain ordinary text, even beside credential-like words."""
        _set_trust("srv", "untrusted")
        args = {"command": command}

        cli_preview = _mcp_handlers._format_trust_gate_arguments(args)
        gateway_preview = _mcp_handlers._format_gateway_trust_gate_command(
            "srv", "write_file", args
        )
        assert cli_preview is not None
        assert gateway_preview is not None
        assert command in cli_preview
        assert json.dumps(command, ensure_ascii=True)[1:-1] in gateway_preview

        with patch("tools.approval_prompt.request_elicitation_consent", return_value="decline") as consent:
            _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

        consent.assert_called_once()
        assert command in consent.call_args.args[0]
        fake_session.call_tool.assert_not_awaited()

    def test_colon_sign_is_not_a_header_delimiter(self, fake_session):
        """The currency sign named COLON SIGN is ordinary argument text."""
        _set_trust("srv", "untrusted")
        command = "Authorization\u20a1 opaque-value"
        args = {"command": command}

        cli_preview = _mcp_handlers._format_trust_gate_arguments(args)
        gateway_preview = _mcp_handlers._format_gateway_trust_gate_command(
            "srv", "write_file", args
        )
        assert cli_preview is not None
        assert gateway_preview is not None
        assert command in cli_preview
        assert json.loads(gateway_preview.removeprefix("MCP untrusted call "))["arguments"] == args

        with patch("tools.approval_prompt.request_elicitation_consent", return_value="decline") as consent:
            _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

        consent.assert_called_once()
        assert command in consent.call_args.args[0]
        fake_session.call_tool.assert_not_awaited()

    @pytest.mark.parametrize("invisible", _INVISIBLE_SECRET_NAME_MARKS)
    def test_invisible_credential_name_marks_are_ignored_in_structured_keys(
        self, fake_session, invisible
    ):
        """Invisible marks cannot turn a structured credential key into metadata."""
        _set_trust("srv", "untrusted")
        secret = f"synthetic-structured-{ord(invisible):x}"
        args = {
            f"to{invisible}ken": secret,
            "header": {"name": f"Co{invisible}okie", "value": secret},
        }

        cli_preview = _mcp_handlers._format_trust_gate_arguments(args)
        gateway_preview = _mcp_handlers._format_gateway_trust_gate_command(
            "srv", "write_file", args
        )
        assert cli_preview is not None
        assert gateway_preview is not None
        assert secret not in cli_preview
        assert secret not in gateway_preview
        assert json.loads(cli_preview)[f"to{invisible}ken"] == "***"

        with patch("tools.approval_prompt.request_elicitation_consent", return_value="decline") as consent:
            _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)
        consent.assert_called_once()
        assert secret not in consent.call_args.args[0]
        fake_session.call_tool.assert_not_awaited()

    @pytest.mark.parametrize("invisible", _INVISIBLE_SECRET_NAME_MARKS)
    def test_invisible_credential_name_marks_before_colon_fail_closed_before_cost(
        self, fake_session, invisible
    ):
        """Unstructured headers remain denied when marks occur within or after a quoted name."""
        from tools import mcp_tool_costs

        _set_trust("srv", "untrusted")
        secret = f"synthetic-unstructured-{ord(invisible):x}"
        header_blob = f'{{"Co{invisible}okie"{invisible}: "{secret}"}}'
        policy = mcp_tool_costs.parse_cost_policy(
            {"write_file": 40}, 100, None, where="test MCP server"
        )
        args = {"header_blob": header_blob}
        with patch.dict(mcp_tool._server_cost_policies, {"srv": policy}, clear=True), \
             patch.dict(mcp_tool_costs._spent, {}, clear=True), \
             patch("tools.approval_prompt.request_elicitation_consent", return_value="accept") as consent:
            result = _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

        assert _mcp_handlers._format_trust_gate_arguments(args) is None
        assert _mcp_handlers._format_gateway_trust_gate_command("srv", "write_file", args) is None
        consent.assert_not_called()
        fake_session.call_tool.assert_not_awaited()
        assert mcp_tool_costs._spent == {}
        assert secret not in result

    @pytest.mark.parametrize("header_blob", _UNSTRUCTURED_SECRET_HEADER_NAME_FORMS)
    def test_unicode_multipart_header_names_fail_closed_before_consent_and_cost(
        self, fake_session, header_blob
    ):
        """Raw header spans agree with compact structured-name classification."""
        from tools import mcp_tool_costs

        _set_trust("srv", "untrusted")
        policy = mcp_tool_costs.parse_cost_policy(
            {"write_file": 40}, 100, None, where="test MCP server"
        )
        args = {"header_blob": header_blob}
        assert _mcp_handlers._format_trust_gate_arguments(args) is None
        assert _mcp_handlers._format_gateway_trust_gate_command("srv", "write_file", args) is None
        with patch.dict(mcp_tool._server_cost_policies, {"srv": policy}, clear=True), \
             patch.dict(mcp_tool_costs._spent, {}, clear=True), \
             patch("tools.approval_prompt.request_elicitation_consent", return_value="accept") as consent:
            result = _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

        consent.assert_not_called()
        fake_session.call_tool.assert_not_awaited()
        assert mcp_tool_costs._spent == {}
        assert "synthetic-header-secret" not in result

    def test_credential_header_sibling_shapes_mask_opaque_values(self):
        """Credential-labelled header values are masked without hiding metadata."""
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
            for secret in (
                "synthetic-kv", "synthetic-values", "synthetic-payload", "synthetic-text",
                "synthetic-body", "synthetic-raw", "synthetic-contents", "synthetic-value-string",
                "synthetic-label-value", "synthetic-field-value", "synthetic-array-value",
            ):
                assert secret not in cli_preview
                assert secret not in gateway_preview
            if isinstance(args, list):
                assert "Path=/synthetic-path" in cli_preview
                assert "Path=/synthetic-path" in gateway_preview

    def test_normalization_overflow_fails_closed(self):
        """Classification overflow cannot fall back to the unnormalized input."""
        oversized = "x" * (_mcp_handlers._TRUST_GATE_ARGUMENTS_MAX_SCALAR_CHARS + 1)
        with pytest.raises(ValueError, match="classification normalization budget"):
            _mcp_handlers._canonicalize_classification_view(oversized)

    def test_authorization_and_cookie_header_shapes_are_masked(self, fake_session):
        """Nested header maps and name/value pairs mask opaque auth and cookie values."""
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
            "cookie_metadata": {
                "name": "session",
                "domain": "example.test",
                "cookie_value": "cookie-value-secret",
            },
        }
        with patch("tools.approval_prompt.request_elicitation_consent", return_value="decline") as consent:
            _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

        consent.assert_called_once()
        message = consent.call_args.args[0]
        for secret in (
            "proxy-opaque-secret",
            "x-opaque-secret",
            "x-authentication-secret",
            "x-auth-data-secret",
            "x-auth-token-secret",
            "proxy-authentication-secret",
            "cookie-opaque-secret",
            "set-cookie-opaque-secret",
            "custom-opaque-secret",
            "pair-proxy-secret",
            "pair-x-secret",
            "pair-authentication-secret",
            "pair-auth-data-secret",
            "pair-auth-token-secret",
            "pair-proxy-authentication-secret",
            "pair-cookie-secret",
            "pair-set-cookie-secret",
            "cookie-value-secret",
        ):
            assert secret not in message
        assert '"X-Request-Id": "request-visible"' in message
        assert '"value": "pair-visible"' in message
        assert '"domain": "example.test"' in message
        fake_session.call_tool.assert_not_awaited()

    def test_authorization_variant_values_are_masked_in_structured_headers(self, fake_session):
        _set_trust("srv", "untrusted")
        args = {
            "headers": {
                "X-Authorization-Data": "x-authorization-data-secret",
                "Authorization-Header": "authorization-header-secret",
                "authorization_code": "authorization-code-secret",
                "author": "Alice",
            },
            "header_list": [
                {"name": "Authorization-Header", "value": "pair-authorization-header-secret"},
            ],
        }
        with patch("tools.approval_prompt.request_elicitation_consent", return_value="decline") as consent:
            _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

        consent.assert_called_once()
        message = consent.call_args.args[0]
        for secret in (
            "x-authorization-data-secret",
            "authorization-header-secret",
            "authorization-code-secret",
            "pair-authorization-header-secret",
        ):
            assert secret not in message
        assert '"author": "Alice"' in message
        fake_session.call_tool.assert_not_awaited()

    def test_mixed_case_header_pair_keys_mask_credentials(self, fake_session):
        """Pascal, upper and mixed-case Name/Value aliases must not reveal secrets."""
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
        for secret in ("pascal-bearer-secret", "upper-cookie-secret",
                       "uk-auth-secret", "header-name-secret"):
            assert secret not in message
        assert '"value": "Alice"' in message
        fake_session.call_tool.assert_not_awaited()

    def test_credential_key_suffixes_are_masked_without_hiding_public_keys(self, fake_session):
        _set_trust("srv", "untrusted")
        args = {
            "secret_key": "secret-key-opaque-value",
            "aws_secret_access_key": "aws-access-opaque-value",
            "secretAccessKey": "camel-access-opaque-value",
            "privateKey": "private-key-opaque-value",
            "authorisation_key": "authorisation-key-opaque-value",
            "header_list": [
                {"Name": "secret_key", "Value": "header-opaque-value"},
            ],
            "public_key": "public-key-visible",
            "object_key": "object-key-visible",
        }
        with patch("tools.approval_prompt.request_elicitation_consent", return_value="decline") as consent:
            _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

        consent.assert_called_once()
        message = consent.call_args.args[0]
        for secret in ("secret-key-opaque-value", "aws-access-opaque-value",
                       "camel-access-opaque-value", "private-key-opaque-value",
                       "authorisation-key-opaque-value",
                       "header-opaque-value"):
            assert secret not in message
        assert "public-key-visible" in message
        assert "object-key-visible" in message
        fake_session.call_tool.assert_not_awaited()

    def test_content_and_data_header_value_aliases_are_masked(self, fake_session):
        """Nested/case-variant header aliases mask secret values but retain benign content."""
        _set_trust("srv", "untrusted")
        args = {
            "nested": [
                {"Name": "Cookie", "content": "synthetic-cookie-content"},
                {"name": "Authorization", "DATA": "synthetic-authorization-data"},
                {"NAME": "Authorisation", "Content": "synthetic-authorisation-content"},
                {"name": "Content-Type", "content": "application/json"},
                {"name": "X-Request-Id", "data": "request-id-visible"},
                ["Cookie", "synthetic-array-cookie"],
            ]
        }
        cli_preview = _mcp_handlers._format_trust_gate_arguments(args)
        gateway_args = {
            "headers": [
                {"Name": "Cookie", "content": "synthetic-cookie"},
                {"name": "Authorization", "data": "synthetic-auth"},
            ]
        }
        gateway_preview = _mcp_handlers._format_gateway_trust_gate_command(
            "srv", "write_file", gateway_args
        )
        assert cli_preview is not None
        assert gateway_preview is not None
        assert all(secret not in cli_preview for secret in (
            "synthetic-cookie-content",
            "synthetic-authorization-data",
            "synthetic-authorisation-content",
            "synthetic-array-cookie",
        ))
        assert all(secret not in gateway_preview for secret in (
            "synthetic-cookie", "synthetic-auth",
        ))
        assert '"content": "application/json"' in cli_preview
        assert '"data": "request-id-visible"' in cli_preview

        with patch("tools.approval_prompt.request_elicitation_consent", return_value="decline") as consent:
            _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

        consent.assert_called_once()
        message = consent.call_args.args[0]
        assert "synthetic-cookie-content" not in message
        assert "synthetic-authorization-data" not in message
        assert "synthetic-authorisation-content" not in message
        assert "synthetic-array-cookie" not in message
        assert "application/json" in message
        assert "request-id-visible" in message
        fake_session.call_tool.assert_not_awaited()

    def test_gateway_uk_authorisation_and_pascal_header_pairs_are_redacted(self):
        for args in (
            {"Authorisation": "uk-opaque", "target": "safe"},
            {"headers": [{"Name": "Authorisation", "Value": "uk-pair-opaque"}]},
            {"headers": [{"NAME": "Cookie", "VALUE": "cookie-pair-opaque"}]},
        ):
            command = _mcp_handlers._format_gateway_trust_gate_command("srv", "do", args)
            assert command is not None
            payload = json.loads(command.removeprefix("MCP untrusted call "))
            assert payload["arguments"] != args
            assert all(secret not in command for secret in
                       ("uk-opaque", "uk-pair-opaque", "cookie-pair-opaque"))

    def test_alternate_header_aliases_and_string_pairs_mask_credentials(self, fake_session):
        """Common header representations must not bypass the same consent redaction."""
        _set_trust("srv", "untrusted")
        args = {
            "headers": [
                {"header_name": "Authorization", "header_value": "header-value-secret"},
                {"HeaderKey": "Cookie", "FieldValue": "field-value-secret"},
                {"KeyName": "Authorisation", "Val": "key-name-secret"},
                ["Authorization", "array-pair-secret"],
                ["X-Request-Id", "request-visible"],
                "author: Alice",
            ]
        }
        with patch("tools.approval_prompt.request_elicitation_consent", return_value="decline") as consent:
            _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

        consent.assert_called_once()
        message = consent.call_args.args[0]
        for secret in ("header-value-secret", "field-value-secret", "key-name-secret",
                       "array-pair-secret"):
            assert secret not in message
        assert "request-visible" in message
        assert "author: Alice" in message
        fake_session.call_tool.assert_not_awaited()

    def test_gateway_alternate_header_pair_repr_is_redacted(self):
        for args in (
            {"headers": [["Authorization", "array-opaque"]]},
            {"header_name": "Authorization", "header_value": "map-opaque"},
        ):
            command = _mcp_handlers._format_gateway_trust_gate_command("srv", "do", args)
            assert command is not None
            for secret in ("array-opaque", "map-opaque", "line-opaque"):
                assert secret not in command

    def test_multiline_and_quoted_inline_headers_fail_closed(self, fake_session):
        _set_trust("srv", "untrusted")
        args = {
            "header_block": "Content-Type: application/json\r\nCookie: sid=cookie-opaque\n"
                            "Host: example.test\nAuthorisation: uk-opaque",
            "command": "curl -H 'Accept: text/plain' -H 'Cookie: curl-opaque' URL",
        }
        with patch("tools.approval_prompt.request_elicitation_consent", return_value="accept") as consent:
            _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

        # Quoted/folded header text cannot be unambiguously masked, so no
        # approval is possible (even if user would accept).
        consent.assert_not_called()
        fake_session.call_tool.assert_not_awaited()

    def test_unrelated_apostrophe_cannot_bypass_fail_closed_header_detection(
        self, fake_session
    ):
        _set_trust("srv", "untrusted")
        args = {"block": "don't\nCookie: sid=abc'def-tail\nHost: example.test"}
        with patch("tools.approval_prompt.request_elicitation_consent", return_value="accept") as consent:
            result = _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

        consent.assert_not_called()
        fake_session.call_tool.assert_not_awaited()
        assert "error" in json.loads(result)

    def test_gateway_multiline_credential_header_block_is_denied(self):
        args = {"block": "Host: ex\nAuthorisation: inline-opaque"}
        command = _mcp_handlers._format_gateway_trust_gate_command("srv", "do", args)
        assert command is None

    def test_unstructured_noncredential_header_block_remains_displayable(self):
        args = {"block": "Host: example.test\nAccept: application/json"}
        command = _mcp_handlers._format_gateway_trust_gate_command("srv", "do", args)
        assert command is not None
        payload = json.loads(command.removeprefix("MCP untrusted call "))
        assert payload["arguments"]["block"] == args["block"]

    def test_unicode_arguments_and_author_metadata_remain_visible(self, fake_session):
        """The Unicode scanner preserves benign text and descriptive author fields."""
        _set_trust("srv", "untrusted")
        args = {
            "text": "café \U0001f642",
            "author": "Alice",
            "authority": "example.test",
            "header": {"name": "Author", "content": "Alice"},
        }
        cli_preview = _mcp_handlers._format_trust_gate_arguments(args)
        gateway_preview = _mcp_handlers._format_gateway_trust_gate_command("srv", "write_file", args)
        assert cli_preview is not None
        assert gateway_preview is not None
        assert json.loads(cli_preview) == args
        gateway_args = json.loads(gateway_preview.removeprefix("MCP untrusted call "))["arguments"]
        assert gateway_args == args

        with patch("tools.approval_prompt.request_elicitation_consent", return_value="decline") as consent:
            _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

        consent.assert_called_once()
        message = consent.call_args.args[0]
        assert "café" in message
        assert '"author": "Alice"' in message
        assert '"authority": "example.test"' in message
        assert '"content": "Alice"' in message
        fake_session.call_tool.assert_not_awaited()

    @pytest.mark.parametrize(
        "header_blob",
        [
            '{"Cookie": "sid=opaque"}',
            '{\"Authorisation\": \"uk-opaque\"}',
            "{'Cookie': 'sid=opaque'}",
            '{"Cookie"\n: "sid=opaque"}',
            '{"Authorisation"\r\n: "uk-opaque"}',
            "{'Cookie'\n: 'sid=opaque'}",
            r'{\"Authorization\": \"escaped-auth-opaque\"}',
            r"{\'Cookie\': \'escaped-cookie-opaque\'}",
            r'{\\"Authorization\\": \\"double-escaped-auth-opaque\\"}',
            r'{\"Cookie\": \"escaped-cookie-opaque\"}',
            r'{\\"Cookie\\": \\"double-escaped-cookie-opaque\\"}',
            r"{\'Authorization\': \'escaped-auth-opaque\'}",
            r"{\\'Authorization\\': \\'double-escaped-auth-opaque\\'}",
            r'{\"Authorisation\": \"escaped-authorisation-opaque\"}',
            r'{\\"Authorisation\\": \\"double-escaped-authorisation-opaque\\"}',
            r"{\'Authorisation\': \'escaped-authorisation-opaque\'}",
            r"{\\'Authorisation\\': \\'double-escaped-authorisation-opaque\\'}",
            r'{\"credentials\": \"escaped-credentials-opaque\"}',
            r'{\\"credentials\\": \\"double-escaped-credentials-opaque\\"}',
            r"{\'credentials\': \'escaped-credentials-opaque\'}",
            r"{\\'credentials\\': \\'double-escaped-credentials-opaque\\'}",
            r'{\"privateKey\": \"escaped-private-key-opaque\"}',
            r'{\\"privateKey\\": \\"double-escaped-private-key-opaque\\"}',
            r"{\'privateKey\': \'escaped-private-key-opaque\'}",
            r"{\\'privateKey\\': \\'double-escaped-private-key-opaque\\'}",
            '"privateKey": "opaque"',
            'Content-Type: application/json\r\nCookie: sid=opaque',
            'curl -H \'Accept: text/plain\' -H \'Cookie: sid=opaque\' URL',
        ],
    )
    def test_quoted_and_escaped_unstructured_credential_headers_fail_closed(
        self, fake_session, header_blob
    ):
        _set_trust("srv", "untrusted")
        args = {"header_blob": header_blob}
        assert _mcp_handlers._format_trust_gate_arguments(args) is None
        assert _mcp_handlers._format_gateway_trust_gate_command("srv", "write_file", args) is None
        with patch("tools.approval_prompt.request_elicitation_consent", return_value="accept") as consent:
            result = _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)
        consent.assert_not_called()
        fake_session.call_tool.assert_not_awaited()
        assert "error" in json.loads(result)

    def test_escaped_credential_header_fails_before_cost_booking(self, fake_session):
        """An escaped credential blob cannot prompt, dispatch, or book a paid call."""
        from tools import mcp_tool_costs

        _set_trust("srv", "untrusted")
        policy = mcp_tool_costs.parse_cost_policy(
            {"write_file": 40}, 100, None, where="test MCP server"
        )
        args = {
            "header_blob": r'{\\"Authorisation\\": \\"double-escaped-authorisation-opaque\\"}'
        }
        with patch.dict(mcp_tool._server_cost_policies, {"srv": policy}, clear=True), \
             patch.dict(mcp_tool_costs._spent, {}, clear=True), \
             patch("tools.approval_prompt.request_elicitation_consent", return_value="accept") as consent:
            result = _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

        assert _mcp_handlers._format_trust_gate_arguments(args) is None
        assert _mcp_handlers._format_gateway_trust_gate_command("srv", "write_file", args) is None
        consent.assert_not_called()
        fake_session.call_tool.assert_not_awaited()
        assert mcp_tool_costs._spent == {}
        assert "error" in json.loads(result)

    @pytest.mark.parametrize("header_blob", _ESCAPED_HEADER_CASES)
    def test_escape_layers_and_encoded_header_delimiters_fail_closed_before_cost(
        self, fake_session, header_blob
    ):
        """Every classification view must reject escaped opaque credential headers."""
        from tools import mcp_tool_costs

        _set_trust("srv", "untrusted")
        policy = mcp_tool_costs.parse_cost_policy(
            {"write_file": 40}, 100, None, where="test MCP server"
        )
        args = {"header_blob": header_blob}
        with patch.dict(mcp_tool._server_cost_policies, {"srv": policy}, clear=True), \
             patch.dict(mcp_tool_costs._spent, {}, clear=True), \
             patch("tools.approval_prompt.request_elicitation_consent", return_value="accept") as consent:
            result = _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

        assert _mcp_handlers._format_trust_gate_arguments(args) is None
        assert _mcp_handlers._format_gateway_trust_gate_command("srv", "write_file", args) is None
        consent.assert_not_called()
        fake_session.call_tool.assert_not_awaited()
        assert mcp_tool_costs._spent == {}
        assert "error" in json.loads(result)

    @pytest.mark.parametrize(
        "benign_text",
        [
            "author: Alice; semicolon is ordinary text",
            "authority: example.test",
            "capital: Paris",
            "rapid: response",
            "café \U0001f642 and ordinary Unicode",
        ],
    )
    def test_benign_unstructured_text_remains_displayable(self, fake_session, benign_text):
        _set_trust("srv", "untrusted")
        args = {"description": benign_text}
        assert _mcp_handlers._format_trust_gate_arguments(args) is not None
        assert _mcp_handlers._format_gateway_trust_gate_command("srv", "write_file", args) is not None
        with patch("tools.approval_prompt.request_elicitation_consent", return_value="decline") as consent:
            _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)
        consent.assert_called_once()
        assert benign_text in consent.call_args.args[0]
        fake_session.call_tool.assert_not_awaited()

    def test_unstructured_credential_in_argument_key_fails_closed(self, fake_session):
        _set_trust("srv", "untrusted")
        args = {"Cookie: sid=key-opaque": "visible", "target": "safe"}
        with patch("tools.approval_prompt.request_elicitation_consent", return_value="accept") as consent:
            result = _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)
        consent.assert_not_called()
        fake_session.call_tool.assert_not_awaited()
        assert "error" in json.loads(result)

    def test_oversized_preview_denies_before_consent_and_rpc(self, fake_session):
        """A hidden mutating argument cannot be approved behind a large benign prefix."""
        _set_trust("srv", "untrusted")
        args = {"notes": "x" * 4_500, "destructive_target": "/production/database"}
        handler = _mcp_handlers._make_tool_handler("srv", "mutate", 30.0)
        with patch("tools.approval_prompt.request_elicitation_consent", return_value="accept") as consent:
            raw = handler(args)

        consent.assert_not_called()
        fake_session.call_tool.assert_not_awaited()
        parsed = json.loads(raw)
        assert "error" in parsed
        assert "Reduce the payload" in parsed["error"]

    def test_preview_cap_allows_exact_boundary_and_rejects_one_char_over(self, fake_session):
        """The complete preview is approvable at 1200 chars, but not at 1201."""
        _set_trust("srv", "untrusted")
        prefix = "x"

        def args_for(prefix_length):
            return {"prefix": "x" * prefix_length, "late_mutating_field": "delete-prod"}

        def rendered_length(args):
            return len(json.dumps(args, ensure_ascii=False, indent=2))

        while rendered_length(args_for(len(prefix))) < 1_200:
            prefix += "x"
        assert rendered_length(args_for(len(prefix))) == 1_200
        under_limit = args_for(len(prefix))
        over_limit = {
            "prefix": under_limit["prefix"] + "x",
            "late_mutating_field": under_limit["late_mutating_field"],
        }
        assert rendered_length(over_limit) == 1_201

        with patch(
            "tools.approval_prompt.request_elicitation_consent", return_value="accept"
        ) as consent:
            accepted = _mcp_handlers._make_tool_handler("srv", "mutate", 30.0)(under_limit)

        consent.assert_called_once()
        message = consent.call_args.args[0]
        assert '"late_mutating_field": "delete-prod"' in message
        assert json.loads(accepted) == {"result": "ok"}
        fake_session.call_tool.assert_awaited_once()

        fake_session.call_tool.reset_mock()
        consent.reset_mock()
        with patch(
            "tools.approval_prompt.request_elicitation_consent", return_value="accept"
        ) as consent:
            refused = _mcp_handlers._make_tool_handler("srv", "mutate", 30.0)(over_limit)

        consent.assert_not_called()
        fake_session.call_tool.assert_not_awaited()
        assert "Reduce the payload" in json.loads(refused)["error"]

    def test_unrenderable_arguments_fail_closed_before_consent_or_transport(self, fake_session):
        """A preview failure cannot turn an untrusted call into an unreviewed dispatch."""
        _set_trust("srv", "untrusted")
        handler = _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)
        with patch("tools.approval_prompt.request_elicitation_consent") as consent:
            raw = handler({"payload": object()})

        consent.assert_not_called()
        fake_session.call_tool.assert_not_awaited()
        assert "error" in json.loads(raw)
        assert "object at" not in raw

    def test_custom_auth_header_shapes_are_masked(self, fake_session):
        """Opaque custom auth names and MCP header name/value objects never enter the card."""
        _set_trust("srv", "untrusted")
        args = {
            "auth": "opaque-auth-secret",
            "AUTH": "opaque-upper-auth-secret",
            "OAuth": "opaque-mixed-oauth-secret",
            "Custom-Auth": "opaque-custom-secret",
            "Proxy-Auth": "opaque-proxy-secret",
            "api_auth": "opaque-api-secret",
            "oauth": "opaque-oauth-secret",
            "headers": {
                "X-Custom-Auth": "opaque-header-secret",
                "CUSTOM-AUTH": "opaque-upper-header-secret",
            },
            "header": {"name": "api_auth", "value": "opaque-object-secret"},
            "header_upper": {"name": "PROXY-AUTH", "value": "opaque-upper-object-secret"},
        }
        with patch("tools.approval_prompt.request_elicitation_consent", return_value="decline") as consent:
            _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

        consent.assert_called_once()
        message = consent.call_args.args[0]
        for secret in (
            "opaque-auth-secret",
            "opaque-upper-auth-secret",
            "opaque-mixed-oauth-secret",
            "opaque-custom-secret",
            "opaque-proxy-secret",
            "opaque-api-secret",
            "opaque-oauth-secret",
            "opaque-header-secret",
            "opaque-upper-header-secret",
            "opaque-object-secret",
            "opaque-upper-object-secret",
        ):
            assert secret not in message
        for key in (
            "auth", "AUTH", "OAuth", "Custom-Auth", "Proxy-Auth", "api_auth", "oauth",
            "X-Custom-Auth", "CUSTOM-AUTH",
        ):
            assert f'"{key}": "***"' in message
        assert message.count('"value": "***"') == 2
        fake_session.call_tool.assert_not_awaited()

    def test_redaction_sees_token_before_preview_size_check(self, fake_session, monkeypatch):
        """A token in an oversized preview is redacted before the call is refused."""
        import agent.redact

        seen = []
        real_redactor = agent.redact.redact_sensitive_text

        def record_redaction(value, **kwargs):
            seen.append(value)
            return real_redactor(value, **kwargs)

        monkeypatch.setattr(agent.redact, "redact_sensitive_text", record_redaction)
        _set_trust("srv", "untrusted")
        token = "sk-boundary-secret-1234567890"
        args = {"padding": "x" * 4_790, "payload": "prefix-" + token}
        with patch("tools.approval_prompt.request_elicitation_consent", return_value="decline") as consent:
            raw = _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)(args)

        assert any(token in value for value in seen)
        consent.assert_not_called()
        assert token not in raw
        fake_session.call_tool.assert_not_awaited()

    def test_control_separated_secret_is_redacted_before_json_escaping(self, fake_session, monkeypatch):
        """JSON's control escapes cannot hide a secret from the central force redactor."""
        import agent.redact

        seen = []
        real_redactor = agent.redact.redact_sensitive_text

        def record_redaction(value, **kwargs):
            seen.append(value)
            return real_redactor(value, **kwargs)

        monkeypatch.setattr(agent.redact, "redact_sensitive_text", record_redaction)
        _set_trust("srv", "untrusted")
        secret = "sk-control-separated-secret-123456"
        with patch("tools.approval_prompt.request_elicitation_consent", return_value="decline") as consent:
            _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)({"payload": secret[:8] + "\x1b" + secret[8:]})

        assert any("\x1b" in value for value in seen)
        assert "control-separated-secret" not in consent.call_args.args[0]
        fake_session.call_tool.assert_not_awaited()

    def test_authorized_untrusted_hint_call_is_not_replayed_when_outcome_is_uncertain(
        self, fake_session
    ):
        """One explicit approval permits one dispatch, never an uncertain replay."""
        _set_trust("srv", "untrusted")
        _set_read_only("srv", "delete_repo", True)  # hostile server annotation
        fake_session.call_tool.side_effect = [RuntimeError("Session terminated"),
                                               _FakeCallToolResult([_FakeContentBlock("replayed")])]
        handler = _mcp_handlers._make_tool_handler("srv", "delete_repo", 30.0)
        with patch(
            "tools.approval_prompt.request_elicitation_consent", return_value="accept"
        ) as consent:
            raw = handler({"repo": "x"})

        consent.assert_called_once()
        fake_session.call_tool.assert_awaited_once()
        parsed = json.loads(raw)
        assert parsed.get("outcome_uncertain") is True, parsed

    def test_denied_approval_blocks_rpc(self, fake_session):
        """'decline' blocks the call — the RPC must never fire."""
        _set_trust("srv", "untrusted")
        handler = _mcp_handlers._make_tool_handler("srv", "delete_repo", 30.0)
        with patch(
            "tools.approval_prompt.request_elicitation_consent",
            return_value="decline",
        ):
            raw = handler({"repo": "x"})
        fake_session.call_tool.assert_not_awaited()
        assert "error" in json.loads(raw)

    def test_read_only_hint_on_untrusted_server_still_requires_approval(
        self, fake_session
    ):
        """A hostile readOnlyHint=True cannot bypass the mandatory trust gate."""
        _set_trust("srv", "untrusted")
        _set_read_only("srv", "list_repos", True)
        handler = _mcp_handlers._make_tool_handler("srv", "list_repos", 30.0)
        with patch(
            "tools.approval_prompt.request_elicitation_consent", return_value="decline"
        ) as consent:
            raw = handler({})
        consent.assert_called_once()
        fake_session.call_tool.assert_not_awaited()
        assert "error" in json.loads(raw)

    def test_trusted_server_skips_approval_for_write_tools(
        self, fake_session
    ):
        """trust: full (and the default) never consults approval."""
        _set_trust("srv", "full")
        handler = _mcp_handlers._make_tool_handler("srv", "delete_repo", 30.0)
        with patch(
            "tools.approval_prompt.request_elicitation_consent"
        ) as consent:
            raw = handler({"repo": "x"})
        consent.assert_not_called()
        assert json.loads(raw) == {"result": "ok"}

    def test_full_trust_read_only_hint_remains_replay_safe(self, fake_session):
        """Full-trust servers retain annotation-based read-only recovery."""
        _set_trust("srv", "full")
        _set_read_only("srv", "list_repos", True)
        assert _mcp_handlers._tool_is_read_only("srv", "list_repos") is True

    def test_unconfigured_server_defaults_to_full_trust(self, fake_session):
        """Backward compat: servers with no trust key behave as before."""
        handler = _mcp_handlers._make_tool_handler("srv", "delete_repo", 30.0)
        with patch(
            "tools.approval_prompt.request_elicitation_consent"
        ) as consent:
            raw = handler({"repo": "x"})
        consent.assert_not_called()
        assert json.loads(raw) == {"result": "ok"}

    def test_read_only_false_hint_is_gated(self, fake_session):
        """An explicit readOnlyHint=False is write-capable."""
        _set_trust("srv", "untrusted")
        _set_read_only("srv", "write_file", False)
        handler = _mcp_handlers._make_tool_handler("srv", "write_file", 30.0)
        with patch(
            "tools.approval_prompt.request_elicitation_consent",
            return_value="decline",
        ) as consent:
            handler({"path": "/etc/passwd"})
        consent.assert_called_once()
        fake_session.call_tool.assert_not_awaited()

    def test_approval_exception_fails_closed(self, fake_session):
        """Any exception in the consent path blocks the call."""
        _set_trust("srv", "untrusted")
        handler = _mcp_handlers._make_tool_handler("srv", "delete_repo", 30.0)
        with patch(
            "tools.approval_prompt.request_elicitation_consent",
            side_effect=RuntimeError("approval backend down"),
        ):
            raw = handler({"repo": "x"})
        fake_session.call_tool.assert_not_awaited()
        assert "error" in json.loads(raw)


class TestTrustGateApprovalRouting:
    """MCP consent uses the API run's registered approval lifecycle only."""

    def test_api_run_callback_can_resolve_mcp_trust_gate(self, monkeypatch):
        """An API run emits and resolves the exact per-call consent request."""
        from gateway.session_context import clear_session_vars, set_session_vars
        from tools import approval, approval_prompt
        from tools.approval_context import (
            reset_current_session_key,
            set_current_session_key,
        )

        session_key = "api-run-mcp-trust"
        seen = []
        # If the API callback is not selected, fail fast instead of waiting for
        # the CLI input timeout in this non-interactive test process.
        monkeypatch.setattr(approval_prompt, "prompt_dangerous_approval", lambda *_args, **_kwargs: "deny")

        def notify(approval_data):
            seen.append(dict(approval_data))
            assert approval.resolve_gateway_approval(
                session_key, "once", request_id=approval_data["request_id"]
            ) == 1

        session_tokens = set_session_vars(
            platform="api_server", session_key=session_key, async_delivery=False
        )
        key_token = set_current_session_key(session_key)
        approval.register_gateway_notify(session_key, notify)
        try:
            assert approval_prompt.request_elicitation_consent(
                "MCP tool 'write' on UNTRUSTED server 'srv' wants to run.",
                "Approve once or deny.", surface="mcp-trust/srv",
            ) == "accept"
        finally:
            approval.unregister_gateway_notify(session_key)
            reset_current_session_key(key_token)
            clear_session_vars(session_tokens)

        assert len(seen) == 1
        assert seen[0]["pattern_key"] == "mcp_elicitation"
        assert seen[0]["request_id"]

    @pytest.mark.parametrize("platform,cron,single_query", [
        ("webhook", "", False),
        ("telegram", "1", False),
        ("api_server", "", True),
        ("local", "", True),  # a `chat -q` turn admitted to the gateway: finite, nobody answers
    ])
    def test_unattended_cron_and_single_query_contexts_do_not_use_callback(
        self, monkeypatch, platform, cron, single_query
    ):
        """A registered callback must not widen consent for webhook, cron, or -q workers (#111526)."""
        from gateway.session_context import clear_session_vars, set_session_vars
        from tools import approval, approval_prompt
        from tools.approval_context import (
            reset_current_session_key,
            set_current_session_key,
        )

        session_key = f"{platform}-mcp-trust"
        notified = []
        session_tokens = set_session_vars(
            platform=platform, session_key=session_key, cron_session=cron
        )
        key_token = set_current_session_key(session_key)
        approval.register_gateway_notify(session_key, lambda data: notified.append(data))
        monkeypatch.setattr(approval_prompt, "prompt_dangerous_approval", lambda *_args, **_kwargs: "deny")
        gateway_waits = []
        monkeypatch.setattr(
            approval_prompt._gw,
            "_await_gateway_decision",
            lambda *_args, **_kwargs: gateway_waits.append(_args) or {"resolved": True, "choice": "once"},
        )
        if single_query:
            monkeypatch.setattr(approval_prompt._ctx, "_is_single_query_approval_context", lambda: True)
        try:
            assert approval_prompt.request_elicitation_consent("write", "Approve once or deny.") == "decline"
        finally:
            approval.unregister_gateway_notify(session_key)
            reset_current_session_key(key_token)
            clear_session_vars(session_tokens)

        assert notified == []
        assert gateway_waits == []


    @pytest.mark.parametrize("context", ["single_query", "cron", "webhook"])
    def test_cli_panel_callback_is_never_asked_without_a_user(self, monkeypatch, context):
        """`hermes chat -q`, cron and unattended platforms can keep the CLI panel callback registered, but
        nobody answers it: consent declines at once instead of waiting the approval timeout (the e2e
        hang after ef1faa4cf8)."""
        from gateway.session_context import clear_session_vars, set_session_vars
        from tools import approval_prompt
        from tools.terminal_tool import set_approval_callback

        if context == "single_query":  # cli_single_query exports the marker into the process env
            monkeypatch.setenv("HERMES_SINGLE_QUERY_SESSION", "1")
            tokens = set_session_vars()
        elif context == "cron":  # the cron scheduler binds it per job
            tokens = set_session_vars(cron_session="1")
        else:  # an unattended platform: no adapter can carry an approval prompt
            tokens = set_session_vars(platform="webhook")
        asked = []
        set_approval_callback(lambda *args, **kwargs: asked.append(args) or "once")
        try:
            assert approval_prompt.request_elicitation_consent("write", "Approve once or deny.") == "decline"
        finally:
            set_approval_callback(None)
            clear_session_vars(tokens)
        assert asked == []


class TestTrustNormalization:
    def test_unknown_trust_value_treated_as_untrusted(self):
        """Garbage trust strings fail closed to untrusted."""
        assert _mcp_registration._normalize_server_trust("banana") == "untrusted"

    def test_known_values(self):
        assert _mcp_registration._normalize_server_trust("full") == "full"
        assert _mcp_registration._normalize_server_trust("UNTRUSTED") == "untrusted"
        assert _mcp_registration._normalize_server_trust("  Full ") == "full"
        # Missing key → default full (backward compatible; documented).
        assert _mcp_registration._normalize_server_trust(None) == "full"


class TestAnnotationCaptureAtDiscovery:
    """_register_server_tools records trust + readOnlyHint metadata."""

    def _make_tool(self, name, annotations=None):
        return SimpleNamespace(
            name=name, description="", inputSchema=None,
            annotations=annotations,
        )

    def test_registration_records_hints_and_trust(self):
        from tools.registry import ToolRegistry

        server = mcp_tool.MCPServerTask("srv")
        server.session = MagicMock()
        server._tools = [
            self._make_tool(
                "list_repos", SimpleNamespace(readOnlyHint=True)
            ),
            self._make_tool(
                "delete_repo", SimpleNamespace(readOnlyHint=False)
            ),
            self._make_tool("no_annotations", None),
        ]
        config = {
            "trust": "untrusted",
            "tools": {"resources": False, "prompts": False},
        }
        with patch("tools.registry.registry", ToolRegistry()), \
             patch("tools.mcp_tool_registration._track_mcp_tool_server"):
            _mcp_registration._register_server_tools("srv", server, config)

        assert mcp_tool._server_trust_levels["srv"] == "untrusted"
        hints = mcp_tool._tool_read_only_hints["srv"]
        assert hints.get("list_repos") is True
        # Anything not exactly True is write-capable.
        assert not hints.get("delete_repo")
        assert not hints.get("no_annotations")

    def test_dict_annotations_supported(self):
        """Cached/JSON annotations arrive as plain dicts."""
        assert _mcp_registration._annotation_read_only_hint(
            SimpleNamespace(annotations={"readOnlyHint": True})
        ) is True
        assert _mcp_registration._annotation_read_only_hint(
            SimpleNamespace(annotations={"readOnlyHint": "yes"})
        ) is False  # non-bool truthy → NOT read-only (hint must be True)
        assert _mcp_registration._annotation_read_only_hint(
            SimpleNamespace(annotations=None)
        ) is False
        assert _mcp_registration._annotation_read_only_hint(
            SimpleNamespace()
        ) is False

    def test_sdk2_snake_case_annotations_supported(self):
        """mcp 2.x models expose ``read_only_hint``; camelCase is only a serialization alias."""
        from mcp.types import ToolAnnotations
        sdk2 = ToolAnnotations.model_validate({"readOnlyHint": True, "destructiveHint": False})
        assert _mcp_registration._annotation_read_only_hint(SimpleNamespace(annotations=sdk2)) is True
        assert _mcp_registration._annotation_read_only_hint(
            SimpleNamespace(annotations=SimpleNamespace(read_only_hint=True))
        ) is True
        assert _mcp_registration._annotation_read_only_hint(
            SimpleNamespace(annotations=SimpleNamespace(read_only_hint=False))
        ) is False
        # 1.x-shaped object (camelCase attribute) still works.
        assert _mcp_registration._annotation_read_only_hint(
            SimpleNamespace(annotations=SimpleNamespace(readOnlyHint=True))
        ) is True
        # Cache dict written by an older client in snake_case is honoured too.
        assert _mcp_registration._annotation_read_only_hint(
            SimpleNamespace(annotations={"read_only_hint": True})
        ) is True
