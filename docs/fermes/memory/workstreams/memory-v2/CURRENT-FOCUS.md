# Current Focus

project_id: fermes-hermes
issue: FHM-007 / GitHub #7
workstream_id: memory-v2
status: External source audit completed; isolated ledger prototype tested; runtime design remains proposed
branch: fermes/memory-v2-fhm007-20261026
source_baseline_sha: e0bb2a8201d9ae43c04cd8f1e8da044c02c2d181
updated: 2026-10-26 Australia/Perth

## Evidence and outcome

- Passed canonical identity gate and read established Fermes decisions and constraints before work.
- Inspected Hermes v0.22.5 interfaces: native Markdown memory, MemoryProvider/MemoryManager, profile scoping, approval, background-review, compaction, session FTS and recovery.
- Cloned and source-reviewed pinned GitHub trees for ReMe, memU, Mem0, LangMem, current Letta Code, Graphiti and Memvid. Detailed Codex report, exact SHAs, licensing correction and live upstream issue risks are in EXTERNAL-CODE-AUDIT.md.
- Codex recommends HYBRID as a **proposal**, not an approved design: retain Hermes lifecycle/security seams; improve native memory under the existing provider interface; selectively adapt third-party retrieval/consolidation/versioning patterns when justified. ReMe embedded and memU local remain benchmark comparators, not mandatory dependencies.
- Created unwired local SQLite/FTS5 ledger prototype: agent/memory_v2_store.py and tests/agent/test_memory_v2_store.py. No active memory registration, migration or runtime changes.
- Authorised host canonical runner succeeded 6/6 using the compatible baseline venv; log /tmp/fhm007/host-canonical-tests.log. First worker's attempt inside its sandbox was blocked, not an E2E PASS.
- Independent Cursor review is in INDEPENDENT-CODE-REVIEW.md. It endorses a non-runtime prototype commit but flags untested revision semantics, retraction revival, source provenance binding, FTS/CJK/index parity, restoration, and potential locking/dedupe issues. Discriminating tests must confirm or reject each finding; in particular BEGIN IMMEDIATE already precedes the dedupe SELECT.
- No external memory framework, cloud service, new Hermes process or production installation was started or modified.

## Exact next action

Triage independent P1 findings by reproducing the failures before changing design. Define the authoritative status/revision and provenance model, write-approval integration policy, and FHM-006 checkpoint handling for owner/ARB review. Add fail-closed regression tests, then build an offline benchmark comparing native, existing built-in/FTS, ReMe embedded and memU local on an identical corpus. Keep current Hermes runtime untouched. A draft PR may hold the isolated prototype and review evidence; do not merge into main or claim memory replacement success before review, retrieval-quality evidence, migration/rollback and owner approval.

## Hard gates

FHM-007 OPEN P1; source-level evidence only; no live Hermes/Qwen integration or semantic retrieval quality PASS. Preserve existing Qwen/LM Studio worktrees and PRs #15/#18.
