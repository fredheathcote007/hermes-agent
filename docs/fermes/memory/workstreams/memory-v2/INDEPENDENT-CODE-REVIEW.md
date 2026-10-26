# FHM-007 independent read-only review

**Identity gate:** `docs/fermes/memory/MEMORY-INDEX.md` lines 3–4 show `project_id: fermes-hermes`. **Branch/worktree:** `fermes/memory-v2-fhm007-20261026` at `/srv/project-coordinator/projects/fermes-hermes-memory-v2-fhm007`. **No edits, commits, pushes, or test re-runs** (host log at `/tmp/fhm007/host-canonical-tests.log` corroborates **6 passed** in `tests/agent/test_memory_v2_store.py`). PRs **#15** and **#18** were not inspected or modified.

---

## Executive verdict

| Question | Independent conclusion |
|----------|------------------------|
| **HYBRID vs wholesale replace** | **Agree** with Codex: no external stack is a drop-in Hermes replacement. **Disagree** with any implication that the native ledger is already “safer end-to-end”; it is safer only as a **deterministic, profile-scoped persistence substrate** if integration gaps are closed. |
| **Commit prototype?** | **Yes**, as an **explicit non-runtime / unwired** module with docs stating WIP and blocked integration. |
| **Runtime integration?** | **Remain blocked** until write-approval binding, provenance policy, FTS/CJK parity decisions, transition semantics, concurrency/dedupe hardening, and adversarial corpus gates. |
| **Live acceptance** | **Not claimed** (architecture doc: “Proposed — owner/ARB approval required”). |

**LangMem licence:** Independently confirmed **MIT** in `/tmp/fhm007/external-source/langmem/LICENSE` (lines 1–21) and `pyproject.toml` line 7 (`license = { file = "LICENSE" }`). Not Apache-2.0.

---

## (1) Challenge: native SQLite ledger vs ReMe embedded vs memU local

### Where “native is substantially safer” holds (with sources)

**As system-of-record for Hermes profile/agent isolation and durable writes**, the native prototype has structural advantages over **using ReMe or memU as the primary store**:

| Dimension | Native ledger | ReMe embedded Hermes adapter | memU local + Hermes bridge |
|-----------|---------------|------------------------------|----------------------------|
| **Write durability** | SQLite WAL + `synchronous=FULL` + `BEGIN IMMEDIATE` (`memory_v2_store.py:206-212`, `300-307`) | FIFO **in-memory** queue; crash can lose queued turns (`/tmp/fhm007/external-source/reme/integrations/hermes_agent/README.md:207-208`, `316`; shutdown abandons queue `__init__.py:395-413`) | SQLAlchemy SQLite with `check_same_thread=False` only; **no** inspected WAL/busy-timeout policy (`memu/.../session.py:24-29`) |
| **Conflict / meaning of updates** | CAS on `expected_revision`; append-only rows (`453-496`) | Model-driven merge/extract in prompts (`EXTERNAL-CODE-AUDIT.md` cites `auto_memory.yaml`) | LLM/agentic ingestion path; Hermes host is **scheduled `-z` bridge**, not `MemoryProvider` lifecycle (`EXTERNAL-CODE-AUDIT.md` cites `hosts/hermes/__init__.py`, `cli.py`) |
| **Profile isolation** | Persisted `profile_key` + open-time validation (`287-297`, `94-96`) | ReMe search is **workspace-wide**; different profiles need different workspaces or recall crosses profiles (`README.md:192-194`) | Scope via user/agent IDs; not the same invariant as Hermes `memory_caller_scope` |
| **Cross-process file safety** | WAL + busy timeout (partially; see P2 below) | Process-local asyncio path locks (`reme/.../_file_io.py:20-40`); atomic replace **without** inspected fsync of file+dir (`158-195`) | Concurrency story not defined at session layer |
| **Dependency / attack surface** | stdlib `sqlite3` only (per `ARCHITECTURE-AND-GAPS.md:152-155`) | `reme-ai` stack + optional HTTP mode without integration auth (audit cites `README.md:125-129`) | Embeddings default toward network providers (`env.py` per audit); cloud mode needs API key |

