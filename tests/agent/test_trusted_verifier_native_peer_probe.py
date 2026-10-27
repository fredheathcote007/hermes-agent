"""Unprivileged native identity diagnostics for the FHM-005 controller contract.

These probes observe the current test process only. They do not authenticate a
protected parent or verifier service, prove same-user isolation, or authorize a
trusted result. The controller wire-field rejection here supplements the
generic unknown-field coverage in test_trusted_verifier_controller_protocol.py.
"""

from __future__ import annotations

import json
import os
import socket
import struct
import sys
from dataclasses import dataclass

import pytest

from agent.trusted_verifier_controller_protocol import (
    AuthorizationResult,
    ControllerAuthority,
    ControllerMessage,
    ControllerProtocolError,
    MessageKind,
    ServiceRole,
    _peer_evidence_from_native_adapter,
)
from tests.agent.test_trusted_verifier_controller_protocol import _binding


@dataclass(frozen=True)
class _ObservedPeer:
    user_id: int
    process_id: int


def _matches_linux_peer(
    observed: _ObservedPeer | None, expected: _ObservedPeer
) -> bool:
    """Exact diagnostic comparison; this is not service authorization."""
    return observed is not None and observed == expected


def _linux_socket_peer_credentials(peer: socket.socket) -> _ObservedPeer | None:
    """Read Linux kernel credentials for a connected AF_UNIX socket peer."""
    if not hasattr(socket, "SO_PEERCRED"):
        return None
    try:
        raw = peer.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
        )
    except OSError:
        return None
    if len(raw) != struct.calcsize("3i"):
        return None
    process_id, user_id, _group_id = struct.unpack("3i", raw)
    if process_id <= 0 or user_id < 0:
        return None
    return _ObservedPeer(user_id=user_id, process_id=process_id)


@pytest.mark.platforms("linux")
def test_linux_unprivileged_socketpair_observes_kernel_peer_and_rejects_mismatch():
    """SO_PEERCRED reports this process; fake UID/PID expectations are denied."""
    if not hasattr(socket, "AF_UNIX") or not hasattr(socket, "SO_PEERCRED"):
        pytest.fail("Linux AF_UNIX/SO_PEERCRED API is unavailable; deny by default")

    expected = _ObservedPeer(user_id=os.getuid(), process_id=os.getpid())
    with socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM) as (left, _right):
        observed = _linux_socket_peer_credentials(left)

    assert observed == expected
    fake_user = _ObservedPeer(
        user_id=expected.user_id + 1, process_id=expected.process_id
    )
    fake_process = _ObservedPeer(
        user_id=expected.user_id, process_id=expected.process_id + 1
    )
    assert _matches_linux_peer(observed, expected)
    assert not _matches_linux_peer(observed, fake_user)
    assert not _matches_linux_peer(observed, fake_process)
    assert not _matches_linux_peer(None, expected)


def _windows_process_user_sid() -> str | None:
    """Read the current process token user SID using only Windows APIs."""
    if sys.platform != "win32":
        return None

    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    token = wintypes.HANDLE()
    token_user = 1
    token_query = 0x0008

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

    class TOKEN_USER(ctypes.Structure):
        _fields_ = [("User", SID_AND_ATTRIBUTES)]

    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), token_query, ctypes.byref(token)
    ):
        return None
    sid_text = wintypes.LPWSTR()
    try:
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(token, token_user, None, 0, ctypes.byref(required))
        if not required.value:
            return None
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token, token_user, buffer, required.value, ctypes.byref(required)
        ):
            return None
        user = ctypes.cast(buffer, ctypes.POINTER(TOKEN_USER)).contents
        if not user.User.Sid or not advapi32.ConvertSidToStringSidW(
            user.User.Sid, ctypes.byref(sid_text)
        ):
            return None
        return sid_text.value
    finally:
        if sid_text:
            kernel32.LocalFree(sid_text)
        kernel32.CloseHandle(token)


def _windows_sid_matches(observed: str | None, expected: str | None) -> bool:
    """Unavailable or mismatched identity never satisfies an expectation."""
    return bool(observed and expected and observed == expected)


def _windows_service_identity_authenticated(
    observed_sid: str | None, expected_service_sid: str | None, *, authenticated: bool
) -> bool:
    """Diagnostic guard: a process SID alone is never a service-auth proof."""
    return authenticated and _windows_sid_matches(observed_sid, expected_service_sid)


@pytest.mark.platforms("windows")
def test_windows_current_process_token_sid_is_observed_and_service_identity_fails_closed():
    """Current token user SID is diagnostic; no service principal is inferred."""
    observed_sid = _windows_process_user_sid()
    assert observed_sid, "Windows token-user API unavailable; deny by default"
    assert _windows_sid_matches(observed_sid, observed_sid)
    assert not _windows_sid_matches(observed_sid, f"{observed_sid}-999")
    assert not _windows_sid_matches(None, observed_sid)
    assert not _windows_service_identity_authenticated(
        observed_sid, observed_sid, authenticated=False
    )


@pytest.mark.parametrize(
    ("provider", "model"),
    [
        ("lm_studio", "qwen3-30b-a3b"),
        ("openai", "gpt-5"),
        ("anthropic", "claude-sonnet-4"),
    ],
)
def test_untrusted_provider_model_outer_metadata_cannot_change_controller_outcome(
    provider: str, model: str
):
    """Provider names are outer metadata, never controller authority inputs."""
    binding = _binding()
    message = ControllerMessage(kind=MessageKind.REQUEST, binding=binding)
    peer = _peer_evidence_from_native_adapter(
        role=ServiceRole.PARENT_AUTHORITY,
        principal_id="diagnostic-peer",
        process_id=os.getpid(),
        generation=3,
    )

    def authorize(candidate: ControllerMessage) -> AuthorizationResult:
        authority = ControllerAuthority(binding=binding, consumed_nonces=set())
        return authority.authorize_request(candidate, peer).result

    baseline = authorize(message)
    outer_metadata = {"provider": provider, "model": model}
    inner_message = ControllerMessage.from_wire(message.to_wire())

    # Metadata is deliberately not supplied to ControllerAuthority.
    assert outer_metadata == {"provider": provider, "model": model}
    assert authorize(inner_message) is baseline
    assert baseline is AuthorizationResult.AUTHORIZED_FOR_VERIFICATION

    injected = message.to_mapping()
    injected.update(outer_metadata)
    with pytest.raises(ControllerProtocolError, match="message fields are not exact"):
        ControllerMessage.from_wire(json.dumps(injected).encode())
