"""FHM-004: exercise real owned process groups without touching Hermes services."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import signal
import sys

import pytest

from hermes_cli.fermes_reliability.supervise_chat import _terminate_process_tree

pytestmark = pytest.mark.platforms("linux")


def _still_running(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split(") ", 1)[1].split()[0]
    except FileNotFoundError:
        return False
    return state not in {"Z", "X", "x"}


@pytest.mark.skipif(os.name != "posix" or not Path("/proc").is_dir(), reason="Linux /proc test only")
@pytest.mark.asyncio
async def test_bounded_stop_reaps_owned_group_and_ignoring_child():
    # Both processes belong to a fresh private session/group created below.
    parent_code = (
        "import subprocess,sys,time;"
        "p=subprocess.Popen([sys.executable,'-c',"
        "'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)']);"
        "print(p.pid,flush=True);time.sleep(60)"
    )
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", parent_code,
        start_new_session=True, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    child_pid = None
    try:
        assert proc.stdout is not None
        raw_pid = await asyncio.wait_for(proc.stdout.readline(), 5)
        child_pid = int(raw_pid.decode().strip())
        assert child_pid > 0
        assert os.getpgid(child_pid) == proc.pid
        await asyncio.wait_for(_terminate_process_tree(proc, timeout=0.3), 5)
        assert proc.returncode is not None
        # A transient un-reaped zombie has no running code and is allowed.
        for _ in range(30):
            if not _still_running(child_pid):
                break
            await asyncio.sleep(0.05)
        assert not _still_running(child_pid), "owned child survived bounded stop"
    finally:
        # Only our unique fresh process group may ever be signalled here.
        try:
            if os.getpgid(proc.pid) == proc.pid:
                os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if proc.returncode is None:
            await asyncio.wait_for(proc.wait(), 5)


@pytest.mark.skipif(os.name != "posix", reason="process-group safety check is POSIX only")
@pytest.mark.asyncio
async def test_shared_group_must_not_receive_any_group_signal():
    """Never signal the parent's group if a child did not isolate itself."""
    from unittest.mock import patch
    from hermes_cli.fermes_reliability import supervise_chat

    class SharedGroupProcess:
        pid = 987654321
        returncode = None
        terminated = False

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def kill(self):
            self.returncode = -9

        async def wait(self):
            return self.returncode

    proc = SharedGroupProcess()
    caller_pgid = os.getpgrp()
    with patch.object(supervise_chat.os, "getpgid", return_value=caller_pgid), \
            patch.object(supervise_chat.os, "killpg") as killpg:
        try:
            await asyncio.wait_for(
                supervise_chat._terminate_process_tree(proc, timeout=0.05), 2
            )
        except supervise_chat.SupervisionBlocked:
            pass  # Appropriate fail-closed outcome when descendants cannot be proven gone.
        killpg.assert_not_called()
    assert proc.terminated or proc.returncode is not None

@pytest.mark.skipif(os.name != "posix", reason="process-group safety check is POSIX only")
@pytest.mark.asyncio
async def test_leaderless_group_refuses_group_signal():
    from unittest.mock import patch
    from hermes_cli.fermes_reliability import supervise_chat

    class Process:
        pid = 987654321
        returncode = -15

        async def wait(self):
            return self.returncode

    # Group lives, but the leader is gone: group identity cannot be proven.
    with patch.object(supervise_chat.os, "getpgid", side_effect=ProcessLookupError), \
            patch.object(supervise_chat.os, "killpg", return_value=None) as killpg:
        with pytest.raises(supervise_chat.SupervisionBlocked, match="leader identity"):
            await supervise_chat._terminate_process_tree(Process(), 0.05)
        assert killpg.call_count == 1
        assert killpg.call_args.args == (987654321, 0)
