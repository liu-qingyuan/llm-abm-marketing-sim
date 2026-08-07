# Repository Retention Cleanup Final Evidence

- schema: `retention-final-evidence-v1`
- Ticket: `#131`
- branch: `main`
- measurement scope: exact manifest roots, approved cleanup actions, release contract/source pairs, durable documentation and bounded GitNexus cache
- status: `passed` with deferred human decisions

## Scope And Sources

本记录是 aggregate-only final evidence。它组合 Ticket #126 的只读 manifest audit、#127 的 documentation current-truth evidence、#128 的三个 generator output contract、#129 的 bounded GitNexus evidence、#130 的 exact cleanup execution 和本 Ticket 的 documentation consolidation。每个 release validation 都使用显式的 v4 contract/source pair；没有 latest discovery、contract rewrite、schema rewrite 或新的 cleanup registry。

- [Retention machine evidence](retention-cleanup-execution-20260730.json)：exact cleanup file/directory evidence，作为 forensic-only machine entry 保留。
- [Current Editorial v3 release evidence](jinjiang-concurrent-message-editorial-v3-formal-release-20260807.md)
- [Editorial v2 rollback release evidence](jinjiang-concurrent-message-editorial-v2-formal-release-20260807.md)
- [Editorial v1 rollback release evidence](jinjiang-concurrent-message-editorial-formal-release-20260729.md)
- [Original Formal release evidence](jinjiang-concurrent-message-formal-release-20260727.md)
- [Two-mode rollback release evidence](jinjiang-concurrent-message-two-mode-formal-release-20260728.md)

## Initial v1 Retention Baseline

Ticket #126 的只读 dry-run 是 historical planning evidence，稳定聚合值如下；它不再是当前 CLI 的输入：

| field | value |
|---|---:|
| schema | `retention-audit-v1` |
| ready for cleanup | `false` |
| aggregate bytes | `6,475,441,711` |
| protected bytes | `640,291,495` |
| lineage bytes | `5,187,512,688` |
| unknown bytes | `242,067,362` |
| protected roots | `6` |
| approved candidates | `9` |
| human-review roots | `5` |
| deferred unknowns | `3` |

该 baseline 的 violations 为 `none`；approved candidate actions 共 `5,180` 个 exact file actions。root-level allowlist、directory postconditions、human-review roots 和 deferred unknown identities 的后续 closure 由 execution table、machine JSON 和当前 manifest 共同保留。

## Aggregate Measurements


所有 byte measurement 都是 regular-file bytes；不把 filesystem block allocation、`.git`、`.venv`、`node_modules` 或 `.omx` 混入 retention action scope。不同阶段分别记录，避免用变动 cache 的历史 baseline 与后续实际值做伪精确相减。

| measurement window | before bytes | after bytes | observed reclaimed | method |
|---|---:|---:|---:|---|
| #126 initial approved action baseline | `6,475,441,711` | n/a | baseline only | read-only auditor aggregate |
| #129 GitNexus exact reset/rebuild | `6,125,569,188` | `125,853,164` | `5,999,716,024` | exact `.gitnexus` regular-file sum before/after bounded rebuild |
| #130 cache/duplicate exact cleanup | `475,726,860` | `125,853,164` | `349,873,696` | exact allowlist file hashes, sizes and empty-directory postconditions |
| cleanup phases observed total | n/a | n/a | `6,349,589,720` | sum of the two independent execution windows above |

#130 removed `5,161` regular files and `263` verified-empty directories across `8/8` applied roots. No partial or failed-closed action was reported. The closing retention audit observes `14` approved `.gitnexus` files and `125,928,016` approved bytes; the cache remains rebuildable and is not a deletion target in this Ticket.

## Cleanup Execution Closure

Ticket #130 只允许 tracked allowlist 中的 exact roots；`.gitnexus` 当时明确 skipped，交由独立 GitNexus scope work 处理。逐 root execution evidence 如下：

