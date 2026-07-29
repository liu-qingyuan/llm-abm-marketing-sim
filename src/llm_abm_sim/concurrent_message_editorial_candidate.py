from __future__ import annotations

import html
import json
from base64 import b64encode
from collections.abc import Mapping, Sequence
from importlib.resources import files
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .concurrent_message_report import ConcurrentMessageReportPayload


_EDITORIAL_LANGUAGES = ("zh-CN", "en-US")
_EDITORIAL_ANCHORS = ("overview", "sample", "exposure-ranking", "llm-decision", "network-feedback")
_EDITORIAL_ASSET_VERSION = "v1"


# This catalog belongs to the candidate. The general report dictionary does not own
# Concurrent-specific terms, source-language boundaries, or mechanism explanations.
_EDITORIAL_CATALOG: dict[str, dict[str, str]] = {
    "zh-CN": {
        "shell.brand": "Multi-Message 研究报告",
        "shell.nav_aria": "五段报告导航",
        "shell.mode_aria": "报告模式",
        "shell.legend_aria": "机制图例",
        "shell.language_aria": "报告语言",
        "nav.overview": "概览",
        "nav.sample": "样本",
        "nav.exposure-ranking": "曝光排序",
        "nav.llm-decision": "LLM 决策",
        "nav.network-feedback": "网络反馈",
        "mode.mechanism": "机制说明",
        "mode.run": "本次运行",
        "language.zh": "中文",
        "language.en": "English",
        "drawer.aria": "机制详情",
        "drawer.close": "关闭详情",
        "drawer.detail": "机制详情",
        "drawer.provenance": "证据归属",
        "drawer.usage": "使用阶段",
        "drawer.limitation": "限制",
        "overview.kicker": "机制说明 · 概览",
        "overview.title": "三条 message，同一个研究样本，并行进入独立队列",
        "overview.lead": "同一个 Research Sample 先存在，再与三条 message 分别形成三组 candidates。每条 message 维护自己的 personalized candidate queue；Platform Environment 先决定 exposure，Decision Adapter 只处理已经曝光的 user × message pair。",
        "overview.metric.sample": "Research Sample · 研究样本用户",
        "overview.metric.pairs": "Eligible pairs · 合格 user × message pairs",
        "overview.metric.messages": "Messages start together · 三条 message 同时开始",
        "overview.metric.capacity": "Per-message capacity · 每条 message 的容量",
        "overview.queue.label": "独立 Per-Message Queue",
        "overview.queue.body": "维护自己的 candidate ranking，不与其他 message 共用 quota。",
        "overview.queue.audience": "Intended Audience Segment · 设计描述",
        "overview.queue.source": "Authoritative source message",
        "overview.queue.source_summary": "查看 source-language message",
        "overview.queue.source_language": "Source language · 原始语言",
        "overview.figure.alt": "同一个 Research Sample 与三条 message 分别形成 user-message candidates，进入三条独立队列、曝光门控和已曝光 pair 决策的机制示意图",
        "overview.figure.caption": "同一研究样本先存在；三条 message 只是分别与它组合，不是由 queue 生成 sample。3,000 是 eligible pairs，30 × Top20 是每条 message 的独立容量合同。",
        "overview.legend.sample": "Research Sample",
        "overview.legend.message": "Messages",
        "overview.legend.candidates": "Candidate Sets",
        "overview.legend.queue": "Per-Message Queue",
        "overview.legend.gate": "Exposure Gate",
        "overview.legend.decision": "LLM Decisions",
        "overview.boundary.title": "稳定机制边界",
        "overview.boundary.body": "机制说明解释可复现的 simulation contract，不读取本次 run 的 exposure、action、Provider failure 或用户结果；这些 persisted evidence 只属于“本次运行”。",
        "sample.kicker": "机制说明 · 样本",
        "sample.title": "先确定传播起点，再补足 1,000 人研究样本",
        "sample.lead": "从完整合格用户池形成 Full-Pool Influence Seed Union，再只加入 seed 的 direct one-hop historical interaction neighbors，最后由 ordinary 用户补足规模。Network Cohort 不是多跳网络、好友关系或总体代表性随机抽样。",
        "sample.figure.alt": "完整合格用户池经过 Full-Pool Influence Seed Union、seed 的 direct one-hop historical interaction neighbors 和 ordinary fill 形成研究样本的机制示意图",
        "sample.figure.caption": "seed union → direct one-hop Network Cohort → ordinary fill → Research Sample。Synthetic Experiment Labels 只用于实验构造、审计和分组解释，不成为 Class routing gate。",
        "sample.legend.seed": "Influence Seed Union",
        "sample.legend.network": "Direct one-hop Network Cohort",
        "sample.legend.ordinary": "Ordinary fill",
        "sample.legend.labels": "Synthetic Experiment Labels",
        "sample.note.limitation.title": "Sample limitation",
        "sample.note.limitation.body": "Seed-first 设计保留与历史网络相连的用户，但不应解读为总体代表性随机样本；Network Cohort 只表示历史直接互动邻居。",
        "sample.note.labels.title": "Synthetic Experiment Labels",
        "sample.note.labels.body": "Class 与 value weights 用于实验构造、审计和分组解释；它们不是自然人口学事实，也不形成硬匹配 exposure routing。",
        "ranking.kicker": "机制说明 · 曝光排序",
        "ranking.title": "共享 Batch 0 起点，三条队列之后各自重排",
        "ranking.lead": "Platform Environment 先执行 Shared Seed Launch。Batch 1 起，三条 message 在各自 eligible user-message pairs 上独立进行 Per-Message Top20 reranking；同一 user 可以跨 message overlap，但同一 user × message pair 最多 exposure 一次。",
        "ranking.figure.alt": "三条 message 共享 Batch 0 seed launch，之后分别进行 Per-Message Top20 reranking，并由独立 exposure gate 选择已曝光 pair 的机制示意图",
        "ranking.figure.caption": "Shared Seed Launch 是共同起点，不是共享的单一 20-slot quota。每条 message 拥有 30 batches × Top20 的独立 capacity 与 pair-level exposure gate。",
        "ranking.legend.launch": "Shared Seed Launch",
        "ranking.legend.queue": "Independent message queues",
        "ranking.legend.overlap": "Allowed cross-message overlap",
        "ranking.legend.gate": "One exposure per pair",
        "ranking.contract.queue.title": "Per-message queues",
        "ranking.contract.queue.body": "三条 queue 独立维护候选；同一用户可以出现在一条或多条 message queue。",
        "ranking.contract.pair.title": "Message-Level Single Exposure",
        "ranking.contract.pair.body": "同一 user × message pair 一旦获得 exposure，就从该 message 的 eligible queue 移除；其他 message 仍可保留该用户。",
        "ranking.contract.capacity.title": "Per-Message Top20",
        "ranking.contract.capacity.body": "每条 message 在 30 个 batch 中各选择 Top20。三条 message 不争抢一个共享 quota。",
        "ranking.formula.title": "Current ranking score",
        "ranking.formula.body": "公式只属于 Platform Environment 的 ranking plane；Decision Adapter 不负责曝光排序。",
        "ranking.boundary.title": "机制说明的读法",
        "ranking.boundary.body": "这里描述方法合同，不预设任意 message 的 outcome、winner 或 causal effect。",
        "decision.kicker": "机制说明 · LLM 决策",
        "decision.title": "平台先决定 exposure，LLM 只处理已曝光 pair",
        "decision.lead": "Platform Environment 拥有 candidate、ranking、delivery capacity 和 exposure gate。Decision Adapter 在 exposure 之后读取当前 user × message，生成结构化 Primary 与 Shadow paired decisions；ranking evidence、Class、其他 messages 和 peer behavior 不进入 Prompt。",
        "decision.fit.title": "Message-User Fit · 六维适配",
        "decision.fit.body": "当前 message 的六维 0/1 value vector 与用户 signed value weights 做 cosine similarity，并归一化到 [0,1]。Class 不做硬匹配。",
        "decision.dimension.cognitive": "认知",
        "decision.dimension.environmental": "环境",
        "decision.dimension.functional": "功能",
        "decision.dimension.health": "健康",
        "decision.dimension.emotional": "情感",
        "decision.dimension.social": "社会",
        "decision.figure.alt": "Platform Environment 先选择曝光，Decision Adapter 再处理同一个 exposed user-message pair，并分出 Primary 与 report-only Shadow 的机制示意图",
        "decision.figure.caption": "Exposure 是 Platform Environment 的边界；Decision 是 Adapter 的边界。Shadow 与 Primary 共享一次 exposure，不改变 action、ranking、feedback 或 runtime state。",
        "decision.legend.platform": "Platform Environment",
        "decision.legend.pair": "Exposed user × message",
        "decision.legend.fit": "Message-User Fit",
        "decision.legend.paired": "Primary / Shadow pair",
        "decision.platform.title": "Platform Environment",
        "decision.platform.body": "负责 candidate queue、per-message ranking、delivery capacity 和 exposure gate；不由 LLM 选择谁被曝光。",
        "decision.adapter.title": "Decision Adapter",
        "decision.adapter.body": "仅在 exposure 后处理当前 user × message，输出 engage / probability / reason / confidence / action。",
        "decision.primary.title": "Primary",
        "decision.primary.body": "正常 runtime action path；只有成功的 Primary positive action 可以产生 campaign feedback。",
        "decision.shadow.title": "Shadow · report-only",
        "decision.shadow.body": "同一次 exposure 的 paired computation，只增加 gender、age、education、monthly_income 四项 Synthetic Experiment Labels。",
        "decision.boundary.title": "Prompt visibility boundary",
        "decision.boundary.body": "Ranking evidence、Class、其他 messages、peer behavior 和 raw payload 都不进入当前 pair 的 Prompt；本报告不展示 raw Prompt。",
        "feedback.kicker": "机制说明 · 网络反馈",
        "feedback.title": "成功 Primary 只影响下一批，同批 context 保持冻结",
        "feedback.lead": "三条 message 的成功 Primary like / comment / share 汇聚到唯一 campaign-level deduplicated user set，再共同进入下一批的三条独立 rankings。Shadow、ignore 和 provider_failed 在传播边界停止。",
        "feedback.figure.alt": "三条 message 的成功 Primary action 汇聚到唯一 campaign-level user deduplicated set，跨过 same-batch frozen divider 后进入三条 next-batch rankings，Shadow、ignore 和 provider_failed 停止传播的机制示意图",
        "feedback.figure.caption": "campaign-level dedup 是唯一共享反馈集合；same-batch context 保持冻结，反馈只在下一批 per-message global reranking 生效。",
        "feedback.legend.success": "Successful Primary",
        "feedback.legend.dedup": "Campaign-level deduplicated set",
        "feedback.legend.next": "Next-batch rankings",
        "feedback.legend.stop": "Stop paths",
        "feedback.source.title": "Propagation source",
        "feedback.source.body": "仅成功 Primary 的 like、comment、share 形成 campaign signal；跨 message 的成功用户按 campaign user 去重。",
        "feedback.stop.title": "Stop paths",
        "feedback.stop.body": "Shadow、ignore、provider_failed 不形成传播信号，不回写同批 ranking。",
        "feedback.time.title": "Time boundary",
        "feedback.time.body": "同批 context 冻结；信号只在下一批三条独立 ranking 中出现。",
        "run.kicker": "本次运行 · Editorial candidate",
        "run.title": "本次运行 evidence 将沿同一条研究链路展开",
        "run.lead": "当前 Ticket 先建立独立的 typed-payload shell。后续 Editorial Tickets 在这里加入概览、样本、曝光排序、LLM trace、网络反馈和 approved downloads；本占位不会调用或生成其他 renderer。",
        "run.status.title": "Typed payload source",
        "run.status.body": "这些 source values 保持原值；它们不是翻译 catalog 的一部分。",
        "run.contract.title": "Persisted contract",
        "run.contract.body": "schema、prompt tokens、model、message IDs、artifact names 和 Decision reasons 继续使用各自的 source language/value。",
        "run.placeholder.title": "后续 evidence surface",
        "run.placeholder.body": "本 section 的 anchor 与 hash grammar 已闭合；完整 run evidence 由后续 Ticket 直接从同一 typed payload 渲染。",
        "run.source.schema": "Payload schema",
        "run.source.profile": "Configuration profile",
        "run.source.model": "Observed model",
        "run.source.primary_token": "Primary prompt token",
        "run.source.shadow_token": "Shadow prompt token",
        "run.source.artifact": "Approved artifact",
        "run.source.approved_artifacts": "Approved artifacts · 已批准产物",
        "run.source.message": "Source message remains unchanged",
        "run.source.reason": "Persisted Decision reason remains unchanged",
        "detail.overview-start.label": "同时开始边界",
        "detail.overview-start.caption": "三条 message 在同一发布边界进入各自 queue",
        "detail.overview-pair.label": "user × message pair",
        "detail.overview-pair.caption": "只有 exposure 后才产生 Decision opportunity",
        "detail.sample-seed.label": "Full-Pool Influence Seed Union",
        "detail.sample-seed.caption": "从完整合格用户池形成研究起点",
        "detail.sample-network.label": "Direct one-hop Network Cohort",
        "detail.sample-network.caption": "只含 seed 的历史直接互动邻居",
        "detail.sample-ordinary.label": "ordinary sample",
        "detail.sample-ordinary.caption": "补足研究样本规模的普通角色",
        "detail.sample-labels.label": "Synthetic Experiment Labels",
        "detail.sample-labels.caption": "Class 与 value weights 的实验标签边界",
        "detail.ranking-launch.label": "Shared Seed Launch",
        "detail.ranking-launch.caption": "三条 queue 共用 Batch 0 的同一 seed union",
        "detail.ranking-queues.label": "three independent queues",
        "detail.ranking-queues.caption": "每条 message 维护自己的候选排序",
        "detail.ranking-pair.label": "same pair at most once",
        "detail.ranking-pair.caption": "同一 user × message 最多一次 exposure",
        "detail.ranking-overlap.label": "cross-message overlap",
        "detail.ranking-overlap.caption": "同一用户可以进入多条 message queue",
        "detail.decision-platform.label": "Platform Environment",
        "detail.decision-platform.caption": "平台拥有 ranking、capacity 和 exposure gate",
        "detail.decision-adapter.label": "Decision Adapter",
        "detail.decision-adapter.caption": "只处理已经曝光的当前 pair",
        "detail.decision-primary.label": "Primary decision",
        "detail.decision-primary.caption": "正常 runtime action path",
        "detail.decision-shadow.label": "Shadow decision",
        "detail.decision-shadow.caption": "同一次 exposure 的 report-only paired computation",
        "detail.decision-fit.label": "six-dimensional Message-User Fit",
        "detail.decision-fit.caption": "ranking-only 的六维 cosine fit evidence",
        "detail.feedback-primary.label": "Primary like / comment / share",
        "detail.feedback-primary.caption": "成功互动才产生 campaign signal",
        "detail.feedback-dedup.label": "campaign user deduplication",
        "detail.feedback-dedup.caption": "跨 message 成功用户只计一次",
        "detail.feedback-next.label": "next-batch reranking",
        "detail.feedback-next.caption": "只进入下一批 per-message ranking",
        "detail.feedback-stop.label": "Shadow / ignore / provider_failed",
        "detail.feedback-stop.caption": "不形成传播信号",
        "detail.feedback-freeze.label": "same-batch context freeze",
        "detail.feedback-freeze.caption": "同一批不回写当前 ranking",
    },
    "en-US": {
        "shell.brand": "Multi-Message Research Report",
        "shell.nav_aria": "Five-section report navigation",
        "shell.mode_aria": "Report mode",
        "shell.legend_aria": "Mechanism legend",
        "shell.language_aria": "Report language",
        "nav.overview": "Overview",
        "nav.sample": "Sample",
        "nav.exposure-ranking": "Exposure ranking",
        "nav.llm-decision": "LLM decision",
        "nav.network-feedback": "Network feedback",
        "mode.mechanism": "Mechanism",
        "mode.run": "This run",
        "language.zh": "中文",
        "language.en": "English",
        "drawer.aria": "Mechanism detail",
        "drawer.close": "Close detail",
        "drawer.detail": "Mechanism detail",
        "drawer.provenance": "Evidence provenance",
        "drawer.usage": "Usage stage",
        "drawer.limitation": "Limitation",
        "overview.kicker": "Mechanism · Overview",
        "overview.title": "Three messages, one research sample, three independent queues",
        "overview.lead": "The same Research Sample exists first, then forms three candidate sets with the three messages. Each message owns a personalized candidate queue; the Platform Environment chooses exposure first, and the Decision Adapter handles only the exposed user × message pair.",
        "overview.metric.sample": "Research Sample · users",
        "overview.metric.pairs": "Eligible pairs · user × message",
        "overview.metric.messages": "Messages start together",
        "overview.metric.capacity": "Per-message capacity",
        "overview.queue.label": "Independent Per-Message Queue",
        "overview.queue.body": "Owns its candidate ranking and does not share a quota with another message.",
        "overview.queue.audience": "Intended Audience Segment · design descriptor",
        "overview.queue.source": "Authoritative source message",
        "overview.queue.source_summary": "View source-language message",
        "overview.queue.source_language": "Source language",
        "overview.figure.alt": "Mechanism diagram showing one Research Sample forming three user-message candidate sets, then three independent queues, exposure gates, and decisions for exposed pairs",
        "overview.figure.caption": "The research sample exists first; messages combine with it separately rather than creating the sample. 3,000 is the eligible-pair denominator, and 30 × Top20 is an independent per-message capacity contract.",
        "overview.legend.sample": "Research Sample",
        "overview.legend.message": "Messages",
        "overview.legend.candidates": "Candidate Sets",
        "overview.legend.queue": "Per-Message Queue",
        "overview.legend.gate": "Exposure Gate",
        "overview.legend.decision": "LLM Decisions",
        "overview.boundary.title": "Stable mechanism boundary",
        "overview.boundary.body": "Mechanism mode explains the reproducible simulation contract. It does not read this run's exposure, action, provider-failure, or user outcomes; those persisted evidence belong to This run.",
        "sample.kicker": "Mechanism · Sample",
        "sample.title": "Establish the propagation starting point, then fill a 1,000-user sample",
        "sample.lead": "The full eligible pool forms the Full-Pool Influence Seed Union. Only the seed users' direct one-hop historical interaction neighbors enter the Network Cohort, and ordinary users fill the remaining capacity. This is not a multi-hop graph, friendship graph, or representative random sample.",
        "sample.figure.alt": "Mechanism diagram showing the full eligible pool becoming an Influence Seed Union, direct one-hop historical interaction neighbors, ordinary fill, and the final research sample",
        "sample.figure.caption": "Seed union → direct one-hop Network Cohort → ordinary fill → Research Sample. Synthetic Experiment Labels support experiment construction, audit, and grouped interpretation; they are not a Class routing gate.",
        "sample.legend.seed": "Influence Seed Union",
        "sample.legend.network": "Direct one-hop Network Cohort",
        "sample.legend.ordinary": "Ordinary fill",
        "sample.legend.labels": "Synthetic Experiment Labels",
        "sample.note.limitation.title": "Sample limitation",
        "sample.note.limitation.body": "Seed-first sampling preserves users connected to historical network evidence, but it is not a representative random sample. Network Cohort means historical direct interaction neighbors only.",
        "sample.note.labels.title": "Synthetic Experiment Labels",
        "sample.note.labels.body": "Class and value weights are synthetic experiment labels for construction, audit, and grouped interpretation. They are not natural demographic facts or hard exposure-routing rules.",
        "ranking.kicker": "Mechanism · Exposure ranking",
        "ranking.title": "Share the Batch 0 launch, then rerank each queue independently",
        "ranking.lead": "The Platform Environment performs the Shared Seed Launch first. From Batch 1 onward, each message independently reranks its eligible user-message pairs with Per-Message Top20; a user may overlap across messages, but one user × message pair can be exposed at most once.",
        "ranking.figure.alt": "Mechanism diagram showing three messages sharing the Batch 0 seed launch, then independently reranking Per-Message Top20 queues with separate exposure gates",
        "ranking.figure.caption": "Shared Seed Launch is a common starting point, not one shared 20-slot quota. Each message owns 30 batches × Top20 and its pair-level exposure gate.",
        "ranking.legend.launch": "Shared Seed Launch",
        "ranking.legend.queue": "Independent message queues",
        "ranking.legend.overlap": "Allowed cross-message overlap",
        "ranking.legend.gate": "One exposure per pair",
        "ranking.contract.queue.title": "Per-message queues",
        "ranking.contract.queue.body": "Each queue maintains its own candidates; the same user may appear in one or more message queues.",
        "ranking.contract.pair.title": "Message-Level Single Exposure",
        "ranking.contract.pair.body": "After a user × message pair is exposed, it leaves that message's eligible queue; the user can remain eligible for another message.",
        "ranking.contract.capacity.title": "Per-Message Top20",
        "ranking.contract.capacity.body": "Each message selects Top20 in 30 batches. The three messages do not compete for one shared quota.",
        "ranking.formula.title": "Current ranking score",
        "ranking.formula.body": "The formula belongs to the Platform Environment ranking plane; the Decision Adapter does not schedule exposure.",
        "ranking.boundary.title": "How to read this mechanism",
        "ranking.boundary.body": "This is a method contract. It does not predeclare a message outcome, winner, or causal effect.",
        "decision.kicker": "Mechanism · LLM decision",
        "decision.title": "The platform chooses exposure; the LLM handles only the exposed pair",
        "decision.lead": "The Platform Environment owns candidates, ranking, delivery capacity, and the exposure gate. After exposure, the Decision Adapter reads the current user × message and produces paired Primary and Shadow decisions; ranking evidence, Class, other messages, and peer behavior are excluded from the Prompt.",
        "decision.fit.title": "Message-User Fit · six dimensions",
        "decision.fit.body": "The current message's six-dimensional 0/1 value vector is compared with signed user value weights by cosine similarity and normalized to [0,1]. Class is not a hard match.",
        "decision.dimension.cognitive": "Cognitive",
        "decision.dimension.environmental": "Environmental",
        "decision.dimension.functional": "Functional",
        "decision.dimension.health": "Health",
        "decision.dimension.emotional": "Emotional",
        "decision.dimension.social": "Social",
        "decision.figure.alt": "Mechanism diagram showing the Platform Environment choosing exposure, the Decision Adapter handling one exposed user-message pair, and Primary plus report-only Shadow paths",
        "decision.figure.caption": "Exposure is the Platform Environment boundary; decision is the Adapter boundary. Shadow and Primary share one exposure and do not change action, ranking, feedback, or runtime state.",
        "decision.legend.platform": "Platform Environment",
        "decision.legend.pair": "Exposed user × message",
        "decision.legend.fit": "Message-User Fit",
        "decision.legend.paired": "Primary / Shadow pair",
        "decision.platform.title": "Platform Environment",
        "decision.platform.body": "Owns candidate queues, per-message ranking, delivery capacity, and the exposure gate; the LLM does not choose who is exposed.",
        "decision.adapter.title": "Decision Adapter",
        "decision.adapter.body": "Handles the current user × message only after exposure and returns engage / probability / reason / confidence / action.",
        "decision.primary.title": "Primary",
        "decision.primary.body": "The normal runtime action path; only a successful Primary positive action can produce campaign feedback.",
        "decision.shadow.title": "Shadow · report-only",
        "decision.shadow.body": "A paired computation for the same exposure that adds only gender, age, education, and monthly_income Synthetic Experiment Labels.",
        "decision.boundary.title": "Prompt visibility boundary",
        "decision.boundary.body": "Ranking evidence, Class, other messages, peer behavior, and raw payload are excluded from the current pair's Prompt; this report does not show the raw Prompt.",
        "feedback.kicker": "Mechanism · Network feedback",
        "feedback.title": "Successful Primary affects the next batch only; same-batch context stays frozen",
        "feedback.lead": "Successful Primary like / comment / share actions from the three messages flow into one campaign-level deduplicated user set, then jointly enter the next batch's three independent rankings. Shadow, ignore, and provider_failed stop at the propagation boundary.",
        "feedback.figure.alt": "Mechanism diagram showing successful Primary actions from three messages flowing into one campaign-level deduplicated user set, crossing a same-batch frozen divider into three next-batch rankings, while Shadow, ignore, and provider_failed stop",
        "feedback.figure.caption": "Campaign-level deduplication is the one shared feedback set. Same-batch context stays frozen, and feedback takes effect only in the next per-message global reranking.",
        "feedback.legend.success": "Successful Primary",
        "feedback.legend.dedup": "Campaign-level deduplicated set",
        "feedback.legend.next": "Next-batch rankings",
        "feedback.legend.stop": "Stop paths",
        "feedback.source.title": "Propagation source",
        "feedback.source.body": "Only successful Primary like, comment, and share actions form campaign signal; successful users are deduplicated at campaign level across messages.",
        "feedback.stop.title": "Stop paths",
        "feedback.stop.body": "Shadow, ignore, and provider_failed do not form propagation signal or write back into the current batch ranking.",
        "feedback.time.title": "Time boundary",
        "feedback.time.body": "The same-batch context is frozen; signal appears only in the next batch's three independent rankings.",
        "run.kicker": "This run · Editorial candidate",
        "run.title": "This run's evidence will follow the same research chain",
        "run.lead": "This Ticket establishes an independent typed-payload shell first. Later Editorial Tickets add overview, sample, exposure ranking, LLM trace, network feedback, and approved downloads here; this scaffold does not call or generate another renderer.",
        "run.status.title": "Typed payload source",
        "run.status.body": "These source values remain unchanged; they are not translation-catalog entries.",
        "run.contract.title": "Persisted contract",
        "run.contract.body": "Schema, prompt tokens, model, message IDs, artifact names, and Decision reasons keep their source language or value.",
        "run.placeholder.title": "Later evidence surface",
        "run.placeholder.body": "The anchor and hash grammar are closed here; later Tickets render the complete run evidence from the same typed payload.",
        "run.source.schema": "Payload schema",
        "run.source.profile": "Configuration profile",
        "run.source.model": "Observed model",
        "run.source.primary_token": "Primary prompt token",
        "run.source.shadow_token": "Shadow prompt token",
        "run.source.artifact": "Approved artifact",
        "run.source.approved_artifacts": "Approved artifacts",
        "run.source.message": "Source message remains unchanged",
        "run.source.reason": "Persisted Decision reason remains unchanged",
        "detail.overview-start.label": "Simultaneous start boundary",
        "detail.overview-start.caption": "The three messages enter their queues at one publication boundary",
        "detail.overview-pair.label": "user × message pair",
        "detail.overview-pair.caption": "A Decision opportunity exists only after exposure",
        "detail.sample-seed.label": "Full-Pool Influence Seed Union",
        "detail.sample-seed.caption": "The research starting point formed from the full eligible pool",
        "detail.sample-network.label": "Direct one-hop Network Cohort",
        "detail.sample-network.caption": "Only historical direct interaction neighbors of seeds",
        "detail.sample-ordinary.label": "ordinary sample",
        "detail.sample-ordinary.caption": "The ordinary role that fills the research sample",
        "detail.sample-labels.label": "Synthetic Experiment Labels",
        "detail.sample-labels.caption": "The experiment-label boundary for Class and value weights",
        "detail.ranking-launch.label": "Shared Seed Launch",
        "detail.ranking-launch.caption": "The three queues share the same Batch 0 seed union",
        "detail.ranking-queues.label": "three independent queues",
        "detail.ranking-queues.caption": "Each message maintains its own candidate ranking",
        "detail.ranking-pair.label": "same pair at most once",
        "detail.ranking-pair.caption": "One exposure at most for each user × message",
        "detail.ranking-overlap.label": "cross-message overlap",
        "detail.ranking-overlap.caption": "One user may enter more than one message queue",
        "detail.decision-platform.label": "Platform Environment",
        "detail.decision-platform.caption": "The platform owns ranking, capacity, and the exposure gate",
        "detail.decision-adapter.label": "Decision Adapter",
        "detail.decision-adapter.caption": "Handles only the current exposed pair",
        "detail.decision-primary.label": "Primary decision",
        "detail.decision-primary.caption": "The normal runtime action path",
        "detail.decision-shadow.label": "Shadow decision",
        "detail.decision-shadow.caption": "A report-only paired computation for the same exposure",
        "detail.decision-fit.label": "six-dimensional Message-User Fit",
        "detail.decision-fit.caption": "Ranking-only six-dimensional cosine-fit evidence",
        "detail.feedback-primary.label": "Primary like / comment / share",
        "detail.feedback-primary.caption": "Only successful interaction produces campaign signal",
        "detail.feedback-dedup.label": "campaign user deduplication",
        "detail.feedback-dedup.caption": "A successful user counts once across messages",
        "detail.feedback-next.label": "next-batch reranking",
        "detail.feedback-next.caption": "Signal enters the next per-message ranking only",
        "detail.feedback-stop.label": "Shadow / ignore / provider_failed",
        "detail.feedback-stop.caption": "These paths do not form propagation signal",
        "detail.feedback-freeze.label": "same-batch context freeze",
        "detail.feedback-freeze.caption": "The current batch ranking is not written back",
    },
}


