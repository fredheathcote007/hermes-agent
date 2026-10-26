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
@pytest.mark.parametrize("provider", ["custom", "custom:edge"])
def test_real_recovery_ladder_keeps_explicit_custom_endpoint_credential(async_mode, provider):
    """A caller-owned custom key survives a same-route retry for bare and named providers."""
    import agent.auxiliary_client as auxiliary

    client = MagicMock()
    client.api_key = "custom-key"
    client.base_url = "https://custom.test/v1"
    get_client = MagicMock(return_value=(client, "custom-model"))
    step = auxiliary._LadderStep("retry_same_provider", (provider, "custom-model", None))
    with patch.object(auxiliary, "_get_cached_client", get_client):
        kind, _, retry = auxiliary._ladder_step_call(
            step,
            SimpleNamespace(),
            {"resolved_api_key": "custom-key", "resolved_model": "custom-model",
             "caller_api_key_provider": provider, "caller_api_key": "custom-key"},
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


def test_custom_caller_key_is_not_carried_to_another_provider_retry():
    import agent.auxiliary_client as auxiliary

    step = auxiliary._LadderStep("retry_same_provider", ("openrouter", "fallback-model", None))
    kind, _, retry = auxiliary._ladder_step_call(
        step, SimpleNamespace(),
        {"resolved_api_key": "custom-key", "resolved_model": "fallback-model",
         "caller_api_key_provider": "custom:edge", "caller_api_key": "custom-key"},
        {},
    )

    assert kind == "retry"
    assert retry["resolved_api_key"] is None
    assert "caller_api_key" not in retry


@pytest.mark.parametrize("async_mode", [False, True])
def test_named_custom_config_key_survives_same_route_pool_retry(async_mode):
    import agent.auxiliary_client as auxiliary

    provider = "custom:edge"
    resolved_config_key = "test-config-key"
    client = MagicMock()
    get_client = MagicMock(return_value=(client, "edge-model"))
    step = auxiliary._LadderStep("retry_same_provider", (provider, "edge-model", None))
    with (patch.object(auxiliary, "_get_auxiliary_task_config", return_value={
              "provider": provider, "api_key": resolved_config_key}),
          patch("hermes_cli.runtime_provider._get_named_custom_provider", return_value=None),
          patch.object(auxiliary, "_get_cached_client", get_client)):
        kind, _, retry = auxiliary._ladder_step_call(
            step,
            SimpleNamespace(),
            {"task": "compression", "resolved_api_key": resolved_config_key,
             "resolved_model": "edge-model", "caller_api_key_provider": provider,
             "caller_api_key": None},
            {},
        )
        rebuilt, _ = auxiliary._prepare_same_provider_retry(
            task="compression", resolved_provider=retry["resolved_provider"],
            resolved_model=retry["resolved_model"], resolved_base_url=None,
            resolved_api_key=retry["resolved_api_key"], resolved_api_mode=None, main_runtime=None,
            final_model="edge-model", messages=[], temperature=None, max_tokens=32, tools=None,
            effective_timeout=10, effective_extra_body={}, reasoning_config=None,
            async_mode=async_mode,
        )

    assert kind == "retry"
    assert retry["resolved_api_key"] == resolved_config_key
    assert "caller_api_key" not in retry
    assert retry["resolved_provider"] == provider
    assert rebuilt is client
    assert get_client.call_args.kwargs["api_key"] == resolved_config_key


def test_named_custom_config_key_is_not_carried_to_another_provider_retry():
    import agent.auxiliary_client as auxiliary

    step = auxiliary._LadderStep("retry_same_provider", ("openrouter", "fallback-model", None))
    with (patch.object(auxiliary, "_get_auxiliary_task_config", return_value={
              "provider": "custom:edge", "api_key": "test-config-key"}),
          patch("hermes_cli.runtime_provider._get_named_custom_provider", return_value=None)):
        kind, _, retry = auxiliary._ladder_step_call(
            step, SimpleNamespace(),
            {"task": "compression", "resolved_api_key": "test-config-key",
             "resolved_model": "fallback-model", "caller_api_key_provider": "custom:edge",
             "caller_api_key": None},
            {},
        )

    assert kind == "retry"
    assert retry["resolved_api_key"] is None
    assert "caller_api_key" not in retry


def test_named_custom_session_key_is_shielded_at_foreign_origin():
    import agent.auxiliary_client as auxiliary

    runtime = {
        "provider": "custom:edge",
        "base_url": "https://session-edge.test/v1",
        "api_key": "test-session-key",
    }
    client = SimpleNamespace(
        base_url="https://aux-edge-proxy.test/v1",
        api_key="test-session-key",
    )

    assert auxiliary._recoverable_pool_provider("custom:edge", client, main_runtime=runtime) is None


def test_named_custom_pool_still_recovers_for_its_own_credential():
    import agent.auxiliary_client as auxiliary

    runtime = {
        "provider": "custom:edge",
        "base_url": "https://session-edge.test/v1",
        "api_key": "test-session-key",
    }
    client = SimpleNamespace(
        base_url="https://aux-edge-proxy.test/v1",
        api_key="test-aux-pool-key",
    )

    assert auxiliary._recoverable_pool_provider("custom:edge", client, main_runtime=runtime) == "custom:edge"


@pytest.mark.parametrize("async_mode", [False, True])
def test_vision_explicit_provider_fallback_uses_auto_route_identity_without_call_key(async_mode):
    import agent.auxiliary_client as auxiliary

    runtime = {"provider": "custom", "model": "main-model", "base_url": "https://main.test/v1",
               "api_key": "main-runtime-key", "api_mode": "chat_completions"}
    selected = MagicMock()
    selected.api_key = "auto-selected-key"
    selected.base_url = "http://lmstudio.test/v1"
    resolve = MagicMock(side_effect=[
        ("custom:edge", None, None),
        ("lmstudio", selected, "lmstudio-vision-model"),
    ])
    with patch.object(auxiliary, "_resolve_task_provider_model", return_value=(
        "custom:edge", "edge-vision-model", None, "caller-edge-key", "anthropic_messages",
    )), patch.object(auxiliary, "resolve_vision_provider_client", resolve):
        route = auxiliary._resolve_call_client(
            "vision", provider="custom:edge", model="edge-vision-model", base_url=None,
            api_key="caller-edge-key", resolved_provider="custom:edge", resolved_model="edge-vision-model",
            resolved_base_url=None, resolved_api_key="caller-edge-key", resolved_api_mode="anthropic_messages",
            main_runtime=runtime, async_mode=async_mode,
        )

    assert resolve.call_count == 2
    assert resolve.call_args_list[0].kwargs["provider"] == "custom:edge"
    auto_call = resolve.call_args_list[1].kwargs
    assert auto_call["provider"] == "auto"
    assert auto_call["model"] == "edge-vision-model"
    assert "api_mode" not in auto_call
    assert "base_url" not in auto_call and "api_key" not in auto_call
    assert route.client is selected
    assert route.resolved_provider == "lmstudio"
    assert route.resolved_model == "lmstudio-vision-model"
    assert route.resolved_base_url == "http://lmstudio.test/v1"
    assert route.resolved_api_key == "auto-selected-key"
    assert route.resolved_api_mode == "chat_completions"


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
