"""LM Studio auxiliary reasoning follows the native provider profile contract."""

import pytest


def test_auxiliary_lmstudio_request_uses_profile_fallback_without_live_probe():
    """Auxiliary calls have no agent capability probe, so retain generic nested reasoning."""
    import agent.auxiliary_client as auxiliary

    kwargs = auxiliary._build_call_kwargs(
        provider="lmstudio",
        model="qwen/qwen3.8-27b",
        messages=[{"role": "user", "content": "hello"}],
        base_url="http://127.0.0.1:1234/v1",
        reasoning_config={"enabled": True, "effort": "low"},
    )

    assert "reasoning_effort" not in kwargs
    assert kwargs["extra_body"]["reasoning"] == {"enabled": True, "effort": "low"}


def test_lmstudio_reasoning_probe_failure_is_distinct_from_empty_capabilities(monkeypatch):
    """A failed catalog request remains retryable; a valid unsupported model is definitive."""
    from hermes_cli import models_local

    monkeypatch.setattr(models_local, "_lmstudio_fetch_raw_models", lambda **_kwargs: None)
    assert models_local.lmstudio_model_reasoning_options(
        "qwen/model", "http://127.0.0.1:1234/v1", api_key=""
    ) is None

    monkeypatch.setattr(models_local, "_lmstudio_fetch_raw_models", lambda **_kwargs: [])
    assert models_local.lmstudio_model_reasoning_options(
        "qwen/model", "http://127.0.0.1:1234/v1", api_key=""
    ) == []


def test_lmstudio_reasoning_probe_preserves_auth_errors(monkeypatch):
    """Bad credentials are surfaced to callers instead of becoming an unknown model."""
    from hermes_cli import auth, models_local

    rejected = auth.AuthError("unauthorized", provider="lmstudio", code="auth_rejected")

    def fail_probe(**_kwargs):
        raise rejected

    monkeypatch.setattr(models_local, "_lmstudio_fetch_raw_models", fail_probe)
    with pytest.raises(auth.AuthError) as caught:
        models_local.lmstudio_model_reasoning_options(
            "qwen/model", "http://127.0.0.1:1234/v1", api_key="bad-key"
        )

    assert caught.value is rejected
