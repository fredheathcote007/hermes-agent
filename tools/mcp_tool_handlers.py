"""Registry-facing sync handlers for MCP tools and utility tools (resources/prompts), plus the per-call recovery
ladder: trust gating, circuit breaker, auth (401) refresh, session-expired reconnect and dead-stdio respawn retry."""

import logging
import asyncio
import contextvars
import inspect
import json
import math
import re
import time
import unicodedata
from contextlib import asynccontextmanager
from functools import partial
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

from hermes_platform import declaration
from tools.registry import invalidate_check_fn_cache, tool_error
from tools.ansi_strip import strip_unicode_tags
from tools.mcp_tool_common import _exc_str, _sanitize_error, mcp_field, _core
from tools import mcp_tool_loop as _loop
from tools.mcp_tool_content import (
    _MCP_HARD_RESULT_CAP_CHARS, _cache_mcp_audio_block, _cache_mcp_image_block, _mcp_result_with_native_images,
    _render_mcp_dropped_block_notice, _render_mcp_resource_block, _strip_reserved_meta_keys,
    _truncate_mcp_text_result)
from tools.mcp_tool_errors import (
    _auth_error_detail, _is_auth_error, _is_session_expired_error, _mcp_call_failed_message)

logger = logging.getLogger("tools.mcp_tool")
_MISSING = object()

declaration.on_change = invalidate_check_fn_cache

_NEEDS_REAUTH_MSG = (
    "MCP server '{s}' requires re-authentication.{detail} Run `hermes mcp login {s}` (or delete the tokens file under "
    "~/.hermes/mcp-tokens/ and restart). Do NOT retry this tool — ask the user to re-authenticate.")
_STDIO_NO_RESPAWN_MSG = (
    "MCP server '{s}' stdio subprocess had exited (this is not a timeout — the call never reached the server). A "
    "respawn was requested but no fresh session came back within {t:.0f}s. Wait a few seconds before retrying; if it "
    "keeps failing the server is not starting and needs the user.")
_STDIO_DIED_AGAIN_MSG = (
    "MCP server '{s}' respawned its stdio subprocess and it exited again immediately. The server is not starting "
    "cleanly — do NOT retry this tool; ask the user to check the server's command and its stderr log.")
_STDIO_OUTCOME_UNCERTAIN_MSG = (
    "MCP server '{s}' lost its stdio subprocess after the tool call began. The operation may have completed, so "
    "Hermes did not replay it. Do NOT retry automatically; inspect the external state first.")
_SESSION_OUTCOME_UNCERTAIN_MSG = (
    "The MCP transport session to '{s}' expired while this write-capable call was in flight, so the outcome is "
    "UNKNOWN — the operation may or may not have taken effect server-side. It was NOT automatically retried to "
    "avoid a duplicate side effect. The connection has {state}. Verify whether the operation took effect (e.g. "
    "with a read-only tool) before re-invoking it.")


def _tool_is_read_only(server_name: str, tool_name: str) -> bool:
    """Whether a tool is safe to replay after a transport failure.

    ``readOnlyHint`` is server-controlled metadata, so it is useful only for
    the operator-trusted tier. An untrusted server's tools are all potentially
    mutating, regardless of the hint, and must never be replayed automatically.
    """
    from tools.mcp_tool_scope import _resolve_server_key, _server_key
    trust_key = _server_key(server_name)
    trust = _core._server_trust_levels.get(trust_key, _core._TRUST_FULL)
    if trust != _core._TRUST_FULL:
        return False
    return _core._tool_read_only_hints.get(_resolve_server_key(server_name), {}).get(tool_name) is True


_TRUST_GATE_ARGUMENTS_MAX_CHARS = 1_200
_TRUST_GATE_ARGUMENTS_MAX_NODES = 256
_TRUST_GATE_ARGUMENTS_MAX_DEPTH = 32
_TRUST_GATE_ARGUMENTS_MAX_SCALAR_CHARS = 64_000
_TRUST_GATE_ARGUMENTS_SERIALIZATION_BUDGET = 4 * _TRUST_GATE_ARGUMENTS_MAX_CHARS + 512
_TRUST_GATE_CLASSIFICATION_MAX_PASSES = 8
_HEADER_NAME_CANDIDATE_MAX_CHARS = 256
_SECRET_NAME_IGNORABLE_CATEGORIES = frozenset({"Cc", "Cf", "Cn", "Me", "Mn", "Zl", "Zp", "Zs"})
_SECRET_NAME_IGNORABLE_CHARS = frozenset({"\u115f", "\u1160", "\u2800", "\u3164", "\uffa0"})
_HEADER_NAME_RFC7230_SEPARATORS = frozenset("!#$%&'*+-.^_`|~")
_HEADER_NAME_SEPARATOR_CATEGORIES = frozenset(
    {
        "Pc", "Pd", "Pe", "Pf", "Pi", "Po", "Ps",
        "Sc", "Sk", "Sm", "So",
    }
)
_CREDENTIAL_KEY_QUALIFIERS = frozenset(
    {
        "secret", "private", "credential", "password", "api", "access", "client",
        "auth", "token", "signing", "encryption", "hmac", "ssh",
    }
)
_PUBLIC_KEY_NAMES = frozenset({"publickey", "publickeyid", "sshpublickey", "sshpublickeyid"})
_NON_SECRET_KEY_BASES = frozenset({"author", "authority", "capital", "rapid"})
_HEADER_NAME_KEY_ALIASES = frozenset(
    {"name", "key", "k", "label", "field", "header", "headername", "headerkey", "fieldname", "keyname"}
)
_HEADER_VALUE_KEY_ALIASES = frozenset(
    {
        "value", "val", "v", "headervalue", "fieldvalue",
        "content", "data", "text", "body", "raw", "contents", "payload", "values", "valuestring",
        "headercontent", "fieldcontent", "headerdata", "fielddata",
    }
)
_AMBIGUOUS_HEADER_VALUE_ALIASES = frozenset({"content", "data", "body", "payload"})
_HEADER_COLON_CONFUSABLES = frozenset({"\u2236", "\u205a", "\u2254", "\u2255"})


class _TrustGatePreviewBudget:
    """Bound the untrusted object walk before it reaches JSON serialization."""

    def __init__(self):
        self.nodes = 0
        self.estimated_chars = 0
        self.active_ids = set()

    def visit(self, value: Any, depth: int) -> None:
        if depth > _TRUST_GATE_ARGUMENTS_MAX_DEPTH:
            raise ValueError("preview nesting limit")
        self.nodes += 1
        if self.nodes > _TRUST_GATE_ARGUMENTS_MAX_NODES:
            raise ValueError("preview node limit")
        if isinstance(value, str) and len(value) > _TRUST_GATE_ARGUMENTS_MAX_SCALAR_CHARS:
            raise ValueError("preview scalar limit")
        if isinstance(value, int) and not isinstance(value, bool):
            try:
                encoded = json.dumps(value, allow_nan=False)
            except (TypeError, ValueError, OverflowError):
                raise ValueError("invalid integer preview value") from None
            if len(encoded) > _TRUST_GATE_ARGUMENTS_SERIALIZATION_BUDGET:
                raise ValueError("preview integer limit")

    def account(self, chars: int) -> bool:
        self.estimated_chars += chars
        if self.estimated_chars > _TRUST_GATE_ARGUMENTS_SERIALIZATION_BUDGET:
            return False
        return True


def _merge_surrogate_pairs(text: str) -> str:
    """Decode JSON UTF-16 pairs while rejecting ambiguous lone surrogates."""
    result = []
    index = 0
    while index < len(text):
        codepoint = ord(text[index])
        if 0xD800 <= codepoint <= 0xDBFF:
            if index + 1 >= len(text):
                raise ValueError("lone surrogate in secret name")
            low = ord(text[index + 1])
            if not 0xDC00 <= low <= 0xDFFF:
                raise ValueError("invalid surrogate pair in secret name")
            result.append(chr(0x10000 + ((codepoint - 0xD800) << 10) + low - 0xDC00))
            index += 2
            continue
        if 0xDC00 <= codepoint <= 0xDFFF:
            raise ValueError("lone surrogate in secret name")
        result.append(text[index])
        index += 1
    return "".join(result)


def _contains_escaped_control(text: str) -> bool:
    """Reject escapes that turn an ambiguous structured name into a control string."""
    short_escapes = {"a": "\a", "b": "\b", "f": "\f", "n": "\n",
                     "r": "\r", "t": "\t", "v": "\v"}
    for index, char in enumerate(text[:-1]):
        if char != "\\":
            continue
        escaped = text[index + 1]
        if escaped in short_escapes:
            return True
        digits = {"x": 2, "u": 4, "U": 8}.get(escaped)
        if digits is not None:
            candidate = text[index + 2:index + 2 + digits]
            if len(candidate) == digits and all(char in "0123456789abcdefABCDEF" for char in candidate):
                codepoint = int(candidate, 16)
                if codepoint <= 0x10FFFF and unicodedata.category(chr(codepoint)) in {"Cc", "Cs"}:
                    return True
        if escaped in "01234567":
            end = index + 1
            while end < len(text) and end < index + 4 and text[end] in "01234567":
                end += 1
            if unicodedata.category(chr(int(text[index + 1:end], 8))) in {"Cc", "Cs"}:
                return True
    return False