# Detail records are separate from the visible label catalog so the drawer can
# re-render without rebuilding the report or storing language in the URL.
_EDITORIAL_DETAILS: dict[str, dict[str, dict[str, str]]] = {
    "overview-start": {
        "zh-CN": {
            "title": "同时开始边界",
            "definition": "三条 authoritative message 在同一个发布边界进入各自的 candidate queue，不按 message 顺序获得先发优势。",
            "provenance": "Synthetic Experiment Contract（合成实验合同）",
            "usage": "Campaign setup（活动初始化） / Ranking（排序）",
            "limitation": "这里解释稳定流程，不展示任意一次 run 的实际 exposure 或 action。",
        },
        "en-US": {
            "title": "Simultaneous start boundary",
            "definition": "The three authoritative messages enter their own candidate queues at one publication boundary; message order does not create a first-mover advantage.",
            "provenance": "Synthetic Experiment Contract",
            "usage": "Campaign setup / Ranking",
            "limitation": "This explains the stable flow, not exposure or action from any particular run.",
        },
    },
    "overview-pair": {
        "zh-CN": {
            "title": "user × message pair",
            "definition": "一个 user × message pair 只有在 Platform Environment 选择 exposure 后才产生 Primary 与 Shadow 的配对 Decision opportunity。",
            "provenance": "Runtime Contract（运行时合同）",
            "usage": "Exposure（曝光） / Decision（决策）",
            "limitation": "没有 exposure 的 pair 不调用 Decision Adapter。",
        },
        "en-US": {
            "title": "user × message pair",
            "definition": "A user × message pair creates a paired Primary and Shadow Decision opportunity only after the Platform Environment selects exposure.",
            "provenance": "Runtime Contract",
            "usage": "Exposure / Decision",
            "limitation": "A pair without exposure does not call the Decision Adapter.",
        },
    },
    "sample-seed": {
        "zh-CN": {
            "title": "Full-Pool Influence Seed Union",
            "definition": "从完整合格用户池形成研究起点的 seed union；它让后续队列有机会观察与历史网络相连的用户。",
            "provenance": "Derived Proxy Metric（派生代理指标）",
            "usage": "Sampling（抽样） / Batch 0 setup（Batch 0 初始化）",
            "limitation": "Seed-first 样本不是总体代表性随机样本，也不是本次 run 的 outcome。",
        },
        "en-US": {
            "title": "Full-Pool Influence Seed Union",
            "definition": "The seed union forms the research starting point from the full eligible pool and preserves an opportunity to observe users connected to historical network evidence.",
            "provenance": "Derived Proxy Metric",
            "usage": "Sampling / Batch 0 setup",
            "limitation": "Seed-first sampling is not a representative random sample or this run's outcome.",
        },
    },
    "sample-network": {
        "zh-CN": {
            "title": "Direct one-hop Network Cohort",
            "definition": "Network Cohort 只含 seed 的历史直接互动邻居，用于保留网络传播识别机会。",
            "provenance": "Historical Behavioral Evidence（历史行为证据）",
            "usage": "Sampling（抽样） / Ranking（排序）",
            "limitation": "连接来自评论、回复或 mention 派生关系，不等于好友关系、多跳关系或真实可见同伴行为。",
        },
        "en-US": {
            "title": "Direct one-hop Network Cohort",
            "definition": "Network Cohort contains only historical direct interaction neighbors of seed users, preserving an opportunity to observe network signal.",
            "provenance": "Historical Behavioral Evidence",
            "usage": "Sampling / Ranking",
            "limitation": "The edges are derived from comments, replies, or mentions. They are not friendship, multi-hop, or real visible peer behavior.",
        },
    },
    "sample-ordinary": {
        "zh-CN": {
            "title": "ordinary sample",
            "definition": "ordinary 角色在 seed 与 Network Cohort 进入配额后补足研究样本，保持完整 sample 的研究范围。",
            "provenance": "Sample Construction（样本构造）",
            "usage": "Sampling（抽样）",
            "limitation": "ordinary 不表示合成用户，也不保证总体代表性。",
        },
        "en-US": {
            "title": "ordinary sample",
            "definition": "The ordinary role fills the research sample after seed and Network Cohort quotas are applied.",
            "provenance": "Sample Construction",
            "usage": "Sampling",
            "limitation": "Ordinary does not mean synthetic and does not guarantee population representativeness.",
        },
    },
    "sample-labels": {
        "zh-CN": {
            "title": "Synthetic Experiment Labels",
            "definition": "Class 与 value weights 是用于实验构造、审计和分组解释的合成实验标签，不是自然人口学事实。",
            "provenance": "Synthetic Experiment Label（合成实验标签）",
            "usage": "Fit（适配） / Report Only（仅报告展示）",
            "limitation": "Class 名称不作为硬匹配 routing 条件。",
        },
        "en-US": {
            "title": "Synthetic Experiment Labels",
            "definition": "Class and value weights are synthetic experiment labels for construction, audit, and grouped interpretation, not natural demographic facts.",
            "provenance": "Synthetic Experiment Label",
            "usage": "Fit / Report Only",
            "limitation": "Class names are not hard routing conditions.",
        },
    },
    "ranking-launch": {
        "zh-CN": {
            "title": "Shared Seed Launch",
            "definition": "三条 queue 在 Batch 0 共用同一个 Full-Pool Influence Seed Union；这是共同起点，不是三条结果的比较。",
            "provenance": "Synthetic Experiment Contract（合成实验合同）",
            "usage": "Batch 0 Ranking（Batch 0 排序）",
            "limitation": "共同 seed 起点不预设任意 message 的 outcome。",
        },
        "en-US": {
            "title": "Shared Seed Launch",
            "definition": "The three queues share one Full-Pool Influence Seed Union in Batch 0; it is a common starting point, not a comparison of outcomes.",
            "provenance": "Synthetic Experiment Contract",
            "usage": "Batch 0 Ranking",
            "limitation": "A shared seed starting point does not predeclare a message outcome.",
        },
    },
    "ranking-queues": {
        "zh-CN": {
            "title": "three independent queues",
            "definition": "每条 message 维护自己的 personalized candidate queue，并在后续 batch 进行自己的全局重排。",
            "provenance": "Per-Message Personalized Top20 Contract",
            "usage": "Ranking（排序） / Exposure（曝光）",
            "limitation": "message queue 独立不代表用户受众互斥。",
        },
        "en-US": {
            "title": "three independent queues",
            "definition": "Each message maintains its own personalized candidate queue and performs its own global reranking in later batches.",
            "provenance": "Per-Message Personalized Top20 Contract",
            "usage": "Ranking / Exposure",
            "limitation": "Independent queues do not make the user audiences mutually exclusive.",
        },
    },
    "ranking-pair": {
        "zh-CN": {
            "title": "same pair at most once",
            "definition": "同一个 user × message pair 一旦获得 exposure，就从该 message 的 eligible queue 移除；其他 message 仍可保留该用户。",
            "provenance": "Runtime Contract（运行时合同）",
            "usage": "Eligibility（资格） / Exposure（曝光）",
            "limitation": "这是 pair-level 规则，不是 user-level 全局屏蔽。",
        },
        "en-US": {
            "title": "same pair at most once",
            "definition": "Once a user × message pair is exposed, it leaves that message's eligible queue; another message may still retain the user.",
            "provenance": "Runtime Contract",
            "usage": "Eligibility / Exposure",
            "limitation": "This is a pair-level rule, not a global user-level block.",
        },
    },
    "ranking-overlap": {
        "zh-CN": {
            "title": "cross-message overlap",
            "definition": "同一用户可以进入多条 message queue；每个 message 独立计算该 user × message 的 fit 与 ranking evidence。",
            "provenance": "Per-Message Queue Contract",
            "usage": "Ranking（排序） / Campaign Coverage（活动覆盖）",
            "limitation": "跨 message overlap 只说明受众可重叠，不生成 message 比较结论。",
        },
        "en-US": {
            "title": "cross-message overlap",
            "definition": "The same user may enter multiple message queues; each message calculates its user × message fit and ranking evidence independently.",
            "provenance": "Per-Message Queue Contract",
            "usage": "Ranking / Campaign Coverage",
            "limitation": "Cross-message overlap indicates possible audience overlap; it does not create a message comparison conclusion.",
        },
    },
    "decision-platform": {
        "zh-CN": {
            "title": "Platform Environment",
            "definition": "Platform Environment 负责候选、per-message ranking、delivery capacity 和 exposure gate；LLM 不参与曝光调度。",
            "provenance": "Platform Environment Contract",
            "usage": "Ranking（排序） / Exposure（曝光）",
            "limitation": "平台排序证据不等同已曝光用户的 action。",
        },
        "en-US": {
            "title": "Platform Environment",
            "definition": "The Platform Environment owns candidates, per-message ranking, delivery capacity, and the exposure gate; the LLM does not schedule exposure.",
            "provenance": "Platform Environment Contract",
            "usage": "Ranking / Exposure",
            "limitation": "Platform ranking evidence is not an exposed user's action.",
        },
    },
    "decision-adapter": {
        "zh-CN": {
            "title": "Decision Adapter",
            "definition": "Decision Adapter 只在 exposure 之后处理当前 user × message，并返回 engage、probability、reason、confidence、action。",
            "provenance": "Decision Adapter Contract",
            "usage": "LLM Decision（LLM 决策）",
            "limitation": "Ranking evidence、Class 和其他 messages 不进入当前 pair 的 Prompt。",
        },
        "en-US": {
            "title": "Decision Adapter",
            "definition": "The Decision Adapter handles the current user × message only after exposure and returns engage, probability, reason, confidence, and action.",
            "provenance": "Decision Adapter Contract",
            "usage": "LLM Decision",
            "limitation": "Ranking evidence, Class, and other messages are excluded from the current pair's Prompt.",
        },
    },
    "decision-primary": {
        "zh-CN": {
            "title": "Primary decision",
            "definition": "Primary 是当前 user × message exposure 的正常 Decision path，只有成功的 Primary positive action 可以产生 campaign feedback。",
            "provenance": "Runtime Simulation Contract（仿真运行合同）",
            "usage": "Decision（决策） / Feedback（反馈）",
            "limitation": "机制模式不展示本次 run 的 action 计数或分布。",
        },
        "en-US": {
            "title": "Primary decision",
            "definition": "Primary is the normal Decision path for the exposed user × message; only a successful Primary positive action can produce campaign feedback.",
            "provenance": "Runtime Simulation Contract",
            "usage": "Decision / Feedback",
            "limitation": "Mechanism mode does not show this run's action counts or distribution.",
        },
    },
    "decision-shadow": {
        "zh-CN": {
            "title": "Shadow decision",
            "definition": "Shadow 与同一 exposure 配对，只增加 gender、age、education、monthly_income 四项 Synthetic Experiment Labels。",
            "provenance": "Synthetic Experiment Label（合成实验标签）",
            "usage": "Paired Sensitivity（配对敏感性） / Report Only（仅报告展示）",
            "limitation": "Shadow 不是第二次 exposure，不改变 action、ranking、feedback 或 runtime state。",
        },
        "en-US": {
            "title": "Shadow decision",
            "definition": "Shadow is paired with the same exposure and adds only four Synthetic Experiment Labels: gender, age, education, and monthly_income.",
            "provenance": "Synthetic Experiment Label",
            "usage": "Paired Sensitivity / Report Only",
            "limitation": "Shadow is not a second exposure and does not change action, ranking, feedback, or runtime state.",
        },
    },
    "decision-fit": {
        "zh-CN": {
            "title": "six-dimensional Message-User Fit",
            "definition": "Message-User Fit 使用六维 message value vector 与 user signed value weights 的 cosine similarity；Class 不做硬匹配。",
            "provenance": "Derived Proxy Metric（派生代理指标）",
            "usage": "Ranking（排序） / Report Only（仅报告展示）",
            "limitation": "raw cosine 从 [-1,1] 归一化到 [0,1]；不把旧 historical affinity 放入 Multi-Message fit。",
        },
        "en-US": {
            "title": "six-dimensional Message-User Fit",
            "definition": "Message-User Fit uses cosine similarity between the six-dimensional message value vector and signed user value weights; Class is not a hard match.",
            "provenance": "Derived Proxy Metric",
            "usage": "Ranking / Report Only",
            "limitation": "Raw cosine is normalized from [-1,1] to [0,1]; legacy historical affinity is not part of Multi-Message fit.",
        },
    },
    "feedback-primary": {
        "zh-CN": {
            "title": "Primary like / comment / share",
            "definition": "只有成功 Primary 的 like、comment、share 可以形成 campaign-level feedback。",
            "provenance": "Campaign Feedback Contract",
            "usage": "Feedback（反馈） / Ranking（排序）",
            "limitation": "这是 simulation ranking feedback，不是现实平台观察或因果效果。",
        },
        "en-US": {
            "title": "Primary like / comment / share",
            "definition": "Only successful Primary like, comment, or share actions can form campaign-level feedback.",
            "provenance": "Campaign Feedback Contract",
            "usage": "Feedback / Ranking",
            "limitation": "This is simulation ranking feedback, not real-platform observation or causal effect.",
        },
    },
    "feedback-dedup": {
        "zh-CN": {
            "title": "campaign user deduplication",
            "definition": "跨三条 message 的成功 Primary 用户按 campaign user 去重后形成下一批的统一反馈集合。",
            "provenance": "Campaign Feedback Contract",
            "usage": "Feedback（反馈） / Ranking（排序）",
            "limitation": "同一用户成功互动多条 message 也只计一次 campaign signal。",
        },
        "en-US": {
            "title": "campaign user deduplication",
            "definition": "Successful Primary users from all three messages form one deduplicated campaign-level feedback set for the next batch.",
            "provenance": "Campaign Feedback Contract",
            "usage": "Feedback / Ranking",
            "limitation": "A user who succeeds on multiple messages contributes one campaign signal.",
        },
    },
    "feedback-next": {
        "zh-CN": {
            "title": "next-batch reranking",
            "definition": "去重后的 Primary feedback 只在下一批进入三条 message 各自的 per-message global reranking。",
            "provenance": "Runtime Contract（运行时合同）",
            "usage": "Next-batch Ranking（下一批排序）",
            "limitation": "这是推荐信号进入路径，不是已观测因果效果。",
        },
        "en-US": {
            "title": "next-batch reranking",
            "definition": "Deduplicated Primary feedback enters each message's per-message global reranking only in the next batch.",
            "provenance": "Runtime Contract",
            "usage": "Next-batch Ranking",
            "limitation": "This is the signal-entry path, not an observed causal effect.",
        },
    },
    "feedback-stop": {
        "zh-CN": {
            "title": "Shadow / ignore / provider_failed",
            "definition": "Shadow、ignore 和 provider_failed 都不形成 campaign propagation signal。",
            "provenance": "Runtime Contract（运行时合同）",
            "usage": "Feedback boundary（反馈边界）",
            "limitation": "这些路径不会回写同批 ranking，也不会改变当前 message 的其他 pair。",
        },
        "en-US": {
            "title": "Shadow / ignore / provider_failed",
            "definition": "Shadow, ignore, and provider_failed do not form a campaign propagation signal.",
            "provenance": "Runtime Contract",
            "usage": "Feedback boundary",
            "limitation": "These paths do not write back into the current batch ranking or change another pair.",
        },
    },
    "feedback-freeze": {
        "zh-CN": {
            "title": "same-batch context freeze",
            "definition": "同批 context 保持冻结；传播信号只在下一批 per-message global reranking 生效。",
            "provenance": "Runtime Contract（运行时合同）",
            "usage": "Batch boundary（批次边界）",
            "limitation": "当前批次不会因为同批成功 action 而重新排序。",
        },
        "en-US": {
            "title": "same-batch context freeze",
            "definition": "Same-batch context stays frozen; propagation signal takes effect only in the next per-message global reranking.",
            "provenance": "Runtime Contract",
            "usage": "Batch boundary",
            "limitation": "The current batch does not rerank because of a same-batch successful action.",
        },
    },
}


