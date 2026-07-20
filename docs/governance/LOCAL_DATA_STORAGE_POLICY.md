# Repository-local data storage policy

`local_storage_policy.v1` freezes the repository directory as the only runtime
storage namespace for this project. Active data roots are `data/raw`,
`data/external`, `data/interim`, and `data/generated`; their large local contents
remain subject to `.gitignore` and artifact/manifest governance.

The retired root named `convergence-research-inputs` is historical evidence only.
New tasks must not read from or write to an external sibling data root, and must
not create a symlink, junction, mount, or other compatibility redirection bearing
that retired name. Historical evidence may preserve old locator text only under
`docs/evidence`, `artifacts/local_storage_migration`, or accepted manifests in
`data/generated`; active code, configuration, handoff, task/stage doctrine, and CI
workflow files may not contain a runtime locator to it.

The migration maps the former `r2a_t04` subtree directly to
`data/generated/r2a/r2a_t04`, preserving its internal relative layout. Any other
former content is retained under `data/generated/_legacy_external_archive`.
Migration receipts are local evidence under
`data/generated/_migration_receipts/RETIRE-CONVERGENCE-RESEARCH-INPUTS-20260720`.
The source may be deleted only after byte-for-byte copy verification, accepted
R2A-T04 locator reconciliation, a clean worktree, and successful Quality for the
authorization commit.