| root | evidence kind | status | files removed | bytes reclaimed | directories removed |
|---|---|---|---:|---:|---:|
| `.mypy_cache` | `cache` | `applied` | `4,949` | `175,567,460` | `247` |
| `.pytest_cache` | `cache` | `applied` | `6` | `75,099` | `3` |
| `.ruff_cache` | `cache` | `applied` | `137` | `236,614` | `5` |
| `playwright-report` | `cache` | `applied` | `1` | `529,332` | `1` |
| `runs/issue-28-final-research-offline-v2` | `duplicate` | `applied` | `9` | `3,500,115` | `1` |
| `runs/jinjiang-concurrent-message-mock-validation-20260726T202200Z` | `duplicate` | `applied` | `23` | `83,277,240` | `1` |
| `runs/jinjiang-concurrent-message-mock-validation-20260726T203300Z` | `duplicate` | `applied` | `23` | `83,277,240` | `1` |
| `test-results` | `cache` | `applied` | `13` | `3,410,596` | `4` |
| `.gitnexus` | `cache` | `skipped` | `14` | `125,853,164` | `0` |

Aggregate execution result: `5,161` regular files, `349,873,696` reclaimed bytes and `263` empty directories; `8` roots fully applied, `0` partial and `0` failed-closed. Duplicate candidates were checked against complete retained file sets and SHA-256 maps before deletion. The exact file and directory records remain in [Retention machine evidence](retention-cleanup-execution-20260730.json).

Preflight and safety boundaries were: auditor rerun with `violations=0`; protected roots `6` and lineage roots `2` verified before/after; `.venv`, `node_modules`, raw profile evidence, historical archive, final dataset, latent-v1 dataset/config, release roots and unknown candidates were not deletion targets; no recursive root deletion, glob expansion, date-based selection, payload inspection, deployment, archive move or rollback-root mutation. Secrets and live API/provider/TikHub/Douyin calls were both `false`.

## Current Retention Audit (v2)

Command:

```bash
.venv/bin/python scripts/audit_retention.py \
  --repo-root . \
  --manifest configs/retention/manifest.json \
  --format json
```

Current result: `audit_valid=true`, `violations=0`, exit `0`, `protected_roots=6`, `lineage_roots=2`, `reproducible_ephemeral_roots=1`, `unresolved_roots=3`. Unknown roots remain retained and deferred; current v2 audit does not treat their classification as a violation.

| classification | roots | observed bytes | final action |
|---|---:|---:|---|
| `contract-protected` | `6` | `640,291,495` | retain |
| `lineage-only` | `2` | `5,187,512,688` | retain / human review |
| `unknown` | `3` | `242,067,362` | defer; retain |

The six protected roots include the original Formal source, two-mode rollback destination, current Editorial destination, final real processed dataset, latent-v1 validation dataset and latent generation config. The raw profile evidence and historical archive remain in place. The three exact unknown identities remain retained:

- `runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T012728Z`
- `runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-editorial-20260729T130742Z`
- `runs/jinjiang-field-lineage-mock-validation-20260720T105313Z`

没有 cold-storage destination，因此没有 externalize、move、compress 或 delete raw profile evidence、historical archive 或 unknown roots。

## Release Contract Closure

The existing single `validate_release(...)` Interface was run three times with `--require-formal-production`:

| purpose | explicit contract | explicit source | result | report SHA-256 | artifact manifest SHA-256 |
|---|---|---|---|---|---|
| original Formal | `configs/deployments/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z.json` | `runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z` | passed | `740f55a30bc4183a75724592496c6b6aa809a85ab385ccf96bc53093cb49a76d` | `bfc793bb7322edabe6fb5eb4cce7e6990ca008a8cb0310e19507b9c14839063d` |
| two-mode rollback | `configs/deployments/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-two-mode-20260728T112653Z.json` | `runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-two-mode-20260728T112653Z` | passed | `ba006c5e18d091a77e8eebd73e86287209ccaf2571023d1114e35fd64872f556` | `cac6fca8e94c55518d902853dd91f82071b90c7cbd6b640043e13fbf32e6734f` |
| current Editorial | `configs/deployments/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-editorial-20260729T131839Z.json` | `runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-editorial-20260729T131839Z` | passed | `1d1e1ead3691aa275c74ff723a79960019c42fd58f179d8b74619f0a0b218ea9` | `309ca67a3d3f5214b462ee9333a41cc157ca6952f2c0ef21abf214daa45b969b` |