def _canonicalize_secret_name(text: str) -> str:
    """Apply the same bounded escape and Unicode view to every structured name."""
    if len(text) > _TRUST_GATE_ARGUMENTS_MAX_SCALAR_CHARS:
        raise ValueError("secret-name classification budget")
    view = text
    for _ in range(_TRUST_GATE_CLASSIFICATION_MAX_PASSES + 1):
        if _contains_escaped_control(view):
            raise ValueError("control escape in secret name")
        view = _merge_surrogate_pairs(_canonicalize_classification_view(view))
        view = unicodedata.normalize("NFKC", view).casefold()
        if "\\" in view:
            raise ValueError("ambiguous escape in secret name")
        if len(view) > _TRUST_GATE_ARGUMENTS_MAX_SCALAR_CHARS:
            raise ValueError("secret-name classification budget")
        if view == text:
            return view
        text = view
    raise ValueError("secret-name escape nesting exceeds preview limit")


def _secret_name_view(key: str) -> str:
    """Return a bounded, compatibility-normalized view with invisible marks removed."""
    if len(key) > _TRUST_GATE_ARGUMENTS_MAX_SCALAR_CHARS:
        raise ValueError("secret-name classification budget")
    normalized = _canonicalize_secret_name(key)
    if len(normalized) > _TRUST_GATE_ARGUMENTS_MAX_SCALAR_CHARS:
        raise ValueError("secret-name classification budget")
    return "".join(
        char for char in normalized
        if not _is_secret_name_ignorable(char)
    )


def _is_secret_name_ignorable(char: str) -> bool:
    """Whether *char* is unambiguously invisible or a separator in a name classifier."""
    return (
        char in _SECRET_NAME_IGNORABLE_CHARS
        or char.isspace()
        or unicodedata.category(char) in _SECRET_NAME_IGNORABLE_CATEGORIES
    )


def _compact_secret_name(key: Any) -> str:
    """Compact a possibly obfuscated name for classification, without changing payload data."""
    if not isinstance(key, str):
        return ""
    return "".join(char for char in _secret_name_view(key) if char.isalnum())


def _secret_name_parts(key: str) -> tuple[str, ...]:
    """Split a validated field name at punctuation and camel-case boundaries."""
    _canonicalize_secret_name(key)
    view = key
    for _ in range(_TRUST_GATE_CLASSIFICATION_MAX_PASSES + 1):
        view = _merge_surrogate_pairs(_canonicalize_classification_view(view))
        view = unicodedata.normalize("NFKC", view)
        if "\\" not in view:
            break
    view = "".join(char for char in view if not _is_secret_name_ignorable(char))
    view = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", view)
    parts = []
    current = []
    for char in view:
        if char.isalnum():
            current.append(char.casefold())
        elif current:
            parts.append("".join(current))
            current = []
    if current:
        parts.append("".join(current))
    return tuple(parts)


def _is_secret_argument_name(key: Any) -> bool:
    """Whether a structured argument key names a credential or secret header."""
    from agent.redact import SECRET_HEADER_NAME_LIST, is_secret_field_name

    if not isinstance(key, str):
        return False
    folded = _secret_name_view(key)
    compact = _compact_secret_name(key)
    parts = _secret_name_parts(key)
    part_set = set(parts)
    # Match credential-bearing header variants (X-Authentication, X-Auth-Data,
    # Proxy-Auth, etc.) without treating descriptive author fields as secrets.
    is_auth_header = (
        # Composite authorization fields (for example authorization_code or
        # X-Authorization-Data) are credentials even though they include "author".
        # Include the UK header spelling too; ordinary author/authority fields
        # remain descriptive, but authorisation is credential-bearing by default.
        "authorization" in compact
        or "authorisation" in compact
        or "oauth" in part_set
        or "authentication" in part_set
        or "auth" in part_set
    )
    # Cookie headers and cookie-shaped fields carry opaque session material even when the
    # value does not resemble a credential to the text redactor. Keep descriptive cookie
    # metadata visible, but mask fields that can hold the actual cookie value.
    is_cookie_field = compact.endswith(
        ("cookie", "cookies", "setcookie", "cookieheader", "cookievalue", "cookiejar")
    )
    # Opaque credential keys often end in "key", not in "secret" or "token". Preserve the
    # original compact substring matching: model-chosen names can use punctuation, Unicode
    # separators, odd casing, or digit suffixes to bypass a segment-only classifier.
    ends_in_key = compact.endswith(("key", "keyid"))
    has_api_qualifier = any(part == "api" or part.startswith("api") for part in parts)
    sensitive_key = (
        ends_in_key
        and (
            bool(part_set & _CREDENTIAL_KEY_QUALIFIERS)
            or has_api_qualifier
        )
    )
    key_base = compact[:-5] if compact.endswith("keyid") else compact[:-3]
    if key_base in _NON_SECRET_KEY_BASES:
        sensitive_key = False
    if compact in _PUBLIC_KEY_NAMES or ("public" in part_set and "key" in part_set):
        sensitive_key = False
    if "key" in part_set and any(part in part_set for part in ("secret", "private", "credential", "credentials", "password", "passwd")):
        sensitive_key = True
    if compact in {
        "accesskey", "accesskeyid", "clientkey", "signingkey",
        "authoroauth", "authorauthentication", "keymaterial",
    }:
        sensitive_key = True
    return (
        is_secret_field_name(folded)
        or folded in SECRET_HEADER_NAME_LIST
        or compact in {"auth", "authorization", "bearer", "token", "secret", "password", "credential"}
        or is_auth_header
        or is_cookie_field
        or sensitive_key
        or compact.endswith(("apikey", "token", "secret", "password", "passwd", "credential", "credentials"))
        or compact.startswith(("secret", "password", "passwd", "credential"))
        or compact == "keymaterial"
        or compact in {"authoroauth", "authorauthentication"}
    )


def _is_header_colon(char: str) -> bool:
    """Whether *char* can delimit a header name in attacker-controlled text."""
    if char == ":" or char in _HEADER_COLON_CONFUSABLES:
        return True
    # This includes FULLWIDTH/SMALL/MODIFIER/SYRIAC colon forms without treating
    # SEMICOLON or COLON SIGN as a header delimiter. Names such as SYRIAC COLON
    # SKEWED LEFT do not end in COLON, so retain their explicit name component.
    name = unicodedata.name(char, "")
    return name.endswith(" COLON") or name.startswith("SYRIAC ") and " COLON " in name


def _is_header_name_char(char: str) -> bool:
    """Whether *char* can occur inside a possibly obfuscated header name."""
    if _is_header_colon(char):
        return False
    # Whitespace is prose structure. Treating it as a name character makes a
    # colon at the end of a paragraph classify every earlier credential word.
    if char.isspace():
        return False
    if char.isalnum() or _is_secret_name_ignorable(char):
        return True
    if char in _HEADER_NAME_RFC7230_SEPARATORS:
        return True
    if unicodedata.category(char) in _HEADER_NAME_SEPARATOR_CATEGORIES:
        return True
    # MINUS SIGN and slash-like compatibility characters are common rich-text
    # substitutions for ASCII name separators but do not all share its category.
    name = unicodedata.name(char, "")
    if any(part in name for part in ("DASH", "HYPHEN", "MINUS", "SOLIDUS", "SLASH")):
        return True
    normalized = unicodedata.normalize("NFKC", char)
    return normalized != char and all(
        _is_secret_name_ignorable(part)
        or part.isalnum()
        or part in _HEADER_NAME_RFC7230_SEPARATORS
        for part in normalized
    )


def _header_name_before_colon(text: str, colon_index: int) -> Optional[str]:
    """Extract the compact name immediately before a header-like separator."""
    cursor = colon_index - 1
    while cursor >= 0 and _is_secret_name_ignorable(text[cursor]):
        if colon_index - cursor > _HEADER_NAME_CANDIDATE_MAX_CHARS:
            raise ValueError("header name candidate span limit")
        cursor -= 1
    end = cursor + 1
    while cursor >= 0 and _is_header_name_char(text[cursor]):
        if colon_index - cursor > _HEADER_NAME_CANDIDATE_MAX_CHARS:
            raise ValueError("header name candidate span limit")
        cursor -= 1
    if end == cursor + 1:
        return None
    # Do not retain the old ASCII regex's 64-character cutoff: an attacker can pad a
    # credential name with format characters and otherwise make the live value visible.
    candidate = text[cursor + 1:end]
    # Preserve fail-closed handling for a compact credential-shaped obfuscation
    # before treating punctuation as a prose boundary.
    if _is_secret_argument_name(candidate):
        return candidate
    # Punctuation outside the RFC name set is an ambiguity boundary. Use the
    # final token for ordinary prose, while the caller's repeated canonical
    # passes still reject credential-shaped obfuscations such as ``api=key``.
    for split in range(len(candidate) - 1, -1, -1):
        if candidate[split].isalnum() or _is_secret_name_ignorable(candidate[split]):
            continue
        if candidate[split] in _HEADER_NAME_RFC7230_SEPARATORS:
            continue
        candidate = candidate[split + 1:]
        break
    return candidate


def _header_candidate_is_uri_or_path(text: str, colon_index: int, candidate: str) -> bool:
    """Avoid treating a host, registry path, or URL port as a header name."""
    url_match = re.search(
        r"(?<![A-Za-z0-9+.-])[A-Za-z][A-Za-z0-9+.-]*://",
        text[:colon_index],
    )
    if url_match:
        authority_start = url_match.end()
        authority_end = len(text)
        for delimiter in "/?#":
            delimiter_index = text.find(delimiter, authority_start)
            if delimiter_index >= 0:
                authority_end = min(authority_end, delimiter_index)
        if colon_index < authority_end:
            authority = text[authority_start:authority_end].rsplit("@", 1)[-1]
            relative_colon = colon_index - authority_start
            if authority.startswith("["):
                closing_bracket = authority.find("]")
                if closing_bracket >= 0 and relative_colon <= closing_bracket:
                    return True
            port = authority[relative_colon + 1:]
            if port.isdigit() and relative_colon > 0:
                return True
        # Once a URL has left its authority, punctuation-attached text is not
        # protected by the URL recognizer and must still be scanned for headers.
        return False
    if "/" not in candidate or any(char.isspace() for char in candidate):
        return False
    first_component = candidate.split("/", 1)[0].strip("\"'`\\")
    return candidate.startswith("/") or "." in first_component


