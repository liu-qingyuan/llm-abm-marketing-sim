# Concurrent Robustness v7 Canonical 发布记录（2026-08-13）

## 状态

- parent Spec：[#183](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/183)
- canonical deployment Ticket：[#191](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/191)
- release bytes implementation commit：`6c9a35edd35204ed5b72bb5236d5c789856d694d`
- 状态：**Mermaid-first v7 production 已部署并通过 canonical public acceptance**
- canonical endpoint：`https://abm.q1ngyuan.top/`
- release ID：`jinjiang-concurrent-robustness-v7-semantic-20260813T152334Z`
- semantic set identity：`c93dccf1a502e94484ad0db7a2abd9a8d5b2c16dd47c918825401da55ef170bf`
- research Provider / TikHub / Douyin / profile API calls：`0`
- composition / closure / promotion / deployment image-generation calls：`0`
- rejected pre-release image-generation calls：`6`；这些 PNG/WebP 与 generation audit 未进入 candidate、release 或 canonical inventory
- secrets 读取、打印或写入：否；部署工具只消费既有授权环境
- atomic `current` switch：`2026-08-13T15:53:35.725084703Z`
- final public verification：`2026-08-13T16:04:48Z`

v7 只发布已在 [#185 comment 5276313349](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/185#issuecomment-5276313349) 整组批准的六张 mechanism Mermaid masters，以及未改变研究语义的 Prompt–Model factorial Mermaid。#186 的 AI raster set 已被用户拒绝，只保留为 release 外的 pre-release 历史。

## 显式 lineage

本次没有扫描“最新”目录，也没有原地修改旧 candidate 或复用旧 release directory：

- Historical Concurrent Formal：`runs/jinjiang-concurrent-message-formal-v1-gpt-5.4-mini-20260727T023746Z/`
- Historical robustness workspace：`runs/jinjiang-concurrent-robustness-formal-v1-openai-codex-20260810T003438Z-workspace/`
- immutable study root：`runs/jinjiang-concurrent-robustness-formal-v1-openai-codex-20260810T003438Z-workspace.study-root/`
- Formal execution contract：`runs/jinjiang-concurrent-robustness-formal-v1-openai-codex-20260810T003438Z-contracts/formal_run_contract.json`
- zero-Provider payload-v1 replay：`runs/jinjiang-concurrent-robustness-report-candidate-v1-replay-semantic-v7-20260813T152334Z/`
- payload-v2 candidate：`runs/jinjiang-concurrent-robustness-report-candidate-v4-semantic-v7-20260813T152334Z/`
- presentation closure-v2：`runs/jinjiang-concurrent-robustness-presentation-closure-v2-semantic-v7-20260813T152334Z.json`
- immutable production source：`runs/jinjiang-concurrent-robustness-production-v7-semantic-20260813T152334Z/`
- release contract：`runs/jinjiang-concurrent-robustness-production-v7-semantic-20260813T152334Z-release-contract.json`
- physical snapshot：`runs/jinjiang-concurrent-robustness-production-v7-semantic-20260813T152334Z-physical-snapshot/`

Frozen v6 presentation candidate 与 2026-08-10 Historical candidate 都按当前 fixed implementation fail closed，分别报告不可重建的 `report.html` 与旧 inventory。两次尝试均在写 destination 前停止。随后通过现有 Report high-level Interface 从同一显式 Formal + study root 生成独立 payload-v1 replay，再物化 payload-v2；没有放宽 validator，也没有修改旧 artifact。

## Candidate identity

### Payload-v1 deterministic replay

- regular files：`39`
- inventory digest：`360f02237689b4ddb654d744b4c7a3954d1f0ba2ffbe00793bc62c4089eaf526`
- candidate identity：`9dc7525c70fe4546aabe8fca77866681145e26b5e59727a6d8ceb4e362785b60`
- candidate content identity：`3f308598c772002ac4089faff03beb15b15021f5195d163f406e06ee20046b08`
- `provider_calls_during_composition=0`

### Payload-v2 semantic candidate

- schema：`concurrent-robustness-report-payload-v2`
- regular files：`43`
- inventory digest：`c4738fe41fe4966af97c50221f27ef949bea08ec2239d0f646ef2fd281fc58b8`
- candidate identity：`e243cb5333a188c4dc1dd6139aad4e78036a7f4315afc3e6129e500a950b3213`
- candidate content identity：`4fdfbbe72f9ba55762802243ba6ec327eff8734eaa1be90228fecbdc3dd30ae5`
- manifest：`51d06669f7c128b4b548242c4fbee401de17c72a451429bca70586c1f8c81fbe`
- `report.html`：`bccd1e33474a7f2170e952f7fec09bafd2a680abb9231e143016eb683e3dfcee`（`2,923,480` bytes）
- report payload：`92be12524a988eda55f09c49847dad8692cce17ca83d2538263a088f1aaa6c29`
- release evidence：`1b65f15f08b320d67d37479f859d8c3f2ef64341dcb6058820131b1b3fd95007`
- accounting：`provider_calls_during_composition=0`、`image_generation_triggered=false`
- eligibility：`production_deploy_eligible=false`

Candidate inventory 精确包含六张 mechanism masters 与 `prompt-model-factorial.mmd`。`project-evidence-chain.mmd`、rejected v4 PNG/WebP 和 `mechanism-image-generation-audit.json` 均不存在。

## Closure 与 production identity

- closure schema：`concurrent-robustness-presentation-closure-contract-v2`
- closure implementation commit：`6c9a35edd35204ed5b72bb5236d5c789856d694d`
- closure SHA-256：`afddb6328d939656ad6de7b68c5b083640ebedebda6eb6007387cd54ec734581`
- closure accounting：`provider_calls_during_closure=0`、`image_generation_triggered=false`
- post-closure mutation check：篡改 `new_candidate_report_sha256` 后按预期被拒绝
- release schema：`abm-report-release-contract-v7`
- release contract SHA-256：`1c5ecc336d84a46efeb1fd459b989a48e3835033ed4ccb9fd733e7e5be6e727d`
- production release identity：`63ca6b262e5804f3abc851fbd177e30ba7653d9ec31b7f666d7ca6a60e29bbc3`
- production report：`ecb7a2535cf6be5585a06851b54de463824058b4345e07635b680910b24cc22f`（`2,923,770` bytes）
- production manifest：`b69b138a9a420e798f29911f48761ce73621105c955d5d4440f3baba51d8b07b`
- production accounting：`provider_calls_during_promotion=0`
- source/snapshot inventory：`46` regular files；canonical JSON `[relative_path, sha256, size]` digest 均为 `82ac9b2856216d128b81f1eb241eebe846ec0ddb89faa714c4d95056b5717248`
- approved downloads：`21`；其中七个 `.mmd`，不含 raster、generation audit、project evidence chain 或 closure contract

## Local pre-deployment validation

通过：

- closure-v2 artifact validation 与独立 post-mutation rejection；
- v7 standalone validator 与 `--require-formal-production`；
- deployment physical snapshot validator；source/snapshot 46-file inventory 与 hashes exact match；
- `report.html < 3 MiB`；artifact safety scan 确认 46 个 regular files、0 symlink、0 non-regular entry、0 high-risk secret marker，且 inventory 与 contract 完全一致；
- actual candidate Playwright：`1 passed`；actual production Playwright：`1 passed`，均覆盖 1440/1600/mobile、zh/en、五段 navigation、机制/本次运行 mode、六图 method disclosure、real-batch、Prompt factorial、trace ready、keyboard/focus、无 overflow、third-party request、console error 或 page error；
- immutable Historical Formal、study、workspace、Formal contracts、old candidates、v6 closure、v6 production/snapshot 与 package assets 共 `301` files 前后不变；manifest digest `f48a6c3ba807ad9a78ffdcf52b9e7670af74d46511ed3a0eb66eea5c4e7319c9`；
- payload-v1 replay、payload-v2 candidate 与 closure 共 `83` files 在 promotion 前后不变；manifest digest `44b2a6164dfbd816572c1e0a34d4a5d4d0696f5bea688832a0d0c0a629dcfc59`；
- persisted v6 `--require-formal-production` compatibility validator 继续通过，v6 report hash 保持 `2c2054be...fdcdb`。

Engineering gates：`713 passed, 2 deselected`；Python compilation、Ruff、validator mypy、Bash syntax 全部通过。

## Canonical deployment evidence

### 显式 transaction

部署只使用本页 frozen v7 contract/source/release ID，并沿用既有 topology：

- SSH target：`BandwagonHost2`
- remote root：`/opt/llm-abm-marketing-sim-report`
- container：`abm-research-report`
- loopback port：`18083`
- image：`nginx:1.27-alpine`
- canonical domain：`abm.q1ngyuan.top`

首次命令使用脚本默认 host token 时，本地代理在 fresh readback 阶段关闭连接；该尝试发生在 remote release 创建、上传和 cutover 之前。独立 readback 证明 canonical 仍为 v6、container healthy 且 remote v7 directory 不存在。随后把既有 SSH alias `BandwagonHost2` 显式传给同一部署脚本，未改变主机、SSH identity 或 remote topology。

成功 transaction 的 fresh readback 是唯一 rollback target：

- release ID：`jinjiang-concurrent-robustness-v6-final-reviewed-20260812T190000Z`
- report SHA-256：`2c2054be939e9df6f57f55c763f24d0b7c6f15b1dfdc6cd397424c938ebfdcdb`
- manifest SHA-256：`f758549c4931dd1b71b4d64f0a537eb209837424443b2218ceb0a1820d339cdc`
- container：`healthy`
- inventory：`42` regular files、`0` symlink

### 成功切换与 remote readback

- atomic `current` 于 `2026-08-13T15:53:35.725084703Z` 指向 v7；
- container started at `2026-08-13T15:53:36.811699251Z`；
- final remote readback：release ID 精确匹配、container `healthy`、`46` regular files、`0` symlink；
- remote/container report hashes 均为 `ecb7a253...cc22f`；
- remote/container manifest hashes 均为 `b69b138a...d8b07b`；
- remote candidate health、Nginx validation 与 atomic switch 均通过。

### Public acceptance

- public report body、`X-Artifact-SHA256` header 与 contract hash 均为 `ecb7a2535cf6be5585a06851b54de463824058b4345e07635b680910b24cc22f`；
- public manifest hash 为 `b69b138a9a420e798f29911f48761ce73621105c955d5d4440f3baba51d8b07b`；
- `46/46` contract artifacts 逐一 HTTP success 且 SHA-256 匹配；七个 `.mmd` 全部匹配；
- deployment standard public Playwright 在成功 transaction 内 `1 passed (1.8m)`，独立重跑同样 `1 passed (1.8m)`；
- focused public desktop/mobile Playwright：`2 passed`，实际操作 zh/en、五段 navigation、六图 disclosure、机制/本次运行 mode、real-batch、Prompt factorial、trace loading→ready、search/message filters、drawer Enter/Escape 与焦点恢复；无横向溢出、third-party request、console error 或 page error；
- public transport 出现可重试的 `SSL_ERROR_SYSCALL`；既有 bounded retry 后全部严格 hash 与 interaction gates 通过，未放宽 contract；
- 成功 transaction 未触发 rollback；v6 release 继续保留为 managed rollback target。首次 pre-readback 失败发生在 cutover 前，不需要 rollback。

部署后没有把 operational 时间、readback 或 public acceptance 事实写回 immutable v7 release bytes。本页与 #191 completion comment 是 deployment transaction 的 operational record。
