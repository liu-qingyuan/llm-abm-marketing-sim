# 锦江 Concurrent Message Editorial v3 Formal Presentation 发布记录

统计周期：2026-08-07；口径更新时间：2026-08-07T21:08:49Z；成功 atomic `current` switch：2026-08-07T20:59:12.555218418Z

## 发布结论

- canonical endpoint [`https://abm.q1ngyuan.top/`](https://abm.q1ngyuan.top/) 已发布 Editorial v3。
- Exposure Ranking 现在以单个关系型 legend item 和三 channel visual grammar 表达：同一 user 可以进入任意两条或全部三条 message queue，overlap 允许但不要求发生；Message-Level Single Exposure 仍只约束相同 `user × message` pair。
- Network Feedback 现在明确区分 terminal `succeeded` Primary positive action、跨 message 的 `user_id` 去重、same-batch snapshot freeze、next-batch shared engaged-neighbor context 和 no-feedback stop paths。共享 set 不会把用户直接注入任何 queue。
- 本次只派生并发布 presentation，没有重跑、筛选或改写原始 3,600 个 persisted Decisions；没有调用 research Provider 或数据采集 API。Editorial v2 作为 managed rollback release 保持完整。

## Release Identity

| 项目 | 路径 / 值 | SHA-256 |
|---|---|---|
| 原始 Formal source | `runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z/` | lineage source；`report.html`: `740f55a30bc4183a75724592496c6b6aa809a85ab385ccf96bc53093cb49a76d` |
| Editorial v3 destination | `runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-editorial-v3-20260807T204815Z/` | `report.html`: `ed661dcc53304b33a37c52e7540db5422c8206bec0e823991e22d7b8c3b46073` |
| Editorial v3 manifest | 同上 `artifact_manifest.json` | `3577ac7bdcc8c780c44e8fbac64f779f7a72321b0f1103581485a6b6645053e8` |
| Editorial v3 v4 contract | `configs/deployments/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-editorial-v3-20260807T204815Z.json` | `3220df5fdeaf81353b060abce87db809f8014cdbfeb3c65ece928dc76e5103c7` |
| Editorial v3 release ID | `jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-editorial-v3-20260807T204815Z` | deployment identity |
| Editorial v2 rollback release ID | `jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-editorial-v2-20260807T131329Z` | `report.html`: `4e6680caf8476aa2b7839a20a985c320ce423c64b974d592b449ee2afa0ddbd8` |

v3 destination 含 23 个 regular files、0 symlink。相对明确原始 Formal source 只有 `report.html` 与 `artifact_manifest.json` 变化，其余 21 个 artifacts byte-identical。v4 contract 相对 v2 contract 只更新 `source_directory`、`artifact_sha256.report.html` 和 `artifact_sha256.artifact_manifest.json`，不包含 release ID。

## Presentation Contract

- 五组 `editorial-mechanism-*-v3.png/.webp` 是新的 versioned source/derivative assets；overview、sample 和 LLM decision 延续已批准几何，Exposure Ranking 与 Network Feedback 使用新的基础几何图元。
- Exposure Ranking figure 同时显示 cobalt、green、amber 三条 queue 的 all-three overlap 关系，并补充 two-channel permission 示例；HTML overlap mark 同样覆盖三个 channel，但仍只保留一个 `Allowed overlap` legend item。
- Feedback figure 将三路 message-level success、唯一 campaign user set、frozen divider、共享 context fan-out、三条独立 next-batch rankings 和 stop paths 分开编码。message color 只表示 message identity，聚合与 context 连接使用 neutral grammar。
- zh-CN / en-US copy、alt、caption、hotspot detail 和 semantic legend 共同说明：只有 terminal `succeeded` 且 action 为 `like/comment/share` 的 Primary 传播；Shadow、ignore、provider_failed 不提交反馈。
- Frozen Editorial v2 report、Editorial v1、two-mode、legacy 和 historical renderer bytes 继续由 exact compatibility goldens 保护；unknown hash 仍 fail closed。

## Deployment and Rollback Evidence

发布前只读 preflight 确认：

- remote `current` 精确指向 Editorial v2 rollback release；remote/public report hash 都是 `4e6680ca…`，manifest hash 都是 `a7895411…`。
- report container 为 `healthy`，v2 release 为 23 个 regular files、0 symlink；计划中的 v3 release ID 不存在。

随后使用显式 contract、source directory 和 release ID 运行既有 deploy transaction：

1. 本地 `--require-formal-production` validation 通过，并从只读 local snapshot 上传 candidate。
2. remote candidate container health、artifact presence 和 Nginx checks 通过后，于 `2026-08-07T20:59:12.555218418Z` 原子切换 `current`。
3. 公网 health、header/body/manifest hash、全部 contract artifacts HEAD 和 deployed Playwright 通过；成功事务未触发 rollback。

最终 readback：

- remote `current` 精确指向 `/opt/llm-abm-marketing-sim-report/releases/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-editorial-v3-20260807T204815Z`。
- container health 为 `healthy`；release 为 23 个 regular files、0 symlink。
- public `/healthz=ok`；public `X-Artifact-SHA256`、public body 与 remote report hash 均为 `ed661dcc…`。
- public/remote manifest hash 均为 `3577ac7b…`。
- Editorial v2 rollback report 保持 `4e6680ca…`；未触发回退。

## Validation and Review

- 聚焦 unit/compatibility：`24 passed`。
- Editorial Playwright：`6 passed`；desktop 与 `390 × 844` 检查无 horizontal overflow、component overlap、external request、console error 或 page error。
- 完整本地门禁：Python compile passed；pytest `549 passed, 2 deselected`；Ruff passed；Pyright `0 errors, 0 warnings, 0 informations`；完整 Playwright `36 passed, 2 skipped`。
- local deployed acceptance：`1 passed`；canonical deployed acceptance：`1 passed`。
- Standards broad reviewer 报告无 Critical/High finding；其文档滞后 Medium follow-up 已随本发布记录和 current 入口更新。
- Spec broad reviewer 在限定 `max_turns` 内终止且没有输出，未启动替代 reviewer，也不声称该审查轴已通过。没有 blocking finding，因此未运行 focused closure。

## Safety Boundary

未修改 Concurrent Message runtime、persisted Decisions、Prompt、global cache、v4 schema 或 sensitivity contract。未读取、打印、迁移或写入 `.env`、secret、raw Prompt、raw Provider payload 或用户级 raw records。没有调用 image model、research Provider、TikHub、Douyin 或 profile API。
