# 一次性接纳明确授权的复测

用户已批准此最小合同变化；真实运行仍属于 #250，36,000 真判断及同源 Evidence/HTML/XLSX/CSV 才算完成。当前 fixed point 为 e96168d8bf140dca14a4269d49063aae28979f1f。

Recovery Task Module 新增 `accept_recovery_task_recheck(plan_path, approval_path, approval_sha256)` Interface；自身持有 source lock，重读来源后追加 `self_check_recheck_accepted` 事件，事件同时作为 create-once readonly receipt。不会调用 Provider。独立 Recheck Module 拥有外部复测证据验证。approval 绑定同一 plan、停止 HEAD、失败 settlement、复测 authorization/intent/result 及明确用户批准。相同 approval 重复调用返回相同 receipt；不追加事件或请求。

仅允许尚无 epoch/Formal dispatch 的任务因单次 self-check connection/0-response 停止且无未决 intent；原失败保留在 self_checks，成功复测单独记账并成为 effective health。一次接纳不发放新自检，后三模型仍各一次。源漂移、unknown、quota、identity、usage、Decision、预算等其他硬停不变。历史 HEAD 是正常 journal append 的前驱，不手工改 HEAD；旧事件与源文件保持原绝对路径/bytes/mode。

新增 receipt/外部引用进入 bundle artifact_facts；Evidence 单列原失败和复测成功的各自 intent/result origin。原 token unknown 和 production_deploy_eligible=false 保留。测试使用 synthetic transports 仅证明实现，不计真实进度。

## 当前架构
```mermaid
flowchart LR
 O[Operator] --> T[Task Module]
 T --> J[Journal]
 T --> S[Study]
 P[独立成功复测] -.无入口.-> T
```
## 目标架构
```mermaid
flowchart LR
 O[Operator] --> T[Task Module]
 A[明确接纳批准] --> R[Recheck Module]
 P[独立成功复测] --> R
 T --> R
 T --> J[Journal]
 T --> S[Study]
 J --> E[Evidence Module]
 E --> H[HTML XLSX CSV]
```
## 当前时序
```mermaid
sequenceDiagram
 participant U as Operator
 participant T as Task
 participant J as Journal
 U->>T: run
 T->>J: replay
 J-->>T: stopped
 T-->>U: stopped
```
## 目标时序
```mermaid
sequenceDiagram
 participant U as Operator
 participant T as Task
 participant R as Recheck
 participant J as Journal
 participant S as Study
 U->>T: accept recheck approval
 T->>J: lock and replay
 T->>R: validate bound artifacts
 R-->>T: checked success
 T->>J: append receipt event
 T-->>U: receipt
 U->>T: run same task
 T->>S: derive epoch with effective health
```
## 当前状态
```mermaid
stateDiagram-v2
 [*] --> ready
 ready --> stopped: self check failed
 stopped --> [*]
```
## 目标状态
```mermaid
stateDiagram-v2
 [*] --> ready
 ready --> stopped: self check failed
 stopped --> ready: one explicit accepted connection recheck
 ready --> running: health and epoch admitted
 running --> stopped: any hard stop
 running --> execution_complete: 36000 decisions
 execution_complete --> complete: zero Provider report closure
```
## 当前类图
```mermaid
classDiagram
 class Task {
  inspect_recovery_task()
 }
 class CampaignProgress {
  self_checks
  status
 }
 Task --> CampaignProgress
```
## 目标类图
```mermaid
classDiagram
 class Task {
  inspect_recovery_task()
  accept_recovery_task_recheck()
 }
 class Recheck {
  validate_receipt()
 }
 class CampaignProgress {
  self_checks
  accepted_rechecks
  effective_self_check()
  status
 }
 Task --> Recheck
 Task --> CampaignProgress
 class Evidence
 Evidence --> CampaignProgress
```
