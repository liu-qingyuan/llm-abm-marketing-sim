# Concurrent Message Legend and Visual Semantics Audit

Status: Consensus complete; discussion evidence; not an implementation Spec or deployment authorization
Evidence date: 2026-08-03
Canonical target: `https://abm.q1ngyuan.top/`
Source commit: `d44f704`
Canonical and local Editorial `report.html` SHA-256: `1d1e1ead3691aa275c74ff723a79960019c42fd58f179d8b74619f0a0b218ea9`

本文记录 Concurrent Message Editorial 页面图例调查的证据与最终视觉语义共识。它不修改 renderer、report artifacts、persisted Decisions、release contract 或 canonical webpage，也不授权 image generation、Formal Run、Provider 调用或 deployment。后续 executable requirements 仍应通过 `$to-spec-lqy` 发布为 Spec。

## Vocabulary

**Legend item**：图例中展示的概念及其 swatch。只有能够指向明确 Visual mark，并说明该 mark 所编码语义的项目，才属于严格图例。

**Visual mark**：图中真实存在并承担编码职责的线、点、柱、区域、节点、图标或其他可辨认图形。热点说明框本身不是其所覆盖概念的 Visual mark。

**Data field/series**：Visual mark 实际绑定的数据字段或序列。静态机制位图没有运行数据 series；若只表达稳定机制概念，应明确记录 `none`，不得伪装成运行数据。

**Interaction state**：决定图形、图例或数据可见性的 mode、language、filter、hover、focus、drawer 等页面状态。

**Narrative annotation**：caption、hotspot、边界说明、公式或解释性文字。它可以解释机制，但不应使用 series swatch 伪装成 Legend item。

**Visual Encoding Reference**：完整机制图生成前单独生成并批准的视觉编码样例。它必须逐项列出 Legend item、Visual mark 样例、Data field/series、Interaction state 和 Narrative annotation 边界；完整图生成后还要反向核对。

## Evidence Baseline

- Canonical body hash 与本地 Editorial destination、Formal release evidence 完全一致，因此本次讨论不存在网页版本分叉。
- Mechanism mode 包含 5 张静态机制位图和 5 组 legend，共 22 个 Legend items。
- Run Evidence mode 当前没有 figure、SVG、canvas 或可见 legend；浏览器核对结果为 `visibleLegends=0`、`visibleFigures=0`、`visibleTables=8`。
- mode 切换会整体隐藏 Mechanism panel；当前没有发现静态机制 legend 残留在 Run Evidence mode。
- language 切换只改变文案，不改变位图 Visual marks。
- hotspot 是覆盖在位图上的可交互 Narrative annotation；点击后打开 detail drawer，不改变底层 mark 或 legend。
- 当前单元和 Playwright tests 验证 asset hash、非空图片、布局、mode、language、filter 和 drawer contract，但没有验证 Legend item 与 Visual mark 的一一对应。

## Agreed Rules

1. **Legend follows observable marks**：当前 Interaction State 中有真实、可辨认的 Visual mark 才显示 Legend item；没有 mark 就隐藏，并用普通 Narrative annotation 说明无数据。公式、边界、lineage 和解释性文字不使用 series swatch。
2. **Audited targets replace current legends**：当前 22 个 Legend items 不是权威输入；每张图下方的 `Approved target legend` 表才是已确认的目标映射，可以删除、改名、拆分或补充当前项。
3. **Generate the reference before the figure**：先为每张图生成并批准 Visual Encoding Reference，再据此生成完整机制图，最后逐项反查 Legend item、Visual mark、Data field/series 和 Interaction state。
4. **Keep encoding axes orthogonal**：在展示三条 message channels 的图中，cobalt、green、amber 始终只编码 message identity；role、state、gate、aggregate 和 timing 使用形状、连接、填充或线型表达。样本图只用颜色区分三个 sample roles。
5. **Geometry does not imply identity by itself**：candidate/user nodes 使用 neutral marks；相同几何形状不表示同一用户。Eligible pair 和 cross-message overlap 必须使用明确 composite or linked-user marks。
6. **Directly label unique structure**：唯一出现的 module region、输入/输出 aggregate、时间边界、阶段和限制使用 direct labels 或 Narrative annotations；严格 legend 只保留各图 `Approved target legend` 中声明的可复用 mark grammar。
7. **Mechanism figures are not run-data charts**：五张静态机制位图不绑定 quantitative run series，不展示本次运行计数、filtered outcome 或因果结论；未来 data-bound chart 继续遵守第 1 条最小规则。

