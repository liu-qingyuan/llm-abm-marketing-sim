# Report Deployment Authorization and Rollback

本文描述 Final Research immutable release 的 Deployment Module。该 Module 只消费 Release Module 已验证并投影的 deployment facts；它不重新解释 realization、Prompt、模型、Provider accounting、metrics、Report bytes 或 release eligibility。默认测试只使用本地 Adapter，不连接 canonical。

## Module 与 Interface

Deployment 流程保留三个稳定 Interface：

1. `validate_abm_report_release.py` 调用 Release Module validator，对显式 contract、source directory 与随机本地 snapshot 做 round-trip validation，并输出 `abm-report-deployment-facts-v1`。
2. `report_deployment.authorize_deployment_files(...)` 按 release schema exact dispatch v13/v14 deployment facts、目标 topology 与独立 operational authorization，生成 hash-bound `abm-report-deployment-plan-v1`。
3. `deploy_abm_report.sh` 只在 plan 闭合后读取 remote `current`，再通过 `verify_fresh_rollback_files(...)` 核对授权中的 rollback identity；随后才允许 candidate write、health、atomic switch 与 public acceptance。

v2–v12 继续沿用既有 deployment behavior。v13 的 composite Formal profile 只由 Release Module 的 `require_full_pool_v13_deployment_profile(...)` 解释；v14 的 Prompt–Model Formal profile 只由 `require_full_pool_v14_deployment_profile(...)` 解释。Deployment 只接收其最小投影，不维护第二份 Prompt、模型、Provider 或指标规则。

## v13 readiness 与 authorization

缺少 `--authorization` 时，v13 preflight 在任何 SSH、upload、remote directory 或 public request 前停止，并在 stderr 输出单行 canonical JSON：

```text
deployment authorization required: { ... }
```

其 schema 为 `abm-report-v13-deployment-readiness-v1`，绑定：

- v13 contract schema 与 SHA-256；
- release ID、release identity、realized source identity；
- canonical endpoint、report/manifest hashes 与 artifact count；
- Release Module 原样投影的 `full-pool-v13-release-readiness-v1`；
- host、remote root、port、container、image 和 `immutable-releases-atomic-current-v1` topology；
- `rollback_identity_required=true`、`remote_connection_authorized=false` 和 `deployment_authorized=false`。

`abm-report-v13-deployment-authorization-v1` 使用 exact fields，固定 explicit approval、authorization reference、上述 release/target bindings，以及 `abm-report-fresh-rollback-identity-v1`。

## v14 readiness 与 authorization

v14 是 additive exact dispatch。缺少 authorization 时，同样以 nonzero 状态在第一次网络或远端副作用前停止；输出 schema 为 `abm-report-v14-deployment-readiness-v1`。除 target topology 外，它精确绑定：

- `abm-report-release-contract-v14` 与 contract SHA-256；
- release ID、release identity、physical snapshot identity；
- Full-Pool source identity、v2 study root identity；
- protected v13 release ID 与 identity；
- report、manifest、teacher `.xlsx` 的路径/hash 和完整 artifact count；
- canonical endpoint；
- Release Module 原样投影的 `full-pool-v14-release-readiness-v1`；
- `rollback_identity_required=true`、`remote_connection_authorized=false`、`deployment_authorized=false`。

该 readiness 可复制到后续独立 `ready-for-human` operational Ticket，但 readiness、fixture、Spec、label、commit 或旧 v13 approval 均不授权 v14 deployment。

`abm-report-v14-deployment-authorization-v1` 必须是 canonical UTF-8 JSON，使用 sorted keys 与 compact separators，且为 regular non-symlink file。它只能包含 exact fields，并绑定：

- `authorization_kind=explicit_operational_deployment`、`authorization_status=approved` 与 authorization reference；
- readiness 中的全部 v14 release/source/report/manifest/workbook identities；
- exact canonical endpoint；
- exact `abm-report-deployment-target-v1`（host、remote root、port、container、image、topology）；
- fresh `abm-report-fresh-rollback-identity-v1`（旧 release ID、managed remote path、report/manifest SHA-256）。

任何 duplicate、extra、missing field，非 canonical bytes，symlink，跨 release/schema identity，或 target/topology 漂移都会 fail closed。domain、host、remote root、port、container、image 或 rollback 任一变化均需新 authorization。

## Fresh rollback readback

合法 v13/v14 authorization 只允许第一次 SSH 执行 read-only `current` readback。Deployment 从 managed `releases/<release-id>` 读取旧 report 与 manifest hashes，形成 canonical fresh readback；它必须与 authorization 中的 rollback identity 完全相等，才能开始 candidate write。

readback 后，remote transaction 仍在 candidate health 前和 atomic switch 前重复检查旧 `current` path、report hash 与 manifest hash，防止授权后发生并发漂移。禁止扫描 latest 目录、从公网 hash 猜测 rollback target或依赖陈旧本地记录。

## Candidate、switch 与 public acceptance

获得合法 plan 与 fresh rollback identity 后，固定顺序为：

