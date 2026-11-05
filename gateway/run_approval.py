"""Gateway approval prompt rendering helpers.

The plain-text fallback shares wording and timeout policy with the native approval card, while
adding typed ``/approve`` steps for surfaces without buttons.
"""

from __future__ import annotations

from agent.i18n import t


def _format_exec_approval_fallback(
    command: str, description: str, command_prefix: str, *, allow_permanent: bool = True,
    allow_session: bool = True, smart_denied: bool = False) -> str:
    """Render the text fallback from approval capabilities, not platform names."""
    from gateway.platforms.base_exec_approval import (
        GATEWAY_APPROVAL_COMMAND_MAX_CHARS, approval_timeout_seconds, ea_header_text,
        ea_reason_label_text, format_approval_deadline_line)
    cmd_preview = (command[:GATEWAY_APPROVAL_COMMAND_MAX_CHARS] + "..."
                   if len(command) > GATEWAY_APPROVAL_COMMAND_MAX_CHARS else command)
    heading = (t("gateway.exec_approval.smart_deny_heading") if smart_denied
               else f"⚠️ **{ea_header_text()}**")

    choices = [t("gateway.exec_approval.text_choice_once", prefix=command_prefix)]
    if not smart_denied and allow_session:
        choices.append(t("gateway.exec_approval.text_choice_session", prefix=command_prefix))
        if allow_permanent:
            choices.append(t("gateway.exec_approval.text_choice_always", prefix=command_prefix))
    choices.append(t("gateway.exec_approval.text_choice_deny", prefix=command_prefix))
    return (
        t("gateway.exec_approval.text_body", heading=heading, command=cmd_preview,
          reason_label=ea_reason_label_text(), reason=description)
        + t("gateway.exec_approval.text_choice_joiner").join(choices[:-1])
        + t("gateway.exec_approval.text_choice_last", choice=choices[-1])
        + format_approval_deadline_line(approval_timeout_seconds()))
