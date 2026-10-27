"""Real-process tests for the unprivileged, always-incomplete controller."""

from __future__ import annotations

import json
import os
import signal
import socket
import struct
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent.trusted_verifier_controller_protocol import (
    MAX_CONTROLLER_MESSAGE_BYTES,
    ControllerBinding,
    ControllerMessage,
    ControllerProtocolError,
    ControllerStatus,
    MessageKind,
)
from agent.trusted_verifier_contract import (
    CONTRACT_ROOT,
    CONTRACT_VERSION,
    ExpectedEffect,
    VerificationRequest,
)
from agent.trusted_verifier_controller_service import (
    ControllerServiceError,
    ForegroundControllerService,
)

_FRAME = struct.Struct("!I")
_REPO = Path(__file__).resolve().parents[2]


def _request() -> ControllerMessage:
    request = VerificationRequest(
        root=CONTRACT_ROOT,
        version=CONTRACT_VERSION,
        session_id="session-test",
        attempt_id="attempt-test",
        authority="parent-authority",
        scope=("workspace:test",),
        policy_digest="sha256:" + "b" * 64,
        nonce="nonce-test",
        correlation_id="correlation-test",
        expected_effects=(
            ExpectedEffect(
                effect="write", subject="file:result", digest="sha256:" + "c" * 64
            ),
        ),
        expires_at=datetime(2030, 1, 1, tzinfo=UTC),
        freshness_seconds=60,
    )
    binding = ControllerBinding(
        request=request, root_digest="sha256:" + "a" * 64, generation=1
    )
    return ControllerMessage(kind=MessageKind.REQUEST, binding=binding)


def _socket_dir() -> Path:
    base = Path(os.environ.get("RUNNER_TEMP") or os.environ["TMPDIR"])
    if base == Path("/tmp") or Path("/tmp") in base.parents:
        raise AssertionError(
            "real socket tests require a runner-owned directory outside /tmp"
        )
    directory = base / f"fhm005-svc-{os.getpid()}"
    directory.mkdir(exist_ok=True)
    return directory


def _start_service(
    socket_dir: Path, expected_uid: int | None = None
) -> subprocess.Popen:
    command = [
        sys.executable,
        "-m",
        "agent.trusted_verifier_controller_service",
        "--socket-dir",
        str(socket_dir),
        "--expected-parent-uid",
        str(os.getuid() if expected_uid is None else expected_uid),
        "--no-trusted-success",
        "--no-service-install",
    ]
    process = subprocess.Popen(
        command,
        cwd=_REPO,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    endpoint = socket_dir / "s"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr else ""
            raise AssertionError(f"service exited before listening: {stderr}")
        if endpoint.exists():
            return process
        time.sleep(0.025)
    process.terminate()
    process.wait(timeout=3)
    raise AssertionError("service did not create its endpoint before timeout")


def _exchange(
    endpoint: Path, payload: bytes, *, declared_length: int | None = None
) -> bytes:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3)
        client.connect(str(endpoint))
        length = len(payload) if declared_length is None else declared_length
        client.sendall(_FRAME.pack(length) + payload)
        try:
            header = client.recv(_FRAME.size)
        except ConnectionResetError:
            # The server may reset after a deliberately oversized/truncated frame.
            return b""
        if not header:
            return b""
        while len(header) < _FRAME.size:
            header += client.recv(_FRAME.size - len(header))
        response_length = _FRAME.unpack(header)[0]
        data = bytearray()
        while len(data) < response_length:
            chunk = client.recv(response_length - len(data))
            if not chunk:
                break
            data.extend(chunk)
        return bytes(data)


def _stop_service(process: subprocess.Popen) -> None:
    process.send_signal(signal.SIGINT)
    process.wait(timeout=5)


@pytest.mark.skipif(os.name == "nt", reason="Linux AF_UNIX process lifecycle")
def test_real_process_observes_kernel_peer_and_never_issues_trusted_result():
    socket_dir = _socket_dir()
    process = _start_service(socket_dir)
    endpoint = socket_dir / "s"
    try:
        wire = _request().to_wire()
        response = ControllerMessage.from_wire(_exchange(endpoint, wire))
        assert response.status is ControllerStatus.INCOMPLETE
        assert response.binding == _request().binding
        assert response.status is not ControllerStatus.ACCEPTED_FOR_VERIFICATION
        assert not list(socket_dir.glob("*receipt*"))
    finally:
        _stop_service(process)
    assert process.returncode == 0
    assert not endpoint.exists()
    socket_dir.rmdir()


@pytest.mark.skipif(os.name == "nt", reason="Linux AF_UNIX transport")
@pytest.mark.parametrize(
    "payload,length",
    [
        (b"{", 1),
        (
            b'{"root":"hermes.trusted_verifier_controller","version":1,"kind":"forged"}',
            None,
        ),
        (b"x" * 4, MAX_CONTROLLER_MESSAGE_BYTES + 1),
    ],
)
def test_malformed_oversized_and_unknown_requests_are_closed(payload, length):
    socket_dir = _socket_dir()
    process = _start_service(socket_dir)
    endpoint = socket_dir / "s"
    try:
        assert _exchange(endpoint, payload, declared_length=length) == b""
    finally:
        _stop_service(process)
    assert not endpoint.exists()
    socket_dir.rmdir()


@pytest.mark.skipif(os.name == "nt", reason="Linux AF_UNIX peer credentials")
def test_kernel_observed_uid_mismatch_is_rejected_and_forged_fields_are_not_trusted():
    socket_dir = _socket_dir()
    process = _start_service(socket_dir, expected_uid=os.getuid() + 1)
    endpoint = socket_dir / "s"
    try:
        response = ControllerMessage.from_wire(
            _exchange(endpoint, _request().to_wire())
        )
        assert response.status is ControllerStatus.REJECTED
        mapping = _request().to_mapping()
        mapping["peer_uid"] = os.getuid() + 1
        with pytest.raises(ControllerProtocolError):
            ControllerMessage.from_wire(json.dumps(mapping).encode())
        assert _exchange(endpoint, json.dumps(mapping).encode()) == b""
    finally:
        _stop_service(process)
    assert not endpoint.exists()
    socket_dir.rmdir()


def test_windows_adapter_is_explicitly_unsupported(monkeypatch, tmp_path):
    import agent.trusted_verifier_controller_service as service_module

    monkeypatch.setattr(service_module.os, "name", "nt")
    with pytest.raises(ControllerServiceError, match="Windows SCM/named-pipe"):
        ForegroundControllerService(
            tmp_path,
            expected_parent_uid=1,
            acknowledge_no_trusted_success=True,
            acknowledge_no_service_install=True,
        )