for _detail_key, _localized_detail in _EDITORIAL_DETAILS.items():
    for _language in _EDITORIAL_LANGUAGES:
        for _field, _value_text in _localized_detail[_language].items():
            _EDITORIAL_CATALOG[_language][f"drawer.{_detail_key}.{_field}"] = _value_text


# Fail at import time if a future copy edit leaves the candidate bilingual contract
# asymmetric. This is intentionally independent from the shared report i18n map.
def _validate_editorial_catalog() -> None:
    expected = set(_EDITORIAL_CATALOG["zh-CN"])
    for _language in _EDITORIAL_LANGUAGES:
        actual = set(_EDITORIAL_CATALOG[_language])
        if actual != expected:
            raise ValueError(
                f"Editorial catalog key mismatch for {_language}: "
                f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
            )


_validate_editorial_catalog()


_EDITORIAL_ASSET_CATALOG: dict[str, dict[str, str]] = {
    "overview": {
        "file": "editorial-mechanism-overview-v1.webp",
        "source": "media-mechanism-overview.png",
        "source_sha256": "fe2843b01e9249c435253f720a9b95d5494726590f7062ea6a355131169308f5",
        "version": _EDITORIAL_ASSET_VERSION,
    },
    "sample": {
        "file": "editorial-mechanism-sample-v1.webp",
        "source": "media-mechanism-sample.png",
        "source_sha256": "add302631c30897badefe1187f2fadf355c6381e90bef186e55555cbdc1f5cff",
        "version": _EDITORIAL_ASSET_VERSION,
    },
    "exposure-ranking": {
        "file": "editorial-mechanism-exposure-ranking-v1.webp",
        "source": "media-mechanism-exposure-ranking.png",
        "source_sha256": "7a17cb52deb1a6a681708a9ffa164ccb08ab31011f8da9e3a90229045b4e6984",
        "version": _EDITORIAL_ASSET_VERSION,
    },
    "llm-decision": {
        "file": "editorial-mechanism-llm-decision-v1.webp",
        "source": "media-mechanism-llm-decision.png",
        "source_sha256": "1503d4669da9b6d844cb9f674b89b19143a56ff9e8c8132437f4218276a4a337",
        "version": _EDITORIAL_ASSET_VERSION,
    },
    "network-feedback": {
        "file": "editorial-mechanism-network-feedback-v1.webp",
        "source": "media-mechanism-network-feedback.png",
        "source_sha256": "c136cb0ca5f7cd231f95f7e7c74f6fb3e1ed3ce465fb822ae7e603c41956a951",
        "version": _EDITORIAL_ASSET_VERSION,
    },
}


