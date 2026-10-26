# FHM-007 — Memory v2 architecture and gaps

project_id: fermes-hermes
issue: FHM-007 / GitHub #7
source_baseline: e0bb2a8201d9ae43c04cd8f1e8da044c02c2d181
branch: fermes/memory-v2-fhm007-20261026
status: Proposed — owner/ARB approval required for material decisions

## Scope and evidence boundary

This is an architecture investigation for the maintained `fredheathcote007/hermes-agent` fork,
not a qualification or acceptance claim. The reviewed source is the v0.22.5-derived worktree at the
SHA above. The current Hermes runtime is not changed by this workstream. Upstream was inspected
read-only through the v0.22.5 release (`bf0203a`, released 2026-10-22) and current upstream source
pages; no upstream code was merged. All research below was recorded on 2026-10-26 UTC and should
be revalidated before dependency or API decisions.

## What exists today

| Area | Existing contract | Consequence for v2 |
|---|---|---|
| Built-in memory | `tools/memory_tool.py` and `tools/memory_tool_store.py` maintain `MEMORY.md` and `USER.md`; edits use a separate lock file, reload before mutation, atomic writes, duplicate suppression, size limits, and drift refusal. | Valuable compatibility surface, but entries have no durable revisions, typed evidence, graph edges, or query index. |
| Provider boundary | `MemoryProvider` + `MemoryManager` support a builtin plus one external provider, lifecycle hooks, bounded external calls, redacted provider egress, background serialization, and memory-write notifications. | The integration seam exists; it must remain opt-in and must not rebuild a prompt prefix mid-turn. |
| Profile/agent isolation | `memory_caller_scope.py` binds provider instances to an explicit `hermes_home`, refuses unresolved callers on multiplexed processes, and prevents one provider instance being rebound across profiles. Context-bound threads carry the scope. | v2 must preserve this rule and add an explicit agent namespace; a path alone is not an authorization boundary. |
| Prompt and injection boundary | `memory_context.py` fences recalled content, strips provider-supplied fence/system-note wrappers, and deduplicates self-contained bullets. `tools/threat_patterns.py` scans strict memory writes and load-time prompt rendering. | v2 records must remain opaque evidence. Retrieval adapters must fence data and never promote stored text to instructions. |
| Write governance | `tools/write_approval.py` supports inline approval for foreground memory writes and staged pending records for background/headless writes. | v2 writes need the same decision point before runtime integration; the ledger itself must not infer approval. |
| Background review | `agent/background_review.py` creates a cache-parity fork, freezes the live tool surface, uses an explicit background origin, and routes memory/skill changes through existing guards. | Review output is a candidate, not authority. v2 must retain evidence and await governed commit. |
| Compaction | `agent/context_compressor.py`, `agent/native_compaction.py`, and `agent/turn_context_compaction.py` preserve recoverable transcript state. Native server compaction is suppressed when the v2 checkpoint requirement is active; checkpoint API version is 2. | FHM-006 must define the durable checkpoint/ledger handoff before memory extraction is wired into compaction. |
| Session history | `hermes_state.py` owns `state.db`; WAL, bounded readers, lock patience, corruption/quarantine handling, FTS5, lineage, backups/export, and profile-aware paths already exist. `tools/session_search_tool.py` provides bounded FTS discovery and hydration. | Do not add memory-v2 tables to `state.db` in this phase. Reuse concepts, not the live schema. |
| Credentials | Secrets use profile-scoped `secret_scope`; provider egress is redacted. | Memory provenance must never store raw credentials or unredacted tool transcripts. A source hash/ID is safer than copying a secret-bearing source. |

## Gaps against the FHM-007 goal

1. There is no Hermes-owned typed ledger for semantic, episodic, procedural, failure, and lesson
   memories. Markdown is human-readable but lacks a stable record identity and queryable history.
2. There is no mandatory provenance shape containing source ID, source hash, quotation/evidence, and
   confidence. Existing metadata is best effort and provider-specific.
3. Replace/remove operations preserve useful text in approval metadata but do not form an immutable
   revision chain or explicit supersession relation.
4. Contradictions are not first-class. Existing dedupe avoids exact duplicates but cannot represent
   two competing claims with evidence and unresolved status.
5. Retrieval is provider-defined. The builtin store has no FTS query, ranking policy, recency policy,
   or current-vs-history distinction.
6. There is no durable, independently restorable memory backup format with ownership validation.
7. Consolidation, forgetting, retention, and PII policy are not a single governed contract. Automatic
   self-correction would be unsafe until evidence, approval, audit, and rollback are specified.