## Figure Audit

### 1. Overview

Source asset: `src/llm_abm_sim/report_assets/media-mechanism-overview.png`
Visible state: Mechanism mode only

当前实际颜色轴是三条 message 通道：蓝色通道、绿色通道和橙色通道分别贯穿 message token、queue、Exposure Gate 和末端 Decision。左侧 navy 节点池是共享 Research Sample。位图本身不绑定运行数据；上方三个 message cards 才读取 persisted payload 中的 message definitions。

| Current Legend item | Actual Visual mark | Data field/series | Assessment | Target status |
|---|---|---|---|---|
| Research Sample | 左侧 navy bracket 与节点池 | `none` in bitmap | 有真实 mark；swatch 不能完整表达节点池形状 | Retain in Mark grammar with a node-pool mark sample |
| Messages | 三个蓝/绿/橙六边形 message tokens | `none` in bitmap; surrounding cards use persisted message order | 单一 cobalt swatch 不完整 | Replace with three keys in the Message channels color group |
| Eligible user × message pair（current: Candidate Sets） | 当前只有三条按 message 着色、指向 sample 的 dotted connectors，没有独立 pair mark | `none` in bitmap; semantic unit is the stable `user × message` candidate contract | green swatch 只碰巧匹配中间通道，不表示 candidate pair | Add a composite neutral-user + message-colored-connection mark and retain as a strict Legend item |
| Per-Message Queue | 三条蓝/绿/橙水平 queue rails 与节点 | `none` | amber swatch 只匹配第三条 queue | Retain in Mark grammar with a queue-rail + neutral-candidate mark sample |
| Exposure Gate | 三个按 message 着色的 gate icons 与 dashed dividers | `none` | navy swatch 不对应三组 gate marks | Retain with a gate-icon mark sample; treat the dashed divider as Narrative annotation |
| Primary / report-only Shadow Decision pair（current: LLM Decisions） | 当前只有三个按 message 着色的单一末端圆环，没有表现 paired roles | `none` in bitmap; semantic contract is one Primary plus one paired Demographic Shadow Decision per exposure | green swatch 只匹配中间通道，并隐藏 Primary/Shadow 配对 | Replace with a same-message-color dual-branch mark: solid/filled Primary and dashed/hollow Shadow |

The Overview target is closed by consensus.

#### Approved target legend

| Group | Target Legend item | Approved Visual mark | Data field/series | Interaction state |
|---|---|---|---|---|
| Message channels | First message channel | cobalt channel accent applied consistently across its pipeline | authoritative first message identity; no quantitative bitmap series | Mechanism mode |
| Message channels | Second message channel | green channel accent applied consistently across its pipeline | authoritative second message identity; no quantitative bitmap series | Mechanism mode |
| Message channels | Third message channel | amber channel accent applied consistently across its pipeline | authoritative third message identity; no quantitative bitmap series | Mechanism mode |
| Mark grammar | Research Sample | navy sample boundary with neutral user nodes | `none`; stable Research Sample concept | Mechanism mode |
| Mark grammar | Eligible user × message pair | neutral user node connected with the corresponding message-channel color | `none`; stable `user × message` candidate unit | Mechanism mode |
| Mark grammar | Per-Message Queue | message-colored queue rail containing neutral candidate nodes | `none`; stable queue contract | Mechanism mode |
| Mark grammar | Exposure Gate | gate icon; message color may pass through without changing gate semantics | `none`; stable exposure boundary | Mechanism mode |
| Mark grammar | Primary / report-only Shadow Decision pair | same-message-color dual branch with solid/filled Primary and dashed/hollow Shadow | `none`; stable paired Decision contract | Mechanism mode |