def _header_candidate_has_structural_context(text: str, colon_index: int) -> bool:
    """Recognize a header token at a credible boundary without trusting prose context."""
    line_start = max(text.rfind("\n", 0, colon_index), text.rfind("\r", 0, colon_index)) + 1
    prefix = text[line_start:colon_index].rstrip()
    cursor = len(prefix) - 1
    while cursor >= 0 and _is_header_name_char(prefix[cursor]):
        cursor -= 1
    before_name = prefix[:cursor + 1].rstrip()
    if not before_name:
        return True
    if before_name[-1] in "{[(:,;":
        return True
    marker = before_name.rsplit(None, 1)[-1]
    if marker in {"-H", "--header", "-h"}:
        return True
    # A prose prefix is not enough to classify an ordinary ``authorization:`` sentence
    # as a header. Other secret-shaped header names are not safely distinguishable from
    # credential-bearing prose when their value has no structured name=value shape, so
    # fail closed rather than rely on the central redactor to recognize every value.
    candidate = _header_name_before_colon(text, colon_index)
    if candidate is None:
        return False
    compact = _compact_secret_name(candidate)
    return compact != "authorization" and _is_secret_argument_name(candidate)


def _canonicalize_classification_view(text: str) -> str:
    """Decode one bounded layer of common string escapes for classification only."""
    replacements = {
        '"': '"', "'": "'", "`": "`", "\\": "\\", "/": "/",
        "a": "\a", "b": "\b", "f": "\f", "n": "\n", "r": "\r",
        "t": "\t", "v": "\v",
    }
    output = []
    output_chars = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char != "\\" or index + 1 >= len(text):
            output.append(char)
            output_chars += 1
            if output_chars > _TRUST_GATE_ARGUMENTS_MAX_SCALAR_CHARS:
                raise ValueError("classification normalization budget")
            index += 1
            continue

        escaped = text[index + 1]
        replacement = replacements.get(escaped)
        consumed = 2
        if escaped in ("x", "u", "U"):
            digits = {"x": 2, "u": 4, "U": 8}[escaped]
            end = index + 2 + digits
            candidate = text[index + 2:end]
            if len(candidate) == digits and all(char in "0123456789abcdefABCDEF" for char in candidate):
                codepoint = int(candidate, 16)
                if codepoint <= 0x10FFFF:
                    replacement = chr(codepoint)
                    consumed = 2 + digits
        if replacement is None and escaped in "01234567":
            end = index + 1
            while end < len(text) and end < index + 4 and text[end] in "01234567":
                end += 1
            replacement = chr(int(text[index + 1:end], 8))
            consumed = end - index
        if replacement is None:
            # Preserve malformed or unknown escapes and let a later bounded pass
            # inspect any suffix without throwing or changing operator text.
            output.extend(("\\", escaped))
            output_chars += 2
        else:
            output.append(replacement)
            output_chars += len(replacement)
        index += consumed
        if output_chars > _TRUST_GATE_ARGUMENTS_MAX_SCALAR_CHARS:
            raise ValueError("classification normalization budget")
    return "".join(output)


def _scan_unstructured_secret_headers(text: str) -> None:
    text = _merge_surrogate_pairs(text)
    for index, char in enumerate(text):
        if _is_header_colon(char):
            name = _header_name_before_colon(text, index)
            if (name is not None and _is_secret_argument_name(name)
                    and not _header_candidate_is_uri_or_path(text, index, name)
                    and _header_candidate_has_structural_context(text, index)):
                raise ValueError("unstructured credential header cannot be safely previewed")


def _reject_unstructured_secret_headers(text: str) -> None:
    """Fail closed on opaque credentials embedded inside arbitrary text.

    Header blobs and shell-quoted -H snippets cannot be redacted reliably
    without misidentifying delimiters and showing only part of a secret. The
    caller must instead supply structured headers whose values can be masked.
    """
    view = _merge_surrogate_pairs(text)
    for pass_number in range(_TRUST_GATE_CLASSIFICATION_MAX_PASSES + 1):
        _scan_unstructured_secret_headers(view)
        next_view = _canonicalize_classification_view(view)
        next_view = _merge_surrogate_pairs(next_view)
        if next_view == view:
            return
        if pass_number == _TRUST_GATE_CLASSIFICATION_MAX_PASSES:
            raise ValueError("unstructured header escape nesting exceeds preview limit")
        view = next_view


def _validate_preview_payload(value: Any, *, _budget=None, _depth: int = 0) -> None:
    """Walk the complete payload before field-aware masking hides any subtree."""
    budget = _budget or _TrustGatePreviewBudget()
    budget.visit(value, _depth)
    if isinstance(value, str):
        _merge_surrogate_pairs(value)
        _reject_unstructured_secret_headers(value)
        if not budget.account(len(value)):
            raise ValueError("preview serialization budget")
        return
    if value is None or isinstance(value, (bool, int)):
        if isinstance(value, int) and not isinstance(value, bool):
            encoded = json.dumps(value, allow_nan=False)
            size = len(encoded)
        else:
            size = 8
        if not budget.account(size):
            raise ValueError("preview serialization budget")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite preview value")
        if not budget.account(16):
            raise ValueError("preview serialization budget")
        return
    if isinstance(value, dict):
        identity = id(value)
        if identity in budget.active_ids:
            raise ValueError("cyclic preview value")
        budget.active_ids.add(identity)
        try:
            for key, item in value.items():
                if not isinstance(key, str) or len(key) > _TRUST_GATE_ARGUMENTS_MAX_SCALAR_CHARS:
                    raise ValueError("invalid preview key")
                _reject_url_credentials_in_key(key)
                _secret_name_view(key)
                _reject_unstructured_secret_headers(key)
                _validate_preview_payload(item, _budget=budget, _depth=_depth + 1)
                if not budget.account(len(key) + 4):
                    raise ValueError("preview serialization budget")
        finally:
            budget.active_ids.remove(identity)
        return
    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in budget.active_ids:
            raise ValueError("cyclic preview value")
        budget.active_ids.add(identity)
        try:
            for item in value:
                _validate_preview_payload(item, _budget=budget, _depth=_depth + 1)
                if not budget.account(2):
                    raise ValueError("preview serialization budget")
        finally:
            budget.active_ids.remove(identity)
        return
    raise ValueError("unsupported preview value")


def _is_header_name_alias(key: Any) -> bool:
    """Whether a structured object key can identify its header name."""
    return _compact_secret_name(key) in _HEADER_NAME_KEY_ALIASES


def _is_header_value_alias(key: Any) -> bool:
    """Whether a structured object key can carry the associated header value."""
    return _compact_secret_name(key) in _HEADER_VALUE_KEY_ALIASES


def _is_header_collection_key(key: Any) -> bool:
    return _compact_secret_name(key) in {
        "header", "headers", "headerlist", "headerblock", "headercollection", "headerpairs",
        "requestheaders", "extraheaders", "httpheaders", "pairs",
    }


def _reject_url_credentials_in_key(key: str) -> None:
    """Reject keys the shared redactor would change instead of renaming controls."""
    from agent.redact import redact_sensitive_text

    redacted = redact_sensitive_text(key, force=True, redact_url_credentials=True)
    if not isinstance(redacted, str) or redacted != key:
        raise ValueError("URL credentials in preview key")


def _is_header_sequence_mapping(value: dict) -> bool:
    """Whether mapping keys explicitly preserve positional sequence semantics."""
    keys = tuple(value)
    if len(keys) < 2:
        return False
    if all(isinstance(key, str) and key.isdecimal() for key in keys):
        return True
    ordinal_keys = ("first", "second", "third", "fourth", "fifth")
    return all(
        isinstance(key, str) and key.casefold() in ordinal_keys
        for key in keys
    )


def _is_ambiguous_header_label(
    value: Any, *, header_context: bool, sequence_context: bool
) -> bool:
    """Recognize credential labels without treating arbitrary session text as a label."""
    if not isinstance(value, str):
        return False
    if _is_secret_argument_name(value):
        return True
    return (header_context or sequence_context) and _compact_secret_name(value) == "session"


def _reject_ambiguous_header_mapping(value: dict, *, header_context: bool) -> None:
    """Reject object-shaped header sequences whose labels are only values."""
    sequence_context = _is_header_sequence_mapping(value)
    if not header_context and not sequence_context:
        return
    if (
        any(_is_header_name_alias(key) for key in value)
        or any(_is_secret_argument_name(key) for key in value)
    ):
        return
    if sequence_context and all(isinstance(key, str) and key.isdecimal() for key in value):
        items = tuple(
            item
            for _index, item in sorted(
                ((int(key), item) for key, item in value.items()),
                key=lambda pair: pair[0],
            )
        )
    elif sequence_context:
        ordinal_keys = ("first", "second", "third", "fourth", "fifth")
        items = tuple(
            item
            for _index, item in sorted(
                ((ordinal_keys.index(key.casefold()), item) for key, item in value.items()),
                key=lambda pair: pair[0],
            )
        )
    else:
        items = tuple(value.values())
    indices = range(len(items)) if sequence_context else range(0, len(items) - 1, 2)
    if any(
        _is_ambiguous_header_label(
            items[index], header_context=header_context, sequence_context=sequence_context
        )
        for index in indices
    ):
        raise ValueError("ambiguous header mapping")


