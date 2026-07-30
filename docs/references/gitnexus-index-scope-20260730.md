# GitNexus Index Scope Evidence

- Status: Current maintenance evidence
- Ticket: GitHub #129
- Measurement date: 2026-07-30
- Repository alias: `llm-abm-marketing-sim`
- Attached branch: `main`
- Policy: tracked root `.gitnexusignore`
- Exact regenerable cache root: `.gitnexus/`
- Retention manifest: `configs/retention/manifest.json` (`.gitnexus` cache evidence)
- Producer: `GITNEXUS_NO_GITIGNORE=1 gitnexus analyze <repo-root> --name llm-abm-marketing-sim --skip-agents-md --force`

This evidence is aggregate-only. It records paths, counts, graph metadata and
commands; it does not read, hash, print or publish raw research records,
provider payloads, prompts, headers or secrets.

## Scope Contract

The forced project command deliberately bypasses `.gitignore`. GitNexus
confirmed during all four rebuilds:

> GITNEXUS_NO_GITIGNORE is set - skipping .gitignore (still reading .gitnexusignore)

`.gitnexusignore` therefore owns the explicit index boundary for this command.
It excludes:

- `runs/`, archive payload below `archive/*/`, and raw/processed research payload;
- `.env*`, virtual environments, `node_modules`, `*.egg-info`, Python caches,
  coverage caches, browser output, build output, temporary directories, logs and
  traces;
- generated agent/tool scratch below the selected `.omx/` directories.

It intentionally keeps source, tests, configs, scripts, release validators,
renderer/rebuild code and durable Markdown. The policy has explicit exceptions
for the lightweight `README.md` and `archive_manifest.json` files that explain
retention and lineage:

- `data/README.md` and the data-directory README files;
- `archive/jinjiang-historical-runs-20260623T022534Z/README.md`;
- `archive/jinjiang-historical-runs-20260623T022534Z/archive_manifest.json`.

The policy does not delete or move any release, dataset, archive or user file.
It only controls the GitNexus reader; the exact local cache is the only root
reset in this Ticket.

## Reset Safety

Before reset:

- `git status --short` was clean at policy commit `0a49440`;
- the active-analysis process check returned no analyzer process;
- `.gitnexus` was a regular directory and `test -L .gitnexus` returned
  `symlink=no`;
- the retention auditor baseline recorded 20 regular files and
  `6,125,569,188` aggregate bytes for this exact root;
- the manifest entry sets `classification=reproducible-ephemeral`,
  `planned_action=delete`, `cache_evidence.exact_root=.gitnexus`, and records
  the GitNexus producer plus status/query rebuild validation;
- `gitnexus clean -f` reported only:
  `Deleted: /Users/liuqingyuan/work/llm-abm-marketing-sim/.gitnexus`.

No `archive/`, `data/`, `runs/`, release or dataset root was passed to cleanup.

## Measurements

The existing index was stale and indexed commit `d8f0432`. The bounded rebuild
ran at policy commit `0a49440`; the repeat rebuild used the same exact command
and commit. The evidence commit rebuild ran at `f8df887`, and the final
measurement rebuild ran at `0e591e8`; both included the tracked evidence. A
subsequent current-HEAD rebuild reproduced the final graph metrics. `communities`
and `processes` are the GitNexus metadata names for the Ticket's clusters and
flows.

| Measure | Before reset | Policy rebuild | Repeat policy rebuild | Evidence commit rebuild | Final measurement rebuild |
|---|---:|---:|---:|---:|---:|
| Indexed commit | `d8f0432` | `0a49440` | `0a49440` | `f8df887` | `0e591e8` |
| Regular index files | 20 | 14 | 14 | 14 | 14 |
| Regular-file aggregate bytes | 6,125,569,188 | 125,779,188 | 125,779,188 | 125,857,260 | 125,857,260 |
| Nodes | 49,614 | 8,359 | 8,359 | 8,366 | 8,366 |
| Edges | 55,132 | 14,123 | 14,123 | 14,132 | 14,132 |
| Clusters (`communities`) | 198 | 208 | 208 | 208 | 208 |
| Flows (`processes`) | 300 | 300 | 300 | 300 | 300 |
| Hashed repository files | not recorded in baseline | 224 | 224 | 225 | 225 |

