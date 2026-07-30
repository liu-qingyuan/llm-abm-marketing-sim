# Retention Audit

Status: Implemented current architecture note

本 Note 记录当前 Retention Module 的只读审计合同。历史 v1 baseline、cleanup execution 和 duplicate verification evidence 继续保留为不可重新执行的 lineage；它们不属于当前 CLI 的输入或输出合同。

## Supported Interface

Retention Module 的受支持直接接口只有：

```python
from llm_abm_sim.retention import RetentionAuditResult, audit_retention, render_retention_report

result = audit_retention("configs/retention/manifest.json", repo_root=".")
```

`manifest_path` 必须是仓库内的 repo-relative、canonical、regular、non-symlink 文件，并且必须被 Git tracked-file 查询确认。manifest 可以是 tracked-but-dirty；结果中的 `manifest_sha256` 绑定实际工作树字节，不要求 clean worktree。

Package root 不 re-export Retention symbols。manifest model、entry model、evidence helper 和 path implementation 都是 Module 内部实现，不是供仿真调用方协调的公共接口。

## Manifest v2

`configs/retention/manifest.json` 是当前唯一 tracked policy manifest，schema 为 `retention-manifest-v2`。每个 entry 只保留：

- root identity、root type、ownership、classification 和 basis；
- 可选的 evidence reference，其中 `contract-protected`、`lineage-only` 和 `reproducible-ephemeral` 必须提供有效 reference；
- `unknown` 可以没有 machine identity evidence，并始终进入 `unresolved_roots`。

`planned_action`、duplicate/cache evidence、file action allowlist 和 directory postcondition 不再属于当前 schema。classification 只描述 policy ownership，不把某个审计结果变成删除许可。

## Audit Semantics

审计按以下顺序处理：

1. 验证 manifest provenance、Git tracking、canonical path 和 symlink safety；
2. 建立 canonical root identity map，拒绝 path alias、同一实体的重复 classification、absolute/Windows path、`..`、`.` 和重复分隔符；
3. 校验 root type、evidence existence 和 structured JSON identity；Markdown evidence 只作为 human reference；
4. 读取 root 的 filesystem metadata，聚合 regular-file count、directory count 和 observed bytes。

root 内容永远不会被打开或 hash，包括 `.env*`、raw Prompt、Provider Payload 和用户级 raw records。审计结果不包含 content digest、file action、directory action 或 cleanup readiness。`audit_valid=true` 只说明 explicit-root policy 的结构与 identity 合法，永不授权删除、移动、压缩或其他 filesystem action。

一个结构合法但包含 lineage 或 unknown roots 的 manifest 返回成功；manifest、path、evidence、root type 或 classification violation 返回非零。CLI 对历史 `retention-manifest-v1` 明确返回 `unsupported-schema`，不提供兼容 Adapter。

## Current Classification

当前 manifest 的 policy shape 是 6 个 contract-protected roots、2 个 lineage-only roots、1 个 reproducible-ephemeral root 和 3 个 unknown roots。它是 explicit-root audit，不是 repository-wide discovery；普通未受合同保护的 run 不能据此推断为可删除，Formal/release root 也不能仅按其位于 `runs/` 目录而删除。

历史 cleanup 若需再次执行，必须由独立、明确授权的 exact-path Ticket 声明路径、验证步骤和 ownership；Retention audit 不提供 apply、delete、move、storage 或 cleanup Adapter。
