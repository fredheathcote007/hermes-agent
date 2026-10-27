"""Unprivileged foreground transport for the fail-closed FHM-005 controller.

This is a real Linux AF_UNIX accept loop, not a protected service. It observes
kernel peer credentials and parses the production wire protocol, but it has no
approved native parent-service attestor. Therefore every syntactically valid
request is answered INCOMPLETE and no capability or receipt is issued. Windows
is explicitly unsupported until an SCM and named-pipe adapter is approved.
"""

from __future__ import annotations

import argparse
import os
import socket
import struct
import sys
import threading
from pathlib import Path
from stat import S_ISSOCK

from agent.trusted_verifier_controller_protocol import (
    MAX_CONTROLLER_MESSAGE_BYTES,
    ControllerMessage,
    ControllerProtocolError,
    ControllerStatus,
    MessageKind,
)

_FRAME = struct.Struct("!I")
_PEERCRED = struct.Struct("3i")


class ControllerServiceError(RuntimeError):
    """The foreground listener cannot safely start or continue."""


class NativeParentAttestor:
    """Unimplemented sealed native adapter seam; never accepts caller claims."""

    def attest_parent(self, peer: tuple[int, int, int]) -> None:
        # SO_PEERCRED supplies useful kernel observations, but does not prove
        # systemd service identity. Owner approval and native service testing
        # are required before this seam can return authority-bearing evidence.
        return None


class ForegroundControllerService:
    """Bounded Linux foreground controller transport with no trusted mode."""

    def __init__(
        self,
        socket_dir: str | Path,
        *,
        expected_parent_uid: int,
        acknowledge_no_trusted_success: bool,
        acknowledge_no_service_install: bool,
        attestor: NativeParentAttestor | None = None,
    ) -> None:
        if os.name == "nt":
            raise ControllerServiceError(
                "unsupported: Windows SCM/named-pipe adapter is not implemented"
            )
        if not sys.platform.startswith("linux") or not hasattr(socket, "SO_PEERCRED"):
            raise ControllerServiceError(
                "unsupported: Linux AF_UNIX peer credentials are required"
            )
        if (
            acknowledge_no_trusted_success is not True
            or acknowledge_no_service_install is not True
        ):
            raise ControllerServiceError(
                "startup requires explicit no-trusted-success and no-service-install guards"
            )
        if type(expected_parent_uid) is not int or expected_parent_uid < 0:
            raise ControllerServiceError(
                "expected parent UID must be a nonnegative integer"
            )
        raw_dir = Path(socket_dir)
        if not raw_dir.is_absolute() or not raw_dir.is_dir() or raw_dir.is_symlink():
            raise ControllerServiceError(
                "socket directory must be an existing absolute non-symlink directory"
            )
        resolved = raw_dir.resolve(strict=True)
        if (
            resolved == Path("/")
            or resolved == Path("/tmp")
            or Path("/tmp") in resolved.parents
        ):
            raise ControllerServiceError("socket directory must not be under /tmp")
        if not os.access(resolved, os.W_OK | os.X_OK):
            raise ControllerServiceError(
                "socket directory must be writable by the operator"
            )
        self.socket_path = resolved / "s"
        if len(os.fsencode(self.socket_path)) >= 108:
            raise ControllerServiceError(
                "Unix socket path exceeds the portable length bound"
            )
        self.expected_parent_uid = expected_parent_uid
        self.attestor = attestor or NativeParentAttestor()
        self._listener: socket.socket | None = None
        self._socket_identity: tuple[int, int] | None = None
        self._stopping = threading.Event()

    def start(self) -> None:
        if self._listener is not None:
            raise ControllerServiceError("service is already started")
        if self.socket_path.exists() or self.socket_path.is_symlink():
            raise ControllerServiceError("refusing to replace an existing endpoint")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            previous_umask = os.umask(0o177)
            try:
                listener.bind(str(self.socket_path))
            finally:
                os.umask(previous_umask)
            info = self.socket_path.lstat()
            if not S_ISSOCK(info.st_mode):
                raise ControllerServiceError("bound endpoint is not a Unix socket")
            self._socket_identity = (info.st_dev, info.st_ino)
            listener.listen(8)
            listener.settimeout(0.2)
            self._listener = listener
        except BaseException:
            listener.close()
            self._cleanup_endpoint()
            raise

    def serve_forever(self) -> None:
        if self._listener is None:
            self.start()
        assert self._listener is not None
        while not self._stopping.is_set():
            try:
                connection, _ = self._listener.accept()
            except TimeoutError:
                continue
            except OSError:
                if self._stopping.is_set():
                    break
                raise
            with connection:
                try:
                    connection.settimeout(2.0)
                    self._handle_connection(connection)
                except Exception:
                    # A malformed peer or an adapter/serializer failure is
                    # scoped to this connection; it must not stop the listener.
                    continue

    def stop(self) -> None:
        self._stopping.set()
        listener, self._listener = self._listener, None
        if listener is not None:
            listener.close()
        self._cleanup_endpoint()

    def _handle_connection(self, connection: socket.socket) -> None:
        try:
            peer = _PEERCRED.unpack(
                connection.getsockopt(
                    socket.SOL_SOCKET, socket.SO_PEERCRED, _PEERCRED.size
                )
            )
            frame = _read_frame(connection)
            message = ControllerMessage.from_wire(frame)
        except (OSError, ControllerProtocolError, TimeoutError):
            return
        if message.kind is not MessageKind.REQUEST:
            return
        # Linux SO_PEERCRED is (pid, uid, gid); never compare the GID to expected UID.
        if peer[0] <= 0 or peer[1] != self.expected_parent_uid:
            status = ControllerStatus.REJECTED
        elif self.attestor.attest_parent(peer) is None:
            status = ControllerStatus.INCOMPLETE
        else:
            # This foreground implementation cannot enable success. Trusted
            # issuance requires a separately approved service implementation.
            status = ControllerStatus.INCOMPLETE
        try:
            response = ControllerMessage(
                kind=MessageKind.STATUS, binding=message.binding, status=status
            ).to_wire()
            connection.sendall(_FRAME.pack(len(response)) + response)
        except Exception:
            # The response echoes untrusted identifiers and can expand beyond
            # the wire bound. In that case, close without issuing any status.
            return

    def _cleanup_endpoint(self) -> None:
        identity, self._socket_identity = self._socket_identity, None
        if identity is None:
            return
        try:
            info = self.socket_path.lstat()
        except FileNotFoundError:
            return
        if (info.st_dev, info.st_ino) == identity and S_ISSOCK(info.st_mode):
            self.socket_path.unlink()


def _read_exact(connection: socket.socket, length: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        chunk = connection.recv(length - len(chunks))
        if not chunk:
            raise OSError("truncated frame")
        chunks.extend(chunk)
    return bytes(chunks)


def _read_frame(connection: socket.socket) -> bytes:
    length = _FRAME.unpack(_read_exact(connection, _FRAME.size))[0]
    if length == 0 or length > MAX_CONTROLLER_MESSAGE_BYTES:
        raise ControllerProtocolError("frame length is outside the protocol bound")
    return _read_exact(connection, length)


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket-dir", required=True)
    parser.add_argument("--expected-parent-uid", required=True, type=int)
    parser.add_argument("--no-trusted-success", action="store_true")
    parser.add_argument("--no-service-install", action="store_true")
    args = parser.parse_args()
    service = ForegroundControllerService(
        args.socket_dir,
        expected_parent_uid=args.expected_parent_uid,
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