The policy rebuild reclaimed `5,999,790,000` bytes; the final measurement
rebuild reclaimed `5,999,711,928` bytes. A later read-only context/auditor
observation measured `125,853,164` regular-file bytes after database lifecycle
compaction, with the same 14 files and graph counts. Filesystem block
allocation (`du -sk`) was `5,982,040 KiB` before reset and varied between
`130,556 KiB` and `130,796 KiB` across rebuilds; these storage observations are
volatile and are not fixed test constants.

The first policy rebuild had 224 hashed files: `src=57`, `tests=57`, `configs=16`,
`scripts=9`, and `docs=72`. The evidence and final measurement commits had 225
hashed files with `docs=73`; the other root counts were unchanged.
A path-key scan found zero payload-like raw/processed JSON, JSONL, CSV, TSV or
ZIP entries. The only keys under those high-level roots were the five explicit
README/manifest exceptions listed above.

## Rebuild Validation

Four runs used the current-workspace form of the project command:

```bash
GITNEXUS_NO_GITIGNORE=1 gitnexus analyze \
  /Users/liuqingyuan/work/llm-abm-marketing-sim \
  --name llm-abm-marketing-sim --skip-agents-md --force
```

The policy run completed in 9.7 seconds, the repeat in 7.0 seconds, the
evidence-commit rebuild in 6.9 seconds and the final measurement rebuild in
6.9 seconds. The first two reported `8,359 nodes | 14,123 edges | 208 clusters |
300 flows`; the last two reported `8,366 nodes | 14,132 edges | 208 clusters |
300 flows`. All four explicitly reported that `.gitnexusignore` was still read.
`gitnexus status` after the final measurement run reported:

```text
Indexed commit: 0e591e8
Current commit: 0e591e8
Status: up-to-date
```

The repeat, final measurement and current-HEAD forced rebuilds did not
re-absorb `runs/`, raw/processed payload, archive payload or generated scratch.
The source graph remained queryable. Because the local GitNexus registry contains
multiple repositories, symbol and query commands use the explicit alias
`-r llm-abm-marketing-sim`.

The post-rebuild retention audit command was:

```bash
. .venv/bin/activate
python scripts/audit_retention.py --repo-root . --manifest configs/retention/manifest.json
```

It returned exit code `2` because three `unknown` roots remain deferred and
`ready_for_cleanup=false`; the structured output reported `Violations - none`.
Its exact `.gitnexus` approved cache action observed 14 regular files and
`125,853,164` aggregate bytes. No delete/apply operation was performed.

Successful exact context smoke results:

- `render_report` in `src/llm_abm_sim/concurrent_message_renderer.py`:
  found exact; incoming `rebuild_concurrent_message_report` and outgoing
  renderer calls returned.
- `rebuild_concurrent_message_report` in
  `src/llm_abm_sim/concurrent_message_report.py`: found exact; renderer,
  artifact-closure calls and process flows returned.
- `validate_release` in `scripts/validate_abm_report_release.py`: found exact;
  validator callers, callees and processes returned.
- `ConcurrentMessageExperimentRunner` in
  `src/llm_abm_sim/concurrent_message_experiment.py`: found exact; package and
  architecture imports plus runner methods returned.

The following query smokes also returned process/definition results:

```bash
gitnexus query 'concurrent message runner' -r llm-abm-marketing-sim -l 3
gitnexus query 'release validation' -r llm-abm-marketing-sim -l 3
```

## Mermaid Alignment

The eight Mermaid diagrams already attached to issue #129 remain authoritative
for this Ticket. The final implementation matches them as follows:

- Current/target architecture: the forced command can bypass `.gitignore`,
  then reads tracked `.gitnexusignore` before producing a bounded source graph.
- Current/target sequence: retention audit and exact-root safety precede
  `clean -f`, forced rebuild, status check and symbol/query validation.
- Current/target state: the cache moves from stale-large to
  policy-tracked/reset-approved/building-bounded/current-bounded/query-validated.
- Current/target class relation: policy, analyze producer, exact index status
  and core symbol/query smoke remain the local responsibilities; release and
  renderer source stay in the indexed graph.

No live LLM, TikHub, Douyin, profile API, deployment or network research call
was triggered by this Ticket. No secret was read, printed or written.