8. FHM-006 checkpoint versioning and FHM-008/FHM-009 learning/optimisation candidate interfaces are
   not yet stable. v2 must expose candidate evidence and status without invoking those systems.

## Proposed architecture (pending approval)

### Storage and scope

Use one independent SQLite file below the owning profile's Hermes home, for example
`<hermes_home>/memory-v2/ledger.sqlite3`. The file is not `state.db` and is not global. One profile
may have several agent namespaces in the file; every query and edge is filtered by the bound
`agent_id`. The store constructor requires an absolute home and validates a persisted profile hash,
rejects symlink/path traversal, and refuses an altered schema/owner marker. This is a fail-closed
application check, not a substitute for filesystem permissions; the directory/database should be
owner-only.

### Immutable records

`memory_revisions` is append-only by `(memory_id, revision)`. A record contains:

- typed kind: `semantic`, `episodic`, `procedural`, `failure`, or `lesson`;
- content as opaque text, a bounded confidence in `[0, 1]`, and explicit status;
- `source_id`, `source_hash`, and bounded `source_quote` plus JSON metadata;
- creation time and a stable memory ID;
- a superseded memory/revision pointer when the new revision is intentional.

No write silently edits an old row. Compare-and-set revisions reject stale writers. Exact normalized
duplicates return the existing active record as a visible dedupe result. A duplicate is not a
contradiction and never causes automatic replacement.

`memory_edges` stores explicit `supersedes`, `contradicts`, `supports`, and `derived_from` edges.
Contradiction is never inferred from lexical mismatch. A future resolver may propose a status change,
but only a governed write may commit it.

### Indexing and transactions

