"""Route identity survives auxiliary retry reconstruction."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.parametrize("async_mode", [False, True])
def test_vision_retry_reuses_selected_mode_runtime_and_explicit_endpoint(async_mode):
    import agent.auxiliary_client as auxiliary

    runtime = {"provider": "custom", "model": "vision-model", "base_url": "https://vision.test/v1"}
    client = object()
    resolved = {}

    def resolve(**kwargs):
        resolved.update(kwargs)
        return "custom", client, "vision-model"

    with (
        patch.object(auxiliary, "resolve_vision_provider_client", side_effect=resolve),
        patch.object(auxiliary, "_build_call_kwargs", return_value={"model": "vision-model"}) as build,
    ):
        rebuilt, kwargs = auxiliary._prepare_same_provider_retry(
            task="vision", resolved_provider="custom", resolved_model="vision-model",
            resolved_base_url=runtime["base_url"], resolved_base_url_explicit=True,
            resolved_api_key="vision-key", resolved_api_mode="chat_completions",
            main_runtime=runtime, final_model="vision-model", messages=[], temperature=None,
            max_tokens=64, tools=None, effective_timeout=20,
            effective_extra_body={}, reasoning_config=None, async_mode=async_mode,
        )

    assert rebuilt is client
    assert kwargs["model"] == "vision-model"
    assert resolved == {
        "provider": "custom", "model": "vision-model", "base_url": runtime["base_url"],
        "api_key": "vision-key", "api_mode": "chat_completions", "async_mode": async_mode,
        "main_runtime": runtime,
    }
    build.assert_called_once()
    assert build.call_args.kwargs["api_key"] == "vision-key"


def test_fallback_request_kwargs_does_not_reuse_primary_api_key():
    import agent.auxiliary_client as auxiliary

    destination = auxiliary._FallbackDestination(
        "openrouter", "https://openrouter.ai/api/v1", "chat_completions", "fallback-model"
    )
    with patch.object(auxiliary, "_build_call_kwargs", return_value={}) as build:
        auxiliary._fallback_request_kwargs(
            destination, task="vision", messages=[], tools=None, temperature=None,
            max_tokens=64, effective_timeout=20, effective_extra_body={}, reasoning_config=None,
            fallback_entry={}, task_config={}, apply_fast_lane=False,
        )

    assert "api_key" not in build.call_args.kwargs


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("initial_key", [None, "failed-key"])
@pytest.mark.asyncio
async def test_real_recovery_ladder_uses_rotated_client_key_for_lmstudio_probe(async_mode, initial_key, monkeypatch):
    """A pool retry rebuilds without the stale key and probes with the selected client key."""
    from hermes_cli import models_local
    import agent.auxiliary_client as auxiliary

    auxiliary._clear_lmstudio_probe_cache()
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])
    stale, fresh = MagicMock(), MagicMock()
    stale.api_key = initial_key or "pool-key-a"
    fresh.api_key = "pool-key-b"
    stale.base_url = fresh.base_url = "http://lmstudio.test/v1"
    rate_error = Exception("rate limit")
    rate_error.status_code = 429
    if async_mode:
        stale.chat.completions.create = AsyncMock(side_effect=rate_error)
        fresh.chat.completions.create = AsyncMock(return_value=response)
    else:
        stale.chat.completions.create.side_effect = rate_error
        fresh.chat.completions.create.return_value = response

    probe_keys = []
    monkeypatch.setattr(
        models_local, "lmstudio_model_reasoning_options",
        lambda _model, _base_url, *, api_key=None, **_kw: probe_keys.append(api_key) or ["off", "low"],
    )
    get_client = MagicMock(side_effect=[(stale, "qwen/model"), (fresh, "qwen/model")])
    with (
        patch.object(auxiliary, "_resolve_task_provider_model", return_value=(
            "lmstudio", "qwen/model", "http://lmstudio.test/v1", initial_key, None)),
        patch.object(auxiliary, "_get_cached_client", get_client),
        patch.object(auxiliary, "_refresh_provider_credentials", return_value=False),
        patch.object(auxiliary, "_recoverable_pool_provider", return_value="lmstudio"),
        patch.object(auxiliary, "_recover_provider_pool", return_value=True),
        patch.object(auxiliary, "_should_retry_same_provider", return_value=False),
        patch.object(auxiliary, "_build_call_kwargs", wraps=auxiliary._build_call_kwargs) as build,
    ):
        invoke = auxiliary.async_call_llm if async_mode else auxiliary.call_llm
        if async_mode:
            result = await invoke(
                task="compression", provider="lmstudio", model="qwen/model",
                messages=[{"role": "user", "content": "hi"}],
                reasoning_config={"enabled": True, "effort": "low"},
            )
        else:
            result = invoke(
                task="compression", provider="lmstudio", model="qwen/model",
                messages=[{"role": "user", "content": "hi"}],
                reasoning_config={"enabled": True, "effort": "low"},
            )

    assert result is response
    assert get_client.call_count == 2
    assert get_client.call_args_list[1].kwargs["api_key"] is None
    assert [call.kwargs["api_key"] for call in build.call_args_list] == [stale.api_key, "pool-key-b"]
    assert probe_keys == [stale.api_key, "pool-key-b"]


@pytest.mark.parametrize("async_mode", [False, True])
def test_real_recovery_ladder_keeps_explicit_custom_endpoint_credential(async_mode):
    """Custom endpoints have no pool credential source, so a retry retains the call key."""
    import agent.auxiliary_client as auxiliary

    client = MagicMock()
    client.api_key = "custom-key"
    client.base_url = "https://custom.test/v1"
    get_client = MagicMock(return_value=(client, "custom-model"))
    step = auxiliary._LadderStep("retry_same_provider", ("custom", "custom-model", None))
    with patch.object(auxiliary, "_get_cached_client", get_client):
        kind, _, retry = auxiliary._ladder_step_call(
            step,
            SimpleNamespace(),
            {"resolved_api_key": "custom-key", "resolved_model": "custom-model"},
            {},
        )
        rebuilt, _ = auxiliary._prepare_same_provider_retry(
            task="compression", resolved_provider=retry["resolved_provider"],
            resolved_model=retry["resolved_model"], resolved_base_url=None,
            resolved_api_key=retry["resolved_api_key"], resolved_api_mode=None, main_runtime=None,
            final_model="custom-model", messages=[], temperature=None, max_tokens=32, tools=None,
            effective_timeout=10, effective_extra_body={}, reasoning_config=None,
            async_mode=async_mode,
        )

    assert kind == "retry"
    assert retry["resolved_api_key"] == "custom-key"
    assert rebuilt is client
    assert get_client.call_args.kwargs["api_key"] == "custom-key"


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.asyncio
async def test_auto_fallback_probe_uses_lmstudio_key_not_primary_provider_key(async_mode, monkeypatch):
    from hermes_cli import models_local
    import agent.auxiliary_client as auxiliary

    client = MagicMock()
    client.api_key = "lmstudio-key"
    client.base_url = "http://lmstudio.test/v1"
    client._hermes_aux_effective_provider = "lmstudio"
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])
    if async_mode:
        client.chat.completions.create = AsyncMock(return_value=response)
    else:
        client.chat.completions.create.return_value = response
    auxiliary._clear_lmstudio_probe_cache()
    observed = []
    monkeypatch.setattr(
        models_local, "lmstudio_model_reasoning_options",
        lambda _model, _base_url, *, api_key=None, **_kw: observed.append(api_key) or ["off", "low"],
    )
    with (
        patch.object(auxiliary, "_resolve_task_provider_model", return_value=(
            "auto", "qwen/model", None, "primary-provider-key", None)),
        patch.object(auxiliary, "_get_cached_client", return_value=(client, "qwen/model")),
    ):
        invoke = auxiliary.async_call_llm if async_mode else auxiliary.call_llm
        if async_mode:
            result = await invoke(
                task="compression", messages=[{"role": "user", "content": "hi"}],
                reasoning_config={"enabled": True, "effort": "low"},
            )
        else:
            result = invoke(
                task="compression", messages=[{"role": "user", "content": "hi"}],
                reasoning_config={"enabled": True, "effort": "low"},
            )

    assert result is response
    assert observed == ["lmstudio-key"]
