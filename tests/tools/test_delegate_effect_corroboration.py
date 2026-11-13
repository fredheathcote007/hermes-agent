"""Behavioral contracts for bounded post-effect delegation readback."""

import hashlib
import json
import subprocess
import pytest

from tools.delegate_tool_child_run import _SchemaOutcome, _build_result_entry
from tools.file_operations_common import WriteResult
from tools.delegate_effect_corroboration import _task_backend as _actual_task_backend
from tools import delegate_effect_corroboration as observer


@pytest.fixture(autouse=True)
def _live_local_backend(monkeypatch):
    # Pure-contract tests explicitly model a live local task environment.
    monkeypatch.setattr("tools.delegate_effect_corroboration._task_backend", lambda _task_id: "local")


def _child():
    from types import SimpleNamespace

    return SimpleNamespace(
        model="child-model",
        session_estimated_cost_usd=0.0,
        session_cost_status="unknown",
        session_prompt_tokens=0,
        session_completion_tokens=0,
        _delegate_role="leaf",
        _current_task_id="child-task",
    )


def _parent(mode="advisory"):
    from types import SimpleNamespace

    return SimpleNamespace(_verification_mode=mode, _turn_file_mutation_paths=set())


def _write_result(path, content, *, completed=True, tool_result=None, call_id="write-1"):
    call = {
        "id": call_id,
        "function": {
            "name": "write_file",
            "arguments": json.dumps({"path": str(path), "content": content}),
        },
    }
    return {
        "final_response": "Wrote the file.",
        "completed": completed,
        "messages": [
            {"role": "assistant", "content": "", "tool_calls": [call]},
            {"role": "tool", "tool_call_id": call_id,
             "content": tool_result or json.dumps({
                 **WriteResult(bytes_written=len(content.encode("utf-8")), verified=True).to_dict(),
                 "resolved_path": str(path), "files_modified": [str(path)],
             })},
        ],
    }


def _entry(child, result, *, parent=None):
    child._delegate_verification_owner = parent
    return _build_result_entry(child, result, 0, 0.1, _SchemaOutcome(None, None, [], 0))


def test_matching_write_file_readback_is_observed_but_not_verified(tmp_path):
    target = tmp_path / "note.txt"
    target.write_text("fresh bytes", encoding="utf-8")
    child = _child()
    child._turn_file_mutation_paths = {str(target)}

    entry = _entry(child, _write_result(target, "fresh bytes"), parent=_parent())

    assert entry["verification_status"] == "unverified"
    assert entry["effect_observation"] == {
        "status": "observed",
        "kind": "file_write",
        "path": str(target),
        "sha256": hashlib.sha256(b"fresh bytes").hexdigest(),
    }


def _windows_path_variant(path):
    rendered = str(path).replace("\\", "/")
    for index, char in enumerate(rendered):
        if char.isalpha():
            toggled = char.swapcase()
            return rendered[:index] + toggled + rendered[index + 1:]
    pytest.fail("temporary path did not contain an alphabetic component")


@pytest.mark.platforms("windows")
def test_windows_path_style_variants_match_allowed_paths_and_result_metadata(tmp_path):
    target = tmp_path / "note.txt"
    target.write_text("fresh bytes", encoding="utf-8")
    rendered = _windows_path_variant(target)
    result = _write_result(target, "fresh bytes")
    result["messages"][1]["content"] = json.dumps({
        **WriteResult(bytes_written=len(b"fresh bytes"), verified=True).to_dict(),
        "resolved_path": rendered,
        "files_modified": [rendered],
    })
    child = _child()
    child._turn_file_mutation_paths = {rendered}

    entry = _entry(child, result, parent=_parent())

    assert entry["effect_observation"]["kind"] == "file_write"


@pytest.mark.platforms("windows")
def test_windows_path_style_variant_still_rejects_wrong_result_path(tmp_path):
    target = tmp_path / "note.txt"
    wrong = tmp_path / "other.txt"
    target.write_text("fresh bytes", encoding="utf-8")
    result = _write_result(target, "fresh bytes")
    result["messages"][1]["content"] = json.dumps({
        **WriteResult(bytes_written=len(b"fresh bytes"), verified=True).to_dict(),
        "resolved_path": _windows_path_variant(wrong),
    })
    child = _child()
    child._turn_file_mutation_paths = {_windows_path_variant(target)}

    entry = _entry(child, result, parent=_parent())

    assert "effect_observation" not in entry


