# FHM-005 artifact identity candidate

Status: source-only, unconnected candidate primitive. This is not a trusted
verifier, protected controller, receipt store, security release, or proof that
an external effect occurred.

## Scope

`agent/verification_artifacts.py` provides two immutable records and two narrow
observation operations:

- `RootIdentity` binds an absolute lexical root path to its observed POSIX
  device and directory inode.
- `ArtifactIdentity` binds a relative file path, device/inode, size, SHA-256,
  request session, request attempt, and root identity.
- `identify_root()` opens every root component descriptor-relatively with
  `O_DIRECTORY`, `O_NOFOLLOW`, and `O_CLOEXEC` where available.
- `scan_artifact()` traverses relative components from an opened root, rejects
  symlinks, traversal/ambiguous segments, hardlinks, special files, directory
  and mount/device crossings, oversized files, read failures, and changed
  inode/metadata/path bindings. It compares bounded pre/post observations and
  checks that the root path still resolves to the same observed identity.

Request session and attempt IDs are required on every artifact record. The
module owns no consumed-receipt set and has no cross-session acceptance path.
It does not create sockets, execute project commands, inspect external systems,
or acknowledge a worker/tool result as successful.

## Platform boundary and limits

The implementation is POSIX-only. On Windows it explicitly raises
`ArtifactUnsupportedError` with `UNSUPPORTED` status because this candidate
does not implement defensible volume/file identifiers and reparse-point-safe
native traversal. Native Windows acceptance tests are pending. Windows must
not silently reuse the POSIX device/inode model, and this candidate does not
reduce DEC-005's requirement for both native operating systems.

The descriptor and post-read checks reduce path substitution and concurrent
mutation races, but they cannot prove that a path was not changed and restored
after the final observation, or that a privileged process/kernel did not
interfere. Directory-root replacement after an already-open descriptor is
detected when the named root can be reopened; a change that is fully restored
before all checks is a residual TOCTOU limitation. These are observations, not
authoritative or guaranteed evidence.

This code is intentionally not imported by runtime completion, the TUI, CLI,
gateway, installer, agent invocation, or FHM-007. A future controller would
need separately approved authority, durable one-use receipt storage, native
Linux and Windows qualification, process containment, and effect-specific
readback before any trust claim could be considered.

## Security-review clarifications (Cursor)

- Root paths must be absolute and lexically canonical; relative roots depend on mutable CWD and are rejected. File paths refuse path-ambiguous Unicode formatting controls and non-NFC names rather than silently normalising them.
- `ArtifactIdentity.contract_digest` is only a `sha256:`-prefixed presentation helper for the pre-existing request/receipt shape; it is not independently authenticated proof, and it is never sufficient to retire a pending memory or delegated effect.
- The filesystem test guard wraps `os.open` and `os.stat`; checking the underlying registered descriptor capability via `inspect.unwrap` accommodates this isolated test environment without bypassing `dir_fd`, `O_NOFOLLOW` or pre/post inode checks.
- The scan has a byte ceiling but **no guaranteed elapsed-time bound** on a stalled kernel or FUSE/NFS read. Same-device bind mounts and races fully restored between observations cannot be ruled out. These require protected controller policy, sandbox timeouts, quiescence and native Linux/Windows qualification before any security/availability claims. Windows remains explicitly `UNSUPPORTED`, not PASS.