1. 核对本地只读 snapshot 的完整 regular-file inventory 与 contract hashes；
2. 上传或复用 exact hash-matched immutable candidate；
3. 核对 remote inventory、report/manifest/release identity 与 contract metadata；
4. 运行 candidate container health 与 Nginx checks；
5. switch 前再次核对 fresh rollback `current`，再原子切换并验证正式 container health；
6. 公网核对 report、manifest 与全部 contract artifacts；
7. 运行 schema-specific browser interaction acceptance；
8. v14 在写 operation facts 前重新加锁核对 `current`、candidate 磁盘 hashes 与正式 container response hashes。

v13 browser gate继续验证 Realized headline、zh-CN/en-US、two-stage inline SVG、DOM fallback、`.mmd` 与既有 downloads。v14 在此基础上必须验证：

- 页面默认是 Realized 主视图，Judgment view 初始隐藏；
- Judgment toggle 可切换且能回到 Realized；
- 表格中的 Prompt anchor 可定位到 Prompt Catalog；
- two-stage inline SVG 与中英双语 fallback 均存在；
- `.mmd` download 可定位；
- teacher `.xlsx` download 可定位，且完整 body 的 SHA-256 与 Release contract 相等。

public body verifier对 report、manifest、CSV、Markdown、Mermaid，以及 v14 teacher `.xlsx` 重新下载完整 body 并计算 SHA-256；large source/trace artifacts继续由 exact manifest、remote hash、public HEAD 与 browser HEAD 闭合。HTTP 200 或单个 report hash 不能单独构成 acceptance。

## Local Adapter failure matrix

`execute_v14_local_deployment(...)` 只驱动 `V14DeploymentAdapter`，自身不打开网络。测试 Adapter 覆盖：

- initial fresh rollback mismatch：在 candidate write 前停止；
- candidate inventory failure；
- candidate health failure；
- switch 前 `current` 漂移；
- atomic switch partial failure（保守视为可能已切换）；
- post-switch health failure；
- public acceptance failure；
- rollback 成功与 rollback 失败。

远端 transaction 从 current revalidation 到 rollback/commit 持有 nonblocking deployment lock；rollback 前还要确认 `current` 仍指向本次 candidate 或已是 fresh rollback，不能覆盖并发外部切换。已切换后的失败必须调用 atomic restore，并分别读取、核对旧 report/manifest 的磁盘 identity 与 container response identity。只有两者都匹配 fresh rollback 才返回 `failed_rolled_back`；恢复异常单独返回 `rollback_failed`。所有失败 outcome 的 `operation_facts` 都是 `null`，不得误报 success。local Adapter 的成功只返回 `abm-report-v14-local-deployment-operation-v1` validation evidence，并显式记录 `remote_connection_authorized=false`、`canonical_deployment_triggered=false`；它不能写成 production operation record。

## Success operation facts 与 handoff

v14 成功后只在独立 operational path 写 `abm-report-v14-deployment-operation-v1`。该 artifact 绑定 authorization/plan、release/source/snapshot identities、target topology、fresh rollback、report/manifest/workbook hashes、artifact count、candidate/switch/public gates、Playwright 后加锁完成的 final current/container identity readback、public-body summary SHA-256、Playwright acceptance、UTC 与 `provider_calls=0`；它不写回 immutable v14 Release。不存在可仅凭 deployment plan 单独生成 success record 的 CLI/API：production shell 只在 remote cutover、post-switch health、完整 public body hash 和 Playwright gates 全部实际通过后，以 exclusive-create 写出该记录；local Adapter evidence 会被 production writer 拒绝。

真实 v14 command 必须显式提供独立输出路径：

```bash
scripts/deploy_abm_report.sh \
  --contract <exact-v14-contract.json> \
  --source-dir <exact-v14-release-directory> \
  --release-id <exact-v14-release-id> \
  --authorization <canonical-v14-authorization.json> \
  --operation-facts-output <new-operational-evidence.json>
```

在没有 authorization 时运行同一命令（省略最后两个授权相关参数）只产生 hash-bound readiness 并 nonzero 停止。将 stderr 中 `deployment authorization required:` 后的 canonical JSON、精确 Release/contract 路径，以及“尚未执行 SSH/public HTTP/cutover”的声明复制到新的 `ready-for-human` Ticket，即构成 operational handoff；它仍需人工给出独立 v14 authorization。

可复制的后续 Ticket 正文模板：

````markdown
## v14 deployment authorization handoff

- Contract: `<exact-v14-contract-path>`
- Immutable Release: `<exact-v14-source-directory>`
- Release ID: `<exact-v14-release-id>`
- Operation evidence output: `<new-path-outside-release>`
- Preflight result: `awaiting_operational_authorization`
- Remote/public/cutover executed during readiness: **no**
- Provider calls during readiness: **0**

### Canonical readiness

```json
<paste the exact canonical JSON printed after `deployment authorization required:`>
```

### Human decision required

Provide one new regular non-symlink `abm-report-v14-deployment-authorization-v1`
file whose exact fields bind the readiness candidate, target topology, and fresh
managed rollback identity. Fixture, Validation evidence, v13 authorization, and
this Ticket do not authorize deployment.
````

当前仓库尚无真实 20-cell/36,000-judgment v14 Formal artifact，因此不能填充上述 exact hash 字段或发起真实 deployment Ticket。本地 #247 验收只证明 contract 和失败状态机，不代表真实 v14 Release、真实 deployment 或公网验收已经发生。
