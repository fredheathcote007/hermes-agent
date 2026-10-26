"""CLI handlers for opt-in supervised execution and observation-only recovery."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


def cmd_supervise(args) -> int:
    if sys.platform != "linux":
        print("Hermes supervised execution currently supports Linux only; no chat was launched.",
              file=sys.stderr)
        return 125
    from hermes_cli.fermes_reliability.supervise_chat import supervise_chat
    try:
        if args.query_file == "-":
            if sys.stdin.isatty():
                raise ValueError("--query-file - requires finite non-interactive stdin")
            prompt_bytes = sys.stdin.buffer.read(1_000_001)
        else:
            with open(args.query_file, "rb") as source:
                prompt_bytes = source.read(1_000_001)
        if len(prompt_bytes) > 1_000_000:
            raise ValueError("prompt exceeds the 1 MB supervisor input limit")
        prompt = prompt_bytes.decode("utf-8")
        return asyncio.run(supervise_chat(
            prompt, deadline=args.deadline,
            settlement_timeout=args.settlement_timeout, executable=args.hermes,
            workspace_parent=args.workspace_parent, checkpoint_path=args.checkpoint))
    except Exception as exc:
        print(f"Supervisor blocked ({type(exc).__name__}); inspect the checkpoint and do not replay.",
              file=sys.stderr)
        return 125


def cmd_recover(args) -> int:
    if sys.platform != "linux":
        print("Hermes supervised recovery currently supports Linux only; checkpoint is unchanged.",
              file=sys.stderr)
        return 125
    from hermes_cli.fermes_reliability.recover_attempt import recover
    try:
        result = asyncio.run(recover(Path(args.checkpoint)))
    except Exception as exc:
        result = {"state": "BLOCKED", "next_action":
                  f"recovery failed ({type(exc).__name__}); inspect gateway and workspace; do not replay"}
    print(json.dumps(result, sort_keys=True))
    # Running is an unresolved attempt, never an automation success.
    return 0 if result.get("state") == "TERMINAL" else 125


def cmd_recover_orphans(args) -> int:
    if sys.platform != "linux":
        print("Hermes orphan scanning currently supports Linux only; no checkpoint was changed.",
              file=sys.stderr)
        return 125
    from hermes_cli.fermes_reliability.recover_orphans import scan
    try:
        result = asyncio.run(scan(Path(args.workspace_parent), limit=args.limit, observe=args.observe,
                                  report_path=Path(args.report) if args.report else None))
    except Exception as exc:
        result = {"attention_required": True, "outcome": "error",
                  "reason": f"scan refused ({type(exc).__name__})"}
    print(json.dumps(result, sort_keys=True))
    return 1 if result.get("attention_required") else 0
