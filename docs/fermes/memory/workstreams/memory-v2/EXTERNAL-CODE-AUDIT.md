# FHM-007 Source Audit

Project identity verified:

```text
project_id: fermes-hermes
```

`docs/fermes/memory/MEMORY-INDEX.md` matched. No source, branch, repository, or runtime files were modified. Tests and third-party services were not run.

The managed filesystem rejected report-file creation (`/tmp/fhm007` and `/tmp/fhm007/external-source` are not writable), so this is the CLI report output.

## Verdict

Decision: **HYBRID**

Do not replace Hermes wholesale with ReMe, memU, Mem0, LangMem, Letta Code, Graphiti, or Memvid.

Keep Hermes’ existing provider boundary, profile isolation, background-review lifecycle, pre-compression checkpoint, file-based memory, redaction, injection fencing, and session FTS. Selectively harvest proven implementation ideas into a native Hermes store.

The strongest direction is the concurrent native SQLite design in the Fermes worktree, but it is currently untracked work-in-progress and is not yet an approved runtime replacement. It has good foundations—immutable revisions, compare-and-set updates, source metadata, explicit edges, FTS5, backup/restore, integrity checks, and process tests—but still needs provider integration, write approval, retention, migration, and adversarial-security gates.

No inspected external project is better end-to-end for Hermes’ exact requirement:

- local-first;
- no mandatory service;
- strict profile/agent isolation;
- durable provenance and revisions;
- safe crash and multi-process behavior;
- deterministic write approval;
- existing FTS compatibility;
- minimal Python integration risk.

## Weighted shortlist

Static architecture score only; no performance claims. Weights: local/no service 25%, isolation 15%, provenance/revisions 15%, security/write approval 15%, durability/concurrency 10%, retrieval 10%, integration/dependency fit 10%.

| Rank | Candidate | Score | Decision |
|---:|---|---:|---|
| 1 | Native Hermes memory ledger | 81/100 | Build toward; not yet approved for replacement |
| 2 | ReMe embedded, selectively wrapped | 62/100 | Useful adapter/reference, not system of record |
| 3 | Letta Code MemFS concepts | 60/100 | Harvest Git revision/lease/conflict ideas |
| 4 | Memvid storage concepts | 55/100 | Harvest WAL/footer/audit ideas; do not adopt directly |
| 5 | memU local | 54/100 | Possible experimental retrieval sidecar |
| 6 | Mem0 OSS | 49/100 | Useful extraction/history ideas; poor isolation defaults |
| 7 | LangMem | 37/100 | Extraction algorithm only; unsuitable persistence layer |
| 8 | Graphiti | 27/100 | Valuable temporal-graph reference, service-heavy |

## Hermes baseline

Hermes already has the right integration seams.

- `agent/memory_provider.py:84-103` defines a provider instance per profile and requires storage/client/tenant binding during `initialize()`. It explicitly prohibits module/class-level mutable profile state.
- `agent/memory_provider.py:116-155` defines availability, initialization, prompt injection, prefetch, queued synchronization, and status hooks.
- `agent/memory_provider.py:167-224` defines lifecycle hooks for shutdown, session changes, pre-compression, delegation, and built-in memory writes.
- `agent/memory_manager.py:99-135` redacts provider egress, including learned-token material.
- `agent/memory_manager.py:142-193` applies a process-wide stuck-call gate keyed by profile home and provider.
- `agent/memory_manager.py:196-229` keeps built-in memory plus at most one external provider and serializes background writes.
- `agent/memory_manager.py:346-380` bounds external prefetch and strips skill scaffolding before provider calls.
- `agent/memory_manager.py:441-471` applies the same treatment to synchronized turns.
- `agent/memory_manager.py:688-749` handles pre-compression checkpointing and provider memory-write notifications.
- `agent/background_review.py:1-6,75-150` runs review asynchronously and keeps the live prompt cache untouched.

