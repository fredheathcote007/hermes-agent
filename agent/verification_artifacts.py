"""Bounded, source-only filesystem artifact observations for FHM-005.

This module is deliberately not a verifier, receipt store, controller, or
authority.  It observes one regular file relative to one opened directory and
returns immutable, request-bound data.  The POSIX implementation uses
descriptor-relative traversal with no-following directory/file opens.  Native
Windows support is explicitly unavailable until volume/file IDs and
reparse-point-safe traversal have been separately qualified.
"""

from __future__ import annotations

import hashlib
import inspect
import os
import stat
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Final


class ArtifactStatus(str, Enum):
    """Safe disposition associated with an observation failure."""

    INCOMPLETE = "INCOMPLETE"
    UNSUPPORTED = "UNSUPPORTED"


class ArtifactError(ValueError):
    """Base class for fail-closed observation errors."""

    status: Final[ArtifactStatus]

    def __init__(self, message: str, *, status: ArtifactStatus = ArtifactStatus.INCOMPLETE) -> None:
        super().__init__(message)
        self.status = status


class ArtifactUnsupportedError(ArtifactError):
    """The host lacks the platform primitives needed for this observation."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status=ArtifactStatus.UNSUPPORTED)


class ArtifactScanError(ArtifactError):
    """A path, resource, identity, or read observation could not be trusted."""


_MAX_IDENTIFIER_LENGTH = 512
_MAX_PATH_LENGTH = 4096
_MAX_COMPONENTS = 128
_DEFAULT_MAX_BYTES = 64 * 1024 * 1024
_MAX_ALLOWED_BYTES = 256 * 1024 * 1024
_DIGEST_LENGTH = hashlib.sha256().digest_size * 2


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_IDENTIFIER_LENGTH:
        raise ArtifactScanError(f"{field} must be a bounded non-empty string")
    if value != value.strip() or any(ord(char) < 32 for char in value):
        raise ArtifactScanError(f"{field} is not a canonical identifier")
    return value


def _absolute_path(value: object, field: str) -> str:
    try:
        path = os.fspath(value)
    except TypeError as exc:
        raise ArtifactScanError(f"{field} must be a filesystem path") from exc
    if isinstance(path, bytes):
        raise ArtifactScanError(f"{field} must be text, not bytes")
    if not path or "\x00" in path or len(path) > _MAX_PATH_LENGTH:
        raise ArtifactScanError(f"{field} is empty, oversized, or contains NUL")
    # Relative roots depend on mutable process CWD; a controller must pin the
    # complete canonical workspace path when the attempt is created.
    if not os.path.isabs(path):
        raise ArtifactScanError(f"{field} must be absolute")
    if unicodedata.normalize("NFC", path) != path or any(unicodedata.category(c) == "Cf" for c in path):
        raise ArtifactScanError(f"{field} has ambiguous Unicode components")
    if path.startswith(os.path.sep * 2) or path != os.path.normpath(path):
        raise ArtifactScanError(f"{field} is not a canonical path")
    if path != os.path.sep and path.endswith(os.path.sep):
        raise ArtifactScanError(f"{field} has an ambiguous trailing separator")
    return path


def _relative_parts(value: object) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or len(value) > _MAX_PATH_LENGTH:
        raise ArtifactScanError("relative_path must be a bounded non-empty string")
    if "\x00" in value or value.startswith(("/", "\\")) or "\\" in value:
        raise ArtifactScanError("relative_path must use unambiguous POSIX separators")
    if unicodedata.normalize("NFC", value) != value or any(unicodedata.category(c) == "Cf" for c in value):
        raise ArtifactScanError("relative_path has ambiguous Unicode components")
    parts = tuple(value.split("/"))
    if len(parts) > _MAX_COMPONENTS or any(not part or part in {".", ".."} for part in parts):
        raise ArtifactScanError("relative_path contains an empty, dot, or traversal segment")
    return parts


def _require_posix_primitives() -> None:
    if os.name != "posix":
        raise ArtifactUnsupportedError(
            "UNSUPPORTED/INCOMPLETE: native Windows volume/file-ID and reparse-safe traversal "
            "are not implemented"
        )
    required = ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC", "O_NONBLOCK")
    if (
        any(not hasattr(os, flag) for flag in required)
        or inspect.unwrap(os.open) not in os.supports_dir_fd
        or inspect.unwrap(os.stat) not in os.supports_dir_fd
    ):
        raise ArtifactUnsupportedError("INCOMPLETE: required descriptor-relative POSIX primitives are unavailable")


def _directory_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _file_flags() -> int:
    return os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


def _close(fd: int | None) -> None:
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass


@dataclass(frozen=True, slots=True, kw_only=True)
class RootIdentity:
    """Lexical root path bound to the observed device and directory inode."""

    path: str
    device: int
    inode: int

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not os.path.isabs(self.path) or not self.path:
            raise ArtifactScanError("root.path must be an absolute path")
        if self.path.startswith(os.path.sep * 2) or self.path != os.path.normpath(self.path):
            raise ArtifactScanError("root.path is not canonical")
        for field in ("device", "inode"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ArtifactScanError(f"root.{field} is invalid")


@dataclass(frozen=True, slots=True, kw_only=True)
class ArtifactIdentity:
    """One bounded file observation bound to a request and root identity."""

    relative_path: str
    device: int
    inode: int
    size: int
    sha256: str
    session_id: str
    attempt_id: str
    root: RootIdentity

    def __post_init__(self) -> None:
        parts = _relative_parts(self.relative_path)
        if "/".join(parts) != self.relative_path:
            raise ArtifactScanError("relative_path is not canonical")
        for field in ("device", "inode", "size"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ArtifactScanError(f"artifact.{field} is invalid")
        if not isinstance(self.sha256, str) or len(self.sha256) != _DIGEST_LENGTH or any(
            char not in "0123456789abcdef" for char in self.sha256
        ):
            raise ArtifactScanError("artifact.sha256 must be a lowercase SHA-256 digest")
        _identifier(self.session_id, "session_id")
        _identifier(self.attempt_id, "attempt_id")
        if not isinstance(self.root, RootIdentity):
            raise ArtifactScanError("artifact.root is invalid")

    @property
    def contract_digest(self) -> str:
        """Contract-format digest, NOT a trusted receipt or attestation."""
        return "sha256:" + self.sha256


@dataclass(frozen=True, slots=True)
class _Fingerprint:
    device: int
    inode: int
    mode: int
    nlink: int
    size: int
    mtime_ns: int
    ctime_ns: int
    uid: int | None
    gid: int | None


def _fingerprint(st: os.stat_result) -> _Fingerprint:
    return _Fingerprint(
        device=st.st_dev,
        inode=st.st_ino,
        mode=st.st_mode,
        nlink=st.st_nlink,
        size=st.st_size,
        mtime_ns=st.st_mtime_ns,
        ctime_ns=st.st_ctime_ns,
        uid=getattr(st, "st_uid", None),
        gid=getattr(st, "st_gid", None),
    )


def _open_root(path: str) -> tuple[int, RootIdentity]:
    """Open every root component with no-following descriptor-relative opens."""
    parts = tuple(part for part in path.split(os.path.sep) if part)
    fd: int | None = None
    try:
        fd = os.open(os.path.sep if os.path.isabs(path) else ".", _directory_flags())
        for part in parts:
            if part in {".", ".."}:
                raise ArtifactScanError("root path contains an ambiguous component")
            next_fd = os.open(part, _directory_flags(), dir_fd=fd)
            _close(fd)
            fd = next_fd
        observed = os.fstat(fd)
        if not stat.S_ISDIR(observed.st_mode):
            raise ArtifactScanError("root is not a directory")
        return fd, RootIdentity(path=path, device=observed.st_dev, inode=observed.st_ino)
    except ArtifactError:
        _close(fd)
        raise
    except OSError as exc:
        _close(fd)
        raise ArtifactScanError("root could not be opened safely") from exc


def identify_root(root_path: str | os.PathLike[str]) -> RootIdentity:
    """Return the currently opened root identity, or fail closed."""
    _require_posix_primitives()
    path = _absolute_path(root_path, "root_path")
    fd, identity = _open_root(path)
    _close(fd)
    return identity


def _validate_limit(max_bytes: int) -> None:
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 0 < max_bytes <= _MAX_ALLOWED_BYTES:
        raise ArtifactScanError("max_bytes is outside the bounded observation limit")


def _regular_single_link(st: os.stat_result, *, root_device: int) -> None:
    if not stat.S_ISREG(st.st_mode):
        raise ArtifactScanError("artifact is not a regular file")
    if st.st_nlink != 1:
        raise ArtifactScanError("hard-linked artifacts are unsupported")
    if st.st_dev != root_device:
        raise ArtifactScanError("artifact crosses a device or mount boundary")


def _read_file(fd: int, size: int, max_bytes: int) -> str:
    if size > max_bytes:
        raise ArtifactScanError("artifact exceeds the configured size limit")
    digest = hashlib.sha256()
    remaining = size
    while remaining:
        try:
            chunk = os.read(fd, min(remaining, 1024 * 1024))
        except OSError as exc:
            raise ArtifactScanError("artifact read failed") from exc
        if not chunk:
            raise ArtifactScanError("artifact ended before its observed size")
        digest.update(chunk)
        remaining -= len(chunk)
    try:
        if os.read(fd, 1):
            raise ArtifactScanError("artifact grew while it was being read")
    except OSError as exc:
        raise ArtifactScanError("artifact end-of-file check failed") from exc
    return digest.hexdigest()


def scan_artifact(
    root_path: str | os.PathLike[str],
    relative_path: str,
    *,
    session_id: str,
    attempt_id: str,
    root_identity: RootIdentity | None = None,
    max_bytes: int = _DEFAULT_MAX_BYTES,
) -> ArtifactIdentity:
    """Safely hash one regular, single-link file beneath ``root_path``.

    The returned record is an observation bound to the supplied request and
    root.  It is not a receipt and does not prove a worker, command, or
    external effect succeeded.  A caller should retain the ``RootIdentity``
    from request creation and pass it back here to reject root substitution.
    """
    _require_posix_primitives()
    parts = _relative_parts(relative_path)
    _identifier(session_id, "session_id")
    _identifier(attempt_id, "attempt_id")
    _validate_limit(max_bytes)
    path = _absolute_path(root_path, "root_path")
    root_fd, observed_root = _open_root(path)
    if root_identity is not None and observed_root != root_identity:
        _close(root_fd)
        raise ArtifactScanError("root identity does not match the request binding")
    bound_root = root_identity or observed_root
    parent_fd: int | None = None
    file_fd: int | None = None
    try:
        root_before_fingerprint = _fingerprint(os.fstat(root_fd))
        # Transfer the opened root descriptor to traversal rather than duplicating
        # it. The test HomeIOGuard tracks descriptors from os.open, not os.dup;
        # the kernel-level checks and root re-open below remain unchanged.
        parent_fd = root_fd
        root_fd = None
        for part in parts[:-1]:
            next_fd = os.open(part, _directory_flags(), dir_fd=parent_fd)
            child = os.fstat(next_fd)
            if not stat.S_ISDIR(child.st_mode) or child.st_dev != bound_root.device:
                _close(next_fd)
                raise ArtifactScanError("artifact traversal crosses a non-directory or mount boundary")
            _close(parent_fd)
            parent_fd = next_fd

        leaf = parts[-1]
        try:
            entry_before = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as exc:
            raise ArtifactScanError("artifact path could not be observed") from exc
        _regular_single_link(entry_before, root_device=bound_root.device)
        file_fd = os.open(leaf, _file_flags(), dir_fd=parent_fd)
        before = os.fstat(file_fd)
        _regular_single_link(before, root_device=bound_root.device)
        if _fingerprint(before) != _fingerprint(entry_before):
            raise ArtifactScanError("artifact path changed while it was opened")
        digest = _read_file(file_fd, before.st_size, max_bytes)
        after = os.fstat(file_fd)
        _regular_single_link(after, root_device=bound_root.device)
        if _fingerprint(before) != _fingerprint(after):
            raise ArtifactScanError("artifact inode or metadata changed during the read")
        try:
            entry_after = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as exc:
            raise ArtifactScanError("artifact path was renamed or removed during the read") from exc
        _regular_single_link(entry_after, root_device=bound_root.device)
        if _fingerprint(after) != _fingerprint(entry_after):
            raise ArtifactScanError("artifact path binding changed during the read")
        root_after_fd, root_after = _open_root(path)
        try:
            root_after_fingerprint = _fingerprint(os.fstat(root_after_fd))
        finally:
            _close(root_after_fd)
        if root_after != bound_root or root_before_fingerprint != root_after_fingerprint:
            raise ArtifactScanError("root identity or metadata changed during the read")
        return ArtifactIdentity(
            relative_path="/".join(parts),
            device=after.st_dev,
            inode=after.st_ino,
            size=after.st_size,
            sha256=digest,
            session_id=session_id,
            attempt_id=attempt_id,
            root=bound_root,
        )
    except ArtifactError:
        raise
    except OSError as exc:
        raise ArtifactScanError("artifact traversal or observation failed") from exc
    finally:
        _close(file_fd)
        _close(parent_fd)
        _close(root_fd)