Each v4 source closure has `23` regular artifacts and no symlink/path escape. The original Formal report-only rebuild returned the existing `report.html`, kept `23` files before/after, and the independent full-tree hash closure reported `changed_files=0`, `decision_changed=0`, `symlinks=0`; its contract and `artifact_manifest.json` stayed unchanged and report SHA-256 stayed `740f55...`. No Provider call, Decision Adapter run or persisted `3,600`-row Decision rewrite occurred. Current Editorial and two-mode rollback retain their own explicit expected report/manifest identities and release lineage.

## Documentation And Generator Gates

- Documentation Navigation Contract plus tracked Markdown local-link scan: `35 passed`; `git diff --check` passed.
- Generator destination coverage proves profile default run-local output, explicit curated output, scope default derived-run output, explicit report override, topic required-output fail-fast and explicit aggregate report output. No new正文 was written to `docs/04-开发验证/`.
- Final real dataset, latent-v1 dataset, latent config and authoritative audit references remain discoverable from `docs/index.md`; current Editorial, current architecture and historical Status markers remain linked.

## Bounded GitNexus Closure

The current bounded index is governed directly by tracked [`.gitnexusignore`](../../.gitnexusignore). The closing command remains:

```bash
GITNEXUS_NO_GITIGNORE=1 gitnexus analyze \
  /Users/liuqingyuan/work/llm-abm-marketing-sim \
  --name llm-abm-marketing-sim --skip-agents-md --force
```

The current bounded index reports `14` regular files, `0` symlinks, `7,951` nodes, `13,545` edges, `212` clusters and `300` flows; regular-file bytes vary with GitNexus database compaction and are not a fixed contract. `gitnexus status` reports the indexed commit equals the current `main` commit and `Status: up-to-date`. Four core-symbol context smokes (`render_report`, `rebuild_concurrent_message_report`, `validate_release`, `ConcurrentMessageExperimentRunner`) and two query smokes returned successfully. The forced command confirmed `.gitnexusignore` is read while `.gitignore` is bypassed and did not re-absorb runs/data/archive payload.

Historical bounded scope measurements retained from the reset/rebuild closure:

| measurement | regular files | regular bytes | nodes | edges | clusters | flows |
|---|---:|---:|---:|---:|---:|---:|
| before reset | `20` | `6,125,569,188` | `49,614` | `55,132` | `198` | `300` |
| policy rebuild | `14` | `125,779,188` | `8,359` | `14,123` | `208` | `300` |
| repeat policy rebuild | `14` | `125,779,188` | `8,359` | `14,123` | `208` | `300` |
| evidence commit rebuild | `14` | `125,857,260` | `8,366` | `14,132` | `208` | `300` |
| final measurement rebuild | `14` | `125,857,260` | `8,366` | `14,132` | `208` | `300` |
| later read-only observation | `14` | `125,853,164` | `8,366` | `14,132` | `208` | `300` |

The path-key scan found zero raw/processed JSON, JSONL, CSV, TSV or ZIP payload entries under indexed high-level roots; the only retained data/archive keys were explicit README/manifest exceptions. These historical measurements are evidence only; the tracked policy and current `gitnexus status` are authoritative for a new rebuild.

## Quality And Boundaries

- `.venv/bin/pytest -q`: `541 passed, 2 deselected`.
- `.venv/bin/python -m py_compile $(find src tests scripts -name '*.py' -print)`: passed.
- `.venv/bin/ruff check src tests scripts`: passed.
- `npx --yes pyright --pythonpath .venv/bin/python src/llm_abm_sim/data_sources tests scripts`: `0 errors, 0 warnings, 0 informations`.
- Focused Navigation/Retention/Concurrent checks: `35 passed`; `git diff --check` passed.
- `ruff format --check` across the historical source/test scope still reports `35` pre-existing files that would be reformatted; no unrelated formatter sweep was included in this Ticket.

No LLM Provider, TikHub, Douyin, profile API or deployment was run. No `.env`, credential, header, raw Prompt, raw Provider payload or user-level record was read into this evidence. No release contract, persisted schema, canonical endpoint, remote `current` symlink or retained root was modified.
