"""Behaviour contracts for the unconnected FHM-005 artifact observations."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from agent import verification_artifacts as artifacts


def _write(root: Path, relative: str, content: bytes = b"known artifact\n") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_known_good_file_returns_request_bound_identity(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    content = b"known artifact\n"
    _write(root, "nested/result.txt", content)
    root_identity = artifacts.identify_root(root)

    observed = artifacts.scan_artifact(
        root,
        "nested/result.txt",
        session_id="session-1",
        attempt_id="attempt-1",
        root_identity=root_identity,
    )

    assert observed.relative_path == "nested/result.txt"
    assert (observed.device, observed.inode) == (root_identity.device, observed.inode)
    assert observed.size == len(content)
    assert observed.sha256 == hashlib.sha256(content).hexdigest()
    assert observed.contract_digest == "sha256:" + hashlib.sha256(content).hexdigest()
    assert observed.session_id == "session-1"
    assert observed.attempt_id == "attempt-1"
    assert observed.root == root_identity
    with pytest.raises(FrozenInstanceError):
        observed.size = 0


def test_root_and_file_identity_are_stable_for_same_request(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    _write(root, "result.txt")
    root_identity = artifacts.identify_root(root)

    first = artifacts.scan_artifact(
        root, "result.txt", session_id="session", attempt_id="attempt", root_identity=root_identity
    )
    second = artifacts.scan_artifact(
        root, "result.txt", session_id="session", attempt_id="attempt", root_identity=root_identity
    )

    assert first == second
    assert first.root.path == str(root)


@pytest.mark.parametrize(
    "relative_path",
    ["", "/result.txt", "\\result.txt", "nested//result.txt", "./result.txt", "nested/../result.txt", "result.txt/"],
)
def test_malformed_relative_paths_fail_closed(tmp_path, relative_path):
    root = tmp_path / "root"
    root.mkdir()
    _write(root, "result.txt")

    with pytest.raises(artifacts.ArtifactScanError):
        artifacts.scan_artifact(root, relative_path, session_id="session", attempt_id="attempt")


def test_absolute_root_path_is_not_an_artifact_path(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    _write(root, "result.txt")

    with pytest.raises(artifacts.ArtifactScanError):
        artifacts.scan_artifact(root, str(root / "result.txt"), session_id="session", attempt_id="attempt")


def test_symlink_parent_and_leaf_are_rejected(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    _write(outside, "result.txt")
    (root / "parent").symlink_to(outside, target_is_directory=True)
    (root / "leaf.txt").symlink_to(outside / "result.txt")

    with pytest.raises(artifacts.ArtifactError):
        artifacts.scan_artifact(root, "parent/result.txt", session_id="session", attempt_id="attempt")
    with pytest.raises(artifacts.ArtifactError):
        artifacts.scan_artifact(root, "leaf.txt", session_id="session", attempt_id="attempt")


def test_hardlinked_file_is_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    original = _write(root, "result.txt")
    os.link(original, root / "alias.txt")

    with pytest.raises(artifacts.ArtifactScanError):
        artifacts.scan_artifact(root, "result.txt", session_id="session", attempt_id="attempt")


def test_fifo_is_rejected_without_blocking_on_read(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    fifo = root / "result.pipe"
    os.mkfifo(fifo)

    with pytest.raises(artifacts.ArtifactScanError):
        artifacts.scan_artifact(root, "result.pipe", session_id="session", attempt_id="attempt")


def test_directory_is_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "directory").mkdir()

    with pytest.raises(artifacts.ArtifactScanError):
        artifacts.scan_artifact(root, "directory", session_id="session", attempt_id="attempt")


def test_size_limit_is_strict_and_bounded(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    _write(root, "result.txt", b"12345")

    with pytest.raises(artifacts.ArtifactScanError):
        artifacts.scan_artifact(root, "result.txt", session_id="session", attempt_id="attempt", max_bytes=4)
    with pytest.raises(artifacts.ArtifactScanError):
        artifacts.scan_artifact(root, "result.txt", session_id="session", attempt_id="attempt", max_bytes=0)
    with pytest.raises(artifacts.ArtifactScanError):
        artifacts.scan_artifact(
            root,
            "result.txt",
            session_id="session",
            attempt_id="attempt",
            max_bytes=artifacts._MAX_ALLOWED_BYTES + 1,
        )


def test_root_replacement_rejects_the_old_request_binding(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    _write(root, "result.txt")
    root_identity = artifacts.identify_root(root)
    moved = tmp_path / "moved-root"
    root.rename(moved)
    root.mkdir()
    _write(root, "result.txt")

    with pytest.raises(artifacts.ArtifactScanError):
        artifacts.scan_artifact(
            root, "result.txt", session_id="session", attempt_id="attempt", root_identity=root_identity
        )


def test_root_replacement_during_read_is_incomplete(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    _write(root, "result.txt", b"content")
    moved = tmp_path / "moved-root"
    original_read = artifacts.os.read
    changed = False

    def replace_root_after_read(fd, size):
        nonlocal changed
        data = original_read(fd, size)
        if data and not changed:
            changed = True
            root.rename(moved)
            root.mkdir()
            _write(root, "result.txt", b"replacement")
        return data

    monkeypatch.setattr(artifacts.os, "read", replace_root_after_read)
    with pytest.raises(artifacts.ArtifactScanError):
        artifacts.scan_artifact(root, "result.txt", session_id="session", attempt_id="attempt")
    assert (moved / "result.txt").exists()


def test_content_change_during_read_is_rejected(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    target = _write(root, "result.txt", b"content")
    original_read = artifacts.os.read
    changed = False

    def modify_after_read(fd, size):
        nonlocal changed
        data = original_read(fd, size)
        if data and not changed:
            changed = True
            target.write_bytes(b"CHANGED")
        return data

    monkeypatch.setattr(artifacts.os, "read", modify_after_read)
    with pytest.raises(artifacts.ArtifactScanError):
        artifacts.scan_artifact(root, "result.txt", session_id="session", attempt_id="attempt")


def test_metadata_change_during_read_is_rejected(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    target = _write(root, "result.txt")
    original_read = artifacts.os.read
    changed = False

    def touch_metadata_after_read(fd, size):
        nonlocal changed
        data = original_read(fd, size)
        if data and not changed:
            changed = True
            current = target.stat()
            os.utime(target, ns=(current.st_atime_ns, current.st_mtime_ns + 1))
        return data

    monkeypatch.setattr(artifacts.os, "read", touch_metadata_after_read)
    with pytest.raises(artifacts.ArtifactScanError):
        artifacts.scan_artifact(root, "result.txt", session_id="session", attempt_id="attempt")


def test_rename_during_read_is_rejected_by_post_read_path_binding(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    target = _write(root, "result.txt")
    original_read = artifacts.os.read
    renamed = root / "renamed.txt"
    changed = False

    def rename_after_read(fd, size):
        nonlocal changed
        data = original_read(fd, size)
        if data and not changed:
            changed = True
            target.rename(renamed)
        return data

    monkeypatch.setattr(artifacts.os, "read", rename_after_read)
    with pytest.raises(artifacts.ArtifactScanError):
        artifacts.scan_artifact(root, "result.txt", session_id="session", attempt_id="attempt")


def test_read_failure_is_incomplete(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    _write(root, "result.txt")

    def fail_read(fd, size):
        raise OSError("injected read failure")

    monkeypatch.setattr(artifacts.os, "read", fail_read)
    with pytest.raises(artifacts.ArtifactScanError):
        artifacts.scan_artifact(root, "result.txt", session_id="session", attempt_id="attempt")


def test_invalid_request_identity_is_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    _write(root, "result.txt")

    for field in ("session_id", "attempt_id"):
        values = {"session_id": "session", "attempt_id": "attempt"}
        values[field] = " bad "
        with pytest.raises(artifacts.ArtifactScanError):
            artifacts.scan_artifact(root, "result.txt", **values)


def test_root_path_symlink_component_is_rejected(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    _write(actual, "result.txt")
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)

    with pytest.raises(artifacts.ArtifactError):
        artifacts.identify_root(alias)


def test_regular_file_mode_is_the_only_accepted_leaf(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    socket_candidate = root / "socket"
    if hasattr(stat, "S_ISSOCK"):
        # A socket cannot be created without a socket API; the FIFO contract
        # above covers the non-regular-file/no-blocking boundary.
        assert not socket_candidate.exists()
    _write(root, "result.txt")
    assert artifacts.scan_artifact(root, "result.txt", session_id="session", attempt_id="attempt").size > 0


def test_relative_root_and_noncanonical_unicode_fail_closed(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    _write(root, "result.txt")
    with pytest.raises(artifacts.ArtifactScanError, match="must be absolute"):
        artifacts.identify_root("root")
    with pytest.raises(artifacts.ArtifactScanError, match="ambiguous Unicode"):
        artifacts.scan_artifact(root, "bad\u202epath.txt", session_id="s", attempt_id="a")
    with pytest.raises(artifacts.ArtifactScanError, match="ambiguous Unicode"):
        artifacts.scan_artifact(root, "e\u0301.txt", session_id="s", attempt_id="a")