def _looks_like_header_name(value: Any) -> bool:
    if not isinstance(value, str) or not _is_secret_argument_name(value):
        return False
    compact = _compact_secret_name(value)
    parts = _secret_name_parts(value)
    part_set = set(parts)
    return (
        compact in {"auth", "oauth", "authorization", "authorisation", "cookie", "setcookie"}
        or "authorization" in compact
        or "authorisation" in compact
        or compact.endswith(("apikey", "token", "secret", "password", "passwd", "credential", "credentials", "key", "keyid"))
        or compact.endswith("auth")
        or bool(part_set & {"auth", "authentication", "authorization", "authorisation", "cookie"})
    )


def _flat_header_credential_value_indices(value: list | tuple, *, header_context: bool) -> set[int]:
    """Return safely aligned credential values in a flat header sequence."""
    secret_name_indices = [
        index for index in range(len(value))
        if not (index % 2 and _is_secret_argument_name(value[index - 1]))
        for item in (value[index],)
        if isinstance(item, str)
        and _is_secret_argument_name(item)
        and (header_context or _looks_like_header_name(item))
    ]
    if not secret_name_indices:
        return set()
    if any(index % 2 for index in secret_name_indices):
        raise ValueError("ambiguous header sequence")
    if any(not isinstance(value[index], str) for index in range(0, len(value), 2)):
        raise ValueError("ambiguous header sequence")
    if any(index + 1 >= len(value) for index in secret_name_indices):
        raise ValueError("ambiguous header sequence")
    return {index + 1 for index in secret_name_indices}


def _mask_secret_scalar(value: Any, budget: _TrustGatePreviewBudget) -> Any:
    """Redact and account for scalar values in an approval preview."""
    from agent.redact import redact_sensitive_text

    if isinstance(value, str):
        _reject_unstructured_secret_headers(value)
        redacted = redact_sensitive_text(value, force=True, redact_url_credentials=True)
        if not isinstance(redacted, str):
            raise ValueError("preview redaction failed")
        if not budget.account(len(redacted)):
            raise ValueError("preview serialization budget")
        return redacted
    if value is None or isinstance(value, (bool, int)):
        if not budget.account(8):
            raise ValueError("preview serialization budget")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite preview value")
        if not budget.account(16):
            raise ValueError("preview serialization budget")
        return value
    raise ValueError("unsupported preview value")


def _mask_secret_argument_fields(value: Any, *, _budget=None, _depth: int = 0,
                                 _header_context: bool = False) -> Any:
    """Redact structured values recursively, with bounded traversal and no object reprs."""
    budget = _budget or _TrustGatePreviewBudget()
    budget.visit(value, _depth)
    if value is None or isinstance(value, (str, bool, int, float)):
        return _mask_secret_scalar(value, budget)
    if isinstance(value, dict):
        identity = id(value)
        if identity in budget.active_ids:
            raise ValueError("cyclic preview value")
        budget.active_ids.add(identity)
        try:
            _reject_ambiguous_header_mapping(value, header_context=_header_context)
            # Header objects may use mixed-case Name/Value or key/value pairs.
            # If several candidate labels are present, any credential-shaped label
            # makes the associated value sensitive; no arbitrary first-key wins.
            header_names = [
                item for key, item in value.items()
                if _is_header_name_alias(key) and isinstance(item, str)
                and (_header_context or _looks_like_header_name(item))
            ]
            header_is_secret = any(
                _is_header_name_alias(key) and isinstance(item, str)
                and _is_secret_argument_name(item)
                and (_header_context or _looks_like_header_name(item))
                for key, item in value.items()
            )
            ambiguous_header_values_are_credential_data = any(
                _compact_secret_name(name) not in {"auth", "oauth", "authcheck"} for name in header_names
            )
            result = {}
            for key, item in value.items():
                if not isinstance(key, str) or len(key) > _TRUST_GATE_ARGUMENTS_MAX_SCALAR_CHARS:
                    raise ValueError("invalid preview key")
                # Untrusted argument keys may themselves contain pasted header
                # blocks or quoted JSON; never expose embedded credential text.
                _reject_unstructured_secret_headers(key)
                secret_field = _is_secret_argument_name(key)
                # Only a recognized value alias is associated with the header name. Other
                # siblings remain visible so the operator sees the consequential payload.
                header_value_field = (
                    header_is_secret
                    and _is_header_value_alias(key)
                    and (
                        _compact_secret_name(key) not in _AMBIGUOUS_HEADER_VALUE_ALIASES
                        or (
                            ambiguous_header_values_are_credential_data
                            and not isinstance(item, (dict, list, tuple))
                        )
                    )
                )
                if (
                    header_is_secret
                    and _compact_secret_name(key) in _AMBIGUOUS_HEADER_VALUE_ALIASES
                    and (
                        isinstance(item, (list, tuple))
                        or (ambiguous_header_values_are_credential_data and isinstance(item, dict))
                    )
                ):
                    raise ValueError("ambiguous credential sequence")
                masked_item = _mask_secret_argument_fields(
                    item, _budget=budget, _depth=_depth + 1,
                    _header_context=_header_context or _is_header_collection_key(key),
                )
                if (header_value_field or secret_field) and item not in (None, ""):
                    result[key] = "***"
                else:
                    result[key] = masked_item
                if not budget.account(len(key) + 4):
                    raise ValueError("preview serialization budget")
            return result
        finally:
            budget.active_ids.remove(identity)
    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in budget.active_ids:
            raise ValueError("cyclic preview value")
        budget.active_ids.add(identity)
        try:
            credential_value_indices = _flat_header_credential_value_indices(
                value, header_context=_header_context
            )
            result = []
            for index, item in enumerate(value):
                masked_item = _mask_secret_argument_fields(
                    item, _budget=budget, _depth=_depth + 1,
                    _header_context=_header_context,
                )
                if index in credential_value_indices and item not in (None, ""):
                    result.append("***")
                else:
                    result.append(masked_item)
                if not budget.account(2):
                    raise ValueError("preview serialization budget")
            return result
        finally:
            budget.active_ids.remove(identity)
    return _mask_secret_scalar(value, budget)


def _escape_trust_gate_controls(text: str) -> str:
    """Make invisible/control argument data unambiguous in an operator-facing card."""
    import unicodedata

    return "".join(
        # JSON encoding yields correct UTF-16 surrogate pairs for non-BMP Cf
        # characters rather than ambiguous five/six-digit backslash-u escapes.
        json.dumps(char, ensure_ascii=True)[1:-1]
        if char != "\n" and unicodedata.category(char) in ("Cc", "Cf", "Cs")
        else char
        for char in text
    )


def _format_trust_gate_arguments(args: Any, *, compact: bool = False) -> Optional[str]:
    """Return a force-redacted, bounded JSON preview, or ``None`` if it is unsafe to render.

    Gateway approval commands use compact JSON so the strict text fallback has room for the
    complete server/tool/arguments payload. CLI/TUI keeps the indented 1200-character preview.
    """
    from agent.redact import redact_sensitive_text

    try:
        _validate_preview_payload(args)
        sanitized = _mask_secret_argument_fields(args)
        rendered = json.dumps(
            # Gateway cards require ASCII-safe JSON. CLI/TUI may display Unicode
            # directly to avoid rejecting legitimate long CJK/emoji arguments.
            sanitized, ensure_ascii=compact, allow_nan=False,
            **({"separators": (",", ":")} if compact else {"indent": 2}),
        )
        rendered = _escape_trust_gate_controls(rendered)
        # Defense in depth for any serializer expansion; the source was already redacted and
        # structured-budgeted above, so this never slices raw argument data.
        rendered = redact_sensitive_text(rendered, force=True)
        if not isinstance(rendered, str):
            return None
        rendered = _escape_trust_gate_controls(rendered)
        if len(rendered) > _TRUST_GATE_ARGUMENTS_MAX_CHARS:
            # A partial card is not an authoritative representation of the call: a hidden
            # later argument could be the mutating target. Refuse before consent instead of
            # inviting approval for a preview that omits arguments.
            return None
        return rendered
    except Exception:
        # Argument reprs are untrusted input. Never expose an exception or fall back to raw args;
        # the caller turns this into a fail-closed trust-gate denial. Keep the traceback so an
        # unexpected formatter failure is diagnosable without weakening that boundary.
        logger.exception("MCP trust-gate preview formatting failed; refusing to render")
        return None


def _trust_gate_check(server_name: str, tool_name: str, booked: Optional[list] = None,
                      args: Any = None) -> Optional[str]:
    """Approval gate for write-capable tools on ``trust: untrusted`` servers, plus the declared spend
    limit on any server. None to proceed, else a ``tool_error``. Fail-closed: approval-system errors
    block. An admitted costed call is charged to the chat's tally and appended to *booked* so the
    caller can refund it when the call never reaches the server."""
    from tools.mcp_tool_scope import _server_key
    from tools import mcp_tool_costs as _costs
    # Trust and costs are the calling profile's own policy (an adopter of a shared connection keeps its own).
    key = _server_key(server_name)
    trust = _core._server_trust_levels.get(key, _core._TRUST_FULL)
    # An untrusted server controls its own annotations. Every native tools/call
    # therefore requires explicit per-call consent; no server hint relaxes this.
    gated = trust != _core._TRUST_FULL
    charge = None
    if key in _core._server_cost_policies:  # no table: not even a session lookup, main's path byte for byte
        from tools.approval_context import get_current_session_key
        charge = _costs.pending_charge(key, server_name, tool_name, get_current_session_key())
    if charge is None:
        return _ask_for_call(server_name, tool_name, None, booked, args=args) if gated else None
    if not gated and charge.reserve_within_limit()[0]:
        if booked is not None:
            booked.append(charge)
        return None
    with charge.asking():  # re-read under the slot: a call that asked first may have booked meanwhile
        return _ask_for_call(server_name, tool_name, charge, booked, gated=gated, args=args)


