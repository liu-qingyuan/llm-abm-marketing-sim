# Retention Cleanup Execution Evidence

- schema: `retention-execution-v1`
- ticket: `#130`
- status: `applied`
- operation_time_utc: `2026-07-30T10:20:07.916242+00:00`
- git_head: `c02b1592f87bfd418726929fd82a66b29c2a7761`
- manifest_sha256_before: `fec99a1ec8274b39fa108d94e19c9838ebc40efe7086890c1acde26adefe461d`
- manifest_sha256_after: `24b743a0055e75718f7d0c20da4f52945ddf2d0605e480b09e1af38600cee6c0`

## Scope

Only roots in the tracked Ticket #130 allowlist were eligible. The independent GitNexus cache was explicitly excluded.

| root | evidence kind | status | files removed | bytes reclaimed | directories removed |
|---|---|---|---:|---:|---:|
| `.mypy_cache` | `cache` | `applied` | 4949 | 175567460 | 247 |
| `.pytest_cache` | `cache` | `applied` | 6 | 75099 | 3 |
| `.ruff_cache` | `cache` | `applied` | 137 | 236614 | 5 |
| `playwright-report` | `cache` | `applied` | 1 | 529332 | 1 |
| `runs/issue-28-final-research-offline-v2` | `duplicate` | `applied` | 9 | 3500115 | 1 |
| `runs/jinjiang-concurrent-message-mock-validation-20260726T202200Z` | `duplicate` | `applied` | 23 | 83277240 | 1 |
| `runs/jinjiang-concurrent-message-mock-validation-20260726T203300Z` | `duplicate` | `applied` | 23 | 83277240 | 1 |
| `test-results` | `cache` | `applied` | 13 | 3410596 | 4 |
| `.gitnexus` | `cache` | `skipped` | 14 | 125853164 | 0 |

## Aggregate

- removed regular files: `5161`
- reclaimed bytes: `349873696`
- removed empty directories: `263`
- fully applied roots: `8`
- partial roots: `0`
- failed-closed roots: `0`
- exact machine-readable file and directory evidence: `docs/references/retention-cleanup-execution-20260730.json`

## Preflight

- auditor rerun: `true`
- auditor violations: `0`
- auditor ready_for_cleanup: `false`
- `ready_for_cleanup=false` remained because human-review and unknown roots were intentionally preserved; scoped approved roots had no violations.
- duplicate candidates were rechecked against the retained root's complete regular-file set and SHA-256 map before deletion.
- persisted duplicate verification records: `3`; each includes candidate/retained roots, complete relative-file set, candidate/retained SHA-256 maps, byte totals, and empty missing/extra/hash-mismatch results.
- cache actions were limited to exact manifest roots and their recorded producer/rebuild evidence.

## Preserved Boundaries

- protected roots verified before/after: `6`
- lineage roots verified before/after: `2`
- explicitly excluded root: `.gitnexus` (`explicitly reserved for the independent GitNexus index Ticket`)
- `.venv`, `node_modules`, `.omx`, raw profile evidence, historical archive, final dataset, latent-v1 dataset/config, release roots, and unknown candidates were not deletion targets.

## Skipped And Post-Audit

- `.gitnexus`: `explicitly reserved for the independent GitNexus index Ticket`; approved actions were not executed by this Ticket.

- post-audit violations: `0`
- post-audit ready_for_cleanup: `false`
- successfully removed roots were removed from the tracked manifest before this post-audit; regenerated ordinary caches are therefore not treated as historical evidence.

## Safety And Access

- secrets read: `false`
- live API/provider/TikHub/Douyin calls: `false`
- filesystem mutation was limited to the exact approved regular files and empty directories listed in the machine-readable evidence.
- no recursive root deletion, glob expansion, date-based selection, payload inspection, deployment, archive move, or rollback-root mutation was used.
