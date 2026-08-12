# Concurrent Robustness v6 Formal Production 发布记录（2026-08-13）

## 状态

- local release Ticket：[#181](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/181)
- canonical deployment Ticket：[#182](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/182)
- release bytes implementation commit：`4fcd61dc6c30724bdf9daec418b2f2ecfa4a48a3`
- 状态：**final reviewed v6 production release 已部署并通过 canonical public acceptance**
- canonical release ID：`jinjiang-concurrent-robustness-v6-final-reviewed-20260812T190000Z`
- Provider、TikHub、Douyin、profile API、image-generation calls：`0`
- secrets 读取、打印或写入：否
- canonical `report.html` SHA-256：`2c2054be939e9df6f57f55c763f24d0b7c6f15b1dfdc6cd397424c938ebfdcdb`（`2,457,620` bytes）
- atomic `current` switch：`2026-08-12T19:27:17.055992641Z`

> `cf6a983`、`771d363` 与最终 `4fcd61d` 依次关闭 production trace denominator、browser single-member gzip 和 v5 compatibility blockers。此前记录的 candidate、closure、production、snapshot 路径与 hashes 均已废弃；下列 `final-reviewed` 链是唯一已发布的 v6 production identity。

## 显式 lineage

- Historical Concurrent Formal：`runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z/`
- Historical robustness workspace：`runs/jinjiang-concurrent-robustness-formal-v1-openai-codex-20260810T003438Z-workspace/`
- immutable study root：`runs/jinjiang-concurrent-robustness-formal-v1-openai-codex-20260810T003438Z-workspace.study-root/`
- Formal contracts：`runs/jinjiang-concurrent-robustness-formal-v1-openai-codex-20260810T003438Z-contracts/`
- historical candidate：`runs/jinjiang-concurrent-robustness-formal-v1-openai-codex-20260810T003438Z-report-candidate/`
- presentation candidate：`runs/jinjiang-concurrent-robustness-report-candidate-v3-final-reviewed-20260812T190000Z/`
- presentation closure：`runs/jinjiang-concurrent-robustness-presentation-closure-v1-final-reviewed-20260812T190000Z.json`
- immutable production source：`runs/jinjiang-concurrent-robustness-production-v6-final-reviewed-20260812T190000Z/`
- release contract：`runs/jinjiang-concurrent-robustness-production-v6-final-reviewed-20260812T190000Z-release-contract.json`
- physical snapshot：`runs/jinjiang-concurrent-robustness-production-v6-final-reviewed-20260812T190000Z-physical-snapshot/`

## Candidate identity

- candidate identity：`075d29b5b1df5d74c15db3288749f086a6a5ce1e17541eb435b390d7c170c9ef`
- candidate content identity：`64d1d6836a3457740f2935477839e2f9e19e12ed30afa56bf556a002450a10eb`
- manifest：`d23339ce1663c69268e3f14e34943b6059c83acb10e459a21d40fef56605ca37`
- `report.html`：`4f1fcb8938658adf33221195e159fdbc9a5437469d3a5a45d1e7d9ce4b29d212`
- report payload：`fddaf5c4565168f299405d1f7c6660da34255a79e41bba9e98a8a575984ea2b3`
- release evidence：`a8cad02e3e5a063a0cf707124ae631e41fed5e2954c24efed6617c4852e35e0a`
- `report.html` size：`2,457,309` bytes（小于 3 MiB）
- candidate inventory：`39` regular files；validation 前后 inventory digest `9a95a370e09edb0253cab37d1567a3973d56b72f5514acbe31bd889eefc83929` 不变
- candidate accounting：`provider_calls_during_composition=0`；`production_deploy_eligible=false`

## Closure 与 production identity

- closure implementation commit：`4fcd61dc6c30724bdf9daec418b2f2ecfa4a48a3`
- closure SHA-256：`73c2aaf2fb99d7438c280fd67e16c452ac9f01ea4c7bd59bf766596f673add09`
- closure accounting：`provider_calls_during_closure=0`
- release id：`jinjiang-concurrent-robustness-v6-final-reviewed-20260812T190000Z`
- release schema：`abm-report-release-contract-v6`
- release contract SHA-256：`b839d8b56122505a76188dc7cc185c28d8a8276c3bb98f1ce19856f466b763c3`
- production report：`2c2054be939e9df6f57f55c763f24d0b7c6f15b1dfdc6cd397424c938ebfdcdb`（`2,457,620` bytes）
- production manifest：`f758549c4931dd1b71b4d64f0a537eb209837424443b2218ceb0a1820d339cdc`
- production release identity：`5583349c3a92267f7915af26cb92e5cae2ed6bed01c4b2ccee4b7b7b84f690fc`
- production accounting：`provider_calls_during_promotion=0`；`production_deploy_eligible=true`
- source/snapshot inventory：`42` regular files，逐文件 hashes exact match；canonical JSON `[relative_path, sha256]` inventory digest 均为 `f642978e6749c45e641494da53293f0e661102e76ab9add1b6f41ca1d4c8b7c9`

`presentation_closure_contract.json` 是 production inventory/release identity 的 regular artifact；它不是 Report 的 `17` 个 approved downloads 之一。production copy 与独立 closure bytes 相同。

## Local pre-deployment validation evidence

通过：

- strengthened presentation closure validation，显式重算 candidate content identity，并绑定最终实现 commit；
- v6 standalone validator 与 `--require-formal-production`；
- deployment physical snapshot validator 与 source/snapshot 42-file exact hash closure；
- actual candidate + production Playwright：`3 passed (2.5m)`，覆盖 Chromium concatenated-member gzip fail-closed、unsupported decoding fail-closed，以及 desktop/mobile、双语、三张 semantic diagrams、Prompt disclosure、trace ready/filter/pagination/drawer、三个 `.mmd` 和全部 approved downloads；无 third-party request、console error 或 page error；
- Python compile；implementation suite：`653 passed, 2 deselected in 285.64s`；
- immutable Historical Formal、study root、Formal contracts 与 historical candidate 共 `112` 个输入文件前后 SHA-256 完全不变；canonical JSON manifest digest 为 `d0f798915284cd639679e24aa3b2a36cfe90448c4de771ca078bbf9e07d2e730`；
- validation 前后 candidate `39` files 与 production `42` files 均保持逐文件不变；
- public canonical report hash 仍为旧 release hash；未执行 SSH、上传或 switch。

## Canonical deployment evidence

### 显式 transaction

部署只使用本页 frozen inputs，没有扫描“最新”目录：

- contract：`runs/jinjiang-concurrent-robustness-production-v6-final-reviewed-20260812T190000Z-release-contract.json`；
- source directory：`runs/jinjiang-concurrent-robustness-production-v6-final-reviewed-20260812T190000Z/`；
- release ID：`jinjiang-concurrent-robustness-v6-final-reviewed-20260812T190000Z`；
- canonical domain：`abm.q1ngyuan.top`；
- 既有授权 infrastructure：SSH target `BandwagonHost2`、remote root `/opt/llm-abm-marketing-sim-report`、container `abm-research-report`、loopback port `18083`、image `nginx:1.27-alpine`。

成功事务前的 fresh remote readback 是本次唯一 rollback target：

- release ID：`jinjiang-concurrent-robustness-production-v1-repair-20260811T193031Z`；
- report SHA-256：`541bcf04820c8643c73ca9e7d927fe6a1d44c23d02f849532bcb18ab6c5eeb43`；
- manifest SHA-256：`8c14f1447af4f2ad3d77b60e4935e902dfbfa62b74b944c348ebebda3bb96e0a`；
- production identity：`f4471399fded9a7879c3d9c653e36ed495374ede2e40b7ec0362428fbae5d259`；
- container：`healthy`，`38` 个 regular files、`0` symlink。

### Fail-closed rollback 与 transport fix

首次 cutover 的 candidate、container 与 Nginx checks 均通过，但 public report body hash 不等于 contract，部署脚本自动恢复上述 rollback target 并重新验证其 canonical hash。独立 bounded diagnostic 确认 Cloudflare 把 downloadable Mermaid edge ID 中的 `@-->` 误识别为邮箱：公网 body 增加 `1,188` bytes，并出现 `/cdn-cgi/` markers；diagnostic 每次都恢复旧 `current`。

修复只作用于 Deployment Module：`report.html` Nginx location 显式返回 `Cache-Control: no-cache, no-transform`，避免该 location 自己的 `add_header X-Artifact-SHA256` 屏蔽 server-level header。真实 Cloudflare 路径验证后，公网 body 恢复为 contract bytes；回归测试固定该 location-level transport contract。失败 candidate 在确认不是 `current`、42-file hashes 正确且无 symlink 后清理，并以同一 frozen release ID 重新执行完整标准部署流程。

### 成功切换与公网验收

- atomic `current` 于 `2026-08-12T19:27:17.055992641Z` 指向 v6 release；container started at `2026-08-12T19:27:17.788144612Z`；
- final remote readback：release ID 精确匹配，container `healthy`，Nginx validation passed，`42` 个 regular files、`0` symlink；
- remote/public/header report SHA-256 均为 `2c2054be939e9df6f57f55c763f24d0b7c6f15b1dfdc6cd397424c938ebfdcdb`；
- remote/public manifest SHA-256 均为 `f758549c4931dd1b71b4d64f0a537eb209837424443b2218ceb0a1820d339cdc`；
- `42/42` contract artifacts 逐文件公网下载并匹配 SHA-256；其中三个 `.mmd` 全部匹配；Report 的 `17/17` approved downloads 均由 public Playwright 实际 HEAD 验收；
- standard deployment public Playwright：`1 passed (1.4m)`，覆盖公网 artifact/download HEAD、Robustness controls、drawer、desktop/mobile 与无横向溢出、third-party request、console error 或 page error；
- focused public Playwright：desktop/mobile `2/2 passed`，直接操作双语导航、三张 semantic diagrams、Prompt 与 Mermaid native disclosures、trace persisted loading marker→runtime ready、filters、pagination、drawer Enter/Escape 和焦点恢复；同样无横向溢出、third-party request、console error、page error 或 `/cdn-cgi/` mutation；
- public transport 出现可重试的 TLS `SSL_ERROR_SYSCALL`；既有 bounded retry 后所有严格 hash 与 interaction gates 通过，没有放宽 contract；
- 成功事务未触发 rollback；部署前 v5 release 继续保留为 managed rollback target。

全过程新增 Provider、TikHub、Douyin、profile API 与 image-generation calls 均为 `0`；没有读取、打印或写入 credential、`.env`、raw Prompt 或 raw Provider payload。

## Engineering validation

- deployment regression suites：`32 passed`；新增 transport regression 先 RED、后 GREEN；focused public Playwright desktop/mobile `2/2 passed`；
- Python compilation 与 full pytest：passed，`654 passed, 2 deselected in 281.65s`；
- Ruff：passed；Bash syntax 与 `git diff --check`：passed；
- changed-file Pyright：`0 errors, 0 warnings, 0 informations`；仓库级既有命令在当前 `npx pyright 1.1.411` 下仍报告 `21` 个位于未改动测试文件的 baseline errors，本 Ticket 未扩大范围修复。