Simultaneous launch、3,000 eligible pairs、`30 × Top20` capacity 和 Platform/Decision divider are Narrative annotations and do not receive swatches.

### 2. Sample Construction

Source asset: `src/llm_abm_sim/report_assets/media-mechanism-sample.png`
Status: Target semantics closed by consensus

| Current Legend item | Actual Visual mark | Data field/series | Assessment | Target status |
|---|---|---|---|---|
| Influence Seed Union | cobalt user nodes in seed selection and network stages | `none` | Mark exists and color broadly matches | Retain as a cobalt sample-role mark |
| Direct one-hop Network Cohort | green user nodes and one-hop edges | `none` | Mark exists and color broadly matches | Retain as a green sample-role mark |
| Ordinary fill | navy outline user nodes; an amber dashed boundary also surrounds the fill stage | `none` | User mark exists, but amber boundary creates a false fourth-role association | Retain navy/neutral outline user mark; replace amber boundary with neutral Narrative annotation |
| Synthetic Experiment Labels | lower orange-accent table/document/database lineage lane | `none` | Metadata/lineage annotation, not a sample-role series | Remove from sample-role legend; retain as independently titled `Synthetic label lineage` Narrative annotation |

The Sample Construction target is closed by consensus.

#### Approved target legend

| Target Legend item | Approved Visual mark | Data field/series | Interaction state |
|---|---|---|---|
| Influence Seed Union | cobalt user mark | `none`; stable seed role | Mechanism mode |
| Direct one-hop Network Cohort | green user mark, with one-hop edges visible in the figure | `none`; stable one-hop network-cohort role | Mechanism mode |
| Ordinary fill | navy/neutral outline user mark | `none`; stable ordinary sample role | Mechanism mode |

完整合格用户池和最终 Research Sample 使用 direct labels。Ordinary fill boundary 是 neutral stage annotation；下方橙色表格、文档和数据库 lane 使用独立 `Synthetic label lineage` 标题与说明。它们都不进入 sample-role legend。

### 3. Exposure Ranking

Source asset: `src/llm_abm_sim/report_assets/media-mechanism-exposure-ranking.png`
Status: Target semantics closed by consensus

| Current Legend item | Actual Visual mark | Data field/series | Assessment | Target status |
|---|---|---|---|---|
| Shared Seed Launch | left navy launch node and three-way branch | `none` | Partial correspondence | Remove from strict legend; directly label the unique neutral/navy launch node and three-way branch |
| Per-Message Personalized Top20（current: Independent message queues） | 当前是三条 blue/green/orange queue sequences，没有明确 Top20 selection mark | `none`; stable per-message ranking and capacity contract | 单一 cobalt swatch 不完整，名称也缺少 personalized ranking 与 Top20 capacity | Replace with inherited Message channels plus a ranking-rail + neutral-candidates + `Top20` selection mark |
| Allowed cross-message overlap | no dedicated mark; repeated candidate shapes do not reliably identify one user | `none` | Legend item currently has no true Visual mark | Retain with neutral candidate nodes on different message rails, explicitly joined by a neutral connector and `same user` direct label |
| Message-Level Single Exposure（current: One exposure per pair） | 当前只有三组 terminal gate rails 与 circles，按 message channel 着色 | `none`; stable pair-level lifecycle contract | amber swatch 只匹配第三条 channel，且当前 mark 没有表达 exposure 后退出 eligible queue | Replace with pair → gate → exposed/closed plus neutral blocked/no-return state mark |

The Exposure Ranking target is closed by consensus.

#### Approved target legend

| Group | Target Legend item | Approved Visual mark | Data field/series | Interaction state |
|---|---|---|---|---|
| Message channels | First message channel | cobalt channel accent | authoritative first message identity; no quantitative bitmap series | Mechanism mode |
| Message channels | Second message channel | green channel accent | authoritative second message identity; no quantitative bitmap series | Mechanism mode |
| Message channels | Third message channel | amber channel accent | authoritative third message identity; no quantitative bitmap series | Mechanism mode |
| Mark grammar | Per-Message Personalized Top20 | message-colored ranking rail with neutral candidate nodes and explicit `Top20` selection bracket/gate | `none`; stable ranking and capacity contract | Mechanism mode |
| Mark grammar | Allowed cross-message overlap | neutral candidate instances on different message rails joined by a neutral connector and `same user` direct label | `none`; stable overlap permission | Mechanism mode |
| Mark grammar | Message-Level Single Exposure | pair-level gate followed by exposed/closed state and neutral blocked/no-return path | `none`; stable pair lifecycle | Mechanism mode |

