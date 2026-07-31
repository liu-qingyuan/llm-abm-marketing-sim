# Retention Audit

Status: Implemented current architecture note

本 Note 记录 Retention Module 的只读审计合同。历史 baseline、cleanup execution 和 GitNexus measurements 已收敛到唯一 human-readable 的 [Retention final evidence](../references/retention-cleanup-final-evidence-20260730.md)；exact cleanup machine JSON 只作为 forensic-only 入口保留，不属于当前 CLI 的输入或输出合同。

## Supported Interface

```python
from llm_abm_sim.retention import RetentionAuditResult, audit_retention, render_retention_report

result = audit_retention("configs/retention/manifest.json", repo_root=".")
```

`configs/retention/manifest.json` 是当前唯一 tracked `retention-manifest-v2` policy manifest。manifest 必须是仓库内 canonical、regular、non-symlink 文件，并通过 Git tracked-file 查询；工作树可以带有 manifest 的合法修改。audit 只读取 manifest、显式 machine identity evidence 和 filesystem metadata，不打开、hash 或输出 configured roots 的内容。

## Audit Semantics

审计依次验证：

1. manifest provenance、Git tracking、canonical path 和 symlink safety；
2. root identity、root type、evidence path 和 structured JSON identity；
3. root 的 regular-file count、directory count 和 observed bytes。

`audit_valid=true` 表示 explicit-root policy 的结构与 identity 合法；它永不授权删除、移动、压缩或其他 filesystem action。unknown roots 保持 unresolved，但不因 classification 本身产生 violation。机器 evidence 只用于需要 identity binding 的 contract-protected、lineage-only 和 reproducible-ephemeral roots。

## Current Classification

当前 manifest 保持：6 个 `contract-protected` roots、2 个 `lineage-only` roots、1 个 `reproducible-ephemeral` root、3 个 `unknown` roots。`.gitnexus` 的 evidence reference 直接指向 tracked [`.gitnexusignore`](../../.gitnexusignore)，由该文件持有 index boundary；必要历史 measurements 收敛在 Retention final evidence，不依赖易过期的 source-tree inventory。

Formal/release roots 不能仅按其位于 `runs/` 目录而删除；普通未受合同保护的 run 输出可以删除后重建，但必须由独立 exact-path、明确授权的 Ticket 决定任何 cleanup action。Retention Module 不提供 apply、delete、move、storage 或 cleanup adapter。

## Verification

离线验证命令：

```bash
. .venv/bin/activate
python scripts/audit_retention.py \
  --repo-root . \
  --manifest configs/retention/manifest.json \
  --format json
```

通过标准是 `audit_valid=true`、`violations=[]`、exit 0，并保留 6 个 `contract-protected`、2 个 `lineage-only`、1 个 `reproducible-ephemeral` 和 3 个 `unknown` roots。unknown roots 继续 retain，但不因 deferred classification 使当前只读 audit 失败。machine JSON、baseline、execution 和 final evidence 的历史测量不写入测试常量；完成报告只记录本次观察值。