Pre-compression is especially important. `agent/memory_manager.py:696-749` supports versioned checkpoint APIs, redacts messages before dispatch, and can refuse compression when a required checkpoint provider fails.

Hermes context handling is defensive but not a semantic trust system:

- `agent/memory_context.py:23-27` strips known tags and injected/system-note forms.
- `agent/memory_context.py:169-185` wraps recalled material in `<memory-context>`.
- The wrapper describes the material as authoritative reference data. This prevents treating it as a new user turn, but there is no semantic prompt-injection or malicious-memory classifier.

Hermes session search is already mature:

- `hermes_state_search.py:825-930` sanitizes FTS5 syntax, supports fallback query relaxation, and routes searches.
- `hermes_state_search.py:936-955` uses fail-open matching behavior.
- `hermes_state_search.py:1070-1145` supports keyword, phrase, AND/OR/NOT, prefix, snippets, context, role/tool filters, and exclusion of rewound rows.
- `tests/hermes_state/test_fts_runtime_rebuild.py:1-13` covers FTS corruption, stale markers, canonical-write fallback, and rebuild behavior.
- `tests/hermes_state/test_fts_projection_integrity.py:1-14,48-83` covers projection integrity for long tool rows.

Conclusion: a replacement must preserve these seams and cannot treat retrieval quality as sufficient justification for removing Hermes’ existing lifecycle and isolation controls.

## Native Fermes SQLite work: independent challenge

The concurrent untracked implementation is architecturally promising:

- `agent/memory_v2_store.py:1-7` describes local SQLite, immutable revisions, explicit writes, and profile/agent scope.
- `agent/memory_v2_store.py:178-213` guards the storage path and enables foreign keys, WAL, and `synchronous=FULL`.
- `agent/memory_v2_store.py:214-271` defines metadata, revisions, source hashes/quotes, supersession, edges, and FTS5.
- `agent/memory_v2_store.py:300-312` uses `BEGIN IMMEDIATE`.
- `agent/memory_v2_store.py:402-557` implements deduplication, immutable revisions, compare-and-set revision updates, status transitions, and explicit edges.
- `agent/memory_v2_store.py:630-674` scopes search to the agent and defaults to latest active revisions.
- `agent/memory_v2_store.py:692-748` provides integrity-checked backup and restore.
- `tests/agent/test_memory_v2_store.py:29-156` covers restart, provenance, isolation, stale writes, explicit contradictions, FTS scope, threaded/process writers, backup, corruption, and ownership checks.

However:

- It is untracked concurrent work, not an integrated provider.
- It has no semantic injection detector.
- It assumes trusted explicit callers for writes.
- It has no retention/compaction or migration policy.
- It has no semantic embedding index.
- Constructor directory creation and storage mutation need to be reconciled with Hermes write-approval policy.
- Runtime integration with `MemoryProvider` and `MemoryManager` remains unproven.

Approval condition: treat it as the leading native prototype, not as an already-approved replacement.

## ReMe — deep assessment

Commit: `363e497ae96733271414ea4224e274e5de5e5253`

License: Apache-2.0 in `pyproject.toml:1-16`; Python 3.11+.

### What is genuinely local

ReMe embedded mode is genuinely service-free:

- `integrations/hermes_agent/README.md:5-15` distinguishes HTTP mode from embedded mode.
- `integrations/hermes_agent/README.md:131-158` constructs `reme.Application` inside Hermes on a dedicated asyncio loop and does not open a service port.
- BM25 search does not require embeddings, but automatic extraction requires a configured model: `README.md:34-40,156-158`.

The adapter is a reasonable Hermes integration:

- `integrations/hermes_agent/embedded_backend.py:25-47` owns the application, event loop, and operation lock.
- `embedded_backend.py:125-149` starts the local SDK.
- `embedded_backend.py:178-255` serializes health, search, and automatic-memory operations.
- `integrations/hermes_agent/__init__.py:107-165` binds the provider to the Hermes home/profile and disables recording in cron, flush, and subagent contexts.
- `__init__.py:348-379` sends the latest completed turn and includes profile/session-derived identifiers.
- `__init__.py:455-520` runs the FIFO automatic-memory writer.