Shared Seed Launch、Batch 0、Batch 1–29、reranking progression arrows 和 `30 × Top20` capacity are direct labels or Narrative annotations and do not receive swatches.

### 4. LLM Decision Boundary

Source asset: `src/llm_abm_sim/report_assets/media-mechanism-llm-decision.png`
Status: Target semantics closed by consensus

| Current Legend item | Actual Visual mark | Data field/series | Assessment | Target status |
|---|---|---|---|---|
| Platform Environment | a multi-mark region containing network input, ranking grid and exposure gate | `none` | Not a single green mark; current swatch maps only part of the region | Remove from strict legend; directly label the complete pre-gate region and pair it with a directly labeled post-gate Decision Adapter region |
| Exposed user × message | cobalt user and message icons after the gate | `none` | Distinct mark exists, but cobalt can be misread as the first message channel and the pair occurs only once | Remove from strict legend; use a neutral composite `Exposed user × message pair` mark with a direct label |
| Message-User Fit | formula band and green-bordered hotspot annotation; no distinct bitmap mark | ranking-only derived proxy; no bitmap series | Narrative annotation currently masquerades as Legend item and appears too close to the post-exposure path | Remove from strict legend and post-exposure path; retain before the gate as `normalized_message_user_fit · ranking only` Narrative annotation |
| Primary Campaign Decision / Demographic Shadow Decision（current: Primary / Shadow pair） | 当前是 separate cobalt Primary path 与 amber dashed Shadow path，却只有一个 amber swatch | `none`; stable paired Decision roles | One swatch collapses two roles, while role colors conflict with the message-channel palette | Split into two strict Legend items: neutral solid/filled Primary and neutral dashed/hollow Shadow, both directly labeled |
| Not selected this batch（unlegended current X paths） | dotted paths ending in X marks near or beyond the gate | per-batch candidate `selected=false`; no bitmap series | X implies terminal exit, but source shows the pair remains eligible until later exposure or horizon end | Replace with a pre-gate neutral dotted loop-back and direct label; do not add to strict legend |

The LLM Decision target is closed by consensus.

#### Approved target legend

| Target Legend item | Approved Visual mark | Data field/series | Interaction state |
|---|---|---|---|
| Exposure Gate | gate icon separating Platform selection from post-exposure Decision handling | `none`; stable exposure boundary | Mechanism mode |
| Primary Campaign Decision | neutral solid path with filled terminal | `none`; stable runtime Decision role | Mechanism mode |
| Demographic Shadow Decision | neutral dashed path with hollow terminal | `none`; stable report-only paired Decision role | Mechanism mode |

Platform Environment、Decision Adapter、`normalized_message_user_fit · ranking only`、`Not selected this batch · no Decision call · remains eligible` 和 the unique Exposed user × message pair use direct labels or Narrative annotations and do not receive swatches.

Source verification: `concurrent_message_experiment.py:1600-1605` builds each batch's eligible set by excluding only users already present in `exposed_by_message[message_id]`, while `concurrent_message_experiment.py:1623-1624` adds only selected users to that set. A candidate not selected in the current Top20 therefore receives no Decision call in that batch but remains eligible for a later batch. It is not a terminal exit or final Message-Level Below Delivery Capacity.

### 5. Network Feedback

Source asset: `src/llm_abm_sim/report_assets/media-mechanism-network-feedback.png`
Status: Target semantics closed by consensus