def _value(source: object, key: str, default: object = "") -> object:
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _escaped(value: object, *, quote: bool = False) -> str:
    return html.escape(str(value), quote=quote)


def _copy(key: str, language: str = "zh-CN") -> str:
    return _EDITORIAL_CATALOG[language][key]


def _i18n(key: str, *, tag: str = "span", class_name: str = "", attrs: str = "") -> str:
    classes = f' class="{_escaped(class_name, quote=True)}"' if class_name else ""
    return (
        f'<{tag}{classes} data-i18n="{_escaped(key, quote=True)}"{attrs}>'
        f"{_escaped(_copy(key), quote=False)}</{tag}>"
    )


def _attribute_i18n(key: str, attribute: str) -> str:
    return (
        f'data-i18n-{_escaped(attribute, quote=True)}="{_escaped(key, quote=True)}" '
        f'{attribute}="{_escaped(_copy(key), quote=True)}"'
    )


def _asset_bytes(asset_key: str) -> bytes:
    asset = _EDITORIAL_ASSET_CATALOG[asset_key]
    return files("llm_abm_sim").joinpath("report_assets").joinpath(asset["file"]).read_bytes()


def _embedded_asset(asset_key: str) -> str:
    return "data:image/webp;base64," + b64encode(_asset_bytes(asset_key)).decode("ascii")


def _paragraphs(value: object) -> str:
    text = str(value or "")
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    if not paragraphs:
        return '<p class="editorial-empty-source">&nbsp;</p>'
    return "".join(f"<p>{_escaped(paragraph)}</p>" for paragraph in paragraphs)


def _hotspot(
    *,
    detail_key: str,
    test_id: str,
    label_key: str,
    class_name: str = "",
) -> str:
    classes = f"editorial-hotspot {class_name}".strip()
    aria_key = f"detail.{detail_key}.label"
    return (
        f'<button class="{_escaped(classes, quote=True)}" type="button" '
        f'data-mechanism-key="{_escaped(detail_key, quote=True)}" '
        f'data-testid="{_escaped(test_id, quote=True)}" '
        f'{_attribute_i18n(aria_key, "aria-label")} '
        'aria-expanded="false" aria-controls="trace-drawer">'
        f'{_i18n(label_key, tag="strong")} '
        f'{_i18n(f"detail.{detail_key}.caption", tag="span")} '
        "</button>"
    )


def _legend(items: Sequence[tuple[str, str]]) -> str:
    return (
        f'<div class="editorial-legend" role="list" {_attribute_i18n("shell.legend_aria", "aria-label")}>'
        + "".join(
            f'<span role="listitem"><i class="editorial-swatch editorial-swatch-{_escaped(color, quote=True)}" aria-hidden="true"></i>'
            f'{_i18n(key)}</span>'
            for color, key in items
        )
        + "</div>"
    )


def _source_message(message: object, index: int) -> str:
    message_id = _escaped(_value(message, "message_id", f"message_{index}"), quote=True)
    title = _escaped(_value(message, "title", message_id))
    audience = _escaped(_value(message, "intended_audience_segment", ""))
    body = _paragraphs(_value(message, "body", ""))
    return (
        f'<details class="editorial-source-message" data-testid="editorial-source-message-{index}" '
        f'data-message-id="{message_id}">'
        f"<summary>{_i18n('overview.queue.source_summary')}</summary>"
        f'<div class="editorial-source-body">'
        f'<p class="editorial-source-label">{_i18n("overview.queue.source")}</p>'
        f'<h4>{title}</h4>'
        f'<p><code>{message_id}</code> · {audience}</p>'
        f'<p class="editorial-source-language">{_i18n("overview.queue.source_language")}</p>'
        f"{body}</div></details>"
    )


def _queue_cards(payload: Any) -> str:
    messages = _value(payload, "messages", [])
    cards: list[str] = []
    for index, message in enumerate(messages if isinstance(messages, Sequence) else [], start=1):
        message_id = _escaped(_value(message, "message_id", f"message_{index}"), quote=True)
        title = _escaped(_value(message, "title", message_id))
        audience = _escaped(_value(message, "intended_audience_segment", ""))
        cards.append(
            f'<article class="editorial-queue-card editorial-queue-card-{index}" '
            f'data-testid="mechanism-message-queue-{index}" data-message-id="{message_id}">'
            f'<span class="editorial-queue-index">MESSAGE 0{index}</span>'
            f"<h3>{title}</h3>"
            f'<p><code>{message_id}</code> {_i18n("overview.queue.body")}</p>'
            f'<p class="editorial-queue-audience">{_i18n("overview.queue.audience")}：{audience}</p>'
            f"{_source_message(message, index)}"
            "</article>"
        )
    return "".join(cards)


def _figure(
    *,
    asset_key: str,
    test_id: str,
    alt_key: str,
    caption_key: str,
    hotspots: str,
) -> str:
    asset = _EDITORIAL_ASSET_CATALOG[asset_key]
    return (
        f'<figure class="editorial-figure editorial-figure-{_escaped(asset_key, quote=True)}" '
        f'data-testid="{_escaped(test_id, quote=True)}" data-asset-key="{_escaped(asset_key, quote=True)}" '
        f'data-asset-file="{_escaped(asset["file"], quote=True)}" '
        f'data-source-sha256="{_escaped(asset["source_sha256"], quote=True)}">'
        f'<img data-testid="{_escaped(test_id, quote=True)}-media" src="{_embedded_asset(asset_key)}" '
        f'data-asset-file="{_escaped(asset["file"], quote=True)}" width="1536" height="1024" '
        f'{_attribute_i18n(alt_key, "alt")}>'
        f'<div class="editorial-hotspot-layer">{hotspots}</div>'
        f"{_i18n(caption_key, tag='figcaption', class_name='editorial-figure-caption')}"
        "</figure>"
    )