**Open upstream risk signals** (not reproduced on clones here; treat as adoption hazards):

- ReMe: #661 (hang/write starvation), #660 (non-resumable batches), #666 (transcript correction dropped), #673 (embedding NaN).
- memU: #606 (Hermes bridge mining scheduled sessions), #688 (transcript sanitisation).
- Mem0: #6515 (concurrent hash dedupe race), #7196 (SQLite locking).

These reinforce **not** making ReMe/memU the ledger of record even when embedded/local.

### Where “substantially safer” is **overstated**

1. **Semantic / injection safety is not solved by SQLite.** The prototype stores arbitrary `content`, `source_hash`, and `source_quote` with **no cryptographic or transcript binding** (`402-411`, `480-491`). ReMe/memU also lack a dedicated injection classifier; Hermes still fences at `memory_context.py` (audit). Native avoids **model-mediated deletion**, but a naïve provider wire-up would still allow **forged provenance** at the API boundary.

2. **Retrieval is weaker than production Hermes session FTS.** Hermes sanitises FTS5 (`hermes_state_search.py:825-859`, `1109+`) and has CJK paths (`_strip_cjk_wildcards`, CJK rebuild). v2 search tokenises with `_QUERY_TOKEN_RE` (`86`, `653-657`) and `unicode61` FTS (`268-270`) — **no** equivalent sanitizer or CJK strategy.

3. **ReMe as comparator, not replacement, is still rational.** Embedded mode gives working prefetch/search integration (audit cites `embedded_backend.py`, `__init__.py`) without porting extraction. For **benchmarking recall**, ReMe/memU can run **beside** the ledger without inheriting their durability/isolation flaws as SoR.

4. **“Deterministic write approval”** is **Hermes policy**, not yet in the ledger (`ARCHITECTURE-AND-GAPS.md:99-105`; no `write_approval` in `memory_v2_store.py`). ReMe/memU are worse on **mutation** semantics, not on **approval UX**, which neither provides.

**Balanced conclusion (1):** Native SQLite is **materially safer and more maintainable than adapting ReMe/memU as the authoritative memory substrate** for Fermes’ isolation, provenance, and durability goals. It is **not** safer than the **current Hermes runtime** until provider integration, approval gates, and retrieval parity exist. **HYBRID** remains correct; ranking native #1 is plausible for **architecture**, not for **production readiness**.

---

## (2) Challenge: P0/P1 defects in `memory_v2_store.py` not covered by six tests

### What the six tests actually prove

| Test | Proves | Does **not** prove |
|------|--------|-------------------|
| `test_restart_provenance_and_agent_isolation` | Round-trip fields; **search** empty for other `agent_id` | `transition()`; wrong-profile restore; symlink TOCTOU; provenance integrity |
| `test_dedupe_revision_history_and_stale_write` | Normalised dedupe; CAS conflict on stale `expected_revision` | Multiprocess dedupe race; revive from non-active head; prior rows marked `active` while superseded |
| `test_contradiction_is_explicit_and_not_automatic` | Edges not auto-created | Edge idempotency / `INSERT OR IGNORE` semantics under error |
| `test_fts_recall_is_scoped_and_indexed_transactionally` | Basic English FTS + agent filter | CJK, FTS5 operator injection, orphan FTS rows, `include_history` |
| `test_concurrent_process_like_writers_and_backup_roundtrip` | 24 threads + 8 processes complete; backup/restore **new filename** | Restore while live writers; WAL checkpoint semantics; lost-update under duplicate content |
| `test_corruption_and_ownership_fail_closed` | Tampered `profile_key`; `../` filename rejected | Symlink races; FTS/revision consistency; `busy_timeout_ms` |

**`transition()` has zero test coverage** (grep: no matches in test file).

---

### Findings table (exact locations)

