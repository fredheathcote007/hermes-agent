# FHM-005 — Native acceptance and adversarial test matrix

status: PROPOSED / NOT EXECUTED
scope: Same candidate SHA must pass natively on Linux and Windows.

| Test gate | Linux | Windows | Required outcome |
|---|---|---|---|
| Receipt provenance | Fake/modify service-owned record; wrong session/attempt/root; replay | Pipe impersonation, ACL tampering, same false records | No unrelated or stale receipt can produce VERIFIED |
| Workspace identity/TOCTOU | Symlink, hardlink, rename, mount swap; concurrent sessions | Reparse point, junction, path case/volume, file locking, rename | Version or object identity mismatch yields INCOMPLETE |
| Trusted/untrusted execution | Project test tries receipt-store/credential read; arbitrary egress/write | Restricted-token attempt; pipe/secrets/outside-root access | Untrusted test cannot access trusted resources |
| Process quiescence | Timeout/grandchild/held pipe/detached writer; PID reuse | Job Object escape, descendant, pipe, PID reuse | No receipt until all owned effects are quiescent |
| Crash and persistence | SIGKILL parent/controller at arm, dispatch, verify, consume | Same plus service restart/reboot/logoff | Durable UNKNOWN, no auto replay |
| UI/gateway states | Missing proof/failed check/unavailable verifier | Same | No surface renders COMPLETE for unresolved work |
| External effects | Browser/CLI/API action accepted but readback absent or delayed | Same | Remain INCOMPLETE unless authoritative scoped readback |
| Install/upgrade/rollback | Wrong UID/socket owner, missing sandbox, failed update | Wrong SID/DACL, interactive fallback, failed update | Trusted mode unavailable; prior receipts fenced |
| Privacy and governance | Inject secrets and personal paths into tool output | Same | No protected receipt or prompt leaks sensitive values |
| Supply chain | Untrusted recipe tries shell injection | Untrusted recipe tries command/path injection | Never execute under controller identity |

**Release rule:** No skipped, environment-blocked, simulated-host or timed-out native security test is counted as PASS. Linux and Windows must both pass on same qualified candidate. Phase-one/PR22 evidence does not establish these checks.

See [ARB review](ARB-REVIEW-20261027.md) and original [reviewer evidence](review-evidence/FIRST-PASS-ALL.md).