def _gateway_mcp_approval_context() -> bool:
    """Whether the current MCP consent can reach a gateway/API approval surface."""
    from tools import approval_context as _ctx

    return (_ctx._is_gateway_approval_context()
            or (_ctx._get_session_platform() == "api_server"
                and not _ctx._is_cron_approval_context()
                and not _ctx._is_single_query_approval_context()))


def _format_gateway_trust_gate_command(server_name: str, tool_name: str, args: Any) -> Optional[str]:
    """Build the complete compact payload that must fit the gateway fallback command field."""
    argument_preview = _format_trust_gate_arguments(args, compact=True)
    if argument_preview is None:
        return None
    try:
        # Keep the bounded, redacted JSON fragment intact. Decoding it and dumping with
        # ensure_ascii=False would reintroduce invisible characters and would misparse the
        # six-digit escape emitted for non-BMP tag characters. Validate, but never substitute
        # the parsed value back into the operator-visible payload.
        json.loads(argument_preview)
        identity = json.dumps(
            {"server": server_name, "tool": tool_name},
            ensure_ascii=True, separators=(",", ":"), allow_nan=False,
        )
        payload = identity[:-1] + ",\"arguments\":" + argument_preview + "}"
        from tools.approval_prompt import prepare_gateway_approval_command
        prepared = prepare_gateway_approval_command(f"MCP untrusted call {payload}")
        from gateway.platforms.base_exec_approval import GATEWAY_APPROVAL_COMMAND_MAX_CHARS
        return (prepared if prepared is not None
                and len(prepared) <= GATEWAY_APPROVAL_COMMAND_MAX_CHARS else None)
    except (TypeError, ValueError):
        return None


def _ask_for_call(server_name: str, tool_name: str, charge, booked: Optional[list], *,
                  gated: bool = True, args: Any = None) -> Optional[str]:
    """Ask the user about one gated and/or costed call; book the charge only on an explicit yes."""
    spent, over = 0.0, False
    if charge is not None:
        if gated:
            spent = charge.spent()
            over = charge.over_limit(spent)
        else:
            reserved, spent = charge.reserve_within_limit()
            if reserved:
                if booked is not None:
                    booked.append(charge)
                return None
            over = True
    extra = charge.lines(spent) if charge is not None else []
    if gated and _gateway_mcp_approval_context():
        message = _format_gateway_trust_gate_command(server_name, tool_name, args)
        if message is None:
            return tool_error(f"MCP tool '{tool_name}' on untrusted server '{server_name}' was blocked: its "
                              "complete approval payload does not fit the gateway display limit. "
                              "Reduce the payload and try again.")
        description = ("MCP untrusted call; approve once only after reviewing the complete payload."
                       + (f" {' '.join(extra)}" if extra else ""))
        title = f"MCP server '{server_name}' is asking"
    elif gated:
        argument_preview = _format_trust_gate_arguments(args)
        if argument_preview is None:
            return tool_error(f"MCP tool '{tool_name}' on untrusted server '{server_name}' was blocked: its "
                              "arguments could not be rendered safely within the approval preview. "
                              "Reduce the payload and try again.")
        head = f"MCP tool '{tool_name}' on UNTRUSTED server '{server_name}' wants to run."
        tail = "This untrusted server tool is treated as potentially mutating and may modify external state."
        # The limit notice leads: the messaging gateway's text fallback keeps only the first ~200 characters.
        message = " ".join([head, *(["This call goes past the chat's spend limit."] if over else []), *extra, tail])
        message += f"\n\nArguments:\n{argument_preview}"
        description = (f"Server '{server_name}' is configured 'trust: untrusted'. "
                       f"Approve to run '{tool_name}' once, or deny to block it.")
        title = f"MCP server '{server_name}' is asking"
    else:
        message = " ".join([f"MCP tool '{tool_name}' on server '{server_name}' would take this chat past its "
                            f"spend limit.", *extra])
        description = (f"Server '{server_name}' declares a spend limit per chat. Approve to run '{tool_name}' "
                       f"once (every further paid call in this chat asks again), or deny to block it.")
        title = f"MCP server '{server_name}' spend limit"
    try:  # lazy: tools.approval routes the prompt to whichever surface owns the session
        from tools.approval_prompt import request_elicitation_consent
        answer = request_elicitation_consent(message, description, surface=f"mcp-trust/{server_name}", title=title)
    except Exception as exc:
        logger.error("MCP trust gate: approval check failed for %s.%s: %s", server_name, tool_name, exc, exc_info=True)
        if over and charge is not None:
            return tool_error(charge.refusal(spent))
        return tool_error(f"MCP tool '{tool_name}' on untrusted server '{server_name}' was blocked: the approval "
                          f"system was unavailable (fail-closed).")
    if answer == "accept":
        if charge is not None:
            charge.book()
            if booked is not None:
                booked.append(charge)
        return None
    logger.info("MCP trust gate: user %s '%s' on %s server '%s'", "cancelled" if answer == "cancel" else "denied",
                tool_name, "untrusted" if gated else "spend-limited", server_name)
    if over and charge is not None:
        return tool_error(charge.refusal(spent))
    return tool_error(f"The user did not approve running write-capable MCP tool '{tool_name}' on untrusted server "
                      f"'{server_name}'. The command was NOT run. Do not retry without explicit user direction.")


def _check_circuit_breaker(server_name: str) -> Optional[str]:
    """Open-breaker error, or None when calls may proceed. After the cooldown the breaker is
    half-open: the next call probes; success resets, failure re-bumps and re-arms the cooldown."""
    from tools.mcp_tool_scope import _resolve_server_key
    key = _resolve_server_key(server_name)
    failures = _core._server_error_counts.get(key, 0)
    age = time.monotonic() - _core._server_breaker_opened_at.get(key, 0.0)
    if failures < _core._CIRCUIT_BREAKER_THRESHOLD or age >= _core._CIRCUIT_BREAKER_COOLDOWN_SEC:
        return None
    retry_in = max(1, int(_core._CIRCUIT_BREAKER_COOLDOWN_SEC - age))
    if _core._server_errors_all_application.get(key):
        # The server answered every time; the calls were rejected. Calling it "unreachable" sent the
        # model to the user instead of to its own arguments (#11113).
        return tool_error(f"MCP server '{server_name}' rejected the last {failures} calls (it is reachable; see the "
                          f"error text those calls returned). Paused for ~{retry_in}s. Do NOT repeat the same call — "
                          f"fix the arguments/URL/target or use a different approach.")
    return tool_error(f"MCP server '{server_name}' is unreachable after {failures} consecutive failures. "
                      f"Auto-retry available in ~{retry_in}s. Do NOT retry "
                      f"this tool yet — use alternative approaches or ask the user to check the MCP server.")


def _acquire_call_server(server_name: str, tool_timeout: float):
    """``(server, None)`` when a call may be dispatched, else ``(None, error)``. No session: a
    reconnect may be completing, so wait briefly before a breaker strike; still down -> ask the
    server task to rebuild (probing a dead transport would re-arm the breaker forever)."""
    from tools import mcp_tool_discovery as _discovery  # lazy: discovery -> registration -> handlers cycle
    not_connected = tool_error(f"MCP server '{server_name}' is not connected")
    from tools.mcp_liveness import unavailable_details
    details = unavailable_details(server_name)
    if details is not None:
        decl, current, sentence = details
        not_connected = tool_error(
            sentence,
            server=server_name,
            state=current.state,
            app={
                "name": decl.name,
                "version": current.availability.version,
                "path": current.availability.path,
            },
            user_action=current.user_action,
            retry=current.retry,
        )
    server = _discovery._get_connected_server_for_call(server_name)
    wait = min(5.0, float(tool_timeout or 5.0))
    if server and (server.session or _loop._wait_for_server_session_ready(server, timeout=wait)):
        return server, None
    _core._bump_server_error(server_name)
    if server and _loop._signal_reconnect(server):
        return None, tool_error(f"MCP server '{server_name}' transport is down; reconnect requested. Do NOT retry this "
                                f"tool immediately — give it a few seconds to come back.")
    return None, not_connected


def _result_is_error(result) -> bool:
    """True only for a JSON payload carrying an ``error`` key (non-JSON = success)."""
    try:
        return "error" in json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return False


def _record_call_outcome(server_name: str, result) -> Any:
    """Breaker bookkeeping: an error payload from the tool itself still counts as a strike (#10447),
    flagged as an application error so the open-breaker message stays truthful."""
    if _result_is_error(result):
        _core._bump_server_error(server_name, application=True)
    else:
        _core._reset_server_error(server_name)
    return result


def _strike(server_name: str, message: str, **extra) -> str:
    """Breaker strike + the ``tool_error`` payload for *message*."""
    _core._bump_server_error(server_name)
    return tool_error(message, **extra)


def _mcp_loop_running() -> bool:
    return _core._mcp_loop is not None and _core._mcp_loop.is_running()


def _lookup_reconnectable_server(server_name: str, require_loop: bool = False):
    """The registered server object when it can be signalled to reconnect, else None.
    With *require_loop*, also None unless the MCP loop is running (nothing to wait on)."""
    from tools.mcp_tool_scope import _resolve_server_key
    with _core._lock:
        srv = _core._servers.get(_resolve_server_key(server_name))
    ok = srv is not None and hasattr(srv, "_reconnect_event") and (_mcp_loop_running() or not require_loop)
    return srv if ok else None


