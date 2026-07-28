# Concurrent Message Campaign Diagnostics

Status: Implemented validation diagnostics note

本 Note 记录并发三 message validation runtime 中 campaign diagnostics 的当前实现边界、模块关系和可见输出。它只描述离线或已授权 Formal run 的 artifact contract，不授权 live API 或 canonical deploy。

相关设计共识见 [`concurrent-message-competition-experiment.md`](concurrent-message-competition-experiment.md)。

## 当前实现

- `ConcurrentCampaignDiagnostics` 从 persisted candidate / pair rows 重建五组指标，并校验 ranking、pair closure、容量和 source-row consistency；
- runner 在 fresh 和 resume 路径都先把安全化的 candidate / pair rows 交给 builder，再把 `payload`、`summary` 写入 `concurrent_campaign_diagnostics.json` 和 `concurrent_validation.json`；
- report writer 在生成 report payload 前再次运行 `validate_concurrent_validation_summary`，并把五组 diagnostics sections 写入报告；
- release validator 从最终 source directory 重新读取 candidate / pair rows，重建 diagnostics，与 persisted diagnostics、validation summary 和 schema token 逐项比较；
- no-feedback diagnostics 不调用 adapter、不推进 runtime state；demographic reason screening 只做 deterministic lexical evidence，不是完整语义偏差分类器。

## 当前架构与调用关系

```mermaid
flowchart LR
    Runner[ConcurrentMessageExperimentRunner] --> Candidates[concurrent_runtime_candidates.csv]
    Runner --> Pairs[concurrent_runtime_pairs.csv]
    Candidates --> Builder[ConcurrentCampaignDiagnostics]
    Pairs --> Builder
    Builder --> Diagnostics[concurrent_campaign_diagnostics.json]
    Builder --> Validation[concurrent_validation.json counts and summary]
    Diagnostics --> Writer[Concurrent message report writer]
    Validation --> Writer
    Writer --> Report[report.html and report payload]
    Writer --> Validator[validate_concurrent_validation_summary]
    ReleaseValidator[Formal release validator] --> Candidates
    ReleaseValidator --> Pairs
    ReleaseValidator --> Builder
```

## 当前时序

```mermaid
sequenceDiagram
    participant R as Runner
    participant C as CandidateRows
    participant P as PairRows
    participant D as ConcurrentCampaignDiagnostics
    participant V as ValidationSummary
    participant W as ReportWriter
    participant X as ReleaseValidator
    R->>C: persist frozen ranking rows
    R->>P: persist selected pair and terminal rows
    C->>D: rebuild ranking and allocation evidence
    P->>D: rebuild funnel, response, and sensitivity evidence
    D-->>V: closed counts and per-message aggregates
    D-->>W: diagnostics payload and summary
    W->>W: validate summary and render five diagnostic sections
    X->>C: rebuild from final source rows before release acceptance
    C-->>X: compare payload, summary, and schema tokens
```

## 当前状态

```mermaid
stateDiagram-v2
    [*] --> RuntimeRowsPersisted
    RuntimeRowsPersisted --> DiagnosticsRebuilt
    DiagnosticsRebuilt --> ValidationCountsClosed
    ValidationCountsClosed --> ReportArtifactsWritten
    ReportArtifactsWritten --> FinalSourcePublished
    DiagnosticsRebuilt --> Rejected: source rows do not close or ranking mismatch
    ValidationCountsClosed --> Rejected: summary mismatch
    Rejected --> [*]
    FinalSourcePublished --> [*]
```

## 当前类关系

```mermaid
classDiagram
    class ConcurrentMessageExperimentRunner {
        +run_and_write(output_dir, mode) Path
    }
    class ConcurrentCampaignDiagnostics {
        +build(candidate_rows, pair_rows) ConcurrentCampaignDiagnosticArtifacts
    }
    class ConcurrentCampaignDiagnosticArtifacts {
        +payload
        +summary
    }
    class write_concurrent_message_report_artifacts
    class rebuild_concurrent_message_report
    class validate_concurrent_validation_summary
    class validate_release
    ConcurrentMessageExperimentRunner --> ConcurrentCampaignDiagnostics
    ConcurrentMessageExperimentRunner --> write_concurrent_message_report_artifacts
    ConcurrentCampaignDiagnostics --> ConcurrentCampaignDiagnosticArtifacts
    write_concurrent_message_report_artifacts --> validate_concurrent_validation_summary
    rebuild_concurrent_message_report --> validate_concurrent_validation_summary
    validate_release --> ConcurrentCampaignDiagnostics
```

## 数据边界

- source of truth 是同一 run 中 persisted 的 `candidate_rows` 与 `pair_rows`；in-memory rows 只在写出前经过安全化，不构成独立事实来源；
- no-feedback comparison 复用同一批冻结 candidates、相同 full-precision score components 和 `user_id` tie-break，只把 campaign feedback component 置 0；
- reason screening 只匹配已展示 demographic label/value 与预声明 direct-causal phrases，保存 matched span，不改写 reason，不触发重跑；
- report payload、diagnostics artifact、validation summary 和 release validator 必须互相闭合；任一 crossed token、缺失行、重复行、排序或计数不一致都在报告发布前失败关闭；
- 所有 message-level differences 保持 descriptive / non-causal，不生成 winner 或综合评分。