@pytest.mark.platforms("posix")
def test_posix_path_comparison_remains_case_sensitive(tmp_path):
    target = tmp_path / "note.txt"
    target.write_text("fresh bytes", encoding="utf-8")
    result = _write_result(target, "fresh bytes")
    result["messages"][1]["content"] = json.dumps({
        **WriteResult(bytes_written=len(b"fresh bytes"), verified=True).to_dict(),
        "resolved_path": str(target).swapcase(),
    })
    child = _child()
    child._turn_file_mutation_paths = {str(target)}

    entry = _entry(child, result, parent=_parent())

    assert "effect_observation" not in entry


def test_file_readback_abstains_for_mismatch_missing_wrong_path_and_malformed_args(tmp_path):
    target = tmp_path / "note.txt"
    target.write_text("different", encoding="utf-8")
    cases = [
        _write_result(target, "expected"),
        _write_result(tmp_path / "missing.txt", "expected"),
        {
            **_write_result(target, "expected"),
            "messages": [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"function": {"name": "write_file", "arguments": "{"}}],
                }
            ],
        },
    ]

    for result in cases:
        child = _child()
        child._turn_file_mutation_paths = {str(target)}
        entry = _entry(child, result, parent=_parent())
        assert entry["verification_status"] == "unverified"
        assert "effect_observation" not in entry


@pytest.mark.platforms("posix")
def test_symlink_and_unreadable_or_foreign_paths_are_not_observed(tmp_path, monkeypatch):
    target = tmp_path / "note.txt"
    target.write_text("expected", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    child = _child()
    child._turn_file_mutation_paths = {str(link)}

    entry = _entry(child, _write_result(link, "expected"), parent=_parent())

    assert entry["verification_status"] == "unverified"
    assert "effect_observation" not in entry


def test_opaque_terminal_effect_stays_unverified(tmp_path):
    child = _child()
    child._turn_file_mutation_paths = {str(tmp_path / "created.txt")}
    result = {
        "final_response": "Done.",
        "completed": True,
        "messages": [
            {"role": "assistant", "content": "", "tool_calls": [{
                "id": "terminal-1",
                "function": {"name": "terminal", "arguments": '{"command":"touch created.txt"}'},
            }]},
            {"role": "tool", "tool_call_id": "terminal-1", "content": "exit code 0"},
        ],
    }

    entry = _entry(child, result, parent=_parent())

    assert entry["verification_status"] == "unverified"
    assert "effect_observation" not in entry


def test_git_observation_requires_parent_intent_and_exact_head_tree(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "tracked.txt").write_text("one", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "tracked.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-q", "-m", "init"],
        check=True,
    )
    head = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()
    tree = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD^{tree}"], text=True).strip()
    child = _child()
    parent = _parent()
    parent._delegate_verification_intent = {
        "kind": "git",
        "cwd": str(tmp_path),
        "expected_head": head,
        "expected_tree": tree,
        "paths": ["tracked.txt"],
    }
    child._turn_file_mutation_paths = set()
    result = {"final_response": "Committed.", "completed": True, "messages": []}

    entry = _entry(child, result, parent=parent)

    assert entry["verification_status"] == "unverified"
    assert entry["effect_observation"]["status"] == "observed"
    assert entry["effect_observation"]["kind"] == "git"


def test_git_wrong_ref_or_subprocess_failure_stays_unverified(tmp_path, monkeypatch):
    child = _child()
    parent = _parent()
    parent._delegate_verification_intent = {
        "kind": "git", "cwd": str(tmp_path), "expected_head": "0" * 40,
        "expected_tree": "1" * 40, "paths": [],
    }
    child._turn_file_mutation_paths = set()
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("no git")))

    entry = _entry(child, {"final_response": "Done.", "completed": True, "messages": []}, parent=parent)

    assert entry["verification_status"] == "unverified"
    assert "effect_observation" not in entry