def _retry_once(server_name: str, retry_call, op_description: str, what: str):
    """Re-run ``retry_call`` after a recovery step. Returns the result when the RPC completed
    (an application error is still the tool's real answer, and still a breaker strike per #10447);
    None when the retry raised (caller falls through)."""
    try:
        result = retry_call()
    except Exception as retry_exc:
        logger.warning("MCP %s/%s retry after %s failed: %s", server_name, op_description, what, retry_exc)
        return None
    return _record_call_outcome(server_name, result)


def _handle_auth_error_and_retry(server_name: str, exc: BaseException, retry_call, op_description: str):
    """OAuth recovery + one retry; None when *exc* is not an auth error. ``handle_401`` decides
    viability; if viable, signal a reconnect (fresh credentials), wait ready, retry once. Any
    failure returns the structured ``needs_reauth`` error so the model stops refreshing."""
    if not _is_auth_error(exc):
        return None
    from tools.mcp_oauth_manager import get_manager
    try:
        recovered = _loop._run_on_mcp_loop(lambda: get_manager().handle_401(server_name, None), timeout=10)
    except Exception as rec_exc:
        logger.warning("MCP OAuth '%s': recovery attempt failed: %s", server_name, rec_exc)
        recovered = False
    if recovered:
        srv = _lookup_reconnectable_server(server_name)
        # Recovery + reconnect is independent evidence of viability: close the breaker here, not only on
        # retry success (else a failing retry pins it open forever).
        if srv is not None and _loop._signal_reconnect_and_wait(
                server_name, srv, op_description=f"{op_description} after OAuth recovery", timeout=15):
            _core._reset_server_error(server_name)
        result = _retry_once(server_name, retry_call, op_description, "auth recovery")
        if result is not None:
            return result
    return _strike(server_name, _NEEDS_REAUTH_MSG.format(s=server_name, detail=_auth_error_detail(exc)),
                   needs_reauth=True, server=server_name)


def _handle_session_expired_and_retry(server_name: str, exc: BaseException, retry_call, op_description: str,
                                      *, call_may_have_side_effects: bool = False):
    """Transport reconnect + one retry on session expiry; None to fall through. Skips
    ``handle_401``: the token is valid, only the server-side session is stale.

    Unlike :func:`_handle_auth_error_and_retry`, this does **not** call the OAuth manager's ``handle_401`` —
    the access token is still valid, only the server-side session state is stale. Setting
    ``_reconnect_event`` causes the server task's lifecycle loop to tear down the current
    ``streamablehttp_client`` + ``ClientSession`` and rebuild them, reusing the existing OAuth provider
    instance. See #13383.

    At-most-once for writes: a session-expired shape can be synthesized by a proxy AFTER the upstream
    executed the request, and the transport errors this classifier also matches (``ClosedResourceError``,
    broken pipe) routinely fire mid-response. With ``call_may_have_side_effects`` the transport is still
    healed but the call is never re-run; the model gets an ``outcome_uncertain`` error instead (same
    contract as the mid-call stdio death path). Callers pass True unless the tool is positively read-only.
    """
    if not _is_session_expired_error(exc):
        return None
    srv = _lookup_reconnectable_server(server_name, require_loop=True)
    if call_may_have_side_effects:
        # Even without a signallable server the outcome is still uncertain: a generic "call failed"
        # would invite the model to re-invoke a write that may already have landed.
        reconnected = srv is not None and _loop._signal_reconnect_and_wait(
            server_name, srv, op_description=f"{op_description} (write, no auto-retry)", timeout=15)
        if reconnected:  # session state failed, not server health: no breaker strike
            _core._reset_server_error(server_name)
        else:
            _core._bump_server_error(server_name)
        logger.warning("MCP server '%s': %s failed with a session-expired/transport error after the request may "
                       "have been dispatched; NOT auto-retrying a write-capable tool (reconnect %s).",
                       server_name, op_description, "succeeded" if reconnected else "failed")
        return tool_error(_SESSION_OUTCOME_UNCERTAIN_MSG.format(
            s=server_name, state="been re-established" if reconnected else "not recovered yet"),
            outcome_uncertain=True, server=server_name)
    if srv is None:
        return None
    logger.info("MCP server '%s': %s failed with session-expired error (%s); signalling transport reconnect "
                "and retrying once.", server_name, op_description, exc)
    if not _loop._signal_reconnect_and_wait(server_name, srv, op_description=op_description, timeout=15):
        logger.warning("MCP server '%s': reconnect did not ready within 15s after session-expired error; "
                       "falling through to error response.", server_name)
        return None
    return _retry_once(server_name, retry_call, op_description, "session reconnect")


class _StdioChildExited(RuntimeError):
    """Stdio subprocess gone when (or while) a call ran. Deliberately NOT a TimeoutError."""

    def __init__(self, message: str, *, in_flight: bool):
        super().__init__(message)
        self.in_flight = in_flight


def _handle_stdio_child_exited_and_retry(server_name: str, exc: Exception, retry_call, op_description: str):
    """Respawn a dead stdio child; retry once only when it was dead before dispatch.

    A mid-call exit is ambiguous: the server may have applied a side effect before its
    response pipe disappeared. Reconnect for future calls but never replay that operation.
    None means this is not our error. This function never spawns itself: it sets
    ``_reconnect_event`` and waits, so spawn frequency stays governed by ``run()``'s rapid-drop
    budget. A pre-dispatch retry whose child dies again reports and stops.

    Why retrying here cannot hot-cycle respawns: this function never spawns anything. It sets
    ``_reconnect_event`` (one signal, same as before) and waits for the server task to publish a fresh
    session. Spawn frequency stays governed entirely by ``run()``'s rapid-drop budget, which parks a
    transport that keeps dropping without proving healthy (#62212).
    """
    if not isinstance(exc, _StdioChildExited):
        return None
    reconnected = False
    srv = _lookup_reconnectable_server(server_name)
    if srv is not None:
        action = "reconnecting without replay" if exc.in_flight else "respawning and retrying once"
        logger.info("MCP server '%s': %s found the stdio subprocess dead (%s); %s.",
                    server_name, op_description, exc, action)
        if _mcp_loop_running():
            reconnected = _loop._signal_reconnect_and_wait(
                server_name, srv, op_description=op_description, timeout=_core._STDIO_RESPAWN_WAIT_SEC)
        else:  # No MCP loop to wait on (non-async adapters, tests): still request the respawn.
            _loop._signal_reconnect(srv)
    if exc.in_flight:
        return _strike(
            server_name,
            _STDIO_OUTCOME_UNCERTAIN_MSG.format(s=server_name),
            outcome_uncertain=True,
        )
    if not reconnected:
        return _strike(server_name, _STDIO_NO_RESPAWN_MSG.format(s=server_name, t=_core._STDIO_RESPAWN_WAIT_SEC))
    try:
        return _record_call_outcome(server_name, retry_call())
    except _StdioChildExited as retry_exc:
        # Died again right after respawn: broken server; run()'s budget takes it to the park.
        logger.warning("MCP server '%s': %s stdio subprocess exited again right after respawn (%s); not retrying "
                       "further.", server_name, op_description, retry_exc)
        if retry_exc.in_flight:
            return _strike(
                server_name,
                _STDIO_OUTCOME_UNCERTAIN_MSG.format(s=server_name),
                outcome_uncertain=True,
            )
        return _strike(server_name, _STDIO_DIED_AGAIN_MSG.format(s=server_name))
    except Exception as retry_exc:
        logger.warning("MCP %s/%s retry after stdio respawn failed: %s", server_name, op_description, retry_exc)
        return _strike(server_name, _sanitize_error(
            f"MCP call failed after respawning the stdio subprocess for '{server_name}': "
            f"{type(retry_exc).__name__}: {_exc_str(retry_exc)}"))


def _dispatch(server_name: str, server: Any, op: str, call, tool_timeout: float, recoverers,
              on_final_failure: Callable[[BaseException], None], record_outcome: bool = False) -> str:
    """Mark the call started on *server* (doubles may lack ``mark_tool_call``), run coroutine function *call*
    on the MCP loop and, on failure, walk ``recoverers`` (``(server_name, exc, retry_call, op) -> Optional[str]``,
    None = not its kind; order matters). Unrecovered exceptions go through ``on_final_failure`` and become the
    generic call-failed error. ``record_outcome`` applies breaker bookkeeping to the FIRST attempt only."""
    if callable(getattr(server, "mark_tool_call", None)):
        server.mark_tool_call()

    def call_once():
        return _loop._run_on_mcp_loop(call, timeout=tool_timeout)

    try:
        result = call_once()
        return _record_call_outcome(server_name, result) if record_outcome else result
    except InterruptedError:
        return tool_error("MCP call interrupted: user sent a new message")
    except Exception as exc:
        for recover in recoverers:
            recovered = recover(server_name, exc, call_once, op)
            if recovered is not None:
                return recovered
        on_final_failure(exc)
        return tool_error(_mcp_call_failed_message(exc))


@asynccontextmanager
async def _track_inflight_rpc(server: Any, server_name: str, op: str, *, retry_safe: bool = True):
    """Register the running RPC so teardown can fail it fast. A deliberate teardown
    (``_reconnecting`` set first) turns the cancel into a retryable RuntimeError; external
    cancels propagate unchanged. Doubles without ``_inflight_tasks`` skip tracking.

    Every user-visible request family wraps its RPC in this context (#48069 salvage). If a deliberate
    reconnect/shutdown teardown cancels the task (``_fail_inflight_calls`` sets ``_reconnecting`` first),
    the cancel is converted into a clean retryable RuntimeError instead of a raw CancelledError; external
    cancels (caller timeout, user interrupt) propagate unchanged. ``retry_safe=False`` (a write-capable
    ``tools/call``) words the error as outcome-uncertain instead of inviting a replay.
    """
    inflight, task = getattr(server, "_inflight_tasks", None), asyncio.current_task()
    tracked = task is not None and inflight is not None
    if tracked:
        inflight.add(task)
    try:
        yield
    except asyncio.CancelledError:
        if getattr(server, "_reconnecting", False):
            advice = ("retry the request on the rebuilt session" if retry_safe else
                      "the request may already have been dispatched, so verify its effect before re-invoking")
            raise RuntimeError(f"MCP {op} on '{server_name}' was aborted by a reconnect teardown; {advice}") from None
        raise
    finally:
        if tracked:
            inflight.discard(task)