def _mechanism_html(payload: Any) -> str:
    run = _value(payload, "run", {})
    funnel = _value(payload, "campaign_funnel", {})
    sample_size = _as_int(_value(run, "sample_size", 1000), 1000)
    message_count = len(_value(payload, "messages", [])) if isinstance(_value(payload, "messages", []), Sequence) else 3
    eligible_pairs = _as_int(_value(funnel, "eligible_user_message_pairs", sample_size * message_count), sample_size * message_count)
    horizon = _as_int(_value(run, "horizon", 30), 30)
    capacity = _as_int(_value(run, "delivery_capacity", 20), 20)
    queue_cards = _queue_cards(payload)

    overview_hotspots = "".join(
        (
            _hotspot(
                detail_key="overview-start",
                test_id="mechanism-overview-hotspot-start",
                label_key="detail.overview-start.label",
                class_name="editorial-hotspot-start",
            ),
            _hotspot(
                detail_key="overview-pair",
                test_id="mechanism-overview-hotspot-pair",
                label_key="detail.overview-pair.label",
                class_name="editorial-hotspot-pair",
            ),
        )
    )
    sample_hotspots = "".join(
        (
            _hotspot(
                detail_key="sample-seed",
                test_id="mechanism-sample-hotspot-seed",
                label_key="detail.sample-seed.label",
                class_name="editorial-hotspot-seed",
            ),
            _hotspot(
                detail_key="sample-network",
                test_id="mechanism-sample-hotspot-network",
                label_key="detail.sample-network.label",
                class_name="editorial-hotspot-network",
            ),
            _hotspot(
                detail_key="sample-ordinary",
                test_id="mechanism-sample-hotspot-ordinary",
                label_key="detail.sample-ordinary.label",
                class_name="editorial-hotspot-ordinary",
            ),
            _hotspot(
                detail_key="sample-labels",
                test_id="mechanism-sample-hotspot-labels",
                label_key="detail.sample-labels.label",
                class_name="editorial-hotspot-labels",
            ),
        )
    )
    ranking_hotspots = "".join(
        (
            _hotspot(
                detail_key="ranking-launch",
                test_id="mechanism-exposure-hotspot-launch",
                label_key="detail.ranking-launch.label",
                class_name="editorial-hotspot-launch",
            ),
            _hotspot(
                detail_key="ranking-queues",
                test_id="mechanism-exposure-hotspot-queues",
                label_key="detail.ranking-queues.label",
                class_name="editorial-hotspot-queues",
            ),
            _hotspot(
                detail_key="ranking-pair",
                test_id="mechanism-exposure-hotspot-pair-gate",
                label_key="detail.ranking-pair.label",
                class_name="editorial-hotspot-pair-gate",
            ),
            _hotspot(
                detail_key="ranking-overlap",
                test_id="mechanism-exposure-hotspot-overlap",
                label_key="detail.ranking-overlap.label",
                class_name="editorial-hotspot-overlap",
            ),
        )
    )
    decision_hotspots = "".join(
        (
            _hotspot(
                detail_key="decision-platform",
                test_id="mechanism-platform-hotspot",
                label_key="detail.decision-platform.label",
                class_name="editorial-hotspot-platform",
            ),
            _hotspot(
                detail_key="decision-adapter",
                test_id="mechanism-adapter-hotspot",
                label_key="detail.decision-adapter.label",
                class_name="editorial-hotspot-adapter",
            ),
            _hotspot(
                detail_key="decision-primary",
                test_id="mechanism-primary-hotspot",
                label_key="detail.decision-primary.label",
                class_name="editorial-hotspot-primary",
            ),
            _hotspot(
                detail_key="decision-shadow",
                test_id="mechanism-shadow-hotspot",
                label_key="detail.decision-shadow.label",
                class_name="editorial-hotspot-shadow",
            ),
            _hotspot(
                detail_key="decision-fit",
                test_id="mechanism-fit-hotspot",
                label_key="detail.decision-fit.label",
                class_name="editorial-hotspot-fit",
            ),
        )
    )
    feedback_hotspots = "".join(
        (
            _hotspot(
                detail_key="feedback-primary",
                test_id="mechanism-feedback-hotspot-primary",
                label_key="detail.feedback-primary.label",
                class_name="editorial-hotspot-primary",
            ),
            _hotspot(
                detail_key="feedback-dedup",
                test_id="mechanism-feedback-hotspot-dedup",
                label_key="detail.feedback-dedup.label",
                class_name="editorial-hotspot-dedup",
            ),
            _hotspot(
                detail_key="feedback-next",
                test_id="mechanism-feedback-hotspot-next",
                label_key="detail.feedback-next.label",
                class_name="editorial-hotspot-next",
            ),
            _hotspot(
                detail_key="feedback-stop",
                test_id="mechanism-feedback-hotspot-stop",
                label_key="detail.feedback-stop.label",
                class_name="editorial-hotspot-stop",
            ),
            _hotspot(
                detail_key="feedback-freeze",
                test_id="mechanism-feedback-hotspot-freeze",
                label_key="detail.feedback-freeze.label",
                class_name="editorial-hotspot-freeze",
            ),
        )
    )

    return f"""
      <section id="overview" class="editorial-section editorial-section-overview" data-section-anchor="overview" data-testid="mechanism-overview-section" tabindex="-1">
        <div class="editorial-section-header">
          <div>
            {_i18n("overview.kicker", class_name="editorial-kicker")}
            {_i18n("overview.title", tag="h1")}
          </div>
          {_i18n("overview.lead", tag="p", class_name="editorial-lead")}
        </div>
        <div class="editorial-metric-strip" data-testid="mechanism-contract-strip">
          <article data-testid="mechanism-sample-size"><strong>{sample_size:,}</strong>{_i18n("overview.metric.sample", tag="span")}</article>
          <article data-testid="mechanism-eligible-pairs"><strong>{eligible_pairs:,}</strong>{_i18n("overview.metric.pairs", tag="span")}</article>
          <article data-testid="mechanism-message-count"><strong>{message_count}</strong>{_i18n("overview.metric.messages", tag="span")}</article>
          <article data-testid="mechanism-batch-contract"><strong>{horizon} × Top{capacity}</strong>{_i18n("overview.metric.capacity", tag="span")}</article>
        </div>
        <div class="editorial-queue-grid" data-testid="mechanism-message-queues">{queue_cards}</div>
        {_figure(asset_key="overview", test_id="mechanism-overview-visual", alt_key="overview.figure.alt", caption_key="overview.figure.caption", hotspots=overview_hotspots)}
        {_legend((("navy", "overview.legend.sample"), ("cobalt", "overview.legend.message"), ("green", "overview.legend.candidates"), ("amber", "overview.legend.queue"), ("navy", "overview.legend.gate"), ("green", "overview.legend.decision")))}
        <div class="editorial-callout editorial-callout-amber" data-testid="mechanism-boundary-note"><strong>{_i18n("overview.boundary.title")}</strong>{_i18n("overview.boundary.body", tag="p")}</div>
      </section>

      <section id="sample" class="editorial-section editorial-section-sample" data-section-anchor="sample" data-testid="mechanism-sample-section" tabindex="-1">
        <div class="editorial-section-header">
          <div>
            {_i18n("sample.kicker", class_name="editorial-kicker")}
            {_i18n("sample.title", tag="h2")}
          </div>
          {_i18n("sample.lead", tag="p", class_name="editorial-lead")}
        </div>
        {_figure(asset_key="sample", test_id="mechanism-sample-visual", alt_key="sample.figure.alt", caption_key="sample.figure.caption", hotspots=sample_hotspots)}
        {_legend((("cobalt", "sample.legend.seed"), ("green", "sample.legend.network"), ("navy", "sample.legend.ordinary"), ("amber", "sample.legend.labels")))}
        <div class="editorial-note-grid">
          <article data-testid="mechanism-sample-limitation"><strong>{_i18n("sample.note.limitation.title")}</strong>{_i18n("sample.note.limitation.body", tag="p")}</article>
          <article data-testid="mechanism-synthetic-labels"><strong>{_i18n("sample.note.labels.title")}</strong>{_i18n("sample.note.labels.body", tag="p")}</article>
        </div>
      </section>

      <section id="exposure-ranking" class="editorial-section editorial-section-ranking" data-section-anchor="exposure-ranking" data-testid="mechanism-exposure-ranking-section" tabindex="-1">
        <div class="editorial-section-header">
          <div>
            {_i18n("ranking.kicker", class_name="editorial-kicker")}
            {_i18n("ranking.title", tag="h2")}
          </div>
          {_i18n("ranking.lead", tag="p", class_name="editorial-lead")}
        </div>
        {_figure(asset_key="exposure-ranking", test_id="mechanism-exposure-ranking-visual", alt_key="ranking.figure.alt", caption_key="ranking.figure.caption", hotspots=ranking_hotspots)}
        {_legend((("navy", "ranking.legend.launch"), ("cobalt", "ranking.legend.queue"), ("green", "ranking.legend.overlap"), ("amber", "ranking.legend.gate")))}
        <div class="editorial-rule-grid">
          <article data-testid="mechanism-queue-contract"><strong>{_i18n("ranking.contract.queue.title")}</strong>{_i18n("ranking.contract.queue.body", tag="p")}</article>
          <article data-testid="mechanism-exposure-contract"><strong>{_i18n("ranking.contract.pair.title")}</strong>{_i18n("ranking.contract.pair.body", tag="p")}</article>
          <article data-testid="mechanism-reranking-contract"><strong>{_i18n("ranking.contract.capacity.title")}</strong>{_i18n("ranking.contract.capacity.body", tag="p")}</article>
        </div>
        <div class="editorial-formula-band" data-testid="mechanism-ranking-formula">
          <div><strong>{_i18n("ranking.formula.title")}</strong>{_i18n("ranking.formula.body", tag="p")}</div>
          <code>0.50 × base_network_relevance + 0.30 × campaign_engaged_neighbor_signal + 0.20 × normalized_message_user_fit</code>
        </div>
        <div class="editorial-callout" data-testid="mechanism-ranking-boundary"><strong>{_i18n("ranking.boundary.title")}</strong>{_i18n("ranking.boundary.body", tag="p")}</div>
      </section>

      <section id="llm-decision" class="editorial-section editorial-section-decision" data-section-anchor="llm-decision" data-testid="mechanism-llm-decision-section" tabindex="-1">
        <div class="editorial-section-header">
          <div>
            {_i18n("decision.kicker", class_name="editorial-kicker")}
            {_i18n("decision.title", tag="h2")}
          </div>
          {_i18n("decision.lead", tag="p", class_name="editorial-lead")}
        </div>
        <div class="editorial-fit-band" data-testid="mechanism-message-user-fit">
          <div><strong>{_i18n("decision.fit.title")}</strong>{_i18n("decision.fit.body", tag="p")}
            <div class="editorial-dimensions" {_attribute_i18n("decision.fit.title", "aria-label")}>
              {_i18n("decision.dimension.cognitive")}{_i18n("decision.dimension.environmental")}{_i18n("decision.dimension.functional")}{_i18n("decision.dimension.health")}{_i18n("decision.dimension.emotional")}{_i18n("decision.dimension.social")}
            </div>
          </div>
          <div class="editorial-formulas">
            <code data-testid="mechanism-fit-cosine">raw_message_user_fit = cosine(message 0/1 value vector, user signed value weights)</code>
            <code data-testid="mechanism-fit-normalization">normalized_message_user_fit = (raw + 1) / 2 · [-1,1] → [0,1]</code>
            <code data-testid="mechanism-fit-score">score = 0.50 × base_network_relevance + 0.30 × campaign_engaged_neighbor_signal + 0.20 × normalized_message_user_fit</code>
          </div>
        </div>
        {_figure(asset_key="llm-decision", test_id="mechanism-decision-visual", alt_key="decision.figure.alt", caption_key="decision.figure.caption", hotspots=decision_hotspots)}
        {_legend((("green", "decision.legend.platform"), ("cobalt", "decision.legend.pair"), ("green", "decision.legend.fit"), ("amber", "decision.legend.paired")))}
        <div class="editorial-rule-grid editorial-responsibility-grid">
          <article data-testid="mechanism-platform-responsibility"><strong>{_i18n("decision.platform.title")}</strong>{_i18n("decision.platform.body", tag="p")}</article>
          <article data-testid="mechanism-adapter-responsibility"><strong>{_i18n("decision.adapter.title")}</strong>{_i18n("decision.adapter.body", tag="p")}</article>
          <article data-testid="mechanism-primary-boundary"><strong>{_i18n("decision.primary.title")}</strong>{_i18n("decision.primary.body", tag="p")}</article>
          <article data-testid="mechanism-shadow-boundary"><strong>{_i18n("decision.shadow.title")}</strong>{_i18n("decision.shadow.body", tag="p")}</article>
        </div>
        <div class="editorial-callout editorial-callout-amber" data-testid="mechanism-prompt-boundary"><strong>{_i18n("decision.boundary.title")}</strong>{_i18n("decision.boundary.body", tag="p")}</div>
      </section>

      <section id="network-feedback" class="editorial-section editorial-section-feedback" data-section-anchor="network-feedback" data-testid="mechanism-network-feedback-section" tabindex="-1">
        <div class="editorial-section-header">
          <div>
            {_i18n("feedback.kicker", class_name="editorial-kicker")}
            {_i18n("feedback.title", tag="h2")}
          </div>
          {_i18n("feedback.lead", tag="p", class_name="editorial-lead")}
        </div>
        {_figure(asset_key="network-feedback", test_id="mechanism-feedback-visual", alt_key="feedback.figure.alt", caption_key="feedback.figure.caption", hotspots=feedback_hotspots)}
        {_legend((("green", "feedback.legend.success"), ("green", "feedback.legend.dedup"), ("cobalt", "feedback.legend.next"), ("amber", "feedback.legend.stop")))}
        <div class="editorial-rule-grid editorial-feedback-grid">
          <article data-testid="mechanism-feedback-positive"><strong>{_i18n("feedback.source.title")}</strong>{_i18n("feedback.source.body", tag="p")}</article>
          <article data-testid="mechanism-feedback-stop"><strong>{_i18n("feedback.stop.title")}</strong>{_i18n("feedback.stop.body", tag="p")}</article>
          <article data-testid="mechanism-feedback-freeze"><strong>{_i18n("feedback.time.title")}</strong>{_i18n("feedback.time.body", tag="p")}</article>
        </div>
      </section>
    """