@pytest.mark.parametrize("mode", ["off", "strict"])
def test_legacy_modes_do_not_read_back_or_expose_observation(tmp_path, monkeypatch, mode):
    target = tmp_path / "note.txt"
    target.write_text("fresh bytes", encoding="utf-8")
    child = _child()
    child._turn_file_mutation_paths = {str(target)}
    parent = _parent(mode)

    def fail_readback(*args, **kwargs):
        raise AssertionError("legacy mode performed advisory readback")

    monkeypatch.setattr("tools.delegate_effect_corroboration._safe_local_bytes", fail_readback)
    entry = _entry(child, _write_result(target, "fresh bytes"), parent=parent)

    assert entry["verification_status"] == "unverified"
    assert "effect_observation" not in entry


@pytest.mark.parametrize("tool_result", [
    None,
    '{"bytes_written": 11, "success": false, "resolved_path": "{path}"}',
    '{"bytes_written": 11, "resolved_path": "{other}"}',
])
def test_write_requires_one_matching_successful_result(tmp_path, tool_result):
    target = tmp_path / "note.txt"
    target.write_text("fresh bytes", encoding="utf-8")
    rendered = (tool_result.replace("{path}", str(target)).replace("{other}", str(tmp_path / "other.txt"))
                if tool_result is not None else None)
    child = _child()
    child._turn_file_mutation_paths = {str(target)}
    result = _write_result(target, "fresh bytes", tool_result=rendered)
    if tool_result is None:
        result["messages"] = result["messages"][:1]  # No matching tool execution.
    entry = _entry(child, result, parent=_parent())
    assert "effect_observation" not in entry


def test_failed_completion_and_unmatched_result_never_observe(tmp_path):
    target = tmp_path / "note.txt"
    target.write_text("fresh bytes", encoding="utf-8")
    child = _child()
    child._turn_file_mutation_paths = {str(target)}
    result = _write_result(target, "fresh bytes", completed=False)
    result["failed"] = True
    result["messages"][1]["tool_call_id"] = "foreign"
    entry = _entry(child, result, parent=_parent())
    assert "effect_observation" not in entry


def test_remote_backend_with_host_collision_abstains(tmp_path, monkeypatch):
    target = tmp_path / "remote.txt"
    target.write_text("fresh bytes", encoding="utf-8")
    monkeypatch.setattr("tools.delegate_effect_corroboration._task_backend", lambda task_id: "ssh")
    child = _child()
    child._current_task_id = "child-task"
    child._turn_file_mutation_paths = {str(target)}
    entry = _entry(child, _write_result(target, "fresh bytes"), parent=_parent())
    assert "effect_observation" not in entry


