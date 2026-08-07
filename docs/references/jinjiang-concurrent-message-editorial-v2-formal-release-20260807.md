# 锦江 Concurrent Message Editorial v2 Formal Presentation 发布与主机迁移记录

统计周期：2026-08-07；口径更新时间：2026-08-07T13:16:55Z；成功 atomic `current` switch：2026-08-07T13:14:02.216579006Z

## 发布结论

- canonical endpoint [`https://abm.q1ngyuan.top/`](https://abm.q1ngyuan.top/) 已发布 Editorial v2，五张机制图使用基础几何图元并显示对应 HTML legends。
- 因旧服务器流量耗尽，用户明确授权将 origin 迁移到 `107.182.185.24`，SSH target 为 `BandwagonHost2`；canonical 域名和远程根目录保持不变。
- 新主机先部署 frozen Editorial v1 作为 managed rollback baseline，再原子切换到 v2；v1 release 仍完整保留。
- 本次只派生和发布 presentation，没有重跑、筛选或改写原始 3,600 个 persisted Decisions，也没有调用 research Provider 或数据采集 API。

## Release Identity

| 项目 | 路径 / 值 | SHA-256 |
|---|---|---|
| 原始 Formal source | `runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z/` | lineage source |
| Editorial v2 destination | `runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-editorial-v2-20260807T073615Z/` | `report.html`: `4e6680caf8476aa2b7839a20a985c320ce423c64b974d592b449ee2afa0ddbd8` |
| Editorial v2 manifest | 同上 `artifact_manifest.json` | `a7895411890c5a5bb48518de36f6055e2adcc4ea914a4e57d9c05e52b833f0ad` |
| Editorial v2 v4 contract | `configs/deployments/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-editorial-v2-20260807T073615Z.json` | `df2cd49f81ce2640b57978f2518afe38c807b80a3a5b7c227efea8f32f5c5759` |
| Editorial v2 release ID | `jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-editorial-v2-20260807T131329Z` | deployment identity |
| Rollback release ID | `jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-editorial-20260729T134133Z` | `report.html`: `1d1e1ead3691aa275c74ff723a79960019c42fd58f179d8b74619f0a0b218ea9` |

v2 destination 含 23 个 regular files、0 symlink。v4 validator 确认其仍为 `formal_research`、`persisted_seed_first_formal_run`、`production` 且 `production_deploy_eligible=true`；presentation derivation 只改变 `report.html` 与 `artifact_manifest.json`。

## Host Migration

- Authorization evidence：GitHub issue #152 的 [new-host migration authorization](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/152#issuecomment-5217289996)。
- Origin：`107.182.185.24`；remote hostname：`beautiful-poll-2.localdomain`；SSH target：`BandwagonHost2`。
- Remote root：`/opt/llm-abm-marketing-sim-report`。
- Host stack：Ubuntu 26.04、Nginx 1.28.3、Docker 29.1.3、Docker Compose 2.40.3；report container image 为 `nginx:1.27-alpine`。
- Service path：host Nginx → `127.0.0.1:18083` → read-only report container。新主机的 80/443/18083 在迁移前无冲突。
- DNS 保持 Cloudflare-proxied canonical 域名；origin 直连与公网 `/healthz` 最终都返回 `ok`。

## Deployment and Rollback Evidence

新主机没有 previous release，首次 bootstrap 暴露 SSH 空参数丢失问题；上传后在任何 `current` 切换前停止。部署脚本随后用显式 sentinel 保留“无上一版本”语义，并增加回归测试。Cloudflare 迁移窗口还出现过 artifact TLS timeout 和 Playwright `ECONNRESET`；失败事务均 fail closed，停止容器并移除 `current`，没有留下半激活 release。

公网 acceptance 保留原 hash/content 门禁，只为 transport error 增加最多 4 次、有界 120 秒的重试。最终执行顺序：

1. Editorial v1 baseline 通过 contract validation、remote candidate/container/Nginx checks 和公网 Playwright，在新主机建立 rollback release。
2. v2 candidate 使用显式 contract、source directory 与 release ID 上传；candidate health 通过后，`current` 于 `2026-08-07T13:14:02.216579006Z` 原子切换。
3. v2 deployed Playwright 通过（`1 passed`）；未触发成功事务的 rollback。

最终远端 readback：

- `current` 精确指向 `/opt/llm-abm-marketing-sim-report/releases/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z-editorial-v2-20260807T131329Z`。
- container health 为 `healthy`；host Nginx 配置校验通过。
- remote/public `report.html` 与 `X-Artifact-SHA256` 均为 `4e6680ca…`。
- remote/public `artifact_manifest.json` 均为 `a7895411…`。
- Editorial v1 rollback report 保持 `1d1e1ead…`。

## Validation

Editorial v2 实现提交 `42fdc8f` 已通过完整门禁；主机迁移与部署支持改动合并后的最终 closure 为 pytest `546 passed, 2 deselected`、Ruff passed、Pyright `0 errors`、完整 Playwright `36 passed, 2 skipped`。其中部署 bootstrap/retry 聚焦测试为 `29 passed`，deployed acceptance 为 `1 passed`。

最终公网 readback 再次确认 `/healthz=ok`，public header/body hash 与本地 contract 一致。部署支持改动不改变 release contract schema、artifact identity、runtime、Decision、Prompt 或 cache。

## Safety Boundary

未读取、打印、迁移或写入旧主机秘密、`.env`、API key、raw Prompt、raw Provider payload 或用户级 raw records。只在新主机安装运行既有部署流程所需的 Nginx、Docker 和 Compose，并写入明确授权的 report remote root、managed Nginx site 与 container service。
