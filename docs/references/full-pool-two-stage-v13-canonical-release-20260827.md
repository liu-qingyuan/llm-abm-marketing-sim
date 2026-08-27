# Full-Pool 两阶段 v13 Canonical 发布记录（2026-08-27）

## 状态

- parent Spec：[#228](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/228)
- authoritative continuation：[#236](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/236)
- operational authorization / deployment Ticket：[#237](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/237)
- authorization comment：[#237 comment 5433928828](https://github.com/liu-qingyuan/llm-abm-marketing-sim/issues/237#issuecomment-5433928828)
- 状态：**Full-Pool nested-v1 v13 production 已部署并通过 canonical public acceptance**
- canonical endpoint：`https://abm.q1ngyuan.top/`
- Release ID：`full-pool-two-stage-v13-production-20260826T142827Z`
- successful deployment completion：`2026-08-27T05:56:37Z`
- independent remote verification：`2026-08-27T08:25:37Z`
- independent public verification：`2026-08-27T08:25:50Z`
- realization / presentation / promotion / deployment Provider calls：`0`
- upstream Formal lineage：`live_api_triggered=true`，requested/observed model 为 `gpt-5.6-sol`
- deployment期间 Provider、TikHub、Douyin、profile或其他live data API calls：`0`
- secrets读取、打印或写入：否；部署工具只消费既有SSH授权环境，不输出credential

本页与#237 completion comment是Deployment Module的operational record。部署事实没有反向写入immutable v13 Release。

## Canonical research identity

v13在冻结的Full-Pool Source-v4 Provider Judgments与ABM feedback之间加入已接受的nested-v1 realization gate：Provider `ignore`保持`ignore`；positive judgment按`provider_probability`做稳定抽样，pass保留`like/comment/share`，fail转为`ignore`。正式规则为`sha256-source-user-message-first-53-bits-uniform-v1`，seed为`20260823`，key只绑定`source identity + user_id + message_id`。

- Formal realized source：`runs/full-pool-two-stage-authoritative-ticket-235-20260826T122716Z/formal-realized-source/`
- realized source identity：`b348c1bd309788df41b2a86106fe5216ce6fc6dc9317a67bc19351d3a249e1d7`
- realized source manifest SHA-256：`2b72356e205e670212f3a7a9dbc88fd64fbabe61c5de004047b82a629c1e33eb`
- closure：36,400 users、3 messages、109,200 exposures/terminals、30 batch commits、1,691,730 candidate rows、270 projection rows
- realized actions：63,420 likes、5 comments、189 shares、45,586 ignores
- realized engagements：63,614 / 109,200 = 58.254579%
- Segment rates：S1 `75.638234%`、S2 `45.164787%`、S3 `45.268930%`
- 排序：S1 `M3 > M1 > M2`、S2 `M2 > M3 > M1`、S3 `M3 > M2 > M1`

Canonical只把单次`user × message` exposure作为Primary engagement单位，不声称S1偏向M1，也不把simulated engagement解释为真实抖音绝对互动率。Provider reason/confidence继续只属于Judgment provenance；页面没有生成`realized_reason`。

## Immutable Release

- release root：`runs/full-pool-two-stage-v13-release-ticket-236-20260826T142827Z/full-pool-two-stage-v13-production-20260826T142827Z/`
- contract：`runs/full-pool-two-stage-v13-release-ticket-236-20260826T142827Z/full-pool-two-stage-v13-production-20260826T142827Z-release-contract.json`
- contract schema：`abm-report-release-contract-v13`
- purpose：`full_pool_two_stage_realization_formal_research`
- sampling status：`persisted_two_stage_realized_full_pool_formal_run`
- production deploy eligible：`true`
- contract SHA-256：`91d03641c9c18abe62a5551be314cbe1aee304afe9ec8aff483916012318ff5a`
- Release identity SHA-256：`27130adc334502f83a4467aa6e4a89ca9ed5436ed451d43732889eae7a2c1f89`
- report SHA-256：`4602ee446159e45610e360183091e6f86d802eb0f2fdfc6a6f44415fb662e784`
- manifest SHA-256：`95d3e1327e71eb19301a5d7b81a71e2a95d37d9442be268368045ab919740a12`
- physical inventory：148 regular files、0 symlink，identity `cfb66badc21e4f43244127316fb072134cec9ab26f46a49baa527c7d33121d5d`
- immutable before/after snapshot SHA-256：均为`23a8e8c4012bfd52229c4b6c4e5e172627eb5f10b302df415250e6886a95087f`

Historical 1,000-user六图及其evidence在v13中保持旧bytes与hash隔离。Full-Pool新机制使用deterministic inline SVG、双语DOM fallback、stable node/edge IDs和同语义`.mmd`；Report只消费realized facts，机制语义仍由Mechanism Presentation Module唯一拥有。

## Deployment authorization与rollback

Authorization artifact使用`abm-report-v13-deployment-authorization-v1` canonical JSON，exact绑定上述Release/source以及以下目标：

- authorization SHA-256：`620cb673468fddecb09b9f160da17f8cbddb277e98b2a8159a5d06b95035b228`
- SSH host：`BandwagonHost2`
- remote root：`/opt/llm-abm-marketing-sim-report`
- topology：`immutable-releases-atomic-current-v1`
- port / container / image：`18083` / `abm-research-report` / `nginx:1.27-alpine`

两次授权transaction都从remote `current` fresh readback并exact验证同一v12 rollback identity：

- rollback Release ID：`full-pool-strict-formal-v12-production-delivery-runs-20260823T132643Z`
- managed path：`/opt/llm-abm-marketing-sim-report/releases/full-pool-strict-formal-v12-production-delivery-runs-20260823T132643Z`
- report SHA-256：`32823528e6ea1d871c8f0157e0bb72c4c19fe1b11881454c8b623b89ef82bf17`
- manifest SHA-256：`0cc7c9c56f34103da4679b74e92dd64627f797e96d103ee31339963b65da14c0`

v12目录与hash在成功后继续保留为managed rollback target。

## 第一次public acceptance失败与恢复

第一次授权transaction于`2026-08-27T03:20:15Z`开始。本地Release、authorization、fresh v12 rollback、远端148-file inventory、candidate container与atomic switch门禁均通过；随后公网逐artifact HEAD在`trace/message_3/batch-000006.json`遇到瞬时网络超时。脚本按contract把public acceptance判为失败，但自动rollback的首次SSH也遇到`Network is unreachable`，因此没有把该尝试描述为成功部署。

恢复时先只读确认v13 report/manifest exact且container healthy，再于`2026-08-27T05:06:45Z`执行授权中的精确v12 rollback。`2026-08-27T05:06:53Z`完成remote disk、container与`current`复核；`2026-08-27T05:07:10Z`公网report与manifest重新匹配v12。该恢复没有重建或修改任一Release。

第二次transaction于`2026-08-27T05:08:06Z`开始，再次fresh readback v12并复用hash-verified v13 remote candidate；没有扫描“最新”目录。正式container于`2026-08-27T05:49:52.878476795Z`启动，完整public acceptance于`2026-08-27T05:56:37Z`通过。

## Canonical public acceptance

成功transaction通过：

- public report header与body SHA-256均匹配`4602ee44...62e784`；
- public manifest SHA-256匹配`95d3e132...740a12`；
- 148/148 contract artifacts完成HTTP acceptance；
- `full-pool-paged-v1` body verifier对50个artifact下载并核对完整body hash，共41,922,337 bytes、7批、每批最多8个；
- 其余98个大型artifact共1,721,373,543 bytes，以exact manifest、remote hash、public HEAD与browser HEAD闭合；
- deployment Playwright：`1 passed (1.4m)`，实际覆盖desktop/mobile、zh-CN/en-US、realized headline、完整九格、trace、two-stage inline SVG、DOM fallback、`.mmd`与data downloads；
- 无third-party request、page error、console error或响应式横向溢出。

独立部署后复核确认：

- remote `current`精确指向v13 managed path；
- remote inventory为148 regular files、0 symlink，container为`healthy`；
- remote disk、container与public report/manifest hashes全部匹配contract；
- 第一次失败位置`trace/message_3/batch-000006.json`随后可完整公网下载，2,178,004 bytes，SHA-256 `910bef214c3a3431b6a344ea933ac11a7a2825fb065cf53b2a1bb919c296e43d`；
- v12 rollback report/manifest hashes仍匹配authorization。

## Operational evidence

- operation root：`runs/full-pool-two-stage-v13-deployment-ticket-237-20260827T031950Z/`
- operation record：`deployment-operation-record.json`
- operation record SHA-256：`122234ea246087e3d7f6050a6f773a8daccae595b56de4dac9e981293bd4e655`
- successful deployment log SHA-256：`45e5268ddcd976572ffedb38da8d71c087e593399411629c671f4db819960e76`
- failed first-attempt log SHA-256：`8c3695645afba838b0942ebef7ff5eaf36b439799c56c6caed7e8293887ff52f`
- rollback recovery log SHA-256：`8f2ec73378eb8b06d51b1b8321102d342f7ec1ae7614c2a344455374013dc419`
- post-deployment remote verification SHA-256：`7fe057b24db77f430a7050009d8d639d224e725ec7dfdca130da05267f4eaa4f`
- post-deployment public verification SHA-256：`99d0c3eb2321837c6db57deb47d8488c9b90e6884abd21976ca7a6329a02862d`

这些operational artifacts不属于immutable Release inventory，不改变Release identity。首次失败、手工verified rollback与第二次成功均保留，不覆盖失败历史。