def _observed_model(payload: Any) -> str:
    accounting = _value(payload, "variant_provider_accounting", {})
    primary = _value(accounting, "primary", {})
    model_counts = _value(primary, "observed_model_counts", {})
    if isinstance(model_counts, Mapping) and model_counts:
        return str(next(iter(model_counts)))
    return ""


def _run_scaffold(payload: Any) -> str:
    run = _value(payload, "run", {})
    schema = _value(payload, "schema_version", "")
    profile = _value(run, "configuration_profile", "")
    model = _observed_model(payload)
    prompt_tokens = _value(run, "prompt_tokens", {})
    primary_token = _value(prompt_tokens, "primary", "")
    shadow_token = _value(prompt_tokens, "shadow", "")
    downloads = _value(payload, "downloads", {})
    artifact_values = []
    if isinstance(downloads, Mapping):
        artifact_values = [str(value) for _, value in sorted(downloads.items())]
    else:
        artifact_values = [str(value) for value in sorted(vars(downloads).values()) if isinstance(value, str)]
    artifact_rows = "".join(
        f'<li><code>{_escaped(artifact)}</code></li>' for artifact in artifact_values
    )

    sections: list[str] = []
    for anchor in _EDITORIAL_ANCHORS:
        sections.append(
            f'<section id="run-{_escaped(anchor, quote=True)}" class="editorial-section editorial-run-section" '
            f'data-section-anchor="{_escaped(anchor, quote=True)}" data-testid="run-{_escaped(anchor, quote=True)}-section" tabindex="-1">'
            f'<div class="editorial-section-header"><div>{_i18n("run.kicker", class_name="editorial-kicker")}'
            f'<h2>{_i18n("run.placeholder.title")}</h2></div>{_i18n("run.placeholder.body", tag="p", class_name="editorial-lead")}</div>'
            f'<p class="editorial-run-anchor-note"><code>#run/{_escaped(anchor)}</code></p></section>'
        )

    return (
        '<div class="editorial-run-scaffold" data-testid="editorial-run-scaffold">'
        '<section class="editorial-run-intro editorial-section" data-section-anchor="overview" data-testid="run-intro" tabindex="-1">'
        '<div class="editorial-section-header"><div>'
        f'{_i18n("run.kicker", class_name="editorial-kicker")}{_i18n("run.title", tag="h1")}'
        f'</div>{_i18n("run.lead", tag="p", class_name="editorial-lead")}</div>'
        '<div class="editorial-run-summary-grid">'
        f'<article><strong>{_i18n("run.status.title")}</strong>{_i18n("run.status.body", tag="p")}'
        '<dl class="editorial-source-list">'
        f'<div><dt>{_i18n("run.source.schema")}</dt><dd><code>{_escaped(schema)}</code></dd></div>'
        f'<div><dt>{_i18n("run.source.profile")}</dt><dd><code>{_escaped(profile)}</code></dd></div>'
        f'<div><dt>{_i18n("run.source.model")}</dt><dd><code>{_escaped(model)}</code></dd></div>'
        '</dl></article>'
        f'<article><strong>{_i18n("run.contract.title")}</strong>{_i18n("run.contract.body", tag="p")}'
        '<dl class="editorial-source-list">'
        f'<div><dt>{_i18n("run.source.primary_token")}</dt><dd><code>{_escaped(primary_token)}</code></dd></div>'
        f'<div><dt>{_i18n("run.source.shadow_token")}</dt><dd><code>{_escaped(shadow_token)}</code></dd></div>'
        f'<div><dt>{_i18n("run.source.message")}</dt><dd>{_i18n("run.source.message")}</dd></div>'
        f'<div><dt>{_i18n("run.source.reason")}</dt><dd>{_i18n("run.source.reason")}</dd></div>'
        '</dl></article>'
        f'<article class="editorial-artifact-list"><strong>{_i18n("run.source.approved_artifacts")}</strong><ul>'
        f'{artifact_rows}</ul></article>'
        '</div></section>'
        + "".join(sections)
        + "</div>"
    )


