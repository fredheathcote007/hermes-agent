# Fermes Hermes maintenance: Qwen / LM Studio branch

## Scope

This branch begins at the official Hermes `v0.22.5` release, commit
`bf0203a794a07aac3ff764972ab9087baa4e4f4e`. The canonical fork is
`fredheathcote007/hermes-agent`; upstream is `NousResearch/hermes-agent`.

The source changes are limited to LM Studio loaded-instance alias and context
selection, local-provider metadata, reasoning-probe failure handling and tests.
The fork's `main` branch is not changed by this work.

## Remote roles for this local checkout

- `origin` -> `https://github.com/NousResearch/hermes-agent.git` (upstream fetch)
- `fork` -> `https://github.com/fredheathcote007/hermes-agent.git` (fork push)

Check the actual remotes before using commands below; other clones may use
`origin` for the fork and `upstream` for the official source.

## Deliberate upstream adoption (never auto-update a patched build)

1. Make sure the working tree is clean, and retain a known-good release/rollback
   commit before updating. Back up profile state separately from source code.
2. Fetch official tags: `git fetch origin --tags`.
3. Inspect the new official release notes, compare changes and identify overlap
   with the local fixes. If upstream already fixed a local defect, remove the
   redundant fork patch rather than carrying competing implementations.
4. On a throwaway update branch from this maintenance branch, merge the exact
   reviewed release tag, e.g. `git merge --no-ff v0.22.6`. Do not merge an
   unreviewed moving `main` into the qualified branch.
5. Resolve conflicts, run local Qwen/LM Studio regression tests and independent
   review, and only then integrate the update branch and push with `git push fork`.
6. Keep a rollback tag or SHA. Avoid using `hermes update` to advance this
   locally patched source checkout without reviewing its fork/channel policy.

## Current acceptance boundaries

- Focused and adjacent Python unit tests have passed on the Linux host.
- Direct Qwen/LM Studio tool-call output and actual model catalogue metadata
  were observed on Dad-PC; this is not a Hermes-to-LM-Studio end-to-end pass.
- Hermes live integration against the local LM Studio gateway, uninterrupted
  autonomous execution, compaction, memory and self-optimisation are NOT
  qualified by this patch alone.
