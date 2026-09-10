# ADR 0010：同一恢复任务中的有界并发

## Context

恢复任务原来使用一个未决intent。并发物理请求需要改变持久化账本，而不是同时启动多个旧runner。LLM仍只返回Decision；Study仍独占调度、累计预算、重试、恢复和反馈提交。来源：[operational #250](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/250)。

## Decision

采用显式批准、同一campaign追加的四路并发扩展，首个合同只允许Gemini3.1并在模型完成后停止。原task/plan、历史失败和预算均不替换；扩展仅可从已有成功自检、完整batch边界且零未决的paused状态接纳。它不释放任何硬停、不续签时效、不增加探针。

每个lane持有独立client/adapter，每个worker只执行一次物理请求。主线程在请求前持久化带pair key的intent，独占预算和有界重试；首个硬停后停止新增派发，仍结算已派发的已知响应。未知provenance保留intent，后续只有显式reconciliation才能处理，不隐式重发或结算。

Kernel先冻结全batch。`_drive_primary_runtime`的可选内部`batch_ready` Seam由恢复runtime用于派发、由独立reader用于全batch坐标与context摘要验证。无此callback的历史行为不变。乱序响应先落盘，Judgment/Realization仍按原序提交；完整barrier才更新下一批推荐反馈。

Task接纳和legal replay共用批准validator；Bundle绑定批准原件，Evidence关联每个显式key的attempt来源。旧missing usage保持unknown，部分模型完成不构成全36k Evidence闭合。

## Alternatives and consequences

不采用多个旧runner：它会拆散唯一预算/源锁和未知请求处理。不共享一个client的可变last_*计量状态。不改变LLM Prompt、wire/visible/thinking合同或增加框架依赖。此设计增加了keyed intent、乱序持久化和drain状态，但保持排序与反馈的单一知识归属。其他模型或其他并发数需要独立明确合同，不能由本次接纳推定。

## 结构对比

以下“当前”指原串行合同，“目标”指上述追加扩展。

## 当前架构
```mermaid
flowchart TB
    O["Operator 单client"] --> S["Study 串行恢复"]
    S --> K["Kernel 冻结batch"]
    S --> J["CampaignJournal 单intent"]
    S --> A["单lane adapter"]
    A --> P["Gemini gateway"]
    J --> E["独立 Evidence / Report"]
```
## 目标架构
```mermaid
flowchart TB
    O["Gemini-only Operator 独立client池"] --> S["Study 并发调度与唯一journal写者"]
    S --> K["Kernel 冻结batch与顺序barrier"]
    S --> J["CampaignJournal 带key intent与settlement"]
    S --> W["最多4个单次请求worker"]
    W --> P["冻结Gemini gateway"]
    J --> E["独立replay / Evidence / Report"]
```
## 当前时序
```mermaid
sequenceDiagram
    participant K as Kernel
    participant S as Study
    participant J as Journal
    participant P as Provider
    K->>S: 冻结batch，返回下一pair
    S->>J: reservation + intent
    S->>P: 请求
    P-->>S: response
    S->>J: settlement + judgment + realized + pair_settled
    S->>K: 顺序关闭pair，最终barrier
```
## 目标时序
```mermaid
sequenceDiagram
    participant K as Kernel
    participant S as Study
    participant J as Journal
    participant W as Workers
    K->>S: 全batch冻结pair/context
    S->>J: batch预约
    loop 未完成pair且未硬停，最多4个in-flight
        S->>J: keyed intent，扣累计slot
        S->>W: 单次物理请求
        W-->>S: keyed结果或unknown
        S->>J: keyed settlement或保留unknown
    end
    S->>J: 按原序提交judgment与realization
    S->>K: 所有pair完成后提交原barrier
```
## 当前状态
```mermaid
stateDiagram-v2
    [*] --> Ready
    Ready --> Running: 合法task和已有成功自检
    Running --> Paused: 零未决时中断
    Paused --> Running: 同task续接
    Running --> Stopped: 硬停
    Running --> Reconciliation: 未决intent
    Running --> Checkpoint: 模型barriers完整
    Checkpoint --> Running: 下一模型
```
## 目标状态
```mermaid
stateDiagram-v2
    [*] --> Paused
    Paused --> BatchReady: 并发合同接纳，零未决
    BatchReady --> Dispatching: 原batch预约
    Dispatching --> Dispatching: keyed结算与有界重试
    Dispatching --> Draining: 首个硬停或unknown
    Draining --> Stopped: 全部已知结算
    Draining --> Reconciliation: 仍有unknown
    Dispatching --> Committing: 全batch响应成功
    Committing --> BatchReady: 顺序judgment及barrier
    Committing --> StageComplete: Gemini四cells完成
    StageComplete --> [*]: 不构造Flash资源
```
## 当前类关系
```mermaid
classDiagram
    class Study {
        run_task(plan, model_resources)
    }
    class CampaignProgress {
        reservation
        inflight
        success_decisions
        transition(kind, payload)
    }
    class Kernel {
        plan_batch()
        commit_primary_batch()
    }
    class ModelLane {
        execute()
    }
    Study --> CampaignProgress
    Study --> Kernel
    Study --> ModelLane
```
## 目标类关系
```mermaid
classDiagram
    class Study {
        run_task(plan, model_resources)
    }
    class RecoveryParallelRuntime {
        run_frozen_batch()
        freeze_work()
    }
    class CampaignProgress {
        parallel_approval
        batch_reservations
        keyed_inflight
        success_decisions
        transition(kind, payload)
    }
    class Kernel {
        plan_batch()
        commit_primary_batch()
    }
    class ParallelAdapterPool {
        four_clients
    }
    Study --> RecoveryParallelRuntime
    RecoveryParallelRuntime --> CampaignProgress
    RecoveryParallelRuntime --> Kernel
    RecoveryParallelRuntime --> ParallelAdapterPool
```

