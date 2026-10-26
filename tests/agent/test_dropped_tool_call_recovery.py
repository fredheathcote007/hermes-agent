"""Regression tests for dropped tool-call recovery.

Some providers (observed: claude-opus-4.8 / claude-sonnet-4.5 on GitHub
Copilot, ~2026-07) return ``finish_reason="tool_calls"`` while the parsed
``tool_calls`` array is empty — the model signalled it wanted to act but the
payload shipped no call. Before the fix, the conversation loop took the
no-tool-calls ``else`` branch, treated the turn's narration as the final
answer, and exited with the task unstarted. On an unattended multi-step job
(e.g. a scheduled PR reviewer) this silently did nothing.

The fix keys on the provider contract violation itself
(``finish_reason == "tool_calls"`` with zero ``tool_calls``) and re-prompts,
bounded to 3 consecutive stalls, with the budget resetting after any
successful tool round so it guards each stall rather than the whole run. A
genuine ``finish_reason="stop"`` text turn is unaffected.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def loop_agent():
    """AIAgent with a mocked OpenAI client (mirrors test_run_agent's fixture)
    so we can stage a dropped-tool-call response + continuation pair on
    ``.chat.completions.create``."""
    from run_agent import AIAgent
    with (
        patch("model_tools.get_tool_definitions", return_value=[{
            "type": "function",
            "function": {
                "name": "terminal",
                "description": "Run a terminal command.",
                "parameters": {"type": "object", "properties": {"command": {"type": "string"}}},
            },
        }]),
        patch("model_tools.check_toolset_requirements", return_value={}),
        patch("agent.process_bootstrap.OpenAI"),
    ):
        agent = AIAgent(
            api_key="test-key-1234567890",
            base_url="https://openrouter.ai/api/v1",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )
        agent.client = MagicMock()
        agent._cached_system_prompt = "You are helpful."
        agent._use_prompt_caching = False
        agent.tool_delay = 0
        agent.compression_enabled = False
        agent.save_trajectories = False
        return agent


def _dropped_tool_call_response(content: str):
    """A response whose finish_reason claims a tool call, but tool_calls is
    empty — the provider contract violation this fix recovers from."""
    from tests.agent.test_run_agent import _mock_assistant_msg
    return SimpleNamespace(
        id="chatcmpl-dropped",
        model="test/model",
        choices=[SimpleNamespace(
            index=0,
            message=_mock_assistant_msg(content=content, tool_calls=None),
            finish_reason="tool_calls",
        )],
        usage=None,
    )


class TestDroppedToolCallRecovery:
    @pytest.mark.parametrize("markup", [
        '<function=terminal>{"command":"pwd"}',
        '<tool_call>{"name":"terminal","arguments":{"command":"pwd"}}',
        '<tool_call><arg_key>command</arg_key><arg_value>pwd',
    ])
    def test_visible_malformed_markup_reprompts_but_never_executes(self, loop_agent, markup):
        """Raw Qwen/GLM-style markup is only a recovery signal, never a tool invocation."""
        from tests.agent.test_run_agent import _mock_response

        loop_agent.client.chat.completions.create.side_effect = [
            _mock_response(content=markup, finish_reason="stop"),
            _mock_response(content="Recovered answer.", finish_reason="stop"),
        ]
        loop_agent._execute_tool_calls = MagicMock()
        with (
            patch.object(loop_agent, "_persist_session"),
            patch.object(loop_agent, "_save_trajectory"),
            patch.object(loop_agent, "_cleanup_task_resources"),
        ):
            result = loop_agent.run_conversation("check this")

        assert loop_agent.client.chat.completions.create.call_count == 2
        assert result["final_response"] == "Recovered answer."
        loop_agent._execute_tool_calls.assert_not_called()
        assert not any(m.get("role") == "tool" for m in result["messages"] if isinstance(m, dict))

    def test_unknown_markup_is_not_promoted_or_executed(self, loop_agent):
        """Unknown names get a retry and cannot become a structured tool call."""
        from tests.agent.test_run_agent import _mock_response

        loop_agent.client.chat.completions.create.side_effect = [
            _mock_response(content='<function=not_offered>{"x":1}', finish_reason="stop"),
            _mock_response(content="I could not use that tool.", finish_reason="stop"),
        ]
        loop_agent._execute_tool_calls = MagicMock()
        with (
            patch.object(loop_agent, "_persist_session"),
            patch.object(loop_agent, "_save_trajectory"),
            patch.object(loop_agent, "_cleanup_task_resources"),
        ):
            result = loop_agent.run_conversation("do it")

        assert loop_agent.client.chat.completions.create.call_count == 2
        assert "not_offered" not in result["final_response"]
        loop_agent._execute_tool_calls.assert_not_called()

    @pytest.mark.parametrize("quoted", [
        'The syntax is `<function=terminal>` in docs.',
        '```xml\n<function=terminal>{"command":"pwd"}\n```',
    ])
    def test_quoted_markup_does_not_reprompt(self, loop_agent, quoted):
        from tests.agent.test_run_agent import _mock_response

        loop_agent.client.chat.completions.create.side_effect = [
            _mock_response(content=quoted, finish_reason="stop"),
        ]
        with (
            patch.object(loop_agent, "_persist_session"),
            patch.object(loop_agent, "_save_trajectory"),
            patch.object(loop_agent, "_cleanup_task_resources"),
        ):
            result = loop_agent.run_conversation("explain syntax")

        assert loop_agent.client.chat.completions.create.call_count == 1
        assert "function=terminal" in result["final_response"]

    @pytest.mark.parametrize("reasoning", [
        '<function=terminal>{"command":"pwd"}',
        '<tool>\n<parameter=name>terminal</parameter><parameter=arguments>pwd',
        '<tool_call>{"name":"terminal","arguments":{"command":"pwd"}}',
    ])
    def test_reasoning_only_malformed_markup_is_retried_not_promoted(self, loop_agent, reasoning):
        from tests.agent.test_run_agent import _mock_response

        loop_agent.client.chat.completions.create.side_effect = [
            _mock_response(content="", reasoning=reasoning, finish_reason="stop"),
            _mock_response(content="Recovered answer.", finish_reason="stop"),
        ]
        with (
            patch.object(loop_agent, "_persist_session"),
            patch.object(loop_agent, "_save_trajectory"),
            patch.object(loop_agent, "_cleanup_task_resources"),
            patch("agent.turn_final_response.answer_in_reasoning_capability", return_value=True),
        ):
            result = loop_agent.run_conversation("check this")

        assert loop_agent.client.chat.completions.create.call_count == 2
        assert result["final_response"] == "Recovered answer."

    def test_complete_visible_answer_ignores_private_reasoning_markup(self, loop_agent):
        from tests.agent.test_run_agent import _mock_response
        loop_agent.client.chat.completions.create.side_effect = [
            _mock_response(
                content="The result is ready.",
                reasoning='<function=terminal>{"command":"pwd"}',
                finish_reason="stop",
            ),
        ]
        with (
            patch.object(loop_agent, "_persist_session"),
            patch.object(loop_agent, "_save_trajectory"),
            patch.object(loop_agent, "_cleanup_task_resources"),
        ):
            result = loop_agent.run_conversation("answer my question")
        assert loop_agent.client.chat.completions.create.call_count == 1
        assert result["completed"] is True
        assert result["final_response"] == "The result is ready."

    def test_plain_mention_of_function_tag_is_not_call(self, loop_agent):
        from tests.agent.test_run_agent import _mock_response
        text = "See the <function=terminal> element in the Qwen template docs."
        loop_agent.client.chat.completions.create.side_effect = [
            _mock_response(content=text, finish_reason="stop"),
        ]
        with (
            patch.object(loop_agent, "_persist_session"),
            patch.object(loop_agent, "_save_trajectory"),
            patch.object(loop_agent, "_cleanup_task_resources"),
        ):
            result = loop_agent.run_conversation("explain syntax")
        assert loop_agent.client.chat.completions.create.call_count == 1
        assert result["final_response"] == text

    def test_no_tools_does_not_treat_markup_as_executable_request(self, loop_agent):
        from tests.agent.test_run_agent import _mock_response
        loop_agent.tools = []
        loop_agent.valid_tool_names = set()
        text = 'A syntax example is <function=terminal>{"command":"pwd"}.'
        loop_agent.client.chat.completions.create.side_effect = [
            _mock_response(content=text, finish_reason="stop"),
        ]
        with (
            patch.object(loop_agent, "_persist_session"),
            patch.object(loop_agent, "_save_trajectory"),
            patch.object(loop_agent, "_cleanup_task_resources"),
        ):
            result = loop_agent.run_conversation("quote the format")
        assert loop_agent.client.chat.completions.create.call_count == 1
        assert result["final_response"] == text

    def test_multi_retry_scaffolding_is_removed_on_success(self, loop_agent):
        from tests.agent.test_run_agent import _mock_response
        loop_agent.client.chat.completions.create.side_effect = [
            _mock_response(content='<function=terminal>{"command":"pwd"}', finish_reason="stop"),
            _mock_response(content='<tool_call>{"name":"terminal","arguments":{}}', finish_reason="stop"),
            _mock_response(content="Recovered answer.", finish_reason="stop"),
        ]
        with (
            patch.object(loop_agent, "_persist_session"),
            patch.object(loop_agent, "_save_trajectory"),
            patch.object(loop_agent, "_cleanup_task_resources"),
        ):
            result = loop_agent.run_conversation("do a harmless check")
        assert loop_agent.client.chat.completions.create.call_count == 3
        assert result["completed"] is True
        assert not any(m.get("_dropped_toolcall_nudge") for m in result["messages"] if isinstance(m, dict))

    def test_turn_start_resets_stale_retry_budget(self, loop_agent):
        from agent.turn_context import _reset_per_turn_agent_state
        loop_agent._dropped_toolcall_retries = 2
        _reset_per_turn_agent_state(loop_agent)
        assert loop_agent._dropped_toolcall_retries == 0

    def test_malformed_markup_retry_exhaustion_fails_turn(self, loop_agent):
        from tests.agent.test_run_agent import _mock_response

        loop_agent.client.chat.completions.create.side_effect = [
            _mock_response(content='<function=terminal>{"command":"pwd"}', finish_reason="stop")
            for _ in range(8)
        ]
        loop_agent._execute_tool_calls = MagicMock()
        with (
            patch.object(loop_agent, "_persist_session"),
            patch.object(loop_agent, "_save_trajectory"),
            patch.object(loop_agent, "_cleanup_task_resources"),
        ):
            result = loop_agent.run_conversation("check this")

        assert loop_agent.client.chat.completions.create.call_count == 4
        assert result["failed"] is True
        assert result["completed"] is False
        assert "not completed" in result["final_response"]
        assert "terminal" not in result["final_response"]
        loop_agent._execute_tool_calls.assert_not_called()
        assert not any(m.get("_dropped_toolcall_nudge") for m in result["messages"] if isinstance(m, dict))

    def test_dropped_tool_call_reprompts_instead_of_exiting(self, loop_agent):
        """finish_reason=tool_calls with an empty tool_calls array must
        re-prompt the model to emit the call rather than exiting the loop
        with the narration as the final answer."""
        from tests.agent.test_run_agent import _mock_response

        loop_agent.client.chat.completions.create.side_effect = [
            _dropped_tool_call_response("Let me verify the PR and gather evidence."),
            _mock_response(content="All checks pass. Approved.", finish_reason="stop"),
        ]

        with (
            patch.object(loop_agent, "_persist_session"),
            patch.object(loop_agent, "_save_trajectory"),
            patch.object(loop_agent, "_cleanup_task_resources"),
        ):
            result = loop_agent.run_conversation("review the PR")

        assert loop_agent.client.chat.completions.create.call_count == 2, (
            "A dropped tool call must trigger a re-prompt (second API call), "
            "not exit the loop after one call."
        )

        # The loop must have injected a nudge user-message telling the model to
        # issue the actual tool call.
        second_call = loop_agent.client.chat.completions.create.call_args_list[1]
        msgs = second_call.kwargs.get("messages") or second_call.args[0].get("messages")
        last_user = next(
            (m for m in reversed(msgs) if m.get("role") == "user"), None,
        )
        assert last_user is not None
        assert "tool call" in (last_user.get("content") or "").lower(), (
            "The nudge must explicitly ask the model to issue the tool call."
        )
        assert "All checks pass" in result["final_response"]


    def test_clean_stop_text_turn_is_unaffected(self, loop_agent):
        """A genuine finish_reason=stop text response must exit normally — the
        recovery path must not fire on ordinary final answers."""
        from tests.agent.test_run_agent import _mock_response

        loop_agent.client.chat.completions.create.side_effect = [
            _mock_response(content="Here is your answer.", finish_reason="stop"),
        ]

        with (
            patch.object(loop_agent, "_persist_session"),
            patch.object(loop_agent, "_save_trajectory"),
            patch.object(loop_agent, "_cleanup_task_resources"),
        ):
            result = loop_agent.run_conversation("hello")

        assert loop_agent.client.chat.completions.create.call_count == 1, (
            "A clean finish_reason=stop turn must not trigger a re-prompt."
        )
        assert "Here is your answer." in result["final_response"]

    def test_persistent_dropped_tool_calls_are_bounded(self, loop_agent):
        """If the model never emits a call, the recovery must give up after a
        bounded number of consecutive stalls instead of looping forever."""
        from tests.agent.test_run_agent import _mock_response

        # Stage plenty of dropped-tool-call responses followed by a clean stop,
        # so that if the bound is respected the loop exits on its own well
        # before exhausting the staged responses (no StopIteration).
        loop_agent.client.chat.completions.create.side_effect = [
            _dropped_tool_call_response("Let me check.") for _ in range(9)
        ] + [_mock_response(content="done", finish_reason="stop")]

        with (
            patch.object(loop_agent, "_persist_session"),
            patch.object(loop_agent, "_save_trajectory"),
            patch.object(loop_agent, "_cleanup_task_resources"),
        ):
            result = loop_agent.run_conversation("review the PR")

        # 1 initial call + at most 3 bounded re-prompts = 4 total before the
        # guard stops firing. It must NOT consume all 9 staged stalls.
        assert loop_agent.client.chat.completions.create.call_count <= 4, (
            "Consecutive dropped tool calls must be bounded (no infinite loop)."
        )
        assert result is not None

    def test_nudge_pair_is_ephemeral_scaffolding(self, loop_agent):
        """The re-prompt pair (interim assistant turn + synthetic user nudge)
        must be flagged as ephemeral scaffolding so persistence never writes
        it to the durable transcript — a resumed session must not replay the
        internal "issue the actual tool call now" instruction as user-authored
        context (#69630 review follow-up)."""
        from agent.session_persistence import _is_ephemeral_scaffolding
        from tests.agent.test_run_agent import _mock_response

        loop_agent.client.chat.completions.create.side_effect = [
            _dropped_tool_call_response("Let me verify the PR."),
            _mock_response(content="All checks pass. Approved.", finish_reason="stop"),
        ]

        with (
            patch.object(loop_agent, "_persist_session"),
            patch.object(loop_agent, "_save_trajectory"),
            patch.object(loop_agent, "_cleanup_task_resources"),
        ):
            result = loop_agent.run_conversation("review the PR")

        assert result["completed"] is True
        # The finalization pop strips the answered pair from the live list —
        # no flagged scaffolding may survive into the returned transcript.
        leftover = [
            m for m in result["messages"]
            if isinstance(m, dict) and m.get("_dropped_toolcall_nudge")
        ]
        assert not leftover, (
            "The re-prompt pair must be stripped at finalization, not kept "
            "in the returned transcript."
        )
        # And the persistence filter must classify the flag as ephemeral so a
        # mid-turn flush can never write the pair to the durable store either.
        assert _is_ephemeral_scaffolding(
            {"role": "user", "content": "nudge", "_dropped_toolcall_nudge": True}
        ), (
            "_dropped_toolcall_nudge messages must be classified as "
            "ephemeral scaffolding so they are never persisted."
        )