@pytest.mark.platforms("posix")
def test_symlinked_ancestor_abstains(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    target = real / "note.txt"
    target.write_text("fresh bytes", encoding="utf-8")
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    child = _child()
    child._turn_file_mutation_paths = {str(alias / "note.txt")}
    entry = _entry(child, _write_result(alias / "note.txt", "fresh bytes"), parent=_parent())
    assert "effect_observation" not in entry


def test_git_requires_named_paths_in_head_change_set(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "tracked.txt").write_text("one", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "tracked.txt"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-q", "-m", "init"], check=True)
    head = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()
    tree = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD^{tree}"], text=True).strip()
    parent = _parent()
    parent._delegate_verification_intent = {"kind": "git", "cwd": str(tmp_path), "expected_head": head,
                                            "expected_tree": tree, "paths": [":(exclude)tracked.txt"]}
    entry = _entry(_child(), {"final_response": "Committed.", "completed": True, "messages": []}, parent=parent)
    assert "effect_observation" not in entry


def test_absent_live_task_environment_cannot_prove_locality(tmp_path, monkeypatch):
    from tools import delegate_effect_corroboration as observer

    target = tmp_path / "note.txt"
    target.write_text("fresh bytes", encoding="utf-8")
    monkeypatch.setattr("tools.terminal_tool_lifecycle.get_active_env", lambda _task_id: None)
    assert _actual_task_backend("child-task") is None  # Config fallback is not task provenance.
    monkeypatch.setattr(observer, "_task_backend", lambda _task_id: None)

    child = _child()
    child._turn_file_mutation_paths = {str(target)}
    entry = _entry(child, _write_result(target, "fresh bytes"), parent=_parent())
    assert "effect_observation" not in entry


@pytest.mark.platforms("posix")
def test_symlinked_ancestor_rejected_even_with_canonical_telemetry(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    target = real / "note.txt"
    target.write_text("fresh bytes", encoding="utf-8")
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)

    child = _child()
    child._turn_file_mutation_paths = {str(target)}  # Production telemetry may canonicalise.
    result = _write_result(alias / "note.txt", "fresh bytes")
    result["messages"][1]["content"] = json.dumps({
        **WriteResult(bytes_written=len(b"fresh bytes"), verified=True).to_dict(),
        "resolved_path": str(target), "files_modified": [str(target)],
    })
    entry = _entry(child, result, parent=_parent())
    assert "effect_observation" not in entry


@pytest.mark.parametrize("sibling", [
    {"function": {"name": "terminal", "arguments": "{}"}},  # No call ID.
    {"id": "write-1", "function": {"name": "terminal", "arguments": "{}"}},  # Duplicate ID.
])
def test_unknown_or_duplicate_sibling_call_abstains(tmp_path, sibling):
    target = tmp_path / "note.txt"
    target.write_text("fresh bytes", encoding="utf-8")
    child = _child()
    child._turn_file_mutation_paths = {str(target)}
    result = _write_result(target, "fresh bytes")
    result["messages"][0]["tool_calls"].append(sibling)
    entry = _entry(child, result, parent=_parent())
    assert "effect_observation" not in entry


def test_matching_parent_git_intent_cannot_corroborate_failed_child(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "tracked.txt").write_text("one", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "tracked.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.name=Test", "-c",
         "user.email=test@example.invalid", "commit", "-q", "-m", "init"], check=True,
    )
    head = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()
    tree = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD^{tree}"], text=True).strip()
    parent = _parent()
    parent._delegate_verification_intent = {
        "kind": "git", "cwd": str(tmp_path), "expected_head": head,
        "expected_tree": tree, "paths": ["tracked.txt"],
    }
    child = _child()
    child._turn_file_mutation_paths = set()
    entry = _entry(child, {"final_response": "Done", "completed": True,
                           "failed": True, "messages": []}, parent=parent)
    assert entry.get("verification_status") == "unverified"
    assert "effect_observation" not in entry


def test_git_invalid_nul_path_bytes_abstain_without_crashing(tmp_path, monkeypatch):
    head = "a" * 40
    tree = "b" * 40

    def fake_git_run(_cwd, args):
        if args[0] == "rev-parse" and args[2] == "HEAD":
            stdout = f"{head}\n".encode()
        elif args[0] == "rev-parse":
            stdout = f"{tree}\n".encode()
        else:
            stdout = b"tracked.txt\0foreign/\xff.txt\0"
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(observer, "_git_run", fake_git_run)
    intent = {
        "kind": "git", "cwd": str(tmp_path), "expected_head": head,
        "expected_tree": tree, "paths": ["tracked.txt"],
    }

    assert observer._git_observation(intent) is None


@pytest.mark.parametrize("write_fields", [
    {"bytes_written": len(b"fresh bytes"), "error": "write failed"},
    {"bytes_written": len(b"fresh bytes") + 1},
    {"bytes_written": "11"},
    {"bytes_written": len(b"fresh bytes"), "verified": False},
    {"bytes_written": len(b"fresh bytes"), "resolved_path": 123},
])
def test_file_observation_rejects_error_or_inconsistent_write_result(tmp_path, write_fields):
    target = tmp_path / "note.txt"
    target.write_text("fresh bytes", encoding="utf-8")
    result_body = {
        "resolved_path": str(target), "files_modified": [str(target)], **write_fields,
    }
    child = _child()
    child._turn_file_mutation_paths = {str(target)}
    entry = _entry(child, _write_result(target, "fresh bytes",
                                        tool_result=json.dumps(result_body)), parent=_parent())
    assert entry.get("verification_status") == "unverified"
    assert "effect_observation" not in entry
