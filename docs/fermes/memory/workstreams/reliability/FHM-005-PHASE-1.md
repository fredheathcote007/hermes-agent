# FHM-005 phase one: provenance and fail-closed completion

## Phase-one durability correction (2026-10-26)

The opt-in stop gate now arms a parent-owned pending marker before each
delegated child can run. The marker is stored in the existing profile-local
verification evidence SQLite store and is bound to the parent session, the
delegation attempt, the child task index, and the parent transport authority.
It is rehydrated at the next parent turn, so eviction or restart before child
verification remains unresolved. Child telemetry may update only an already
armed exact binding; stale, foreign, or late telemetry cannot create or revive
a row. A completed child with no command use and no landed paths retires its
own marker. Failed, unknown, running, or unobservable command outcomes remain
pending and cannot produce `completed=true`; observable completed paths are
retired only after the same opt-in parent verifier has fresh full evidence.

This is durable pending-state/re-hydration hardening, not a trusted verifier.
It does not replay children, treat worker or gateway receipts as proof, change
the default policy, or promote a new security boundary. The independent
verifier execution and authority review gate below remains open.

This branch implements a fail-closed stop policy for explicitly enabled
`agent.verify_on_stop` sessions. Parent turns receive child landed-file paths
from child runtime telemetry, and completion requires fresh, full
`hermes verify` evidence for the same session and each changed project root.
Worker terminal receipts and child completion prose are not independent proof.
If a delegated child used the terminal but landed-file telemetry is absent, the
parent marks the outcome unobservable and fails closed because command-line
edits cannot yet be scoped to paths.
If evidence is missing, stale, foreign-session, failed, or unavailable after
the bounded continuation, the turn returns `completed=false`, `failed=true`,
and `verification_unresolved=true` with an explicit incomplete response.

Legacy opt-in/default behavior is unchanged; this phase makes the existing
opt-in fail closed. Prose-only changes do not enter the gate. No verifier
process is launched by the stop gate, and no worker-provided command or log is
treated as an independent verifier.

## Architecture review gate

Before enabling this policy by default or claiming general independent
verification, ARB must approve a verifier execution boundary that establishes
trusted command selection, bounded process execution, environment/worktree
isolation, output capture, scoped path binding, session provenance, freshness,
and cancellation/resource cleanup. Its evidence must be minted by Hermes after
the verifier process exits, with a machine-readable terminal result. Until that
engine and its trust boundary are reviewed and qualified, this phase may report
work unresolved; it must not invent a successful verdict.

## Owner decision and current limitations

- DEC-004 approves fail-closed completion for delegated/external work; see `docs/fermes/memory/DECISIONS.md`.
- Phase one uses the existing opt-in `HERMES_VERIFY_ON_STOP=1` or `agent.verify_on_stop` configuration; it does not silently change production defaults.
- **P0: Parent-owned pending paths and unknown command effects are in-memory only.** They survive normal turn resets but are not durable across agent eviction or process restart. A detached child can therefore attribute late telemetry to an evicted parent while the replacement agent has no pending marker, creating a false-success risk. Durable pending state or equivalent rehydration is required for full FHM-005 acceptance.
- **P0: Terminal outcomes remain conservatively incomplete when evidence is absent.** Under opt-in verification, missing path attribution or untrusted/missing evidence fails closed. In particular, terminal and `execute_code` use without landed file-tool paths is treated as unobservable, including read-only commands such as `ls` or `git status`; this can produce false-positive incomplete outcomes. FHM-005 remains open until the policy can distinguish harmless reads from effects without weakening the fail-closed guarantee.
- A `hermes verify` ledger entry must not be treated as adversarially independent merely because it has kind=`verify`: child and parent may share the same local execution rights. A separately authorised parent verifier, scoped artifact hashes/versions, fresh post-child receipt and tamper-resistant provenance remain a material design/qualification gate.
- The fallback is deliberately conservative: unobservable command effects may leave a turn incomplete until an operator examines effects; there is no automatic replay or silent success. FHM-005 stays OPEN.
- Focused evidence for this correction is retained in `/tmp/fermes-fhm005-durability-codex.log`; the source-vs-live qualification distinction remains: local source/tests are not hosted CI, live gateway, or trusted-verifier qualification.
