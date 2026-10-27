"""Native transport checks; default test ACLs do not qualify a protected SCM DACL."""

from __future__ import annotations

import ctypes
import json
import os
import struct
import threading
import time
from ctypes import wintypes
from datetime import UTC, datetime

import pytest

from agent.trusted_verifier_controller_protocol import (
    MAX_CONTROLLER_MESSAGE_BYTES,
    ControllerBinding,
    ControllerMessage,
    ControllerStatus,
    MessageKind,
)
from agent.trusted_verifier_contract import (
    CONTRACT_ROOT,
    CONTRACT_VERSION,
    ExpectedEffect,
    VerificationRequest,
)
from agent.trusted_verifier_windows_controller_service import (
    WindowsControllerServiceError,
    WindowsForegroundControllerService,
)

_FRAME = struct.Struct("!I")
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_OPEN_EXISTING = 3
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


def _request() -> ControllerMessage:
    request = VerificationRequest(
        root=CONTRACT_ROOT,
        version=CONTRACT_VERSION,
        session_id="windows-session-test",
        attempt_id="windows-attempt-test",
        authority="parent-authority",
        scope=("workspace:test",),
        policy_digest="sha256:" + "b" * 64,
        nonce="windows-nonce-test",
        correlation_id="windows-correlation-test",
        expected_effects=(
            ExpectedEffect(
                effect="write", subject="file:result", digest="sha256:" + "c" * 64
            ),
        ),
        expires_at=datetime(2030, 1, 1, tzinfo=UTC),
        freshness_seconds=60,
    )
    return ControllerMessage(
        kind=MessageKind.REQUEST,
        binding=ControllerBinding(
            request=request, root_digest="sha256:" + "a" * 64, generation=1
        ),
    )


def _native_client_api():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.WaitNamedPipeW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD)
    kernel.WaitNamedPipeW.restype = wintypes.BOOL
    kernel.WriteFile.argtypes = (
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    )
    kernel.WriteFile.restype = wintypes.BOOL
    kernel.ReadFile.argtypes = kernel.WriteFile.argtypes
    kernel.ReadFile.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def _connect(kernel, pipe_name: str):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        handle = kernel.CreateFileW(
            pipe_name,
            _GENERIC_READ | _GENERIC_WRITE,
            0,
            None,
            _OPEN_EXISTING,
            0,
            None,
        )
        if handle != _INVALID_HANDLE_VALUE:
            return handle
        kernel.WaitNamedPipeW(pipe_name, 100)
    raise AssertionError("foreground named-pipe listener did not become available")


def _exchange(
    kernel, pipe_name: str, payload: bytes, declared_length: int | None = None
):
    handle = _connect(kernel, pipe_name)
    try:
        frame_length = len(payload) if declared_length is None else declared_length
        packet = _FRAME.pack(frame_length) + payload

        def write_all(data: bytes) -> bool:
            offset = 0
            while offset < len(data):
                buffer = ctypes.create_string_buffer(data[offset:])
                written = wintypes.DWORD()
                if (
                    not kernel.WriteFile(
                        handle,
                        buffer,
                        len(data) - offset,
                        ctypes.byref(written),
                        None,
                    )
                    or written.value == 0
                ):
                    return False
                offset += written.value
            return True

        def read_exact(length: int) -> bytes | None:
            result = bytearray()
            while len(result) < length:
                buffer = ctypes.create_string_buffer(length - len(result))
                read = wintypes.DWORD()
                if (
                    not kernel.ReadFile(
                        handle,
                        buffer,
                        length - len(result),
                        ctypes.byref(read),
                        None,
                    )
                    or read.value == 0
                ):
                    return None
                result.extend(buffer.raw[: read.value])
            return bytes(result)

        if not write_all(packet):
            return b""
        header = read_exact(_FRAME.size)
        if header is None:
            return b""
        length = _FRAME.unpack(header)[0]
        if not 0 < length <= MAX_CONTROLLER_MESSAGE_BYTES:
            return b""
        return read_exact(length) or b""
    finally:
        kernel.CloseHandle(handle)


def _start_service():
    service = WindowsForegroundControllerService(
        acknowledge_no_trusted_success=True,
        acknowledge_no_service_install=True,
    )
    errors: list[BaseException] = []

    def serve():
        try:
            service.serve_forever()
        except BaseException as exc:  # captured for assertion in the test thread
            errors.append(exc)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return service, thread, errors


@pytest.mark.platforms("linux")
def test_non_windows_import_and_startup_fail_explicitly():
    assert os.name != "nt"
    with pytest.raises(WindowsControllerServiceError, match="unavailable"):
        WindowsForegroundControllerService(
            acknowledge_no_trusted_success=True,
            acknowledge_no_service_install=True,
        )


@pytest.mark.platforms("windows")
def test_native_pipe_returns_incomplete_and_observes_kernel_client_pid():
    kernel = _native_client_api()
    service, thread, errors = _start_service()
    pipe_name = service.pipe_name
    try:
        for _ in range(2):
            response = ControllerMessage.from_wire(
                _exchange(kernel, pipe_name, _request().to_wire())
            )
            assert response.status is ControllerStatus.INCOMPLETE
            assert response.binding == _request().binding
            assert response.status is not ControllerStatus.ACCEPTED_FOR_VERIFICATION
        assert service.last_observed_client_pid == os.getpid()
        assert not errors
    finally:
        service.stop()
        thread.join(timeout=3)
    assert not thread.is_alive()
    assert not errors


@pytest.mark.platforms("windows")
@pytest.mark.parametrize(
    "payload,length",
    [
        (b"{", None),
        (b"x", MAX_CONTROLLER_MESSAGE_BYTES + 1),
        (b"x" * (MAX_CONTROLLER_MESSAGE_BYTES + 1), None),
    ],
)
def test_invalid_and_oversized_frames_close_then_listener_recovers(payload, length):
    kernel = _native_client_api()
    service, thread, errors = _start_service()
    try:
        assert _exchange(kernel, service.pipe_name, payload, length) == b""
        response = ControllerMessage.from_wire(
            _exchange(kernel, service.pipe_name, _request().to_wire())
        )
        assert response.status is ControllerStatus.INCOMPLETE
    finally:
        service.stop()
        thread.join(timeout=3)
    assert not thread.is_alive()
    assert not errors


@pytest.mark.platforms("windows")
def test_caller_supplied_pid_claim_is_rejected_and_listener_survives():
    kernel = _native_client_api()
    service, thread, errors = _start_service()
    try:
        mapping = _request().to_mapping()
        mapping["client_pid"] = os.getpid()
        assert (
            _exchange(
                kernel,
                service.pipe_name,
                json.dumps(mapping, separators=(",", ":")).encode(),
            )
            == b""
        )
        response = ControllerMessage.from_wire(
            _exchange(kernel, service.pipe_name, _request().to_wire())
        )
        assert response.status is ControllerStatus.INCOMPLETE
    finally:
        service.stop()
        thread.join(timeout=3)
    assert not thread.is_alive()
    assert not errors


@pytest.mark.platforms("windows")
def test_startup_guards_are_required():
    with pytest.raises(WindowsControllerServiceError, match="startup requires"):
        WindowsForegroundControllerService(
            acknowledge_no_trusted_success=False,
            acknowledge_no_service_install=True,
        )