Use SQLite WAL with `synchronous=FULL`, foreign keys, a bounded busy timeout, and `BEGIN IMMEDIATE`
for mutations. A transaction writes the record and its FTS5 row together. FTS results are joined to
the latest active revision and agent scope; historical search is explicit. A startup/integrity check
must fail closed rather than rebuilding or dropping evidence. WAL is appropriate for same-host
concurrent readers plus a serialized writer, but SQLite WAL is not a network-filesystem protocol and
requires checkpoint/backup attention ([SQLite WAL](https://www.sqlite.org/wal.html),
[SQLite FTS5](https://www.sqlite.org/fts5.html)).

### Retrieval safety and efficiency

Phase 1 uses lexical FTS5 only: no embeddings, no model call, no vector extension, and no network.
Query tokens are parameterized/quoted and result size is bounded. Returned content is data, not
instructions; the eventual prompt adapter must use the existing memory fence/scrubber and include
provenance/confidence so the model can distinguish evidence from authority. Optional local
embeddings can be evaluated later behind an explicit provider/capability boundary, with a deterministic
lexical fallback and no dependency in the core ledger.

### Governed writes and lifecycle

The future integration adapter should call `write_approval` before `add`, `revise`, `transition`, or
edge creation. Foreground and background-review origins remain distinguishable. Candidate extraction
from FHM-008 and FHM-009 must write a proposal/evidence record or pending action, not mutate trusted
memory directly. Consolidation and forgetting must be explicit, reversible where possible, logged,
and retention/PII-aware. No automatic self-correction is part of this phase.

### Interfaces to adjacent workstreams

- **FHM-006:** compaction may publish a versioned checkpoint/evidence handoff only after the checkpoint
  API v2 contract, ownership, and recovery semantics are approved. A missing or stale checkpoint
  fails closed for any operation that would discard the only transcript evidence.
- **FHM-008 SkillHone:** consume completed-session evidence and produce candidate procedural/lesson
  records with source IDs, hashes, confidence, and review state. Never write skills from an unreviewed
  memory or from model text alone.
- **FHM-009 SkillOpt:** read immutable failures/lessons and append optimisation hypotheses plus evaluation
  links. It must not rewrite the evidence or claim an improvement without FHM-010 corpus results.
- **Session search/state:** keep `state.db` authoritative for transcript history. Store source session
  IDs and hashes in v2; resolve full transcript evidence through the existing bounded session search
  path at integration time.
- **Backup/restore:** include the standalone ledger and SQLite sidecars only through a profile-aware
  backup manifest. Restore must verify profile ownership, schema, integrity, and destination absence;
  never merge an untrusted database into a live profile implicitly.

## Threat and failure review

| Threat/edge | Required control | Current v2 status |
|---|---|---|
| Cross-profile leakage | Explicit home, persisted profile hash, scoped agent queries, no global singleton, owner-only files | Foundation implemented/tested; runtime caller binding still pending |
| Cross-agent leakage | Bound `agent_id` on every read/write/edge/search | Foundation implemented/tested |
| Prompt injection/data poisoning | Preserve raw evidence, mark untrusted metadata, fence at adapter, threat scan at governed write | Foundation stores opaque data; adapter and policy pending |
| Credential/PII retention | Shared egress redaction before extraction; source references preferred; retention class and deletion audit required | Policy pending; ledger has no secret discovery |
| Stale concurrent update | WAL, transaction, compare-and-set revision, no in-place mutation | Foundation implemented/tested |
| FTS drift/corruption | Same-transaction FTS insert, integrity check, explicit rebuild/repair command later | Foundation implemented/tested; operational repair pending |
| Backup race | SQLite backup API under store lock, atomic destination replacement, integrity/owner check on restore | Foundation implemented/tested; live backup integration pending |
| Automatic forgetting | No implicit delete; status transitions and history retained | Foundation implemented |
| Forensic history | Immutable rows, provenance, edge metadata, timestamps, no silent correction | Foundation implemented; audit export pending |
| FHM-006 checkpoint loss | Versioned checkpoint gate before destructive compression | Existing v2 checkpoint seam; v2 ledger integration pending |
| Network filesystem/WAL | Reject/declare unsupported deployment; same-host profile home | Documented; deployment check pending |

## Alternatives and dependency/licence assessment

This is a pattern comparison, not a code-harvesting decision. No third-party code was copied.

| Project/pattern | Verified licence/source | Useful pattern | Why not a Phase 1 dependency |
|---|---|---|---|
| Native Hermes | This fork and upstream v0.22.5 source; existing project code | Profile-scoped provider contract, redaction, approval, FTS session search, checkpoint gate | The live contracts are broad; routing them now would break prompt-cache and runtime isolation invariants. |
| Mem0 | Apache-2.0 in upstream `pyproject.toml`/README. Core package currently declares qdrant-client, pydantic, openai, httpx, posthog, pytz, SQLAlchemy, protobuf, with many vector/LLM extras: [source](https://github.com/mem0ai/mem0/blob/main/pyproject.toml). | Extract/update/search workflow and optional vector backends | Dependency and telemetry/surface footprint are far beyond a stdlib-first local ledger; its default path is not a provenance/audit contract for Hermes. |
| Letta/MemFS | Apache-2.0 repository licence; docs describe git-backed memory filesystem and dreaming/review: [docs](https://github.com/letta-ai/letta-docs-md/blob/main/configuration/memory/index.md). | Human-auditable versioned memory, background reflection, explicit memory blocks | Git-backed files do not provide typed FTS/relation transactions, and the current runtime is a separate agent stack. Borrow concepts only. |
| LangMem | MIT licence in upstream LICENSE: [source](https://raw.githubusercontent.com/langchain-ai/langmem/main/LICENSE). README describes hot-path tools and background extraction/consolidation: [source](https://github.com/langchain-ai/langmem/blob/main/README.md). | Separate hot-path and background memory-manager roles | Framework/storage coupling and LLM-driven consolidation are not needed for this bounded foundation; exact current dependency closure should be rechecked before any reuse. |
| Graphiti | Apache-2.0; current `graphiti-core` declares Neo4j plus LLM/network/telemetry dependencies and optional local/vector backends: [pyproject](https://github.com/getzep/graphiti/blob/main/pyproject.toml). | Temporal entities/relations and episode provenance | Graph database and model dependencies violate local stdlib-first scope. Graph is an optional future adapter, not a core Phase 1 dependency. |

The only Phase 1 implementation dependency is Python's `sqlite3` with FTS5, which is verified in this
environment. FTS5 availability should remain a startup capability check on platforms where SQLite is
system-provided. The baseline `pyproject.toml` supports Python `>=3.11,<3.15`; no dependency or lock
file was changed.

## Open decisions (PROPOSED, not approved)

- **P1:** adopt the independent ledger file and schema versioning, or extend the existing provider
  surface first. Owner/ARB decision required before runtime routing.
- **P1:** choose whether one profile file may contain multiple agent namespaces, or use one file per
  `(profile, agent)`. This implementation uses one profile file plus agent filtering to make backup
  and profile ownership visible, but the authorization model needs review.
- **P1:** define the governed write policy, including approval for background review, confidence
  thresholds, contradiction review, PII classes, retention, and audit export.
- **P1:** define FHM-006 checkpoint version/restore coupling before any compaction path writes v2.
- **P2:** select an optional local embedding implementation only after measuring lexical recall and
  platform/package/licence impact. Do not add it to the core dependency set by default.
- **P2:** decide whether a graph adapter is warranted after the typed edge model and evaluation corpus
  demonstrate a real retrieval need.