| Current Legend item | Actual Visual mark | Data field/series | Assessment | Target status |
|---|---|---|---|---|
| Propagating Primary action · like / comment / share（current: Successful Primary） | 当前是 three cobalt solid paths ending in check marks | `none`; stable positive-action feedback contract | Current green swatch is wrong, all three paths incorrectly share one message color, and `Successful Primary` can include or be confused with non-propagating provider success | Retain as a strict mark using inherited Message channels + solid path + filled positive-action node + terminal check |
| Campaign engaged-user set · deduplicated by user（current: Campaign-level deduplicated set） | 当前是 central green double-ring node | `none`; stable campaign engaged-user aggregation contract | Distinct mark exists, but green conflicts with the second message channel and the label omits membership and deduplication unit | Retain with a neutral merge/aggregate mark showing duplicate user inputs collapsing to one user; no run count |
| Next-batch per-message reranking（current: Next-batch rankings） | 当前是 three cobalt outgoing paths ending in check marks | `none`; stable next-batch ranking contract | All paths incorrectly share one message color, and check marks can be mistaken for action outcomes | Retain with inherited Message channels + outgoing ranking rail / ordered-candidate / `Top20` terminals; remove checks and mark next-batch-only timing |
| No campaign feedback（current: Stop paths） | 当前是 three amber dashed paths ending in X marks | `none`; stable non-propagation contract | Amber conflicts with the third message channel, while `Stop paths` and X imply broader termination than the actual feedback boundary | Retain with neutral dashed path + feedback barrier/zero-signal terminal; directly label Shadow、Primary `ignore` and `provider_failed` sources |

The Network Feedback target is closed by consensus.

#### Approved target legend

| Group | Target Legend item | Approved Visual mark | Data field/series | Interaction state |
|---|---|---|---|---|
| Message channels | First message channel | cobalt channel accent | authoritative first message identity; no quantitative bitmap series | Mechanism mode |
| Message channels | Second message channel | green channel accent | authoritative second message identity; no quantitative bitmap series | Mechanism mode |
| Message channels | Third message channel | amber channel accent | authoritative third message identity; no quantitative bitmap series | Mechanism mode |
| Feedback grammar | Propagating Primary action · like / comment / share | message-colored solid path + filled positive-action node + terminal check | `none`; stable propagation-source contract | Mechanism mode |
| Feedback grammar | Campaign engaged-user set · deduplicated by user | neutral merge/aggregate mark showing duplicate user inputs collapse to one user | `none`; stable campaign user-dedup contract | Mechanism mode |
| Feedback grammar | Next-batch per-message reranking | three message-colored outgoing paths ending in ranking rail / ordered-candidate / `Top20` marks | `none`; stable next-batch ranking contract | Mechanism mode |
| Feedback grammar | No campaign feedback | neutral dashed path + feedback barrier/zero-signal terminal | `none`; stable non-propagation contract | Mechanism mode |

The same-batch context frozen divider、Shadow / Primary `ignore` / `provider_failed` source labels、next-batch-only timing and non-causal/no-run-count limitations are direct labels or Narrative annotations and do not receive swatches.

## Interaction-State Findings

| State | Figures | Legends | Finding |
|---|---:|---:|---|
| Mechanism mode | 5 visible | 5 visible | All identified mismatches occur here |
| Run Evidence mode | 0 visible | 0 visible | No stale mechanism legend detected |
| Chinese / English | Same bitmap marks | Translated labels | Translation does not change mark correspondence |
| Hotspot hover/focus/open drawer | Same bitmap marks | Same legend | Annotation state changes only; no series visibility change |
| Run Evidence filters | Tables only | No legend | No zero-series or filtered-series legend issue currently applicable |

## Consensus Closure

五张受影响机制图的 Legend item → Visual mark → Data field/series → Interaction state 映射均已闭合，当前没有未决设计分支。现有 Run Evidence mode 没有 figure 或 legend，因此没有发现 stale、filtered 或 zero-series legend；未来 data-bound chart 统一遵守“有可观察 mark 才显示 Legend item”的最小规则。

本文只记录调查证据和设计共识，不授权修改 renderer、report assets、persisted Decisions、release contract 或 canonical webpage，也不授权 image generation、Provider/API 调用或 deployment。下一步由用户调用 `$to-spec-lqy`，把本记录整理为 executable Spec。
