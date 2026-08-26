# Report Deployment Authorization and Rollback

本文描述 Final Research immutable release 的 Deployment Module。该 Module 只消费 Release Module 已验证并投影的 deployment facts；它不拥有 realization、Report bytes、release purpose/status、Provider accounting 或 release inventory 的重复实现。默认测试使用本地 adapter，不连接 canonical。

## Module 与 Interface

Deployment 流程分为三个稳定 Interface：

1. `validate_abm_report_release.py` 调用 Release Module validator，对显式 contract、source directory 与随机本地 snapshot 做 round-trip validation，并输出 `abm-report-deployment-facts-v1`。
2. `report_deployment.authorize_deployment_files(...)` 对 v13 deployment facts、目标 topology 与独立 operational authorization做本地preflight，生成hash-bound `abm-report-deployment-plan-v1`。
3. `deploy_abm_report.sh` 只在plan闭合后读取remote `current`，再通过`verify_fresh_rollback_files(...)`核对授权中的rollback identity；随后才允许candidate write、health、atomic switch与public acceptance。

v2–v12继续沿用既有deployment behavior，不要求新的v13 authorization artifact。v13 purpose、sampling status与composite Provider accounting由Release Module的`require_full_pool_v13_deployment_profile(...)`唯一解释；Deployment调用方不维护第二份映射。

## v13 readiness 与 authorization

缺少`--authorization`时，v13 preflight在任何SSH、upload、remote directory或public request前停止，并在stderr输出单行canonical JSON：

```text
deployment authorization required: { ... }
```

其schema为`abm-report-v13-deployment-readiness-v1`，只包含release与目标侧可知的facts：

- v13 contract schema与SHA-256；
- release ID、release identity、realized source identity；
- canonical endpoint、report/manifest hashes与artifact count；
- Release Module原样投影的`full-pool-v13-release-readiness-v1`；
- host、remote root、port、container、image和`immutable-releases-atomic-current-v1` topology；
- `rollback_identity_required=true`、`remote_connection_authorized=false`和`deployment_authorized=false`。

该readiness适合复制到`ready-for-human` operational Ticket，但它本身不授权部署。Spec、label、commit、release readiness或普通collaborator confirmation也不能替代authorization artifact。

`abm-report-v13-deployment-authorization-v1`使用exact fields并固定：

- `authorization_kind=explicit_operational_deployment`与`authorization_status=approved`；
- authorization reference；
- exact contract hash、release ID与identity、realized source identity；
- exact canonical endpoint与完整deployment target；
- `abm-report-fresh-rollback-identity-v1`，包含旧release ID、managed remote release path、report SHA-256与manifest SHA-256。

字段结构如下；实际文件必须用sorted keys与compact separators序列化：

```json
{
  "schema_version": "abm-report-v13-deployment-authorization-v1",
  "authorization_kind": "explicit_operational_deployment",
  "authorization_status": "approved",
  "authorization_reference": "github:#<ticket>:<approval>",
  "release_contract_schema": "abm-report-release-contract-v13",
  "contract_sha256": "<sha256>",
  "release_id": "<release-id>",
  "release_identity_sha256": "<sha256>",
  "realized_source_identity": "<sha256>",
  "canonical_endpoint": "https://abm.q1ngyuan.top/",
  "deployment_target": {
    "schema_version": "abm-report-deployment-target-v1",
    "canonical_endpoint": "https://abm.q1ngyuan.top/",
    "host": "<ssh-host>",
    "remote_root": "/opt/llm-abm-marketing-sim-report",
    "topology": "immutable-releases-atomic-current-v1",
    "port": 18083,
    "container_name": "abm-research-report",
    "image": "nginx:1.27-alpine"
  },
  "rollback_identity": {
    "schema_version": "abm-report-fresh-rollback-identity-v1",
    "release_id": "<old-release-id>",
    "remote_release": "/opt/llm-abm-marketing-sim-report/releases/<old-release-id>",
    "report_sha256": "<sha256>",
    "manifest_sha256": "<sha256>"
  }
}
```

artifact必须是canonical UTF-8 JSON、regular file、无symlink、无duplicate/extra/missing fields。domain、host、remote root、port、container、image或topology任一变化都需要新的artifact。

## Fresh rollback readback

合法authorization只允许第一次SSH执行read-only `current` readback。Deployment从managed `releases/<release-id>`读取旧report与manifest hashes，形成canonical fresh readback；它必须与authorization中的rollback identity完全相等，才能开始remote candidate write。

readback后，remote transaction仍在candidate health前和atomic switch前重复检查旧`current` path、report hash与manifest hash，防止授权后发生并发漂移。禁止扫描latest目录、从公网hash猜测rollback target或依赖陈旧本地记录。

## Candidate、switch 与 public acceptance

获得合法plan与fresh rollback identity后，固定顺序为：

1. 核对本地只读snapshot的完整regular-file inventory与contract hashes；
2. 上传或复用exact hash-matched immutable candidate；
3. 核对remote inventory、report/manifest/release identity与contract metadata；
4. 运行candidate container health与Nginx checks；
5. 原子切换`current`并验证正式container health；
6. 公网核对report、manifest与全部contract artifacts；
7. 对Full-Pool v13实际操作realized headline、zh-CN/en-US、two-stage inline SVG、DOM fallback、`.mmd`和data downloads。

public body verifier对report、manifest、CSV、Markdown、Mermaid与bounded metadata重新下载并计算SHA-256；large source/trace artifacts继续由exact manifest、remote hash、public HEAD与browser HEAD共同闭合。HTTP 200或单个report hash不能单独构成acceptance。

## Failure 与 rollback

candidate health、switch/post-switch health或public acceptance任一步失败都保留或恢复该次fresh readback identity。若已切换，Deployment原子恢复旧`current`、重启并等待旧container healthy，然后同时验证：

- `current`重新指向授权且fresh-readback的旧release；
- 旧release磁盘report/manifest hashes未变；
- 旧container实际返回的report/manifest hashes未变。

恢复失败会单独报告，不能把失败事务描述为成功rollback。成功deployment只把UTC、release/hash、fresh rollback与public acceptance写入operational evidence；这些事实不反向写入immutable v13 release。