### Provenance and conflicts

ReMe records session/source identifiers:

- `reme/steps/file_io/daily_write.py:13-113` writes daily Markdown with source/session provenance.
- `reme/steps/auto_memory.py:229-260,464-523` performs merge and fingerprint/idempotency handling.

The conflict model is not deterministic:

- `reme/prompts/auto_memory.yaml:1-23,61-96,134-190` instructs the model to extract, merge, deduplicate, rewrite, and resolve timeline conflicts.
- No immutable revision/CAS/version-history API was found in the inspected memory path.

Thus ReMe provides useful provenance, but model output controls the meaning of updates and conflicts.

### Durability and security defects

- The queue is in-memory and crash loss is explicitly documented: `integrations/hermes_agent/README.md:192-208`.
- File path locks are process-local: `reme/steps/file_io/_file_io.py:20-40`.
- Atomic replacement is used, but the inspected write path does not fsync the file and directory: `_file_io.py:158-197`.
- HTTP mode has no integration authentication: `README.md:125-129`; the client sends ordinary HTTP requests in `integrations/hermes_agent/client.py:35-82`.
- Shutdown can abandon queued/in-flight work after timeout: `integrations/hermes_agent/__init__.py:395-453`.
- No dedicated semantic prompt-injection detector was found. Protection is primarily Hermes fencing plus model prompts.

Recommendation: use only as an optional embedded adapter or source of file/provenance ideas. Do not make it the system of record.

## memU — deep assessment

Commit: `42ef9fa3a8034f5817684cba23ef69fa70a58197`

License: Apache-2.0 in `LICENSE.txt:1-5`; the project metadata’s license declaration is incomplete/commented.

### Local versus cloud

memU does have a true local SQLite path:

- `src/memu/env.py:155-169` accepts SQLite paths and creates a local database configuration.
- `src/memu/env.py:189-246` selects local or cloud mode.
- Cloud mode requires `MEMU_CLOUD_API_KEY`: `env.py:209-217`.

But local does not mean fully offline:

- `env.py:172-186` defaults the embedding provider to OpenAI.
- The local service therefore needs an embedding provider unless configured with another compatible provider.
- `src/memu/database/sqlite/session.py:14-45` uses `check_same_thread=False`, but the inspected session setup has no explicit WAL, busy timeout, or cross-process lock policy.

### Hermes adapter

The Hermes integration is not a direct `MemoryProvider` replacement:

- `src/memu/hosts/hermes/__init__.py:1-13` describes recording as a scheduled bridging task and injection as a standing instruction in `SOUL.md`.
- `src/memu/hosts/hermes/cli.py:1-15,51-64` drives scheduled `hermes -z` prompts.
- `src/memu/hosts/retrieval.py:1-16,32-42,59-117` retrieves files and returns paths/source information.

This is an agent-mediated workflow, not a deterministic Hermes prefetch/write lifecycle.

### Retrieval and correctness

- `src/memu/app/agentic.py:187-230` performs progressive, LLM-free vector retrieval after embedding the query.
- `agentic.py:343-391` creates plans, embeds, and writes resources.
- Embedding failures leave the store unchanged, but independent repository operations can partially apply.
- `tests/test_agentic.py:242-340,414-435` cover failed embeddings, batching, deduplication, resource updates, and visibility between SQLite instances. Tests were inspected but not run.

Scope is configurable through user/agent IDs, but the Hermes adapter does not establish Hermes profile isolation as a hard storage invariant. A shared configured database could therefore share data unless callers explicitly use profile-specific scope.

Recommendation: experiment only as a retrieval comparator. Do not use its scheduled prompt bridge as Hermes’ primary memory path.

## Mem0 — deep assessment

