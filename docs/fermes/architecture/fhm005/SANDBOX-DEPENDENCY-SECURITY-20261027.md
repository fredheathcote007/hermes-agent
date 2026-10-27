# FHM-005 — Linux worker sandbox dependency security gate

**Date:** 2026-10-27
**Design-branch baseline SHA:** `dac20ffbeaf63c3d923a0e887c83e4c596f7781f` (not a qualified runtime image; the older implementation-state SHA records its historical milestone baseline)
**Status:** P0 release condition; current host is not qualified for hostile-worker execution
**Scope:** proposed Linux worker sandbox only; no package update, installation, deployment, or
FHM-007 change is authorized by this note

## Decision-relevant finding

The Project Coordinator host is Ubuntu 26.04.1 LTS and currently has:

```text
Package:   bubblewrap
Installed: 0.11.1-1ubuntu0.3
Candidate: 0.11.1-1ubuntu0.3
Binary:    /usr/bin/bwrap, mode 0755 (-rwxr-xr-x), not setuid
```

The upstream [GHSA-pxhw-h44j-8pfx / CVE-2026-87766](https://github.com/containers/bubblewrap/security/advisories/GHSA-pxhw-h44j-8pfx)
lists all bubblewrap versions below `0.12.0` as affected and `0.12.0` as fixed. The issue is a
setup-time symlink traversal: when bubblewrap creates files using attacker-controlled filesystem
content, a symlink can redirect creation outside the sandbox. The upstream advisory says the
arguments are not normally attacker-controlled, so applicability depends on the exact bwrap
arguments and whether the worker can supply or influence untrusted paths. This finding does not
prove that this host or any user system has been exploited.

[Ubuntu USN-8779-2](https://ubuntu.com/security/notices/USN-8779-2) records that the earlier Ubuntu
fix for CVE-2026-87766 introduced a Flatpak regression and was reverted pending a complete fix. It
lists `0.11.1-1ubuntu0.3` for Ubuntu 26.04. Therefore the installed package and the current apt
candidate must be treated as unpatched for this FHM-005 gate, notwithstanding the Ubuntu package
revision and the fact that the executable is non-setuid. Non-setuid mode reduces privilege impact;
it does not remove the path-integrity risk for files writable by the launching identity.

## Gate interpretation

The local inventory is a **host preflight PASS** only for identifying the package, candidate, binary
mode, and absence of the setuid bit. It is a **sandbox dependency BLOCK** for the proposed worker
boundary because the selected version is below the upstream fixed version.

No bwrap invocation with attacker-controlled input was performed. No hostile-worker test, filesystem
write test, or containment qualification was performed. Consequently, this worktree has **no hostile-
worker PASS** and must not report one. Under DEC-004/006/007, the trusted verifier remains unavailable
or incomplete rather than successful until the dependency and the complete native containment gate
are independently qualified on the exact candidate SHA. This note is not owner authorization to
install a service, change OS security policy, update a package, enable trusted mode, or accept an
outstanding High/Critical risk.

## Non-mutating host preflight

These commands inspect local package metadata and file attributes only. They do not invoke `bwrap`,
consume attacker-controlled paths, contact a package repository, update packages, or write to the
host:

```sh
sed -n '1,20p' /etc/os-release
dpkg-query -W -f='${binary:Package}\n${Status}\n${Version}\n${Architecture}\n' bubblewrap
dpkg-query -S /usr/bin/bwrap
apt-cache policy bubblewrap
stat -c 'path=%n mode=%a (%A) uid=%u gid=%g' /usr/bin/bwrap
find /usr/bin/bwrap -maxdepth 0 -perm /4000 -printf 'setuid_or_setgid=%m\n'
dpkg --verify bubblewrap
```

Interpret `dpkg --verify` as package-file evidence only, not as a vulnerability-fix or hostile-worker
test. On this host it returned exit status 0 while reporting missing documentation files; that does
not change the package version or establish sandbox safety. If available, a security-approved
preflight may also inspect file capabilities without executing the binary:

```sh
getcap -n /usr/bin/bwrap
```

The release record must retain the exact package version, selected executable path, file mode and
privilege metadata, apt candidate, host release, source SHA, and security approval identity. A
successful inventory command is never a substitute for adversarial native qualification.

## Safely approvable paths

One of the following must be explicitly reviewed and approved before a Linux worker may use a
bubblewrap-based boundary with untrusted content:

1. **Verified fixed binary.** Precheck the exact executable selected by the worker launcher and
   require a patched/fixed bubblewrap release at or above `0.12.0`, obtained from a source whose
   provenance, integrity, and signature or equivalent verification have been approved by security.
   Rechecking only the Ubuntu revision, or finding a different binary elsewhere on `PATH`, is not
   sufficient. This option does not authorize the update itself.
2. **Avoid the vulnerable use.** Do not pass untrusted filesystem content or attacker-influenced
   paths to the unpatched bubblewrap. Use a qualified systemd user/process isolation design together
   with a trusted container or VM whose identity, path boundary, protected-state access, descendant
   containment, and failure behavior have been demonstrated for this threat model. Plain systemd
   sandboxing alone is not sufficient evidence of an equivalent boundary and must not be claimed as
   the fix.

If neither path is qualified, the Linux worker must remain disabled for hostile or untrusted content
and route to the existing opt-in fail-closed/manual or external-attestation fallback. Any future
qualification must cover the actual launcher arguments and path sources; version inventory alone
cannot establish applicability or safety.

## References

- [Bubblewrap GHSA-pxhw-h44j-8pfx / CVE-2026-87766](https://github.com/containers/bubblewrap/security/advisories/GHSA-pxhw-h44j-8pfx)
- [Ubuntu USN-8779-2: Bubblewrap regression](https://ubuntu.com/security/notices/USN-8779-2)
- [FHM-005 validation plan](VALIDATION-PLAN.md)
- [FHM-005 implementation state](IMPLEMENTATION-STATE.md)
- [DEC-004–DEC-007](../../memory/DECISIONS.md)
