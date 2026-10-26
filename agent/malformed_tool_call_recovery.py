"""Recognize visible, unparsed tool-call syntax without interpreting or executing it."""

from __future__ import annotations

import re
from typing import Any


_FENCED_CODE = re.compile(r"```[\s\S]*?(?:```|\Z)|~~~[\s\S]*?(?:~~~|\Z)")
_INLINE_CODE = re.compile(r"(?<!`)`{1,2}(?!`)[^`\n]*`{1,2}(?!`)")
# A tag mentioned in ordinary prose is not a pending call; require call-shaped
# arguments after it, not merely a function name.
_FUNCTION_TAG = re.compile(
    r"<function\s*=\s*([a-zA-Z_][\w.-]*)\s*>\s*(?=<parameter\s*=|\{)",
    re.IGNORECASE,
)
_TOOL_CALL_TAG = re.compile(r"<tool_call\b[^>]*>([\s\S]*?)(?:</tool_call\s*>|\Z)", re.IGNORECASE)
_ARG_TAG = re.compile(r"<(?:arg_key|arg_value)\s*>", re.IGNORECASE)
_REASONING_TOOL_PARAMETER = re.compile(r"<tool(?:\s[^>]*)?>[\s\S]*?<parameter\s*=\s*name\s*>\s*[A-Za-z_][\w.:-]*", re.IGNORECASE)


def _without_examples(text: Any) -> str:
    if not isinstance(text, str) or not text:
        return ""
    return _INLINE_CODE.sub(" ", _FENCED_CODE.sub(" ", text))


def has_unparsed_tool_syntax(content: Any, reasoning: Any = None) -> bool:
    """True for actual-looking markup outside code, even when its name is unknown.

    This is deliberately a recovery signal only: it never parses arguments into a tool call.
    Reasoning is inspected to prevent malformed markup there from being promoted to an answer.
    """
    for text in (content, reasoning):
        visible = _without_examples(text)
        if not visible:
            continue
        if _FUNCTION_TAG.search(visible):
            return True
        # Older Qwen-like models can strand the function name in a nonstandard
        # <tool><parameter=name>...</parameter> reasoning fragment. The provider
        # never emitted a structured call, so do not promote it as an answer.
        if _REASONING_TOOL_PARAMETER.search(visible):
            return True
        for match in _TOOL_CALL_TAG.finditer(visible):
            body = match.group(1)
            if _ARG_TAG.search(body) or re.search(r'"(?:name|arguments|parameters)"\s*:', body):
                return True
    return False


def discard_dropped_tool_call_scaffolding(messages: list[dict[str, Any]]) -> None:
    """Discard all private retry rows, not just the latest tail pair.

    Do not change the list identity: the current session and return value may
    both reference this same list. These rows are excluded from durable writes.
    """
    messages[:] = [
        row for row in messages
        if not (isinstance(row, dict) and row.get("_dropped_toolcall_nudge"))
    ]


def malformed_tool_call_result(messages: list[dict[str, Any]], api_call_count: int) -> dict[str, Any]:
    """Terminal failure after retries: raw markup is never presented as completed work."""
    from agent.turn_failure_copy import stamp_failure

    response = (
        "The model repeatedly returned malformed tool-call syntax, so the request was not "
        "completed. No tool was run from that text. Please resend the request."
    )
    return stamp_failure({
        "final_response": response,
        "messages": messages,
        "api_calls": api_call_count,
        "error": "Malformed tool-call syntax persisted after bounded recovery retries.",
        "partial": False,
        "failed": True,
        "completed": False,
    }, "invalid_response", True)