Commit: `2c81af3bbe27d9bccb09c772d583df9e9be72ee5`

License: Apache-2.0 in `pyproject.toml:5-25`. The Hermes standalone provider README identifies an included standalone provider under MIT terms; preserve its separate notice.

The OSS package is not the managed benchmark:

- `README.md:65` identifies managed-platform benchmark optimizations as proprietary. Those results must not be attributed to the OSS code.

### Algorithms

- `mem0/memory/main.py:760-817` accepts user, agent, and run scope.
- `main.py:881-916` supports raw insertion without model extraction.
- `main.py:918-971` performs vector retrieval, context selection, structured LLM extraction, and ID-constrained updates.
- `mem0/configs/prompts.py:176-222` lets the update model choose ADD/UPDATE/DELETE/NONE.
- `prompts.py:264-295` handles contradictions through model-directed deletion.
- `mem0/memory/storage.py:11-18,102-255` stores history with old/new values, events, actors, and roles.

This is a useful mature extraction/history algorithm, but conflict behavior remains model-prompt controlled.

### Storage and Hermes integration

- `mem0/utils/factory.py:152-218` supports many embedding and vector backends.
- SQLite is a history store, not the native semantic vector store.
- The OSS backend supports local vector stores such as Qdrant, but this is additional storage and dependency surface: `mem0/integrations/hermes-plugin-mem0/_backend.py:145-285`.
- The Hermes adapter deliberately searches by `user_id`, potentially across gateways and agents: `integrations/hermes-plugin-mem0/__init__.py:248-255`.
- `__init__.py:305-316` asynchronously sends truncated turn content for extraction; failures are logged/circuit-broken.
- The adapter README documents forced termination interrupting pending writes: `integrations/hermes-plugin-mem0/README.md:70-106`.

Recommendation: harvest extraction/history concepts only behind a quarantined candidate-memory layer. Do not use the default user-scoped adapter for strict Hermes profile isolation.

## LangMem

Commit: `48e3c11f5bb527282c7d5339c6a87a0b35abccfc`

License: MIT in root `LICENSE` (verified); `pyproject.toml:7` points to that licence file.

The extraction algorithm is high quality conceptually:

- `src/langmem/knowledge/extraction.py:185-206` specifies extraction, contextualization, confidence, consolidation, correction, and deletion.
- `extraction.py:217-235` configures model-driven inserts, updates, and deletes.
- `extraction.py:237-445` performs structured, multi-step extraction through model/tool calls.
- `extraction.py:695-815` provides model-driven memory search over LangGraph namespaces.

The persistence and runtime dependency are unsuitable for direct Hermes replacement:

- `pyproject.toml` depends on LangGraph/LangChain ecosystem packages.
- `src/langmem/reflection.py:254-380` requires a LangGraph BaseStore/runtime and uses a worker thread.
- No Hermes adapter or independent local persistence layer was found.
- No semantic injection detector was found.

Recommendation: reuse prompt/schema ideas only, with deterministic Hermes-side approval and immutable revisions.

## Letta Code MemFS

Commit: `1fb6ea4d30942ef9220b096ba7f4185f18184fc1`

License: Apache-2.0 in `package.json:139-172`.

Letta Code has the strongest external revision/conflict model:

- `src/agent/memory-filesystem.ts:46-130` scopes memory under `~/.letta/agents/{agentId}/memory`.
- `src/agent/memory-git.ts:1184-1377` stages, commits, initializes, and tracks Git revisions.
- `src/agent/memory-git-hooks.ts:1-239` validates protected files, frontmatter, and constraints.
- `src/agent/memory-operation.ts:15-57` provides a process-wide file lease.
- `src/agent/subagents/memory-worker.ts:67-75,174-215` uses isolated worktrees for reflection and merges completed work.
- `src/agent/memory-conflict-repair.ts:109-220` performs compare-and-set-style conflict repair.

Limitations:

