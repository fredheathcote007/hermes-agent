"""Memory review prompts require attributable evidence without changing skill review."""

from agent.background_review import (
    _COMBINED_REVIEW_PROMPT,
    _MEMORY_REVIEW_PROMPT,
    _SKILL_REVIEW_PROMPT,
)


def test_grounding_rule_is_in_memory_prompts_but_not_skill_prompt():
    markers = (
        "Save only facts GROUNDED in this conversation",
        "a user's actual statement or a tool result you can point to",
        "never turn a one-off request into a standing preference",
    )
    for marker in markers:
        assert marker in _MEMORY_REVIEW_PROMPT
        assert marker in _COMBINED_REVIEW_PROMPT
        assert marker not in _SKILL_REVIEW_PROMPT


def test_grounding_rule_allows_direct_general_or_stated_preferences():
    assert "always" in _MEMORY_REVIEW_PROMPT
    assert "from now on" in _MEMORY_REVIEW_PROMPT
    assert "I hate X" in _MEMORY_REVIEW_PROMPT
    assert "stop doing Y" in _MEMORY_REVIEW_PROMPT