| Pri | Finding | Evidence (`file:line`) | Acceptance impact |
|-----|---------|------------------------|-------------------|
| **P1** | **Head revision can be “revived” after retract/supersede:** `revise()` only checks revision number, not prior **status**; always inserts new **`active`** revision. | `467-487` | Governance: deleted/retracted memories can reappear in search (`647-667` filters latest **and** `status='active'`). |
| **P1** | **Stale “active” rows in history:** `revise()` / `transition()` never mark older revisions non-active; only **latest** revision drives search. Auditors/`history()` see multiple `active` rows. | `480-534`, `630-636` | Conflicts with “immutable chain + explicit status” narrative (`ARCHITECTURE-AND-GAPS.md:64-74`). |
| **P1** | **Multiprocess dedupe race:** duplicate `add()` for same normalised content can create **two** `memory_id`s (no DB unique constraint on active content hash; SELECT-then-INSERT). | `425-435` | Violates “exact duplicates return existing” under parallel writers (thread test uses distinct strings). |
| **P1** | **Provenance is forgeable at store API:** `source_id` / `source_hash` / `source_quote` accepted without verification against content or session transcript. | `402-411`, `488-491` | Blocks “zero invented provenance” gate until provider binds hashes to redacted transcript (`ARCHITECTURE-AND-GAPS.md:36-37`). |
| **P1** | **FTS query surface narrower than Hermes:** token regex `[\w-]{1,80}` drops CJK and many scripts; no `_sanitize_fts5_query` equivalent. Malformed queries fail closed to `[]` but behaviour differs from session search. | `86`, `653-657` vs `hermes_state_search.py:825-859` | Benchmark corpus with CJK/multilingual (`EXTERNAL-CODE-AUDIT.md:394-395`) will fail parity. |
| **P1** | **`restore_from` vs live database:** no exclusion lock on existing ledger; only “target must not exist” (`737-738`). Another process can hold WAL on **source** profile DB during copy. | `718-748` | Backup/restore gate under concurrent gateway. |
| **P1** | **Integrity check does not prove FTS↔revision bijection:** `check_integrity` runs SQLite + FTS5 `integrity-check` (`676-690`) but no count/join audit. Manual FTS drift would not be caught by tests. | `676-690` | FTS consistency gate in audit (`EXTERNAL-CODE-AUDIT.md:409`). |
| **P2** | **`busy_timeout_ms` ignored:** constructor accepts `busy_timeout_ms` (`149`, `159-161`) but `_configure` hardcodes `PRAGMA busy_timeout=5000` (`208`). | `149`, `208` | Misleading API; tuning for gateway load untestable. |
| **P2** | **Directory permissions:** `memory-v2` created `0o700` (`194`) but `hermes_home` mkdir uses default mode (`184`). | `184`, `194` | Hardening vs `ARCHITECTURE-AND-GAPS.md:58-60` “owner-only”. |
| **P2** | **Symlink TOCTOU:** checks `root.is_symlink()` after `mkdir` (`195-196`); race between check and `connect` not eliminated. | `193-204` | Lower risk on single-user profile home; still worth test if threat model includes shared parent dir. |
| **P2** | **`transition()` untested;** no legal transition matrix (e.g. arbitrary `active` → `active` duplicate). | `498-534`, tests absent | Status governance unspecified. |
| **P2** | **`add_edge` uses `INSERT OR IGNORE`:** silent dedupe; returned row may not match newly generated `edge_id` (`584-603`). | `584-603` | Audit edge identity if duplicates matter. |

**Not P0 in isolated prototype** (P0 if wired to runtime without fixes):

- Missing `write_approval` / `MemoryProvider` / redaction hooks (by design in module docstring `1-7`; integration would be **P0**).
- No semantic injection detector (same class as ReMe/memU; Hermes threat scan at write boundary per architecture).

---

### Recommended acceptance-blocking tests (add before runtime integration)

