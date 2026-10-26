# Stage 1 direction superseded on 2026-10-26

**Current owner decision: DEC-004.** Start with a full fork of ReMe at
https://github.com/fredheathcote007/fermes-reme using the existing embedded Hermes
provider. First qualify standalone local ReMe memory with its current file-based
store and BM25, then fix only reproduced operational/security failures. SQLite
ledger wiring and additional/revised vector infrastructure are deferred until
the plugin works and has an evidence-backed gap. The following plan documents
the pre-decision SQLite prototype and remains historical evidence for PR #19;
it is **not** the active Stage 1 delivery plan.

---

# FHM-007 — Memory v2 implementation plan

project_id: fermes-hermes
issue: FHM-007 / GitHub #7
status: Proposed — no acceptance or approval declared

## Stage 0 — architecture gate

Owner/ARB reviews `ARCHITECTURE-AND-GAPS.md`, especially the profile/agent authorization model,
governed write policy, FHM-006 checkpoint contract, PII/retention rules, and whether a profile-local
multi-agent file is acceptable. No runtime integration starts until these decisions are recorded as
approved decisions.

Exit evidence: approved decision IDs, threat-model review, and a test matrix covering profile,
agent, session, background-review, backup, restore, and crash/restart boundaries.

## Stage 1 — isolated ledger foundation (this workstream)

Implemented only in the isolated branch:

1. Add `agent/memory_v2_store.py` using stdlib `sqlite3` and FTS5 only.
2. Require an explicit absolute profile home and safe agent ID; reject traversal/symlinks and validate
   a persisted owner/schema marker.
3. Store typed records with bounded confidence, raw source ID/hash/quotation, metadata, and immutable
   revisions. Add explicit supersession and contradiction/support/derivation edges.
4. Use WAL, `synchronous=FULL`, busy timeout, serialized `BEGIN IMMEDIATE` writes, same-transaction
   FTS indexing, compare-and-set revisions, restart durability, integrity checks, and atomic SQLite
   backup/restore for the original profile.
5. Add deterministic tests for restart/provenance, profile and agent isolation, dedupe, stale revision
   refusal, supersession, contradiction, FTS recall, concurrent writers, corruption/ownership refusal,
   and backup roundtrip.

Non-goals: no provider/tool registration, no `state.db` schema changes, no prompt changes, no
embeddings, no LLM calls, no automatic consolidation/forgetting, and no production deployment.

Exit evidence: focused tests, ruff, compileall, diff check, source SHA, and explicit failures.

## Stage 2 — policy and adapter seam

After Stage 0 approval, define a narrow adapter behind the existing `MemoryProvider`/`MemoryManager`
seam. The adapter must:

- bind to the caller's profile scope and agent identity at initialization;
- use `write_approval` before all durable mutations, including background review;
- redact egress before converting session/transcript evidence into a candidate;
- return fenced, bounded, provenance-bearing context and a deterministic recall indicator;
- avoid rebuilding the system prompt or tool surface mid-conversation;
- fail closed on owner mismatch, stale revision, FTS corruption, missing checkpoint, or ambiguous
  agent identity;
- keep v2 failure non-blocking for the user's current answer where the operation is an optional side
  effect, while reporting the durable write failure to logs/status.

Tests: real imports against temporary `HERMES_HOME`, two profiles in one process, two agents in one
profile, background-review origin, approval staging, prompt byte stability, bounded recall, and
restart during a write.

## Stage 3 — session and compaction integration

Integrate source references to `state.db`/`session_search` without copying unbounded transcripts.
Define the FHM-006 checkpoint handoff and version fence first. A compaction path may not discard
evidence until a compatible checkpoint is durably acknowledged. Verify native compaction suppression,
local compression, restart recovery, lineage, and session-search hydration against the existing
contracts. Keep transcript authority in `state.db`.

## Stage 4 — governed extraction and learning interfaces

FHM-008 consumes completed-turn/session evidence and emits reviewable procedural/lesson candidates.
FHM-009 consumes immutable failure/lesson records and emits optimisation hypotheses. Both interfaces
must carry provenance, confidence, source hash, model/runtime identity where relevant, and evaluation
links. They may stage pending writes, but cannot silently promote model output to trusted memory or
skills. FHM-010 supplies the qualification corpus and regression gates.

## Stage 5 — retrieval improvements and optional graph

Measure FTS5 lexical recall first. Only if a corpus-backed gap is demonstrated, evaluate an entirely
local embedding provider with optional dependencies, deterministic model/version metadata, rebuild
and fallback behavior, and licence/platform review. Evaluate graph storage only after typed edges
prove insufficient; keep graph optional and never required for core recall or restore.

## Stage 6 — operations

Add profile-aware backup manifests, restore dry-run/verification, retention/PII reports, explicit
forget/retract workflows, FTS rebuild/repair, metrics without outbound telemetry, and forensic export.
Exercise crash consistency, disk-full/permission errors, WAL sidecars, concurrent profiles, backup
while writing, and downgrade/upgrade schema paths. Document unsupported network-filesystem homes.

## Verification ledger for this branch

| Check | Result | Notes |
|---|---|---|
| Source baseline | `e0bb2a8201d9ae43c04cd8f1e8da044c02c2d181` | v0.22.5-derived isolated worktree |
| `scripts/run_tests.sh tests/agent/test_memory_v2_store.py` | BLOCKED | Repository environment bootstrap attempted uv cache/network writes unavailable in managed sandbox; no false PASS claim |
| Fallback focused pytest | PASS: 6 tests | `python3 -m pytest --confcutdir=tests/agent -q tests/agent/test_memory_v2_store.py`; bypassed root conftest because the available interpreter lacks `ruamel` |
| Ruff | PASS | `ruff check` and `ruff format --check` on the new module/test |
| Compileall | PASS | `python3 -m compileall -q agent/memory_v2_store.py tests/agent/test_memory_v2_store.py` |
| `git diff --check` | PASS | Final worktree diff has no whitespace errors |