- It is current TypeScript/Bun/Node code, not a Python Hermes library.
- It provides Git revision history rather than a native scoped relational memory API.
- Retrieval quality is not equivalent to Hermes FTS or semantic search.
- No dedicated semantic injection classifier was found.

Recommendation: selectively borrow worktree, lease, protected-file, and conflict-repair patterns. Do not port the whole runtime.

## Graphiti

Commit: `5c27edfa8d3e0f49b2571bcebb4261bcc89ee037`

License: Apache-2.0 in `pyproject.toml:1-22`.

Graphiti is a temporal graph system, not a local Hermes memory replacement:

- `graphiti_core/graphiti.py:209-225` exposes LLM, embedder, reranker, and graph-driver dependencies.
- `graphiti.py:1334-1505` adds episodes with source/name/reference time/group ID and performs LLM extraction, deduplication, and resolution.
- `graphiti.py:1913-2017` performs hybrid graph/vector/text search.
- `driver/driver.py:59-63` supports Neo4j, FalkorDB, Kuzu, and Neptune.
- `driver/kuzu_driver.py:137-157` describes Kuzu local mode but marks it deprecated/unmaintained.
- `graphiti_core/telemetry/telemetry.py:15-37,76-115` enables telemetry by default unless disabled.

It has useful temporal-edge concepts but requires a graph database and model/embedding stack. It has no Hermes profile-storage invariant or semantic injection defense.

Recommendation: use only for future temporal-relationship research.

## Memvid

Commit: `e6bd9f7b9c38cd8d5370fa0fc936ac1dcd751813`

License: Apache-2.0 in `Cargo.toml:1-13`.

Memvid has the strongest low-level single-file durability primitives:

- `src/memvid/lifecycle.rs:44-105` maintains a file handle, lock, TOC, WAL, indexes, and generation state.
- `src/lock.rs:17-69,129-192` implements OS-level shared/exclusive file locks.
- `src/io/wal.rs:96-150,230-238,350-374` implements checksummed WAL append, flush, fsync, and recovery.
- `src/footer.rs:6-18,20-117` scans for the last valid commit footer.
- `src/memvid/mutation.rs:123-158,755-768` stages, flushes, syncs, commits, and tracks superseded/deleted frames.
- `src/memvid/audit.rs:20-151` provides structured audit/source-span records.
- `src/memvid/acl.rs:96-177` supports optional tenant-enforced ACLs.

The cloned repository is Rust. The README points to an external Python SDK rather than providing a drop-in Python Hermes module: `README.md:118-127`. No Hermes profile/agent adapter exists.

Recommendation: borrow WAL, locking, audit, and recovery design ideas only. Avoid FFI/subprocess integration unless native SQLite cannot meet measured gates.

## Security and trust-boundary assessment

The common weakness across ReMe, memU, Mem0, LangMem, and Graphiti is model-mediated memory mutation. None of the inspected code provides a dedicated semantic prompt-injection detector for memory content.

Required Hermes policy:

1. User/model-generated memory candidates are untrusted.
2. Every candidate must retain source session, message, quote/hash, actor, and timestamp.
3. Protected/system memory must be read-only to model-generated writers.
4. Model-generated update/delete/contradiction actions must become candidates, not immediate mutations.
5. Explicit user memory tools may write directly, subject to scope and audit.
6. Retrieved content must remain fenced and must not be described as inherently authoritative without provenance/confidence.
7. Cross-profile retrieval must fail closed.
8. Any external HTTP mode must require authenticated, local-trust configuration; unauthenticated HTTP is not acceptable.

## Risk and defect table