1. **`test_revise_rejects_non_active_head_and_transition_retract_blocks_search`** — retract then `revise()`; assert conflict or policy.
2. **`test_history_single_active_semantics_or_document_multi_active`** — after revise, assert expected status model (product decision).
3. **`test_multiprocess_add_same_content_single_memory_id`** — N processes, one normalised string; expect one id (or define explicit merge policy).
4. **`test_restore_wrong_profile_and_restore_while_writer`** — negative paths for `718-748`.
5. **`test_fts_cjk_corpus_or_explicit_skip`** — document/tokeniser limits vs Hermes session FTS.
6. **`test_fts_adversarial_query_never_raises`** — operators, quotes, `%`, empty tokens (parity with `hermes_state_search.py:825-859`).
7. **`test_fts_rowid_matches_revision_count`** — projection integrity after corruption injection.
8. **`test_provenance_rejects_unbound_hash`** (once policy exists at provider layer).
9. **Integration:** `MemoryProvider` mock enforcing `memory_caller_scope` + `write_approval` before any `add`/`revise`/`transition`.

---

## Remediation summary

| Priority | Remediation |
|----------|-------------|
| **P1** | Enforce **head status** on `revise()`; define whether older revisions stay `active` or gain `superseded` for audit; test `transition()` fully. |
| **P1** | **Dedupe:** unique partial index or `INSERT ... ON CONFLICT` strategy for `(agent_id, kind, content_hash)` where latest is active. |
| **P1** | **Provenance:** provider computes `source_hash` from redacted transcript bytes; store rejects mismatch when policy enabled. |
| **P1** | **FTS:** port/adapt Hermes sanitizer; decide CJK tokenizer or delegate session search for transcript evidence. |
| **P1** | **Restore:** quiesce writers or copy via SQLite backup API from consistent snapshot; fsync destination. |
| **P2** | Wire `busy_timeout_ms` to PRAGMA; chmod `hermes_home` creation policy; optional symlink re-check before open. |

---

## Final answers

1. **Native vs ReMe/memU:** **Yes** for **maintainability and SoR safety** relative to those adapters, with **documented upstream risks** and **ReMe durability/isolation weaknesses** in source. **No** for claiming overall memory safety or retrieval maturity vs current Hermes + session FTS.

2. **Six tests:** They validate a **useful POC spine** (restart, CAS, dedupe, agent FTS scope, basic MP concurrency, backup round-trip, ownership tamper) but **do not** prove transition semantics, provenance integrity, dedupe under MP races, CJK/FTS parity, restore concurrency, or FTS projection integrity.

3. **Commit as non-runtime prototype:** **Allowed** with clear WIP labelling and no provider registration.

4. **Runtime integration:** **Stay blocked** until P1 items, integration harness, adversarial corpus, and owner/ARB gates in `ARCHITECTURE-AND-GAPS.md` / `EXTERNAL-CODE-AUDIT.md` are satisfied.

5. **Codex HYBRID:** **Endorsed**; treat native ledger score as **architectural fit**, not measured recall or security proof.

6. **LangMem:** **MIT** confirmed independently (not Apache).

## Supervisor triage: reported defects require discriminating tests

The read-only Cursor findings are retained verbatim above, but must not all be treated as proven defects.
- The alleged multiprocess duplicate race requires reproduction: `MemoryV2Store.add()` enters `_transaction()` and executes SQLite `BEGIN IMMEDIATE` **before** its duplicate SELECT and INSERT. A unique index may still be useful, but check transaction serialisation first.
- Historical revisions retaining `status=active` can be intentionally correct as **status at the time**; the latest revision determines effective status. Define and test those semantics rather than mutate historical rows.
- Store-level `source_hash` is caller-supplied by design and cannot independently authenticate transcripts. Provenance must be verified at the **trusted Hermes adapter** boundary before a record enters the ledger.
- Other findings, especially reactivation of a retracted head, FTS/CJK coverage, FTS projection consistency, controlled restore, and silent edge-ignore behaviour, need reproducing tests and explicit architecture/policy decisions before runtime integration.
- This is a review of a prototype, not a sign-off for active memory replacement, merge to main, or deployment.
