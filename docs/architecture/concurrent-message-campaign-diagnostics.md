# Concurrent Message Campaign Diagnostics

Status: Implemented validation diagnostics note

本 Note 记录并发三 message validation runtime 中 campaign diagnostics 的当前实现边界、模块关系和可见输出。它只描述离线 validation diagnostics，不授权 live API 或 canonical deploy。

相关设计共识见 [`concurrent-message-competition-experiment.md`](concurrent-message-competition-experiment.md)。

## 变化影响

- 新增纯离线 `ConcurrentCampaignDiagnostics` builder，从 persisted candidate / pair rows 重建五组指标；
- runner 额外写出 `concurrent_campaign_diagnostics.json`，并让 `concurrent_validation.json` 的基础计数闭合到 source-row diagnostics；
- report.html 新增 Campaign Funnel、Message Allocation、Primary Audience Response、Campaign Feedback Effect、Demographic Decision Sensitivity 五个用户可见 sections；
- no-feedback diagnostics 不调用 adapter，不推进 runtime state；
- demographic reason screening 只做 deterministic lexical evidence，不是完整语义偏差分类器。

## 当前架构与调用关系

```mermaid
flowchart LR
    Runner[ConcurrentMessageExperimentRunner] --> Candidates[concurrent_runtime_candidates.csv]
    Runner --> Pairs[concurrent_runtime_pairs.csv]
    Runner --> Validation[concurrent_validation.json]
    Runner --> Report[report.html]
    Note[No independent campaign diagnostics rebuild] --> Validation
```

## 目标架构与调用关系

```mermaid
flowchart LR
    Runner[ConcurrentMessageExperimentRunner] --> Candidates[concurrent_runtime_candidates.csv]
    Runner --> Pairs[concurrent_runtime_pairs.csv]
    Candidates --> Builder[ConcurrentCampaignDiagnostics]
    Pairs --> Builder
    Builder --> Diagnostics[concurrent_campaign_diagnostics.json]
    Builder --> Validation[concurrent_validation.json counts closure]
    Builder --> Report[report.html diagnostic sections]
    Builder --> Screening[Deterministic reason screening evidence]
```

## 当前时序

```mermaid
sequenceDiagram
    participant R as Runner
    participant V as ValidationSummary
    participant W as ReportWriter
    R->>V: aggregate counts directly from in-memory rows
    V-->>R: basic validation summary
    R->>W: render simple report tables
    Note over R,W: no source-row rebuilt campaign diagnostics artifact
```

## 目标时序

```mermaid
sequenceDiagram
    participant R as Runner
    participant C as CandidateRows
    participant P as PairRows
    participant D as ConcurrentCampaignDiagnostics
    participant V as ValidationSummary
    participant W as ReportWriter
    R->>C: persist frozen ranking rows
    R->>P: persist selected pair rows
    C->>D: rebuild ranking and allocation evidence
    P->>D: rebuild funnel, response, sensitivity evidence
    D-->>V: closed counts and per-message aggregates
    D-->>W: five visible diagnostic sections
    D-->>R: diagnostics artifact without adapter calls or runtime mutation
```

## 当前状态

```mermaid
stateDiagram-v2
    [*] --> RuntimeRowsBuilt
    RuntimeRowsBuilt --> ValidationSummaryWritten
    ValidationSummaryWritten --> BasicReportWritten
    BasicReportWritten --> [*]
```

## 目标状态

```mermaid
stateDiagram-v2
    [*] --> RuntimeRowsBuilt
    RuntimeRowsBuilt --> DiagnosticsRebuilt
    DiagnosticsRebuilt --> ValidationCountsClosed
    ValidationCountsClosed --> DiagnosticArtifactWritten
    DiagnosticArtifactWritten --> ReportSectionsRendered
    ReportSectionsRendered --> [*]
    DiagnosticsRebuilt --> Rejected: source rows do not close or ranking mismatch
    Rejected --> [*]
```

## 当前类关系

```mermaid
classDiagram
    class ConcurrentMessageExperimentRunner
    class _MessageScore
    class ValidationSummary
    ConcurrentMessageExperimentRunner --> _MessageScore
    ConcurrentMessageExperimentRunner --> ValidationSummary
```

## 目标类关系

```mermaid
classDiagram
    class ConcurrentMessageExperimentRunner {
        +run_and_write(output_dir) Path
    }
    class ConcurrentCampaignDiagnostics {
        +build(candidate_rows, pair_rows) ConcurrentCampaignDiagnosticArtifacts
    }
    class ConcurrentCampaignDiagnosticArtifacts {
        +payload
        +summary
    }
    class validate_concurrent_validation_summary {
        +validate(validation_summary, diagnostics)
    }
    ConcurrentMessageExperimentRunner --> ConcurrentCampaignDiagnostics
    ConcurrentCampaignDiagnostics --> ConcurrentCampaignDiagnosticArtifacts
    ConcurrentCampaignDiagnosticArtifacts --> validate_concurrent_validation_summary
```

## 边界说明

- source of truth 是 persisted `candidate_rows` 与 `pair_rows`；
- no-feedback comparison 复用同一批冻结 candidates、相同 full-precision score components 和 `user_id` tie-break，只把 campaign feedback component 置 0；
- reason screening 只匹配已展示 demographic label/value 与预声明 direct-causal phrases，保存 matched span，不改写 reason，不触发重跑；
- 所有 message-level differences 保持 descriptive / non-causal，不生成 winner 或综合评分。