| Priority | Finding | Evidence | Required response |
|---|---|---|---|
| P0 | No external candidate satisfies Hermes’ complete local, isolation, security, durability, and integration requirements | Combined source comparison above | Do not direct-replace Hermes |
| P0 | Model-generated memory can be semantically poisoned; no inspected candidate has a dedicated injection detector | ReMe `auto_memory.yaml:1-190`; LangMem `extraction.py:185-245`; Mem0 `prompts.py:176-295`; Hermes `memory_context.py:169-185` | Require candidate quarantine and deterministic approval |
| P1 | ReMe embedded queue can lose turns on crash | ReMe `integrations/hermes_agent/README.md:196-208` | Add durable spool before production use |
| P1 | ReMe file locks are process-local; write path lacks fsync durability | ReMe `_file_io.py:20-40,158-197` | Do not use as system of record |
| P1 | ReMe HTTP integration has no authentication | ReMe `README.md:125-129`; `client.py:35-82` | Loopback-only or authenticated proxy, preferably embedded |
| P1 | memU Hermes integration is a scheduled prompt bridge, not a native provider | memU `hosts/hermes/__init__.py:1-13`; `cli.py:51-64` | Keep outside the core write path |
| P1 | memU SQLite connection setup lacks explicit multiprocess locking/WAL policy | memU `database/sqlite/session.py:14-45` | Add and test before concurrency use |
| P1 | Mem0 adapter intentionally searches by user across agents/gateways | Mem0 adapter `__init__.py:248-255` | Must use strict Hermes profile/agent namespace |
| P1 | Mem0 asynchronous sync truncates content and may silently fail/circuit-break | Mem0 adapter `__init__.py:305-316` | Preserve full source locally; treat remote sync as optional |
| P1 | All model-driven conflict systems can delete or rewrite facts based on model judgment | ReMe, LangMem, Mem0 prompt files cited above | Convert mutations into approved revisions |
| P2 | Graphiti defaults to external graph/model services; Kuzu is deprecated | Graphiti `graphiti.py:209-225`; `kuzu_driver.py:137-157` | Exclude from local-first baseline |
| P2 | Graphiti telemetry is enabled by default unless disabled | `telemetry.py:15-37,76-115` | Require explicit privacy configuration |
| P2 | Memvid requires Rust/Python integration work | Memvid `README.md:118-127` | Use design ideas, not direct dependency |
| P2 | LangMem requires LangGraph persistence/runtime | LangMem `pyproject.toml`; `reflection.py:254-380` | Harvest algorithm only |
| P2 | Mem0 notices code fetches remote configuration periodically | Mem0 `mem0/memory/notices.py:20-27,62-87` | Disable or isolate for reproducibility |
| P2 | Hermes FTS has historical corruption/projection failure paths, but fallback/rebuild tests exist | Hermes FTS tests cited above | Preserve current fallback tests and add candidate-index checks |

## Licensing and reuse

Six projects are Apache-2.0 licensed; LangMem is MIT licensed. Verify full notices before code harvesting:

- ReMe: `pyproject.toml:1-16`
- memU: `LICENSE.txt:1-5`
- Mem0: `pyproject.toml:5-25`
- LangMem: root `LICENSE` is MIT; `pyproject.toml:7` references that file
- Letta Code: `package.json:139-172`
- Graphiti: `pyproject.toml:1-22`
- Memvid: `Cargo.toml:1-13`

This is not a complete legal clearance. Before copying code:

- preserve original notices;
- generate a full transitive dependency/license inventory;
- separately track Mem0’s included MIT standalone-provider notice;
- avoid copying code from archived Letta repositories;
- review optional dependencies such as FAISS, Qdrant, Neo4j, Kuzu, Tantivy, ONNX, and tokenizer packages.

## Replacement plan