async def _call_tool_racing_stdio_death(server, server_name: str, tool_name: str, args: dict, progress_callback=None):
    """``session.call_tool`` that fails fast when the stdio child is/gets dead: pre-call (a dead
    child must not hold the slot for the full timeout) and mid-call (race against
    ``_watch_stdio_children``). Both raise :class:`_StdioChildExited` for the respawn path, which
    owns the reconnect signal; only pre-call failure is safe to replay. callable()/``is True``
    because MagicMock attributes are truthy."""
    # Fast-fail (#81995): a stdio subprocess that is already dead must not own this call slot — fail
    # immediately instead of waiting out the full tool timeout on a transport nobody will ever answer.
    _stdio_dead = getattr(server, "_stdio_children_dead", None)
    if callable(_stdio_dead) and _stdio_dead() is True:
        raise _StdioChildExited(
            f"MCP stdio subprocess for '{server_name}' had already exited when the call was dispatched",
            in_flight=False,
        )
    # A progress callback makes the SDK send ``_meta.progressToken``, the spec's opt-in for
    # ``notifications/progress``; without one the server must stay silent.
    extra = {"progress_callback": progress_callback} if progress_callback is not None else {}
    _call_coro = server.session.call_tool(tool_name, arguments=args, **extra)
    _watch_children = getattr(server, "_watch_stdio_children", None)
    if not (inspect.iscoroutinefunction(_watch_children) and asyncio.iscoroutine(_call_coro)):
        # Stubbed sessions return a non-awaitable, or there is no child-watcher to race: plain await.
        return await _call_coro if asyncio.iscoroutine(_call_coro) else _call_coro
    # Fast-fail machinery (#81995): the RPC races a stdio-children watcher so a dead subprocess fails the
    # call immediately instead of riding out the full tool timeout.
    rpc_task = asyncio.ensure_future(_call_coro)
    watch_task = asyncio.ensure_future(_watch_children())
    try:
        done, _pending = await asyncio.wait({rpc_task, watch_task}, return_when=asyncio.FIRST_COMPLETED)
        if watch_task in done and not rpc_task.done():
            rpc_task.cancel()
            raise _StdioChildExited(
                f"MCP stdio subprocess for '{server_name}' exited mid-call",
                in_flight=True,
            )
        try:
            return await rpc_task
        except Exception as exc:
            # The SDK usually sees the closed pipe before the 250 ms watcher poll does. On a stdio
            # server a transport-closure error after dispatch is the same ambiguous mid-call death;
            # it must not fall through to the session-expired recoverer, which replays the call.
            _is_http = getattr(server, "_is_http", None)
            if callable(_is_http) and _is_http() is False and _is_session_expired_error(exc):
                raise _StdioChildExited(
                    f"MCP stdio subprocess for '{server_name}' closed its transport mid-call",
                    in_flight=True,
                ) from exc
            raise
    finally:
        watch_task.cancel()
        if not rpc_task.done():
            rpc_task.cancel()
        await asyncio.gather(rpc_task, watch_task, return_exceptions=True)


# ---------------------------------------------------------- result rendering

def _error_result_text(result) -> str:
    """Concatenated text of an ``isError`` result's blocks (EmbeddedResource error payloads
    carry text under ``.resource.text``)."""
    texts = (getattr(b, "text", None) or getattr(getattr(b, "resource", None), "text", None) for b in (result.content or []))
    return "".join(str(t) for t in texts if t)


def _render_content_blocks(result, server_name: str) -> tuple[str, int, list[str]]:
    """Text passes through; image/audio blocks are cached (MEDIA: tags); resource blocks are
    materialized rather than silently dropped; unsupported blocks become an inline drop notice
    (kimi-code#3227). Returns ``(text, usable_parts, image_paths)``: ``usable_parts`` counts REAL
    rendered blocks (whitespace-only text and drop notices excluded) for the structuredContent
    arbitration; ``image_paths`` are the files THIS call's image blocks were cached to — never
    parsed back out of the text, where a server-written ``MEDIA:`` line could name any local file."""
    parts: list[str] = []
    usable_parts = 0
    image_paths: list[str] = []
    # MCP tool results can also include ImageContent blocks (screenshot / Blockbench / Playwright etc.);
    # cache those via the gateway's image-cache helper so they flow through Hermes' MEDIA: tag convention
    # and out to messaging adapters that render images natively. Without this, image blocks were silently
    # dropped and the agent got an empty response. Distilled from #17915 (c3115644151) and #10848
    # (gnanirahulnutakki), both too stale to cherry-pick. #10848's approach (integrate with Hermes' MEDIA
    # tag + cache_image_from_bytes) was the cleaner of the two — plugs into existing infrastructure.
    for block in (result.content or []):
        if getattr(block, "text", None):
            parts.append(strip_unicode_tags(block.text))
            if block.text.strip():
                usable_parts += 1
            continue
        image = _cache_mcp_image_block(block)
        if image.startswith("MEDIA:"):
            image_paths.append(image[len("MEDIA:"):])
        rendered = image or _cache_mcp_audio_block(block) or _render_mcp_resource_block(block, server_name)
        if rendered:
            parts.append(rendered)
            usable_parts += 1
            continue
        block_type = getattr(block, "type", None) or type(block).__name__
        if block_type in {"text", "resource", "audio", "image"}:  # benign empty render
            logger.debug("MCP %s: content block type %r rendered empty", server_name, block_type)
        else:
            logger.warning("MCP %s: dropping unsupported content block type %r", server_name, block_type)
            # Surface the drop to the MODEL, not just the log: a silent drop leaves the agent
            # believing the tool returned less than it did, with no way to recover.
            parts.append(_render_mcp_dropped_block_notice(block, block_type))
    # Hard-cap pathological payloads; ordinary large results pass to spillover.
    return _truncate_mcp_text_result("\n".join(parts)), usable_parts, image_paths


def _capped_structured_content(result):
    """``structuredContent`` (or None); over the hard cap it degrades to the head+tail
    truncated JSON string (multi-MB JSON flood guard)."""
    # Hard-cap pathological payloads before they propagate (#56059); ordinary large results pass untouched
    # to the spillover layer. Arbitration against ``content`` lives in _render_call_tool_result.
    # Server-level `_meta` is also surfaced (ported from
    # MoonshotAI/kimi-code#2596): servers return namespaced metadata there (validated contracts,
    # browser-handoff payloads, ...) that was previously invisible to the agent. Protocol-reserved keys are
    # dropped first (kimi-code#2600) — per the MCP spec's key-name rules a prefix is reserved when a
    # `modelcontextprotocol` or `mcp` label is followed by at least one more label (e.g.
    # `modelcontextprotocol.io/...`, `tools.mcp.com/...`); those carry host/protocol plumbing, not
    # model-facing data. Unprefixed and vendor-namespaced keys (`com.example.mcp/...`) pass through — their
    # semantics belong to the server.
    structured = mcp_field(result, "structured_content", "structuredContent")
    try:
        as_json = json.dumps(structured, ensure_ascii=False, default=str) if structured is not None else ""
    except (TypeError, ValueError):
        return structured
    return _truncate_mcp_text_result(as_json) if len(as_json) > _MCP_HARD_RESULT_CAP_CHARS else structured


def _content_dual_emits_structured(result, structured) -> bool:
    """True when some text block is ``structuredContent`` serialized as JSON — the spec's
    backwards-compat dual-emit ("a tool that returns structured content SHOULD also return the
    serialized JSON in a TextContent block"). Compared as parsed JSON so whitespace, indent, key
    order and ``ensure_ascii`` escaping do not matter; checked per block because the spec puts the
    copy in *a* block and a server may add a status line next to it. Deterministic equality, not a
    richness heuristic: a prose summary or a reorganised rendering fails it and keeps its
    ``structuredContent`` (#115430)."""
    for block in (result.content or []):
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            if json.loads(text) == structured:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _render_call_tool_result(result, server_name: str, image_paths: Optional[list[str]] = None) -> str:
    """Pure: ``CallToolResult`` -> handler JSON (``image_paths``, when given, receives the files this
    call's image blocks were cached to). ``content`` and ``structuredContent`` are both
    forwarded, except that a ``structuredContent`` whose JSON also sits verbatim in a text block
    (the spec's backwards-compat dual-emit; compared as parsed JSON) is dropped, because that copy
    would reach the model twice (kimi-code#3234). Any other usable text — a status line, a prose
    summary, a reorganised rendering — keeps ``structuredContent`` alongside it (#115430): the
    earlier "content wins whenever it rendered anything" rule irreversibly lost servers whose
    data lived only in ``structuredContent``, while the residual duplicate for a faithful
    reorganisation costs only tokens, so data-preservation wins. No richness or size heuristic is
    used. ``structuredContent`` fills ``result`` when the blocks rendered effectively empty
    (structuredContent-only servers); ``_meta`` minus reserved keys is always surfaced."""
    if mcp_field(result, "is_error", "isError", False):
        return tool_error(_sanitize_error(_truncate_mcp_text_result(_error_result_text(result) or "MCP tool returned an error")))
    text_result, usable_parts, cached_images = _render_content_blocks(result, server_name)
    if image_paths is not None:
        image_paths.extend(cached_images)
    structured = _capped_structured_content(result)
    meta = _strip_reserved_meta_keys(mcp_field(result, "meta", "meta"))
    # A str here is the over-cap truncation stand-in (wire structuredContent is always an object): next to
    # usable text it would be a second multi-MB copy — the flood #56059 caps — so it only fills an empty result.
    if structured is not None and usable_parts > 0 and (isinstance(structured, str) or _content_dual_emits_structured(result, structured)):
        structured = None
    if structured is None and meta is None:
        return json.dumps({"result": text_result}, ensure_ascii=False)
    # Key order is part of the output: "result" leads when there is text, otherwise "_meta" precedes it.
    payload: dict[str, Any] = {"result": text_result} if text_result else {}
    # Cap structuredContent too — a malicious server could flood context via a multi-MB JSON payload
    # (#56059). When the serialized form exceeds the hard cap, replace it with the truncated string (head +
    # tail preserved) so it degrades gracefully instead of flooding downstream.
    if structured is not None:
        payload["structuredContent" if text_result else "result"] = structured
    if meta is not None:
        payload["_meta"] = meta
    payload.setdefault("result", text_result)
    try:
        return json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError):  # Non-serializable metadata: drop the extras, keep the call.
        return json.dumps({"result": text_result}, ensure_ascii=False)