_EDITORIAL_CSS = r"""
:root {
  --editorial-ink: #081a3a;
  --editorial-muted: #667085;
  --editorial-rule: #d7dee8;
  --editorial-paper: #ffffff;
  --editorial-cool-paper: #f5f7fa;
  --editorial-cobalt: #0b57d0;
  --editorial-green: #087a55;
  --editorial-amber: #c86f00;
  --editorial-header-offset: 76px;
}
* { box-sizing: border-box; }
html { min-width: 320px; scroll-padding-top: calc(var(--editorial-header-offset) + 16px); }
body { margin: 0; background: var(--editorial-paper); color: var(--editorial-ink); font-family: "PingFang SC", "Microsoft YaHei", system-ui, -apple-system, sans-serif; font-size: 16px; line-height: 1.55; letter-spacing: 0; }
button, input, select { font: inherit; letter-spacing: 0; }
button { cursor: pointer; }
code { overflow-wrap: anywhere; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.editorial-report { min-height: 100vh; background: var(--editorial-paper); }
.editorial-report *, .editorial-report *::before, .editorial-report *::after { box-sizing: border-box; }
.editorial-header { position: sticky; top: 0; z-index: 40; display: grid; grid-template-columns: auto minmax(0, 1fr) auto auto; align-items: center; gap: 26px; min-height: 76px; padding: 10px clamp(24px, 3vw, 48px); border-bottom: 1px solid var(--editorial-rule); background: rgba(255, 255, 255, .98); }
.editorial-brand { min-width: max-content; color: var(--editorial-ink); font-size: 19px; font-weight: 650; white-space: nowrap; }
.editorial-nav { display: flex; justify-content: center; gap: clamp(18px, 2.2vw, 36px); min-width: 0; overflow-x: auto; white-space: nowrap; }
.editorial-nav a { position: relative; display: inline-flex; align-items: center; min-height: 42px; padding: 8px 0; color: var(--editorial-ink); text-decoration: none; font-size: 15px; font-weight: 560; }
.editorial-nav a::after { position: absolute; right: 0; bottom: 0; left: 0; height: 3px; background: transparent; content: ""; }
.editorial-nav a:hover, .editorial-nav a:focus-visible, .editorial-nav a[aria-current="location"] { color: var(--editorial-cobalt); }
.editorial-nav a[aria-current="location"]::after { background: var(--editorial-cobalt); }
.editorial-mode-tabs { display: flex; gap: 2px; min-width: max-content; padding: 3px; border: 1px solid var(--editorial-rule); background: var(--editorial-paper); }
.editorial-mode-tabs button { min-height: 40px; padding: 7px 15px; border: 0; background: transparent; color: var(--editorial-ink); font-size: 14px; font-weight: 600; white-space: nowrap; }
.editorial-mode-tabs button[aria-selected="true"] { outline: 2px solid var(--editorial-cobalt); outline-offset: -2px; color: var(--editorial-cobalt); }
.editorial-language-tabs { display: flex; align-items: center; gap: 6px; min-width: max-content; }
.editorial-language-tabs button { padding: 4px 0; border: 0; background: transparent; color: var(--editorial-muted); font-size: 14px; }
.editorial-language-tabs button[aria-pressed="true"] { color: var(--editorial-cobalt); font-weight: 700; }
.editorial-language-divider { color: var(--editorial-rule); }
.editorial-mode-panel[hidden] { display: none !important; }
.editorial-section { min-width: 0; padding: clamp(58px, 6vw, 96px) clamp(24px, 4vw, 64px); border-bottom: 1px solid var(--editorial-rule); scroll-margin-top: calc(var(--editorial-header-offset) + 16px); }
.editorial-section-overview { background: #fbfdff; }
.editorial-section-sample { background: #ffffff; }
.editorial-section-ranking { background: #f7f9fc; }
.editorial-section-decision { background: #ffffff; }
.editorial-section-feedback { background: #f8fcfa; }
.editorial-section-header { display: grid; grid-template-columns: minmax(0, 1.08fr) minmax(300px, .92fr); gap: clamp(28px, 5vw, 80px); align-items: end; max-width: 1280px; margin: 0 auto 36px; }
.editorial-kicker { display: block; margin-bottom: 13px; color: var(--editorial-green); font-size: 15px; font-weight: 650; }
.editorial-section h1, .editorial-section h2 { max-width: 780px; margin: 0; color: var(--editorial-ink); font-size: clamp(34px, 3.1vw, 45px); font-weight: 650; line-height: 1.18; }
.editorial-section h1 { font-size: clamp(38px, 3.4vw, 48px); }
.editorial-section h3, .editorial-section h4 { margin: 0; color: var(--editorial-ink); line-height: 1.28; }
.editorial-lead { max-width: 580px; margin: 0; color: var(--editorial-ink); font-size: 17px; line-height: 1.68; }
.editorial-metric-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); max-width: 1280px; margin: 0 auto 28px; border-top: 1px solid var(--editorial-rule); border-bottom: 1px solid var(--editorial-rule); }
.editorial-metric-strip article { min-width: 0; min-height: 112px; padding: 18px 20px; border-right: 1px solid var(--editorial-rule); }
.editorial-metric-strip article:last-child { border-right: 0; }
.editorial-metric-strip strong { display: block; margin-bottom: 7px; color: var(--editorial-ink); font-size: 36px; font-weight: 650; line-height: 1; }
.editorial-metric-strip span { display: block; color: var(--editorial-muted); font-size: 13px; line-height: 1.45; }
.editorial-queue-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; max-width: 1280px; margin: 0 auto 36px; }
.editorial-queue-card { min-width: 0; padding: 20px; border-top: 3px solid var(--editorial-cobalt); border-bottom: 1px solid var(--editorial-rule); background: var(--editorial-paper); }
.editorial-queue-card-2 { border-top-color: var(--editorial-green); }
.editorial-queue-card-3 { border-top-color: var(--editorial-amber); }
.editorial-queue-index { display: block; margin-bottom: 9px; color: var(--editorial-cobalt); font-size: 12px; font-weight: 700; }
.editorial-queue-card-2 .editorial-queue-index { color: var(--editorial-green); }
.editorial-queue-card-3 .editorial-queue-index { color: var(--editorial-amber); }
.editorial-queue-card h3 { margin-bottom: 10px; font-size: 18px; overflow-wrap: anywhere; }
.editorial-queue-card > p { margin: 0 0 10px; color: var(--editorial-muted); line-height: 1.55; }
.editorial-queue-card code { color: var(--editorial-ink); }
.editorial-queue-audience { font-size: 13px; }
.editorial-source-message { margin-top: 17px; border-top: 1px solid var(--editorial-rule); }
.editorial-source-message summary { padding: 12px 0 2px; color: var(--editorial-cobalt); font-size: 13px; font-weight: 650; cursor: pointer; }
.editorial-source-body { padding-top: 10px; color: var(--editorial-muted); font-size: 13px; }
.editorial-source-body h4 { margin: 6px 0; font-size: 15px; }
.editorial-source-body p { margin: 0 0 10px; }
.editorial-source-body code { color: var(--editorial-ink); }
.editorial-source-label, .editorial-source-language { color: var(--editorial-green); font-weight: 650; }
.editorial-figure { position: relative; max-width: 1280px; min-width: 0; margin: 0 auto; }
.editorial-figure > img { display: block; width: 100%; height: auto; aspect-ratio: 3 / 2; border-top: 1px solid var(--editorial-rule); border-bottom: 1px solid var(--editorial-rule); background: var(--editorial-paper); object-fit: contain; }
.editorial-figure-caption { display: block; max-width: 960px; margin-top: 13px; color: var(--editorial-muted); font-size: 13px; line-height: 1.55; }
.editorial-hotspot-layer { position: absolute; inset: 0 auto auto 0; width: 100%; height: auto; aspect-ratio: 3 / 2; pointer-events: none; }
.editorial-hotspot { position: absolute; display: grid; gap: 2px; min-width: 146px; max-width: 220px; padding: 8px 10px; border: 1px solid var(--editorial-cobalt); background: rgba(255, 255, 255, .95); color: var(--editorial-ink); text-align: left; box-shadow: 0 5px 14px rgba(8, 26, 58, .1); pointer-events: auto; }
.editorial-hotspot strong, .editorial-hotspot span { display: block; overflow-wrap: anywhere; }
.editorial-hotspot strong { font-size: 12px; line-height: 1.25; }
.editorial-hotspot span { color: var(--editorial-muted); font-size: 11px; line-height: 1.25; }
.editorial-hotspot:hover, .editorial-hotspot:focus-visible, .editorial-hotspot[aria-expanded="true"] { outline: 3px solid rgba(11, 87, 208, .18); outline-offset: 2px; }
.editorial-hotspot-start { top: 6%; left: 3%; }
.editorial-hotspot-pair { right: 3%; bottom: 7%; }
.editorial-hotspot-seed { top: 20%; left: 20%; }
.editorial-hotspot-network { top: 27%; left: 43%; }
.editorial-hotspot-ordinary { right: 5%; bottom: 13%; }
.editorial-hotspot-labels { right: 3%; top: 6%; border-color: var(--editorial-amber); }
.editorial-hotspot-launch { top: 7%; left: 5%; }
.editorial-hotspot-queues { top: 6%; left: 39%; }
.editorial-hotspot-pair-gate { right: 3%; top: 41%; }
.editorial-hotspot-overlap { left: 39%; bottom: 8%; }
.editorial-hotspot-platform { top: 8%; left: 4%; border-color: var(--editorial-green); }
.editorial-hotspot-adapter { top: 10%; left: 48%; }
.editorial-hotspot-primary { right: 4%; top: 17%; }
.editorial-hotspot-shadow { right: 4%; bottom: 10%; border-color: var(--editorial-amber); }
.editorial-hotspot-fit { left: 37%; top: 43%; border-color: var(--editorial-green); }
.editorial-hotspot-dedup { left: 38%; top: 42%; border-color: var(--editorial-green); }
.editorial-hotspot-next { right: 4%; top: 10%; }
.editorial-hotspot-stop { right: 4%; bottom: 10%; border-color: var(--editorial-amber); }
.editorial-hotspot-freeze { left: 39%; bottom: 8%; }
.editorial-legend { display: flex; flex-wrap: wrap; gap: 10px 24px; max-width: 1280px; margin: 15px auto 0; color: var(--editorial-muted); font-size: 13px; line-height: 1.4; }
.editorial-legend span { display: inline-flex; align-items: center; gap: 7px; }
.editorial-swatch { display: inline-block; width: 11px; height: 11px; border: 1px solid currentColor; background: transparent; }
.editorial-swatch-navy { color: var(--editorial-ink); }
.editorial-swatch-cobalt { color: var(--editorial-cobalt); background: var(--editorial-cobalt); }
.editorial-swatch-green { color: var(--editorial-green); background: var(--editorial-green); }
.editorial-swatch-amber { color: var(--editorial-amber); background: var(--editorial-amber); }
.editorial-callout { display: grid; grid-template-columns: minmax(180px, .32fr) minmax(0, 1fr); gap: 20px; max-width: 1280px; margin: 32px auto 0; padding: 17px 20px; border-left: 4px solid var(--editorial-cobalt); background: var(--editorial-cool-paper); }
.editorial-callout strong { color: var(--editorial-ink); }
.editorial-callout p { margin: 0; color: var(--editorial-muted); line-height: 1.6; }
.editorial-callout-amber { border-left-color: var(--editorial-amber); background: #fffaf4; }
.editorial-note-grid, .editorial-rule-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; max-width: 1280px; margin: 32px auto 0; }
.editorial-rule-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.editorial-note-grid article, .editorial-rule-grid article { min-width: 0; padding: 18px 0 0; border-top: 2px solid var(--editorial-rule); }
.editorial-note-grid article:first-child, .editorial-rule-grid article:first-child { border-top-color: var(--editorial-cobalt); }
.editorial-note-grid article:last-child { border-top-color: var(--editorial-amber); }
.editorial-rule-grid article:nth-child(2) { border-top-color: var(--editorial-green); }
.editorial-rule-grid article:nth-child(3) { border-top-color: var(--editorial-amber); }
.editorial-note-grid strong, .editorial-rule-grid strong { display: block; margin-bottom: 7px; color: var(--editorial-ink); }
.editorial-note-grid p, .editorial-rule-grid p { margin: 0; color: var(--editorial-muted); line-height: 1.6; }
.editorial-formula-band { display: grid; grid-template-columns: minmax(220px, .42fr) minmax(0, 1.58fr); gap: 24px; max-width: 1280px; margin: 32px auto 0; padding: 18px 0; border-top: 1px solid var(--editorial-rule); border-bottom: 1px solid var(--editorial-rule); }
.editorial-formula-band strong { display: block; margin-bottom: 7px; color: var(--editorial-green); }
.editorial-formula-band p { margin: 0; color: var(--editorial-muted); font-size: 14px; }
.editorial-formula-band code, .editorial-formulas code { display: block; padding: 10px 12px; border-left: 3px solid var(--editorial-cobalt); background: var(--editorial-cool-paper); color: var(--editorial-ink); font-size: 13px; line-height: 1.55; }
.editorial-fit-band { display: grid; grid-template-columns: minmax(260px, .7fr) minmax(0, 1.3fr); gap: 30px; max-width: 1280px; margin: 0 auto 32px; padding: 20px 0; border-top: 1px solid var(--editorial-rule); border-bottom: 1px solid var(--editorial-rule); }
.editorial-fit-band strong { display: block; margin-bottom: 8px; color: var(--editorial-green); }
.editorial-fit-band p { margin: 0; color: var(--editorial-muted); line-height: 1.6; }
.editorial-dimensions { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 16px; }
.editorial-dimensions span { padding: 6px 9px; border: 1px solid #b9dfce; background: #f0faf5; color: var(--editorial-green); font-size: 12px; }
.editorial-formulas { display: grid; gap: 9px; min-width: 0; }
.editorial-formulas code:nth-child(2) { border-left-color: var(--editorial-green); }
.editorial-formulas code:nth-child(3) { border-left-color: var(--editorial-amber); }
.editorial-responsibility-grid, .editorial-feedback-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.editorial-responsibility-grid article:nth-child(3) { border-top-color: var(--editorial-cobalt); }
.editorial-responsibility-grid article:nth-child(4), .editorial-feedback-grid article:nth-child(3) { border-top-color: var(--editorial-amber); }
.editorial-detail-drawer { position: fixed; inset: 0; z-index: 80; display: grid; grid-template-columns: 1fr minmax(360px, 580px); background: rgba(8, 26, 58, .58); }
.editorial-detail-drawer[hidden] { display: none; }
.editorial-report[data-drawer-state="open"] .editorial-header { z-index: 90; }
.editorial-drawer-surface { min-width: 0; height: 100%; overflow: auto; padding: calc(var(--editorial-header-offset) + 28px) 32px 42px; background: var(--editorial-paper); box-shadow: -10px 0 30px rgba(8, 26, 58, .2); }
.editorial-drawer-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; padding-bottom: 18px; border-bottom: 1px solid var(--editorial-rule); }
.editorial-drawer-header h2 { margin: 0; color: var(--editorial-ink); font-size: 25px; line-height: 1.2; }
.editorial-drawer-close { width: 40px; height: 40px; flex: 0 0 40px; border: 1px solid var(--editorial-rule); background: var(--editorial-paper); color: var(--editorial-ink); font-size: 22px; line-height: 1; }
.editorial-drawer-close:hover, .editorial-drawer-close:focus-visible { border-color: var(--editorial-cobalt); color: var(--editorial-cobalt); }
.editorial-drawer-body { padding-top: 22px; color: var(--editorial-muted); }
.editorial-drawer-body p { margin: 0 0 16px; line-height: 1.65; }
.editorial-drawer-body dl { margin: 22px 0 0; }
.editorial-drawer-body dt { margin-top: 18px; color: var(--editorial-green); font-size: 12px; font-weight: 700; }
.editorial-drawer-body dd { margin: 4px 0 0; color: var(--editorial-ink); line-height: 1.55; }
.editorial-run-section { background: var(--editorial-paper); }
.editorial-run-intro { background: #fbfdff; }
.editorial-run-summary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); max-width: 1280px; margin: 0 auto; border-top: 1px solid var(--editorial-rule); border-bottom: 1px solid var(--editorial-rule); }
.editorial-run-summary-grid article { min-width: 0; padding: 20px; border-right: 1px solid var(--editorial-rule); }
.editorial-run-summary-grid article:last-child { border-right: 0; }
.editorial-run-summary-grid strong { display: block; margin-bottom: 7px; color: var(--editorial-ink); }
.editorial-run-summary-grid p { margin: 0 0 16px; color: var(--editorial-muted); line-height: 1.6; }
.editorial-source-list { display: grid; gap: 10px; margin: 0; }
.editorial-source-list div { min-width: 0; padding-top: 9px; border-top: 1px solid var(--editorial-rule); }
.editorial-source-list dt { color: var(--editorial-muted); font-size: 12px; }
.editorial-source-list dd { margin: 2px 0 0; color: var(--editorial-ink); font-size: 12px; overflow-wrap: anywhere; }
.editorial-artifact-list ul { max-height: 240px; margin: 0; padding-left: 18px; overflow: auto; color: var(--editorial-ink); font-size: 12px; }
.editorial-artifact-list li { margin-bottom: 7px; overflow-wrap: anywhere; }
.editorial-run-anchor-note { max-width: 1280px; margin: 0 auto; color: var(--editorial-muted); }
.editorial-run-anchor-note code { color: var(--editorial-cobalt); }
.editorial-section :focus-visible, .editorial-report button:focus-visible, .editorial-report a:focus-visible, .editorial-report summary:focus-visible { outline: 3px solid rgba(11, 87, 208, .3); outline-offset: 3px; }
@media (max-width: 1220px) {
  .editorial-header { grid-template-columns: auto minmax(0, 1fr) auto; gap: 18px; }
  .editorial-language-tabs { grid-column: 3; grid-row: 1; }
  .editorial-mode-tabs { grid-column: 1 / -1; grid-row: 2; justify-self: center; }
  .editorial-nav { grid-column: 2; grid-row: 1; }
}
@media (max-width: 820px) {
  .editorial-header { grid-template-columns: 1fr auto; align-items: center; }
  .editorial-brand { grid-column: 1; grid-row: 1; }
  .editorial-language-tabs { grid-column: 2; grid-row: 1; }
  .editorial-nav { grid-column: 1 / -1; grid-row: 2; justify-content: flex-start; }
  .editorial-mode-tabs { grid-column: 1 / -1; grid-row: 3; width: 100%; }
  .editorial-mode-tabs button { flex: 1; }
  .editorial-section-header, .editorial-fit-band, .editorial-formula-band { grid-template-columns: 1fr; gap: 18px; }
  .editorial-metric-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .editorial-metric-strip article:nth-child(2) { border-right: 0; }
  .editorial-metric-strip article:nth-child(-n + 2) { border-bottom: 1px solid var(--editorial-rule); }
  .editorial-queue-grid, .editorial-run-summary-grid { grid-template-columns: 1fr; }
  .editorial-run-summary-grid article { border-right: 0; border-bottom: 1px solid var(--editorial-rule); }
  .editorial-run-summary-grid article:last-child { border-bottom: 0; }
  .editorial-rule-grid, .editorial-responsibility-grid, .editorial-feedback-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 680px) {
  .editorial-header { padding: 10px 18px; }
  .editorial-nav { gap: 20px; }
  .editorial-nav a { font-size: 14px; }
  .editorial-section { padding: 48px 18px; }
  .editorial-section h1, .editorial-section h2 { font-size: 32px; }
  .editorial-lead { font-size: 16px; }
  .editorial-metric-strip { grid-template-columns: 1fr 1fr; }
  .editorial-metric-strip article { padding: 15px 12px; }
  .editorial-metric-strip strong { font-size: 28px; }
  .editorial-figure > img { aspect-ratio: 3 / 2; }
  .editorial-hotspot-layer { position: static; display: flex; flex-wrap: wrap; gap: 8px; width: auto; height: auto; aspect-ratio: auto; padding-top: 10px; }
  .editorial-hotspot { position: static; min-width: 0; max-width: none; flex: 1 1 180px; box-shadow: none; }
  .editorial-note-grid, .editorial-rule-grid, .editorial-responsibility-grid, .editorial-feedback-grid { grid-template-columns: 1fr; }
  .editorial-callout { grid-template-columns: 1fr; gap: 7px; }
  .editorial-detail-drawer { grid-template-columns: 1fr; }
  .editorial-drawer-surface { padding: calc(var(--editorial-header-offset) + 22px) 18px 32px; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: .01ms !important; animation-iteration-count: 1 !important; scroll-behavior: auto !important; transition-duration: .01ms !important; }
}
"""


