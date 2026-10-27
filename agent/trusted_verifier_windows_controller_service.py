"""Unprivileged Windows named-pipe transport for the FHM-005 controller.

The transport uses a local Win32 byte pipe and reports the kernel-observed
client PID for diagnostics. A PID or account SID does not identify the
protected SCM parent service, so every valid request remains INCOMPLETE. This
module installs no service, changes no ACL, and creates no trusted capability.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import struct
import threading
import time
import uuid
from ctypes import wintypes

from agent.trusted_verifier_controller_protocol import (
    MAX_CONTROLLER_MESSAGE_BYTES,
    ControllerMessage,
    ControllerProtocolError,
    ControllerStatus,
    MessageKind,
)

_FRAME = struct.Struct("!I")
_PIPE_ACCESS_DUPLEX = 0x00000003
_FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
_PIPE_TYPE_BYTE = 0x00000000
_PIPE_READMODE_BYTE = 0x00000000
_PIPE_NOWAIT = 0x00000001
_PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
_ERROR_PIPE_CONNECTED = 535
_ERROR_PIPE_LISTENING = 536
_ERROR_NO_DATA = 232
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_IO_TIMEOUT_SECONDS = 2.0


class WindowsControllerServiceError(RuntimeError):
    """The named-pipe adapter cannot safely start or continue."""


def _kernel32():
    if os.name != "nt":
        raise WindowsControllerServiceError("Windows named pipes are unavailable")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateNamedPipeW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    )
    kernel.CreateNamedPipeW.restype = wintypes.HANDLE
    kernel.ConnectNamedPipe.argtypes = (wintypes.HANDLE, ctypes.c_void_p)
    kernel.ConnectNamedPipe.restype = wintypes.BOOL
    kernel.SetNamedPipeHandleState.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
        ctypes.c_void_p,
    )
    kernel.SetNamedPipeHandleState.restype = wintypes.BOOL
    kernel.PeekNamedPipe.argtypes = (
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    )
    kernel.PeekNamedPipe.restype = wintypes.BOOL
    kernel.ReadFile.argtypes = (
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    )
    kernel.ReadFile.restype = wintypes.BOOL
    kernel.WriteFile.argtypes = kernel.ReadFile.argtypes
    kernel.WriteFile.restype = wintypes.BOOL
    kernel.GetNamedPipeClientProcessId.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.ULONG),
    )
    kernel.GetNamedPipeClientProcessId.restype = wintypes.BOOL
    kernel.DisconnectNamedPipe.argtypes = (wintypes.HANDLE,)
    kernel.DisconnectNamedPipe.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


class WindowsForegroundControllerService:
    """A local-only, always-incomplete foreground pipe listener."""

    def __init__(
        self,
        *,
        acknowledge_no_trusted_success: bool,
        acknowledge_no_service_install: bool,
    ) -> None:
        if os.name != "nt":
            raise WindowsControllerServiceError("Windows named pipes are unavailable")
        if (
            acknowledge_no_trusted_success is not True
            or acknowledge_no_service_install is not True
        ):
            raise WindowsControllerServiceError(
                "startup requires explicit no-trusted-success and no-service-install guards"
            )
        self._kernel = _kernel32()
        self.pipe_name = ""
        self._stop = threading.Event()
        self._handle = None
        self.last_observed_client_pid: int | None = None

    def serve_forever(self) -> None:
        while not self._stop.is_set():
            handle = self._create_pipe()
            self._handle = handle
            try:
                if self._wait_for_client(handle):
                    self._handle_connection(handle)
            finally:
                self._kernel.DisconnectNamedPipe(handle)
                self._kernel.CloseHandle(handle)
                if self._handle == handle:
                    self._handle = None

    def stop(self) -> None:
        self._stop.set()

    def _create_pipe(self):
        # A fresh name plus FIRST_PIPE_INSTANCE closes the disconnect/recreate
        # race where a same-user process could squat a reused endpoint.
        self.pipe_name = rf"\\.\pipe\hermes-fhm005-{uuid.uuid4().hex}"
        flags = _PIPE_ACCESS_DUPLEX | _FILE_FLAG_FIRST_PIPE_INSTANCE
        handle = self._kernel.CreateNamedPipeW(
            self.pipe_name,
            flags,
            _PIPE_TYPE_BYTE
            | _PIPE_READMODE_BYTE
            | _PIPE_NOWAIT
            | _PIPE_REJECT_REMOTE_CLIENTS,
            1,
            MAX_CONTROLLER_MESSAGE_BYTES + _FRAME.size,
            MAX_CONTROLLER_MESSAGE_BYTES + _FRAME.size,
            0,
            None,
        )
        if handle == _INVALID_HANDLE_VALUE:
            raise WindowsControllerServiceError(
                f"CreateNamedPipeW failed with Win32 error {ctypes.get_last_error()}"
            )
        return handle

    def _wait_for_client(self, handle) -> bool:
        while not self._stop.is_set():
            if self._kernel.ConnectNamedPipe(handle, None):
                return True
            error = ctypes.get_last_error()
            if error == _ERROR_PIPE_CONNECTED:
                return True
            if error != _ERROR_PIPE_LISTENING:
                raise WindowsControllerServiceError(
                    f"ConnectNamedPipe failed with Win32 error {error}"
                )
            self._stop.wait(0.025)
        return False

    def _handle_connection(self, handle) -> None:
        client_pid = wintypes.ULONG()
        if not self._kernel.GetNamedPipeClientProcessId(
            handle, ctypes.byref(client_pid)
        ):
            return
        if client_pid.value == 0:
            return
        self.last_observed_client_pid = int(client_pid.value)
        try:
            payload = self._read_frame(handle)
            message = ControllerMessage.from_wire(payload)
        except (WindowsControllerServiceError, ControllerProtocolError):
            return
        if message.kind is not MessageKind.REQUEST:
            return
        # PID observation is diagnostic. SCM service SID/token attestation is
        # intentionally unavailable pending separately approved provisioning.
        try:
            response = ControllerMessage(
                kind=MessageKind.STATUS,
                binding=message.binding,
                status=ControllerStatus.INCOMPLETE,
            ).to_wire()
        except ControllerProtocolError:
            return
        self._write_all(handle, _FRAME.pack(len(response)) + response)

    def _read_frame(self, handle) -> bytes:
        deadline = time.monotonic() + _IO_TIMEOUT_SECONDS

        def exact(size: int) -> bytes:
            result = bytearray()
            while len(result) < size:
                if self._stop.is_set() or time.monotonic() >= deadline:
                    raise WindowsControllerServiceError("pipe read timed out")
                available = wintypes.DWORD()
                if not self._kernel.PeekNamedPipe(
                    handle, None, 0, None, ctypes.byref(available), None
                ):
                    raise WindowsControllerServiceError("named-pipe peer disconnected")
                if available.value == 0:
                    self._stop.wait(0.01)
                    continue
                amount = min(size - len(result), int(available.value))
                buffer = ctypes.create_string_buffer(amount)
                read = wintypes.DWORD()
                if (
                    not self._kernel.ReadFile(
                        handle, buffer, amount, ctypes.byref(read), None
                    )
                    or read.value == 0
                ):
                    error = ctypes.get_last_error()
                    if error == _ERROR_NO_DATA:
                        continue
                    raise WindowsControllerServiceError("named-pipe read failed")
                result.extend(buffer.raw[: read.value])
            return bytes(result)

        length = _FRAME.unpack(exact(_FRAME.size))[0]
        if length == 0 or length > MAX_CONTROLLER_MESSAGE_BYTES:
            raise ControllerProtocolError("frame length is outside the protocol bound")
        return exact(length)

    def _write_all(self, handle, payload: bytes) -> None:
        offset = 0
        deadline = time.monotonic() + _IO_TIMEOUT_SECONDS
        while offset < len(payload) and time.monotonic() < deadline:
            written = wintypes.DWORD()
            chunk = payload[offset:]
            buffer = ctypes.create_string_buffer(chunk)
            if not self._kernel.WriteFile(
                handle, buffer, len(chunk), ctypes.byref(written), None
            ):
                return
            if written.value == 0:
                return
            offset += written.value


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-trusted-success", action="store_true")
    parser.add_argument("--no-service-install", action="store_true")
    args = parser.parse_args()
    service = WindowsForegroundControllerService(
        acknowledge_no_trusted_success=args.no_trusted_success,
        acknowledge_no_service_install=args.no_service_install,
    )
    try:
        service.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