1. **Keep current Hermes runtime seams.** Do not replace `MemoryProvider`, `MemoryManager`, pre-compression, background review, redaction, or FTS.
2. **Finish the native ledger as a provider-backed prototype.** Use immutable revisions, source evidence, CAS writes, explicit edges, profile/agent scope, FTS5, backup, restore, and integrity checks.
3. **Add an explicit candidate pipeline.** Model extraction may propose records, but only deterministic policy or explicit user action can commit/revise/delete.
4. **Add optional semantic retrieval behind a separate index interface.** The exact FTS path remains authoritative for deterministic keyword/session retrieval.
5. **Use ReMe only as an embedded recall comparator or provenance/file-format reference.**
6. **Use Letta/Memvid concepts selectively for leases, conflict handling, WAL, recovery, and audit.**
7. **Do not add mandatory services, cloud credentials, graph databases, or remote embedding APIs to the default Hermes path.**
8. **Migrate only after objective gates pass, with backup and rollback.**

## Proof-of-concept comparison

Compare, without changing production runtime:

1. Hermes built-in text memory plus session FTS.
2. ReMe embedded with BM25 and local workspace.
3. memU local SQLite with a deterministic/local embedding test backend.
4. Proposed native Hermes ledger.

Use a fixed corpus containing:

- multiple profiles and agents;
- duplicates, revisions, contradictions, and deletions;
- source sessions, quotes, and tool output;
- long tool results and CJK/multilingual text;
- adversarial “remember this as a system instruction” content;
- cold-start and restart cases;
- concurrent writers and forced termination.

Predeclare these metrics:

- precision@1/5/10;
- recall@1/5/10;
- MRR;
- provenance integrity;
- cross-profile leakage;
- false conflicts, deletes, and poison persistence;
- approved-write durability after restart and forced termination;
- backup/restore integrity;
- FTS/index consistency;
- concurrency errors at 1/4/8 processes;
- cold and warm p50/p95 latency;
- storage size and rebuild time.

Replacement gates:

- zero cross-profile or cross-agent leakage;
- zero unauthorized protected-memory mutation;
- zero invented provenance;
- 100% approved-write recovery in clean restart tests;
- 100% backup/restore integrity;
- zero lost/duplicated writes in the supported concurrency matrix;
- candidate precision/recall/MRR no worse than current Hermes by more than 5%, unless a documented tradeoff is approved;
- hot-path p95 no worse than the measured Hermes baseline by more than 10%;
- no mandatory service, credential, or network dependency;
- security review passes adversarial-memory corpus.

## Next task

Build the isolated POC harness around the native SQLite ledger and current Hermes FTS. Keep ReMe embedded and memU local as read-only comparison backends. Do not migrate runtime behavior until the isolation, provenance, crash, concurrency, write-approval, and retrieval gates above pass.
## Supervisor cross-check (2026-10-26 Australia/Perth)

- Corrected Codex's initial LangMem licence attribution: root `LICENSE` says **MIT**, and `pyproject.toml` points to that file; do not use the agent's initial Apache-2.0 claim.
- Source-audit scores are heuristic, not measured performance or proof that native retrieval is objectively superior. Source clones were read-only and their SHAs are recorded above.
- Verified current **open GitHub issue reports** relevant to replacement: ReMe #661 (dream-integrate hang and write starvation), #660 (non-resumable completed batches), #666 (same-ID transcript correction dropped), #673 (float16 zero-vector NaN); memU #606 (Hermes bridge mines its own scheduled sessions), #688 (Hermes transcript sanitisation review); Mem0 #6515 (concurrent hash dedupe race), #7196 (SQLite locking report for mem0 2.0.19). These reports are not independently reproduced against cloned snapshots and may have partial fixes in HEAD; investigate before adoption.
- Independent Hermes canonical test runner verified the isolated native ledger prototype: `HERMES_PYTHON=/srv/project-coordinator/projects/fermes-hermes-qwen-v0225/.venv/bin/python scripts/run_tests.sh tests/agent/test_memory_v2_store.py` resulted **6 passed, 0 failed**. Host log: `/tmp/fhm007/host-canonical-tests.log`. This does not establish live integration or comparative retrieval uplift.
- Recommendation remains **HYBRID PROPOSED, NOT APPROVED**. No production migration, automatic review, FHM-006 checkpoint activation, or main merge until owner/ARB gates, independent security review and benchmark proof.