_EDITORIAL_SCRIPT = r"""
(() => {
  const root = document.querySelector('[data-testid="editorial-report"]');
  if (!root) return;
  const catalog = __EDITORIAL_CATALOG__;
  const details = __EDITORIAL_DETAILS__;
  const anchors = ['overview', 'sample', 'exposure-ranking', 'llm-decision', 'network-feedback'];
  const languages = ['zh-CN', 'en-US'];
  const modeButtons = [...root.querySelectorAll('[data-report-mode-target]')];
  const modePanels = [...root.querySelectorAll('[data-report-mode-panel]')];
  const navigationLinks = [...root.querySelectorAll('[data-report-anchor]')];
  const languageButtons = [...root.querySelectorAll('[data-report-language]')];
  const header = root.querySelector('.editorial-header');
  const drawer = document.getElementById('trace-drawer');
  const drawerTitle = drawer?.querySelector('[data-testid="mechanism-detail-title"]');
  const drawerBody = drawer?.querySelector('[data-testid="mechanism-detail-body"]');
  const closeButton = drawer?.querySelector('[data-testid="editorial-drawer-close"]');
  const mechanismButtons = [...root.querySelectorAll('[data-mechanism-key]')];
  const state = { language: 'zh-CN', mode: 'mechanism', anchor: 'overview', drawerKey: null, returnFocus: null };
  let previousBodyOverflow = '';

  function copy(key) {
    return catalog[state.language][key] || key;
  }

  function syncHeaderOffset() {
    const height = Math.ceil(header?.getBoundingClientRect().height || 76);
    root.style.setProperty('--editorial-header-offset', `${height}px`);
    document.documentElement.style.setProperty('--editorial-header-offset', `${height}px`);
  }

  function applyLanguage() {
    const location = parseHash();
    if (window.location.hash) {
      state.mode = location.mode;
      state.anchor = location.anchor;
    }
    document.documentElement.lang = state.language;
    root.dataset.reportLanguage = state.language;
    root.querySelectorAll('[data-i18n]').forEach((element) => {
      const key = element.dataset.i18n;
      if (key) element.textContent = copy(key);
    });
    root.querySelectorAll('[data-i18n-aria-label]').forEach((element) => {
      element.setAttribute('aria-label', copy(element.dataset.i18nAriaLabel));
    });
    root.querySelectorAll('[data-i18n-alt]').forEach((element) => {
      element.setAttribute('alt', copy(element.dataset.i18nAlt));
    });
    root.querySelectorAll('[data-i18n-placeholder]').forEach((element) => {
      element.setAttribute('placeholder', copy(element.dataset.i18nPlaceholder));
    });
    languageButtons.forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.reportLanguage === state.language));
    });
    const title = document.querySelector('title[data-i18n]');
    if (title) title.textContent = copy(title.dataset.i18n);
    if (state.drawerKey) renderDrawer(state.drawerKey);
    setActiveNavigation(state.anchor);
  }

  function hashFor(mode, anchor) {
    return mode === 'run-evidence' ? `#run/${anchor}` : `#${anchor}`;
  }

  function parseHash() {
    const raw = window.location.hash.slice(1);
    if (raw.startsWith('run/') && anchors.includes(raw.slice(4))) return { mode: 'run-evidence', anchor: raw.slice(4) };
    if (anchors.includes(raw)) return { mode: 'mechanism', anchor: raw };
    return { mode: 'mechanism', anchor: 'overview' };
  }

  function targetFor(mode, anchor) {
    const panel = modePanels.find((candidate) => candidate.dataset.reportModePanel === mode);
    return panel?.querySelector(`[data-section-anchor="${anchor}"]`) || null;
  }

  function setActiveNavigation(anchor) {
    state.anchor = anchor;
    navigationLinks.forEach((link) => {
      if (link.dataset.reportAnchor === anchor) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
      link.setAttribute('href', hashFor(state.mode, link.dataset.reportAnchor));
    });
  }

  function setMode(mode) {
    state.mode = mode;
    root.dataset.reportMode = mode;
    modeButtons.forEach((button) => {
      const selected = button.dataset.reportModeTarget === mode;
      button.setAttribute('aria-selected', String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
    modePanels.forEach((panel) => {
      panel.hidden = panel.dataset.reportModePanel !== mode;
    });
    setActiveNavigation(state.anchor);
    syncHeaderOffset();
  }

  function applyLocation({ focus = false } = {}) {
    const location = parseHash();
    if (state.drawerKey && location.mode !== state.mode) closeDrawer(false);
    state.mode = location.mode;
    state.anchor = location.anchor;
    setMode(location.mode);
    setActiveNavigation(location.anchor);
    const target = targetFor(location.mode, location.anchor);
    if (focus && target) {
      target.scrollIntoView({ block: 'start' });
      target.focus({ preventScroll: true });
    }
  }

  function navigate(mode, anchor, focus) {
    closeDrawer(false);
    const nextHash = hashFor(mode, anchor);
    if (window.location.hash !== nextHash) history.pushState(null, '', nextHash);
    state.mode = mode;
    state.anchor = anchor;
    applyLocation({ focus });
  }

  function focusableInDrawer() {
    if (!drawer) return [];
    return [...drawer.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')]
      .filter((element) => !element.hasAttribute('disabled') && element.offsetParent !== null);
  }

  function renderDrawer(key) {
    const detail = details[key]?.[state.language];
    if (!detail || !drawerTitle || !drawerBody) return;
    drawerTitle.textContent = detail.title;
    drawerBody.innerHTML = '';
    const definition = document.createElement('p');
    definition.textContent = detail.definition;
    const list = document.createElement('dl');
    for (const [labelKey, value] of [
      ['drawer.provenance', detail.provenance],
      ['drawer.usage', detail.usage],
      ['drawer.limitation', detail.limitation],
    ]) {
      const label = document.createElement('dt');
      label.textContent = copy(labelKey);
      const valueElement = document.createElement('dd');
      valueElement.textContent = value;
      list.append(label, valueElement);
    }
    drawerBody.append(definition, list);
  }

  function openDrawer(key, trigger) {
    if (!drawer || !details[key]?.[state.language]) return;
    state.drawerKey = key;
    state.returnFocus = trigger;
    renderDrawer(key);
    drawer.hidden = false;
    root.dataset.drawerState = 'open';
    previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    mechanismButtons.forEach((button) => button.setAttribute('aria-expanded', String(button === trigger)));
    closeButton?.focus();
  }

  function closeDrawer(restoreFocus = true) {
    if (!drawer || drawer.hidden) return;
    const returnFocus = state.returnFocus;
    drawer.hidden = true;
    root.dataset.drawerState = 'closed';
    document.body.style.overflow = previousBodyOverflow;
    mechanismButtons.forEach((button) => button.setAttribute('aria-expanded', 'false'));
    state.drawerKey = null;
    state.returnFocus = null;
    if (restoreFocus && returnFocus?.isConnected) returnFocus.focus();
  }

  modeButtons.forEach((button, index) => {
    button.addEventListener('click', () => navigate(button.dataset.reportModeTarget, state.anchor, false));
    button.addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      event.preventDefault();
      const offset = event.key === 'ArrowRight' ? 1 : -1;
      const next = modeButtons[(index + offset + modeButtons.length) % modeButtons.length];
      next.focus();
      navigate(next.dataset.reportModeTarget, state.anchor, false);
    });
  });

  navigationLinks.forEach((link) => link.addEventListener('click', (event) => {
    event.preventDefault();
    navigate(state.mode, link.dataset.reportAnchor, true);
  }));

  languageButtons.forEach((button) => button.addEventListener('click', () => {
    const language = button.dataset.reportLanguage;
    if (!languages.includes(language) || language === state.language) return;
    state.language = language;
    applyLanguage();
  }));

  mechanismButtons.forEach((button) => button.addEventListener('click', () => openDrawer(button.dataset.mechanismKey, button)));
  closeButton?.addEventListener('click', () => closeDrawer(true));
  drawer?.addEventListener('click', (event) => {
    if (event.target === drawer) closeDrawer(true);
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && state.drawerKey) {
      event.preventDefault();
      closeDrawer(true);
      return;
    }
    if (event.key !== 'Tab' || !state.drawerKey) return;
    const focusable = focusableInDrawer();
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });

  window.addEventListener('hashchange', () => applyLocation({ focus: true }));
  window.addEventListener('popstate', () => applyLocation({ focus: true }));
  window.addEventListener('resize', syncHeaderOffset);
  if (typeof ResizeObserver === 'function' && header) new ResizeObserver(syncHeaderOffset).observe(header);

  if (typeof IntersectionObserver === 'function') {
    const visibleSections = new Set();
    const observer = new IntersectionObserver((entries) => {
      if (state.drawerKey) return;
      entries.forEach((entry) => {
        if (entry.isIntersecting && !entry.target.closest('[hidden]')) visibleSections.add(entry.target);
        else visibleSections.delete(entry.target);
      });
      const current = [...visibleSections]
        .filter((section) => !section.closest('[hidden]'))
        .sort((left, right) => Math.abs(left.getBoundingClientRect().top - 96) - Math.abs(right.getBoundingClientRect().top - 96))[0];
      if (current) setActiveNavigation(current.dataset.sectionAnchor);
    }, { rootMargin: '-96px 0px -55% 0px', threshold: 0 });
    root.querySelectorAll('[data-report-mode-panel] [data-section-anchor]').forEach((section) => observer.observe(section));
  }

  syncHeaderOffset();
  applyLanguage();
  applyLocation({ focus: window.location.hash.length > 0 });
})();
"""


def _render_editorial_candidate(payload: ConcurrentMessageReportPayload) -> str:
    """Render the private bilingual Editorial candidate directly from typed payload data."""
    mechanism = _mechanism_html(payload)
    run_scaffold = _run_scaffold(payload)
    title = _escaped(_value(payload, "title", "Multi-Message Research Report"), quote=True)
    catalog_json = json.dumps(_EDITORIAL_CATALOG, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    details_json = json.dumps(_EDITORIAL_DETAILS, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    script = _EDITORIAL_SCRIPT.replace("__EDITORIAL_CATALOG__", catalog_json).replace("__EDITORIAL_DETAILS__", details_json)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title data-i18n="shell.brand">{title}</title>
  <style>{_EDITORIAL_CSS}</style>
</head>
<body>
  <main class="editorial-report" data-testid="editorial-report" data-report-mode="mechanism" data-report-language="zh-CN" data-drawer-state="closed">
    <header class="editorial-header">
      <div class="editorial-brand" data-i18n="shell.brand">{_copy('shell.brand')}</div>
      <nav class="editorial-nav" aria-label="{_copy('shell.nav_aria')}" data-i18n-aria-label="shell.nav_aria">
        <a data-report-anchor="overview" href="#overview">{_copy('nav.overview')}</a>
        <a data-report-anchor="sample" href="#sample">{_copy('nav.sample')}</a>
        <a data-report-anchor="exposure-ranking" href="#exposure-ranking">{_copy('nav.exposure-ranking')}</a>
        <a data-report-anchor="llm-decision" href="#llm-decision">{_copy('nav.llm-decision')}</a>
        <a data-report-anchor="network-feedback" href="#network-feedback">{_copy('nav.network-feedback')}</a>
      </nav>
      <div class="editorial-mode-tabs" role="tablist" aria-label="{_copy('shell.mode_aria')}" data-i18n-aria-label="shell.mode_aria">
        <button id="editorial-mechanism-tab" type="button" role="tab" aria-selected="true" aria-controls="editorial-mechanism-panel" tabindex="0" data-report-mode-target="mechanism" data-testid="mechanism-mode-button">{_copy('mode.mechanism')}</button>
        <button id="editorial-run-tab" type="button" role="tab" aria-selected="false" aria-controls="editorial-run-panel" tabindex="-1" data-report-mode-target="run-evidence" data-testid="run-evidence-mode-button">{_copy('mode.run')}</button>
      </div>
      <div class="editorial-language-tabs" role="group" aria-label="{_copy('shell.language_aria')}" data-i18n-aria-label="shell.language_aria">
        <button type="button" data-report-language="zh-CN" aria-pressed="true">{_copy('language.zh')}</button>
        <span class="editorial-language-divider" aria-hidden="true">/</span>
        <button type="button" data-report-language="en-US" aria-pressed="false">{_copy('language.en')}</button>
      </div>
    </header>
    <section id="editorial-mechanism-panel" role="tabpanel" aria-labelledby="editorial-mechanism-tab" data-report-mode-panel="mechanism" data-testid="mechanism-mode-panel">
      {mechanism}
    </section>
    <section id="editorial-run-panel" role="tabpanel" aria-labelledby="editorial-run-tab" data-report-mode-panel="run-evidence" data-testid="run-evidence-mode-panel" hidden>
      {run_scaffold}
    </section>
    <aside id="trace-drawer" class="editorial-detail-drawer" data-testid="evidence-drawer" role="dialog" aria-modal="true" aria-label="{_copy('drawer.aria')}" data-i18n-aria-label="drawer.aria" hidden>
      <div aria-hidden="true"></div>
      <div class="editorial-drawer-surface">
        <div class="editorial-drawer-header">
          <h2 data-testid="mechanism-detail-title">{_copy('drawer.detail')}</h2>
          <button class="editorial-drawer-close" type="button" data-testid="editorial-drawer-close" aria-label="{_copy('drawer.close')}" data-i18n-aria-label="drawer.close">×</button>
        </div>
        <div class="editorial-drawer-body" data-testid="mechanism-detail-body"></div>
      </div>
    </aside>
  </main>
  <script>{script}</script>
</body>
</html>
"""


# Alias stays private so tests and design validation can call the candidate seam
# without adding a public renderer selector or a persisted renderer token.
_render_editorial_report = _render_editorial_candidate