def _make_tool_handler(server_name: str, tool_name: str, tool_timeout: float, *, native_images: bool = False):
    """Sync handler (``handler(args_dict, **kwargs)``) calling an MCP tool via the background loop. Always a JSON
    string, except with ``native_images`` (the registry handler the agent loop dispatches): a result carrying
    images then becomes the ``_multimodal`` envelope when the active route takes images in tool results.
    Direct callers (plugins' ``ctx.call_mcp``) keep the string contract and the ``MEDIA:`` paths."""
    op = f"tools/call {tool_name}"

    def _handler(args: dict, **kwargs) -> Any:
        # Security boundary: untrusted-server write tools need approval before ANY transport work (incl. lazy spawn).
        booked: list = []  # a costed call's charge; refunded when the call never reaches the server
        error = _trust_gate_check(server_name, tool_name, booked, args)
        if error is not None:
            return error
        server, error = None, _check_circuit_breaker(server_name)
        if error is None:
            server, error = _acquire_call_server(server_name, tool_timeout)
        if server is None:
            for charge in booked:
                charge.refund()
            return error
        # Only a readOnlyHint=True tool on a full-trust server is replayed after session expiry;
        # a 401 is always pre-dispatch so the auth recoverer keeps its retry for every tool.
        read_only = _tool_is_read_only(server_name, tool_name)
        image_paths: list[str] = []  # the LAST attempt's cached images (a recoverer may retry _call)
        # Read on the agent's thread: the coroutine below runs on the MCP loop, outside this context.
        from agent.tool_progress_relay import current_tool_progress
        report = current_tool_progress()

        async def _on_progress(progress, total, message):
            if report is not None:
                report(progress, total, message)

        async def _call():
            async with server._rpc_lock, _track_inflight_rpc(server, server_name, op, retry_safe=read_only):
                server._pending_call_context = contextvars.copy_context()  # for the elicitation callback
                try:
                    result = await _call_tool_racing_stdio_death(
                        server, server_name, tool_name, args, _on_progress if report is not None else None)
                finally:
                    server._pending_call_context = None
            if getattr(server, "_mark_session_proven", None) is not None:  # round-trip done: transport healthy
                server._mark_session_proven()
            image_paths.clear()
            return _render_call_tool_result(result, server_name, image_paths)

        def _on_failure(exc):
            _core._bump_server_error(server_name)
            logger.error("MCP tool %s/%s call failed: %s", server_name, tool_name, exc)
        session_expired = partial(_handle_session_expired_and_retry, call_may_have_side_effects=not read_only)
        text = _dispatch(
            server_name, server, op, _call, tool_timeout,
            (_handle_stdio_child_exited_and_retry, _handle_auth_error_and_retry, session_expired),
            _on_failure, record_outcome=True)
        # Off the MCP loop on purpose: image prep is CPU work (bounded vision pool) that must not stall other servers' I/O.
        return _mcp_result_with_native_images(text, image_paths) if native_images and not _result_is_error(text) else text
    return _handler


def _make_utility_handler(op: str, log_label: str, rpc, render, required: Optional[str] = None):
    """``(server_name, tool_timeout) -> sync handler`` for one utility tool: ``rpc(session, args,
    server_name)`` awaited under ``_rpc_lock``, ``render(result, server_name)`` -> JSON-able
    payload, ``required`` validated before any transport work."""
    def _factory(server_name: str, tool_timeout: float):
        def _handler(args: dict, **kwargs) -> str:
            from tools import mcp_tool_discovery as _discovery  # lazy: import cycle
            server = _discovery._get_connected_server_for_call(server_name)
            if not server or not server.session:
                return tool_error(f"MCP server '{server_name}' is not connected")
            if required and not args.get(required):
                return tool_error(f"Missing required parameter '{required}'")

            async def _call():
                async with server._rpc_lock:
                    result = await rpc(server.session, args, server_name)
                return json.dumps(render(result, server_name), ensure_ascii=False)
            return _dispatch(
                server_name, server, op, _call, tool_timeout,
                (_handle_auth_error_and_retry, _handle_session_expired_and_retry),
                lambda exc: logger.error("MCP %s/%s failed: %s", server_name, log_label, exc))
        return _handler
    return _factory


def _pick(obj, *specs) -> dict:
    """``{out_key: value}`` for each ``(out_key, attr[, truthy])`` present on *obj* (presence check so SDK models
    and stubs behave alike; ``truthy`` also skips falsy). Key order = spec order."""
    entry = {}
    for out_key, attr, *truthy in specs:
        value = getattr(obj, attr, _MISSING)
        if value is not _MISSING and (value or not (truthy and truthy[0])):
            entry[out_key] = value
    return entry


def _render_resource_list(all_resources, server_name: str) -> dict:
    resources = []
    for r in all_resources:
        entry = _pick(r, ("uri", "uri"), ("name", "name"), ("description", "description", True))
        if "uri" in entry:
            entry["uri"] = str(entry["uri"])
        mime = mcp_field(r, "mime_type", "mimeType")
        if mime:
            entry["mimeType"] = mime  # camelCase: this is the tool's own JSON output shape
        resources.append(entry)
    return {"resources": resources}


def _render_read_resource(result, server_name: str) -> dict:
    parts: list[str] = []
    for block in getattr(result, "contents", []):
        if getattr(block, "text", None) is not None:
            parts.append(strip_unicode_tags(block.text))
        elif getattr(block, "blob", None) is not None:  # binary -> document cache, like EmbeddedResource blocks
            rendered = _render_mcp_resource_block(SimpleNamespace(type="resource", resource=block), server_name)
            parts.append(rendered or f"[binary data, {len(block.blob)} bytes]")
    return {"result": "\n".join(parts)}


def _render_prompt_list(all_prompts, server_name: str) -> dict:
    prompts = []
    for p in all_prompts:
        entry = _pick(p, ("name", "name"), ("description", "description", True))
        if getattr(p, "arguments", None):
            entry["arguments"] = [{"name": a.name, **_pick(a, ("description", "description", True), ("required", "required"))}
                                  for a in p.arguments]
        prompts.append(entry)
    return {"prompts": prompts}


def _render_get_prompt(result, server_name: str) -> dict:
    messages = []
    for msg in getattr(result, "messages", []):
        entry = _pick(msg, ("role", "role"))
        if hasattr(msg, "content"):
            entry["content"] = strip_unicode_tags(msg.content.text if hasattr(msg.content, "text") else str(msg.content))
        messages.append(entry)
    return {"messages": messages, **_pick(result, ("description", "description", True))}


_make_list_resources_handler = _make_utility_handler(
    "resources/list", "list_resources",
    lambda session, args, sn: _core._paginate_full_list(session.list_resources, "resources", sn), _render_resource_list)
_make_read_resource_handler = _make_utility_handler(
    "resources/read", "read_resource",
    lambda session, args, sn: session.read_resource(args["uri"]), _render_read_resource, required="uri")
_make_list_prompts_handler = _make_utility_handler(
    "prompts/list", "list_prompts",
    lambda session, args, sn: _core._paginate_full_list(session.list_prompts, "prompts", sn), _render_prompt_list)
_make_get_prompt_handler = _make_utility_handler(
    "prompts/get", "get_prompt",
    lambda session, args, sn: session.get_prompt(args["name"], arguments=args.get("arguments", {})),
    _render_get_prompt, required="name")


def _make_check_fn(server_name: str):
    """Connection-alive check; lazy (schema-cache registered) servers count as available.

    When the server's owner registered an application declaration (`requires.app`), the
    application must also be present on this host, or the tools are not offered even while a
    stale connection lingers. With no declaration registered the check is the connection check
    alone. Returns a plain bool: the registry caches ``bool(fn())``.
    """
    from tools.mcp_tool_scope import _resolve_server_key

    def _connected() -> bool:
        with _core._lock:
            key = _resolve_server_key(server_name)
            server = _core._servers.get(key)
            return ((server is not None and (server.session is not None or server._is_recycled_stdio()))
                    or key in _core._lazy_server_configs)

    def _check() -> bool:
        if not _connected():
            return False
        return _declared_app_offerable(server_name)
    return _check


def _declared_app_offerable(server_name: str) -> bool:
    """True unless the registered declaration is unavailable on this host. Called only for a
    connected server, so a reachable loopback port outranks the interactive-session rule."""
    from hermes_platform import declaration
    from hermes_platform.resolver.availability import availability

    decl = declaration.lookup(server_name)
    if decl is None:
        return True
    return bool(availability(decl).offerable)
