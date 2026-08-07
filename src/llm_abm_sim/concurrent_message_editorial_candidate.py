from __future__ import annotations

import html
import json
from base64 import b64encode
from collections import Counter
from collections.abc import Mapping, Sequence
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from .concurrent_message_report import ConcurrentMessageReportPayload


_EDITORIAL_LANGUAGES = ("zh-CN", "en-US")
_EDITORIAL_ANCHORS = ("overview", "sample", "exposure-ranking", "llm-decision", "network-feedback")
_EDITORIAL_ASSET_VERSION = "v1"


_EDITORIAL_DOWNLOAD_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("report", ("report_payload", "validation_evidence", "manifest")),
    ("sample-users", ("sample_manifest_json", "sample_manifest_csv", "users_json", "users_csv")),
    ("decision", ("decision_trace_json", "decision_trace_csv", "primary_actions_csv", "provider_failures_csv")),
    ("runtime-diagnostics", ("runtime_contract", "diagnostics_contract", "field_lineage", "rankings_csv", "exposures_csv", "terminals_csv")),
)
_EDITORIAL_DOWNLOAD_KEYS = tuple(key for _, keys in _EDITORIAL_DOWNLOAD_GROUPS for key in keys)


# The candidate owns presentation grouping; the Report Module owns the persisted download paths.
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
            "drawer.tabs_aria": "详情证据分组",
            "drawer.tab.summary": "摘要",
            "drawer.tab.decision": "Primary 与 Shadow",
            "drawer.tab.context": "Context",
            "drawer.tab.lineage": "Lineage",
            "drawer.identity": "Identity",
            "drawer.provider_terminal": "Provider terminal",
            "drawer.paired_outcome": "配对结果 / 差异",
            "drawer.disagreement": "Engage difference",
            "drawer.ranking_summary": "Ranking summary",
            "drawer.prompt_boundary": "Prompt visibility boundary",
            "drawer.message": "Message",
            "drawer.user": "User",
            "drawer.batch": "Batch",
            "drawer.class": "Class",
            "drawer.seed": "Seed",
            "drawer.primary": "Primary",
            "drawer.shadow": "Shadow",
            "drawer.status": "Status",
            "drawer.action": "Action",
            "drawer.probability": "Probability",
            "drawer.confidence": "Confidence",
            "drawer.source": "Decision source",
            "drawer.prompt_token": "Prompt token",
            "drawer.authoritative": "Authoritative message",
            "drawer.primary_reason": "Persisted Primary reason",
            "drawer.shadow_reason": "Persisted Shadow reason",
            "drawer.primary_context": "Primary context",
            "drawer.shadow_context": "Shadow context",
            "drawer.peer_context": "Peer context",
            "drawer.field_differences": "Field differences",
            "drawer.field_provenance": "Field Provenance",
            "drawer.field_usage_stage": "Field Usage Stage",
            "drawer.aggregate_source": "Aggregate source",
            "drawer.aggregate_evidence": "Aggregate evidence",
            "drawer.not_in_prompt": "Ranking evidence、Class、其他 messages 和 peer behavior 不进入任何 Prompt。",
            "drawer.feedback_batch": "Feedback batch evidence",
            "drawer.feedback_summary": "Batch summary",
            "drawer.feedback_full_ranking": "Full-ranking Top20 user IDs",
            "drawer.feedback_no_feedback_ranking": "Paired no-feedback Top20 user IDs",
            "drawer.feedback_overlap_ids": "Top20 overlap user IDs",
            "drawer.feedback_added_ids": "Feedback added user IDs",
            "drawer.feedback_removed_ids": "Feedback removed user IDs",
            "drawer.feedback_source": "Aggregate source",
            "drawer.feedback_no_ids": "No user IDs in this batch.",
            "drawer.no_differences": "没有 persisted field differences。",
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
        "run.lead": "本次 run evidence 直接从 typed persisted payload 展开概览、样本、曝光排序、LLM trace、网络反馈和 approved downloads；不会调用或生成其他 renderer。",
        "run.status.title": "Typed payload source",
        "run.status.body": "这些 source values 保持原值；它们不是翻译 catalog 的一部分。",
        "run.contract.title": "Persisted contract",
        "run.contract.body": "schema、prompt tokens、model、message IDs、artifact names 和 Decision reasons 继续使用各自的 source language/value。",
        "run.placeholder.title": "后续 evidence surface",
        "run.placeholder.body": "其余 run evidence anchors 已保留；后续 implementation Ticket 会从同一份 typed payload 增加对应 evidence surface。",
        "run.source.schema": "Payload schema",
        "run.source.profile": "Configuration profile",
        "run.source.model": "Observed model",
        "run.source.primary_token": "Primary prompt token",
        "run.source.shadow_token": "Shadow prompt token",
        "run.source.artifact": "Approved artifact",
        "run.source.approved_artifacts": "Approved artifacts · 已批准产物",
        "run.source.message": "Source message remains unchanged",
        "run.source.reason": "Persisted Decision reason remains unchanged",
        "run.overview.kicker": "本次运行 · 概览",
        "run.overview.title": "Formal run 的证据从同一份 persisted payload 展开",
        "run.overview.lead": "这里显示本次 run 的实际覆盖、曝光和 paired accounting。所有计数都来自 persisted payload；它们是 descriptive evidence，不是 winner 或因果效果。",
        "run.status.label": "运行状态 · Run status",
        "run.status.formal": "Formal",
        "run.status.not_formal": "非 Formal",
        "run.status.profile": "Configuration profile",
        "run.status.schema": "Payload schema",
        "run.status.model": "Observed model",
        "run.status.tokens": "Prompt tokens",
        "run.metric.sample": "Sample users · 研究样本用户",
        "run.metric.eligible": "Eligible pairs · 合格 user × message pairs",
        "run.metric.exposures": "Actual exposures · 实际曝光 pairs",
        "run.metric.distinct": "Distinct users · 去重曝光用户",
        "run.accounting.title": "Primary / Shadow accounting",
        "run.accounting.attempted": "attempted",
        "run.accounting.succeeded": "succeeded",
        "run.accounting.failures": "provider_failed",
        "run.accounting.primary": "Primary",
        "run.accounting.shadow": "Shadow · report-only",
        "run.funnel.title": "Campaign Funnel",
        "run.funnel.sample": "Sample users",
        "run.funnel.eligible": "Eligible user × message pairs",
        "run.funnel.exposures": "Actual exposures",
        "run.funnel.distinct": "Distinct exposed users",
        "run.coverage.title": "Exposure coverage · 曝光覆盖",
        "run.coverage.subtitle": "按曝光 message 数量分组；每项明确显示 numerator / denominator。",
        "run.coverage.messages": "messages exposed · 曝光 message 数",
        "run.sample.kicker": "本次运行 · 样本",
        "run.sample.title": "Seed-first sample 的角色与 Class 构成",
        "run.sample.lead": "样本角色、latent Class 和 exposure coverage 都从本次 persisted user rows 聚合。Intended Audience Segment 只保留为 message 的 design descriptor，不进入 eligibility 或 Prompt field。",
        "run.sample.roles": "Sample roles · 样本角色",
        "run.sample.role": "角色",
        "run.sample.count": "数量",
        "run.sample.seed": "seed",
        "run.sample.network": "network_cohort",
        "run.sample.ordinary": "ordinary",
        "run.sample.classes": "Latent Class composition · Latent Class 构成",
        "run.sample.class": "Class",
        "run.sample.coverage": "Exposure coverage by sample user · 按样本用户的曝光覆盖",
        "run.sample.authoritative": "Authoritative messages · 权威 messages",
        "run.sample.authoritative.body": "下方正文保持 authoritative source language 原文。",
        "run.sample.design_descriptor": "Intended Audience Segment · design descriptor",
        "run.sample.source_body": "Authoritative source body",
        "run.message.audience": "Intended Audience Segment · design descriptor",
        "run.message.id": "Message ID",
        "run.message.body": "Authoritative source body",
        "run.exposure.kicker": "本次运行 · 曝光排序",
        "run.exposure.title": "三条 message 的 600 exposures 与 30-batch persisted ranking",
            "run.trace.batch": "Batch",
            "run.trace.class": "Class",
            "run.trace.kicker": "本次运行 · LLM Decision Trace",
            "run.trace.title": "每一次 exposure 都保留 Primary / Shadow paired evidence",
            "run.trace.lead": "这张 trace table 先在全部 1,800 persisted rows 上应用筛选，再进行分页。首屏只呈现 identity、terminal status、paired outcome、ranking summary 和 Prompt visibility boundary；完整 message、contexts 与 lineage 位于 shared drawer 的对应 tab。",
            "run.trace.summary": "Message action summary",
            "run.trace.message": "Message",
            "run.trace.actions": "Primary action counts",
            "run.trace.positive_rate": "Positive rate",
            "run.trace.sensitivity": "Paired sensitivity",
            "run.trace.paired_coverage": "Paired coverage",
            "run.trace.disagreement_rate": "Disagreement",
            "run.trace.mean_delta": "Mean absolute probability delta",
            "run.trace.flagged_reasons": "Flagged Shadow reasons",
            "run.trace.filters": "Trace filters",
            "run.trace.search": "Search",
            "run.trace.search_placeholder": "trace id, user id, message or class",
            "run.trace.message_filter": "Message",
            "run.trace.class_filter": "Class",
            "run.trace.batch_filter": "Batch",
            "run.trace.action_filter": "Primary action",
            "run.trace.provider_filter": "Provider status",
            "run.trace.disagreement_filter": "Primary / Shadow disagreement",
            "run.trace.all_messages": "All messages",
            "run.trace.all_classes": "All Classes",
            "run.trace.all_batches": "All batches",
            "run.trace.all_actions": "All actions",
            "run.trace.all_provider_status": "All Provider status",
            "run.trace.all_disagreement": "All paired outcomes",
            "run.trace.only_disagreement": "Disagreement only",
            "run.trace.no_disagreement": "No disagreement",
            "run.trace.table_aria": "Persisted LLM Decision Trace",
            "run.trace.user": "User",
            "run.trace.primary_action": "Primary",
            "run.trace.provider": "Provider",
            "run.trace.disagreement": "Difference",
            "run.trace.ranking": "Rank",
            "run.trace.page_size": "Rows per page",
            "run.trace.rows": "Rows",
            "run.trace.empty": "No persisted trace rows match these filters.",
            "run.trace.previous": "Previous page",
            "run.trace.next": "Next page",
            "run.trace.first_page": "First page",
            "run.trace.last_page": "Last page",
            "run.trace.open_row": "Open trace detail",
            "run.trace.action.like": "like",
            "run.trace.action.comment": "comment",
            "run.trace.action.share": "share",
            "run.trace.action.ignore": "ignore",
            "run.trace.action.provider_failed": "provider_failed",
        "run.exposure.lead": "先看每条 message 的 exposure、union、overlap、Class × Message matrix 和 Message-User Fit range；batch table 默认分页，selector 可访问全部 30 batches / 90 rows。这里不生成 winner 或 causal claim。",
        "run.exposure.summary": "Exposure summary",
        "run.exposure.per_message": "Per-message exposures",
        "run.exposure.union": "Union of exposed users",
        "run.exposure.three_way": "Three-way intersection",
        "run.exposure.pairwise": "Pairwise overlap",
        "run.exposure.matrix": "Class × Message matrix",
        "run.exposure.fit": "Message-User Fit · normalized proxy metric",
        "run.exposure.fit_metric": "min / mean / max",
        "run.exposure.message": "Message",
        "run.exposure.min": "min",
        "run.exposure.mean": "mean",
        "run.exposure.max": "max",
        "run.exposure.batch_table": "Persisted batch rows",
        "run.exposure.selector": "Filter batches by message",
        "run.exposure.all_messages": "All messages",
        "run.exposure.batch": "Batch",
        "run.exposure.selected": "Selected pairs",
        "run.exposure.eligible_users": "Eligible users",
        "run.exposure.capacity": "Capacity",
        "run.exposure.below": "Below capacity",
        "run.exposure.cumulative": "Cumulative pairs",
        "run.exposure.page": "Page",
        "run.exposure.rows": "Rows",
        "run.exposure.previous": "Previous page",
        "run.exposure.next": "Next page",
        "run.exposure.table_aria": "Persisted exposure batch table",
        "run.exposure.pagination_aria": "Exposure batch pagination",
        "run.exposure.empty": "No persisted batch rows match this filter.",
        "run.evidence.descriptive": "Descriptive persisted evidence; no winner, attribution, or causal effect is inferred.",
        "run.feedback.kicker": "本次运行 · 网络反馈",
        "run.feedback.title": "Primary feedback 只在下一批改变三条 ranking",
        "run.feedback.lead": "默认先看 changed message-batches、Top20 overlap 和 exact batch evidence；完整 added/removed user IDs 只在 shared drawer/detail 或 approved downloads 中展开。",
        "run.feedback.changed": "changed message-batches",
        "run.feedback.batch_total": "all message-batches",
        "run.feedback.message": "Message",
        "run.feedback.batch": "Batch",
        "run.feedback.eligible": "Eligible users",
        "run.feedback.top_count": "Top20",
        "run.feedback.overlap": "Top20 overlap",
        "run.feedback.added": "added",
        "run.feedback.removed": "removed",
        "run.feedback.range": "Top20 overlap range",
        "run.feedback.scope": "Batch evidence scope",
        "run.feedback.changed_only": "Changed batches only",
        "run.feedback.all_batches": "All batches",
        "run.feedback.all_messages": "All messages",
        "run.feedback.details": "Open batch detail",
        "run.feedback.table_aria": "Persisted network feedback batch evidence",
        "run.feedback.rows": "batches",
        "run.feedback.descriptive": "Paired no-feedback diagnostics are descriptive simulation evidence; they do not claim that every batch changed or that feedback caused a platform effect.",
        "run.downloads.kicker": "本次运行 · Approved downloads",
        "run.downloads.title": "17 个 approved artifacts，按研究职责分组",
        "run.downloads.lead": "所有 href 都来自 payload 的 canonical view；artifact 名称保持 authoritative 原值，缺失、改名、crossed 或 escaped target 在 closure 阶段 fail closed。",
        "run.downloads.group.report": "Report",
        "run.downloads.group.sample-users": "Sample / Users",
        "run.downloads.group.decision": "Decision",
        "run.downloads.group.runtime-diagnostics": "Runtime / Diagnostics",
        "run.downloads.link": "Approved artifact",
        "run.downloads.table_aria": "Approved concurrent message downloads",
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
            "drawer.tabs_aria": "Detail evidence groups",
            "drawer.tab.summary": "Summary",
            "drawer.tab.decision": "Primary and Shadow",
            "drawer.tab.context": "Context",
            "drawer.tab.lineage": "Lineage",
            "drawer.identity": "Identity",
            "drawer.provider_terminal": "Provider terminal",
            "drawer.paired_outcome": "Paired outcome / difference",
            "drawer.disagreement": "Engage difference",
            "drawer.ranking_summary": "Ranking summary",
            "drawer.prompt_boundary": "Prompt visibility boundary",
            "drawer.message": "Message",
            "drawer.user": "User",
            "drawer.batch": "Batch",
            "drawer.class": "Class",
            "drawer.seed": "Seed",
            "drawer.primary": "Primary",
            "drawer.shadow": "Shadow",
            "drawer.status": "Status",
            "drawer.action": "Action",
            "drawer.probability": "Probability",
            "drawer.confidence": "Confidence",
            "drawer.source": "Decision source",
            "drawer.prompt_token": "Prompt token",
            "drawer.authoritative": "Authoritative message",
            "drawer.primary_reason": "Persisted Primary reason",
            "drawer.shadow_reason": "Persisted Shadow reason",
            "drawer.primary_context": "Primary context",
            "drawer.shadow_context": "Shadow context",
            "drawer.peer_context": "Peer context",
            "drawer.field_differences": "Field differences",
            "drawer.field_provenance": "Field Provenance",
            "drawer.field_usage_stage": "Field Usage Stage",
            "drawer.aggregate_source": "Aggregate source",
            "drawer.aggregate_evidence": "Aggregate evidence",
            "drawer.not_in_prompt": "Ranking evidence, Class, other messages, and peer behavior are excluded from every Prompt.",
            "drawer.feedback_batch": "Feedback batch evidence",
            "drawer.feedback_summary": "Batch summary",
            "drawer.feedback_full_ranking": "Full-ranking Top20 user IDs",
            "drawer.feedback_no_feedback_ranking": "Paired no-feedback Top20 user IDs",
            "drawer.feedback_overlap_ids": "Top20 overlap user IDs",
            "drawer.feedback_added_ids": "Feedback added user IDs",
            "drawer.feedback_removed_ids": "Feedback removed user IDs",
            "drawer.feedback_source": "Aggregate source",
            "drawer.feedback_no_ids": "No user IDs in this batch.",
            "drawer.no_differences": "No persisted field differences.",
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
        "run.lead": "This run evidence expands directly from the typed persisted payload into overview, sample, exposure ranking, LLM trace, network feedback, and approved downloads; it does not call or generate another renderer.",
        "run.status.title": "Typed payload source",
        "run.status.body": "These source values remain unchanged; they are not translation-catalog entries.",
        "run.contract.title": "Persisted contract",
        "run.contract.body": "Schema, prompt tokens, model, message IDs, artifact names, and Decision reasons keep their source language or value.",
        "run.placeholder.title": "Later evidence surface",
        "run.placeholder.body": "The remaining run evidence anchors are reserved; later implementation Tickets will add their evidence surfaces from the same typed payload.",
        "run.source.schema": "Payload schema",
        "run.source.profile": "Configuration profile",
        "run.source.model": "Observed model",
        "run.source.primary_token": "Primary prompt token",
        "run.source.shadow_token": "Shadow prompt token",
        "run.source.artifact": "Approved artifact",
        "run.source.approved_artifacts": "Approved artifacts",
        "run.source.message": "Source message remains unchanged",
        "run.source.reason": "Persisted Decision reason remains unchanged",
        "run.overview.kicker": "This run · Overview",
        "run.overview.title": "Formal run evidence expands from one persisted payload",
        "run.overview.lead": "This view shows actual run coverage, exposure, and paired accounting. Every count comes from the persisted payload; it is descriptive evidence, not a winner claim or causal effect.",
        "run.status.label": "Run status",
        "run.status.formal": "Formal",
        "run.status.not_formal": "Not Formal",
        "run.status.profile": "Configuration profile",
        "run.status.schema": "Payload schema",
        "run.status.model": "Observed model",
        "run.status.tokens": "Prompt tokens",
        "run.metric.sample": "Sample users",
        "run.metric.eligible": "Eligible user × message pairs",
        "run.metric.exposures": "Actual exposures",
        "run.metric.distinct": "Distinct exposed users",
        "run.accounting.title": "Primary / Shadow accounting",
        "run.accounting.attempted": "attempted",
        "run.accounting.succeeded": "succeeded",
        "run.accounting.failures": "provider_failed",
        "run.accounting.primary": "Primary",
        "run.accounting.shadow": "Shadow · report-only",
        "run.funnel.title": "Campaign Funnel",
        "run.funnel.sample": "Sample users",
        "run.funnel.eligible": "Eligible user × message pairs",
        "run.funnel.exposures": "Actual exposures",
        "run.funnel.distinct": "Distinct exposed users",
        "run.coverage.title": "Exposure coverage",
        "run.coverage.subtitle": "Users grouped by distinct messages exposed; numerator / denominator is explicit.",
        "run.coverage.messages": "messages exposed",
        "run.sample.kicker": "This run · Sample",
        "run.sample.title": "Seed-first sample roles and Class composition",
        "run.sample.lead": "Sample roles, latent Class, and exposure coverage are aggregated from the persisted user rows. Intended Audience Segment remains a message design descriptor; it is not an eligibility or Prompt field.",
        "run.sample.roles": "Sample roles",
        "run.sample.role": "Role",
        "run.sample.count": "Count",
        "run.sample.seed": "seed",
        "run.sample.network": "network_cohort",
        "run.sample.ordinary": "ordinary",
        "run.sample.classes": "Latent Class composition",
        "run.sample.class": "Class",
        "run.sample.coverage": "Exposure coverage by sample user",
        "run.sample.authoritative": "Authoritative messages",
        "run.sample.authoritative.body": "The body below remains in its authoritative source language.",
        "run.sample.design_descriptor": "Intended Audience Segment · design descriptor",
        "run.sample.source_body": "Authoritative source body",
        "run.message.audience": "Intended Audience Segment · design descriptor",
        "run.message.id": "Message ID",
        "run.message.body": "Authoritative source body",
        "run.exposure.kicker": "This run · Exposure ranking",
        "run.exposure.title": "600 exposures per message across the persisted 30-batch ranking",
            "run.trace.batch": "Batch",
            "run.trace.class": "Class",
            "run.trace.kicker": "This run · LLM Decision Trace",
            "run.trace.title": "Every exposure keeps Primary / Shadow paired evidence",
            "run.trace.lead": "This trace table applies filters to all 1,800 persisted rows before pagination. The first viewport shows only identity, terminal status, paired outcome, ranking summary, and the Prompt visibility boundary; full message, contexts, and lineage live in the corresponding shared-drawer tabs.",
            "run.trace.summary": "Message action summary",
            "run.trace.message": "Message",
            "run.trace.actions": "Primary action counts",
            "run.trace.positive_rate": "Positive rate",
            "run.trace.sensitivity": "Paired sensitivity",
            "run.trace.paired_coverage": "Paired coverage",
            "run.trace.disagreement_rate": "Disagreement",
            "run.trace.mean_delta": "Mean absolute probability delta",
            "run.trace.flagged_reasons": "Flagged Shadow reasons",
            "run.trace.filters": "Trace filters",
            "run.trace.search": "Search",
            "run.trace.search_placeholder": "trace id, user id, message or class",
            "run.trace.message_filter": "Message",
            "run.trace.class_filter": "Class",
            "run.trace.batch_filter": "Batch",
            "run.trace.action_filter": "Primary action",
            "run.trace.provider_filter": "Provider status",
            "run.trace.disagreement_filter": "Primary / Shadow disagreement",
            "run.trace.all_messages": "All messages",
            "run.trace.all_classes": "All Classes",
            "run.trace.all_batches": "All batches",
            "run.trace.all_actions": "All actions",
            "run.trace.all_provider_status": "All Provider status",
            "run.trace.all_disagreement": "All paired outcomes",
            "run.trace.only_disagreement": "Disagreement only",
            "run.trace.no_disagreement": "No disagreement",
            "run.trace.table_aria": "Persisted LLM Decision Trace",
            "run.trace.user": "User",
            "run.trace.primary_action": "Primary",
            "run.trace.provider": "Provider",
            "run.trace.disagreement": "Difference",
            "run.trace.ranking": "Rank",
            "run.trace.page_size": "Rows per page",
            "run.trace.rows": "Rows",
            "run.trace.empty": "No persisted trace rows match these filters.",
            "run.trace.previous": "Previous page",
            "run.trace.next": "Next page",
            "run.trace.first_page": "First page",
            "run.trace.last_page": "Last page",
            "run.trace.open_row": "Open trace detail",
            "run.trace.action.like": "like",
            "run.trace.action.comment": "comment",
            "run.trace.action.share": "share",
            "run.trace.action.ignore": "ignore",
            "run.trace.action.provider_failed": "provider_failed",
        "run.exposure.lead": "Start with per-message exposure, union, overlap, Class × Message matrix, and Message-User Fit ranges. The batch table is paginated by default; the selector exposes all 30 batches / 90 rows. This view makes no winner or causal claim.",
        "run.exposure.summary": "Exposure summary",
        "run.exposure.per_message": "Per-message exposures",
        "run.exposure.union": "Union of exposed users",
        "run.exposure.three_way": "Three-way intersection",
        "run.exposure.pairwise": "Pairwise overlap",
        "run.exposure.matrix": "Class × Message matrix",
        "run.exposure.fit": "Message-User Fit · normalized proxy metric",
        "run.exposure.fit_metric": "min / mean / max",
        "run.exposure.message": "Message",
        "run.exposure.min": "min",
        "run.exposure.mean": "mean",
        "run.exposure.max": "max",
        "run.exposure.batch_table": "Persisted batch rows",
        "run.exposure.selector": "Filter batches by message",
        "run.exposure.all_messages": "All messages",
        "run.exposure.batch": "Batch",
        "run.exposure.selected": "Selected pairs",
        "run.exposure.eligible_users": "Eligible users",
        "run.exposure.capacity": "Capacity",
        "run.exposure.below": "Below capacity",
        "run.exposure.cumulative": "Cumulative pairs",
        "run.exposure.page": "Page",
        "run.exposure.rows": "Rows",
        "run.exposure.previous": "Previous page",
        "run.exposure.next": "Next page",
        "run.exposure.table_aria": "Persisted exposure batch table",
        "run.exposure.pagination_aria": "Exposure batch pagination",
        "run.exposure.empty": "No persisted batch rows match this filter.",
        "run.evidence.descriptive": "Descriptive persisted evidence; no winner, attribution, or causal effect is inferred.",
        "run.feedback.kicker": "This run · Network feedback",
        "run.feedback.title": "Primary feedback changes all three rankings in the next batch only",
        "run.feedback.lead": "Start with changed message-batches, Top20 overlap, and exact batch evidence; full added/removed user IDs appear only in the shared drawer/detail or approved downloads.",
        "run.feedback.changed": "changed message-batches",
        "run.feedback.batch_total": "all message-batches",
        "run.feedback.message": "Message",
        "run.feedback.batch": "Batch",
        "run.feedback.eligible": "Eligible users",
        "run.feedback.top_count": "Top20",
        "run.feedback.overlap": "Top20 overlap",
        "run.feedback.added": "added",
        "run.feedback.removed": "removed",
        "run.feedback.range": "Top20 overlap range",
        "run.feedback.scope": "Batch evidence scope",
        "run.feedback.changed_only": "Changed batches only",
        "run.feedback.all_batches": "All batches",
        "run.feedback.all_messages": "All messages",
        "run.feedback.details": "Open batch detail",
        "run.feedback.table_aria": "Persisted network feedback batch evidence",
        "run.feedback.rows": "batches",
        "run.feedback.descriptive": "Paired no-feedback diagnostics are descriptive simulation evidence; they do not claim that every batch changed or that feedback caused a platform effect.",
        "run.downloads.kicker": "This run · Approved downloads",
        "run.downloads.title": "17 approved artifacts grouped by research responsibility",
        "run.downloads.lead": "Every href comes from the payload's canonical view; artifact names remain authoritative, and missing, renamed, crossed, or escaped targets fail closed during closure.",
        "run.downloads.group.report": "Report",
        "run.downloads.group.sample-users": "Sample / Users",
        "run.downloads.group.decision": "Decision",
        "run.downloads.group.runtime-diagnostics": "Runtime / Diagnostics",
        "run.downloads.link": "Approved artifact",
        "run.downloads.table_aria": "Approved concurrent message downloads",
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


_EDITORIAL_V2_ASSET_VERSION = "v2"
_EDITORIAL_V2_ASSET_CATALOG: dict[str, dict[str, str]] = {
    "overview": {
        "file": "editorial-mechanism-overview-v2.webp",
        "sha256": "fe112e7d898e881dd7d379333e2192e87c62278820a52ea4b0f6bd39fee550bc",
        "source": "editorial-mechanism-overview-v2.png",
        "source_sha256": "769f6168d278bd9e6080631fab7b0411aa578f8cea6d7fbeba17aa04b33b6019",
        "version": _EDITORIAL_V2_ASSET_VERSION,
    },
    "sample": {
        "file": "editorial-mechanism-sample-v2.webp",
        "sha256": "a01d8ea31980568b06bf8a03a42592e83387883ed0f60ea097218879bb120b37",
        "source": "editorial-mechanism-sample-v2.png",
        "source_sha256": "1981001fda541d15cf87fbc52cbedd787e831c6f066717d670e68d2d7f02fba3",
        "version": _EDITORIAL_V2_ASSET_VERSION,
    },
    "exposure-ranking": {
        "file": "editorial-mechanism-exposure-ranking-v2.webp",
        "sha256": "92073c232aa770bb400375ce3495ac21a59f121a4e823e789e01a8fb0e917812",
        "source": "editorial-mechanism-exposure-ranking-v2.png",
        "source_sha256": "d2891f472388a00bc620a37a2469cfbfa9b1ddd6412d639ded6e3cea8a03a80f",
        "version": _EDITORIAL_V2_ASSET_VERSION,
    },
    "llm-decision": {
        "file": "editorial-mechanism-llm-decision-v2.webp",
        "sha256": "96a5a87a01da39ef73a8c2a1cb510bcd008697cf595b760acc891e911ff53368",
        "source": "editorial-mechanism-llm-decision-v2.png",
        "source_sha256": "2653f6e55e8098cbde6550269ba062d39aba9013fcbe764dc8d9c32a40d41795",
        "version": _EDITORIAL_V2_ASSET_VERSION,
    },
    "network-feedback": {
        "file": "editorial-mechanism-network-feedback-v2.webp",
        "sha256": "548f0d601e84291125fac1926ea1304f723ad8fff37c013297b1f4e54719df50",
        "source": "editorial-mechanism-network-feedback-v2.png",
        "source_sha256": "eec88039e3b1dc0b682be1a4c35db2e5e2b283b62e9dbbdb7ca86be6b5dd0fe0",
        "version": _EDITORIAL_V2_ASSET_VERSION,
    },
}


_EDITORIAL_V2_COPY: dict[str, dict[str, str]] = {
    "zh-CN": {
        "v2.legend.channel.first": "第一条 message 通道",
        "v2.legend.channel.second": "第二条 message 通道",
        "v2.legend.channel.third": "第三条 message 通道",
        "v2.legend.research_sample": "Research Sample",
        "v2.legend.eligible_pair": "Eligible user × message pair",
        "v2.legend.per_message_queue": "Per-Message Queue",
        "v2.legend.exposure_gate": "Exposure Gate",
        "v2.legend.decision_pair": "Primary / report-only Shadow Decision pair",
        "v2.legend.seed_union": "Influence Seed Union",
        "v2.legend.network_cohort": "Direct one-hop Network Cohort",
        "v2.legend.ordinary_fill": "Ordinary fill",
        "v2.legend.personalized_top20": "Per-Message Personalized Top20",
        "v2.legend.cross_message_overlap": "Allowed cross-message overlap",
        "v2.legend.single_exposure": "Message-Level Single Exposure",
        "v2.legend.primary_decision": "Primary Campaign Decision",
        "v2.legend.shadow_decision": "Demographic Shadow Decision",
        "v2.legend.propagating_primary": "传播 Primary action · like / comment / share",
        "v2.legend.engaged_user_dedup": "Campaign engaged-user set · 按用户去重",
        "v2.legend.next_batch_reranking": "下一批 per-message reranking",
        "v2.legend.no_campaign_feedback": "No campaign feedback",
    },
    "en-US": {
        "v2.legend.channel.first": "First message channel",
        "v2.legend.channel.second": "Second message channel",
        "v2.legend.channel.third": "Third message channel",
        "v2.legend.research_sample": "Research Sample",
        "v2.legend.eligible_pair": "Eligible user × message pair",
        "v2.legend.per_message_queue": "Per-Message Queue",
        "v2.legend.exposure_gate": "Exposure Gate",
        "v2.legend.decision_pair": "Primary / report-only Shadow Decision pair",
        "v2.legend.seed_union": "Influence Seed Union",
        "v2.legend.network_cohort": "Direct one-hop Network Cohort",
        "v2.legend.ordinary_fill": "Ordinary fill",
        "v2.legend.personalized_top20": "Per-Message Personalized Top20",
        "v2.legend.cross_message_overlap": "Allowed cross-message overlap",
        "v2.legend.single_exposure": "Message-Level Single Exposure",
        "v2.legend.primary_decision": "Primary Campaign Decision",
        "v2.legend.shadow_decision": "Demographic Shadow Decision",
        "v2.legend.propagating_primary": "Propagating Primary action · like / comment / share",
        "v2.legend.engaged_user_dedup": "Campaign engaged-user set · deduplicated by user",
        "v2.legend.next_batch_reranking": "Next-batch per-message reranking",
        "v2.legend.no_campaign_feedback": "No campaign feedback",
    },
}
_EDITORIAL_V2_CATALOG = {
    language: {**_EDITORIAL_CATALOG[language], **_EDITORIAL_V2_COPY[language]}
    for language in _EDITORIAL_LANGUAGES
}


_EDITORIAL_V1_LEGEND_ITEMS: dict[str, tuple[tuple[str, str], ...]] = {
    "overview": (
        ("navy", "overview.legend.sample"),
        ("cobalt", "overview.legend.message"),
        ("green", "overview.legend.candidates"),
        ("amber", "overview.legend.queue"),
        ("navy", "overview.legend.gate"),
        ("green", "overview.legend.decision"),
    ),
    "sample": (
        ("cobalt", "sample.legend.seed"),
        ("green", "sample.legend.network"),
        ("navy", "sample.legend.ordinary"),
        ("amber", "sample.legend.labels"),
    ),
    "exposure-ranking": (
        ("navy", "ranking.legend.launch"),
        ("cobalt", "ranking.legend.queue"),
        ("green", "ranking.legend.overlap"),
        ("amber", "ranking.legend.gate"),
    ),
    "llm-decision": (
        ("green", "decision.legend.platform"),
        ("cobalt", "decision.legend.pair"),
        ("green", "decision.legend.fit"),
        ("amber", "decision.legend.paired"),
    ),
    "network-feedback": (
        ("green", "feedback.legend.success"),
        ("green", "feedback.legend.dedup"),
        ("cobalt", "feedback.legend.next"),
        ("amber", "feedback.legend.stop"),
    ),
}


_EDITORIAL_V2_LEGEND_ITEMS: dict[str, tuple[tuple[str, str, str, str], ...]] = {
    "overview": (
        ("overview-first-message-channel", "v2.legend.channel.first", "channel cobalt", "message-identity"),
        ("overview-second-message-channel", "v2.legend.channel.second", "channel green", "message-identity"),
        ("overview-third-message-channel", "v2.legend.channel.third", "channel amber", "message-identity"),
        ("overview-research-sample", "v2.legend.research_sample", "sample", "mark-grammar"),
        ("overview-eligible-pair", "v2.legend.eligible_pair", "eligible-pair", "mark-grammar"),
        ("overview-per-message-queue", "v2.legend.per_message_queue", "queue", "mark-grammar"),
        ("overview-exposure-gate", "v2.legend.exposure_gate", "gate", "mark-grammar"),
        ("overview-decision-pair", "v2.legend.decision_pair", "decision-pair cobalt", "mark-grammar"),
    ),
    "sample": (
        ("sample-influence-seed-union", "v2.legend.seed_union", "seed", "sample-role"),
        ("sample-direct-one-hop-network-cohort", "v2.legend.network_cohort", "network", "sample-role"),
        ("sample-ordinary-fill", "v2.legend.ordinary_fill", "ordinary", "sample-role"),
    ),
    "exposure-ranking": (
        ("ranking-first-message-channel", "v2.legend.channel.first", "channel cobalt", "message-identity"),
        ("ranking-second-message-channel", "v2.legend.channel.second", "channel green", "message-identity"),
        ("ranking-third-message-channel", "v2.legend.channel.third", "channel amber", "message-identity"),
        ("ranking-personalized-top20", "v2.legend.personalized_top20", "top20", "mark-grammar"),
        ("ranking-cross-message-overlap", "v2.legend.cross_message_overlap", "overlap", "mark-grammar"),
        ("ranking-single-exposure", "v2.legend.single_exposure", "single-exposure", "mark-grammar"),
    ),
    "llm-decision": (
        ("decision-exposure-gate", "v2.legend.exposure_gate", "gate", "neutral-role-state"),
        ("decision-primary", "v2.legend.primary_decision", "primary", "neutral-role-state"),
        ("decision-shadow", "v2.legend.shadow_decision", "shadow", "neutral-role-state"),
    ),
    "network-feedback": (
        ("feedback-first-message-channel", "v2.legend.channel.first", "channel cobalt", "message-identity"),
        ("feedback-second-message-channel", "v2.legend.channel.second", "channel green", "message-identity"),
        ("feedback-third-message-channel", "v2.legend.channel.third", "channel amber", "message-identity"),
        ("feedback-propagating-primary", "v2.legend.propagating_primary", "propagating", "feedback-grammar"),
        ("feedback-engaged-user-dedup", "v2.legend.engaged_user_dedup", "dedup", "feedback-grammar"),
        ("feedback-next-batch-reranking", "v2.legend.next_batch_reranking", "reranking", "feedback-grammar"),
        ("feedback-no-campaign-feedback", "v2.legend.no_campaign_feedback", "no-feedback", "neutral-role-state"),
    ),
}


def _value(source: object, key: str, default: object = "") -> object:
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(cast(Any, value)) if value is not None else default
    except (TypeError, ValueError):
        return default


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(cast(Any, value)) if value is not None else default
    except (TypeError, ValueError):
        return default


def _required_mapping(source: object, key: str, context: str) -> Mapping[str, Any]:
    value = _value(source, key, None)
    if not isinstance(value, Mapping):
        raise ValueError(f"{context}.{key} must be a persisted mapping")
    return value


def _required_sequence(source: object, key: str, context: str) -> Sequence[Any]:
    value = _value(source, key, None)
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ValueError(f"{context}.{key} must be a persisted sequence")
    return value


def _required_int(source: object, key: str, context: str) -> int:
    value = _value(source, key, None)
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{context}.{key} must be a persisted integer")
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{context}.{key} must be a persisted integer") from exc


def _required_float(source: object, key: str, context: str) -> float:
    value = _value(source, key, None)
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{context}.{key} must be a persisted number")
    try:
        return float(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{context}.{key} must be a persisted number") from exc


def _format_count(value: object) -> str:
    return f"{_as_int(value):,}"


def _format_fit(value: object) -> str:
    formatted = f"{_as_float(value):.3f}"
    return formatted[1:] if formatted.startswith("0.") else formatted


_TRACE_ACTIONS = ("like", "comment", "share", "ignore", "provider_failed")


def _safe_trace_value(value: object) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _safe_trace_value(nested) for key, nested in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_safe_trace_value(nested) for nested in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _safe_trace_mapping(source: object, key: str, context: str) -> dict[str, Any]:
    return {
        str(name): _safe_trace_value(value)
        for name, value in sorted(_required_mapping(source, key, context).items(), key=lambda item: str(item[0]))
    }


def _safe_trace_sequence(source: object, key: str, context: str) -> list[Any]:
    return [_safe_trace_value(value) for value in _required_sequence(source, key, context)]


def _required_bool(source: object, key: str, context: str) -> bool:
    value = _value(source, key, None)
    if not isinstance(value, bool):
        raise ValueError(f"{context}.{key} must be a persisted boolean")
    return value


def _required_string_sequence(source: object, key: str, context: str) -> list[str]:
    values = _required_sequence(source, key, context)
    result: list[str] = []
    for index, value in enumerate(values):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{context}.{key}[{index}] must be a non-empty persisted string")
        result.append(value)
    if len(set(result)) != len(result):
        raise ValueError(f"{context}.{key} must not contain duplicate values")
    return result


def _validated_downloads(payload: Any) -> dict[str, str]:
    from .concurrent_message_report import ConcurrentMessageDownloadLinks

    raw_downloads = _value(payload, "downloads", None)
    if raw_downloads is None:
        raise ValueError("payload.downloads is required")
    canonical = ConcurrentMessageDownloadLinks().model_dump(mode="json")
    if isinstance(raw_downloads, Mapping):
        actual = dict(raw_downloads)
    else:
        actual = {key: _value(raw_downloads, key, None) for key in canonical}
    if set(actual) != set(canonical):
        raise ValueError("approved downloads do not match the canonical artifact keys")
    normalized: dict[str, str] = {}
    for key in _EDITORIAL_DOWNLOAD_KEYS:
        value = actual.get(key)
        if not isinstance(value, str) or value != canonical[key]:
            raise ValueError(f"approved download {key} does not match the canonical artifact layout")
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or "\\" in value:
            raise ValueError(f"approved download {key} escapes the run directory")
        normalized[key] = value
    return normalized


def _feedback_effect_data(
    payload: Any,
    *,
    message_ids: Sequence[str],
    message_titles: Mapping[str, str],
    horizon: int,
    delivery_capacity: int,
) -> dict[str, Any]:
    source = _required_mapping(payload, "campaign_feedback_effect", "payload")
    if horizon <= 0:
        raise ValueError("feedback evidence requires positive horizon and delivery capacity")
    if delivery_capacity <= 0:
        raise ValueError("feedback evidence requires positive delivery capacity")
    flag_fields = (
        "advances_runtime_state",
        "calls_decision_adapter",
        "descriptive_only",
        "feedback_component_zeroed_only",
        "full_precision_ranking",
        "non_causal",
        "same_candidate_set_and_frozen_state",
    )
    flags = {field: _required_bool(source, field, "campaign_feedback_effect") for field in flag_fields}
    if flags != {
        "advances_runtime_state": False,
        "calls_decision_adapter": False,
        "descriptive_only": True,
        "feedback_component_zeroed_only": True,
        "full_precision_ranking": True,
        "non_causal": True,
        "same_candidate_set_and_frozen_state": True,
    }:
        raise ValueError("campaign feedback diagnostics do not close to the descriptive frozen-state contract")

    overall = _required_mapping(source, "overall", "campaign_feedback_effect")
    expected_batch_count = len(message_ids) * horizon
    message_batch_count = _required_int(overall, "message_batch_count", "campaign_feedback_effect.overall")
    changed_message_batch_count = _required_int(
        overall, "changed_message_batch_count", "campaign_feedback_effect.overall"
    )
    added_ids = _required_string_sequence(
        overall, "distinct_feedback_added_user_ids", "campaign_feedback_effect.overall"
    )
    removed_ids = _required_string_sequence(
        overall, "distinct_feedback_removed_user_ids", "campaign_feedback_effect.overall"
    )
    changed_ids = _required_string_sequence(overall, "distinct_changed_user_ids", "campaign_feedback_effect.overall")
    if message_batch_count != expected_batch_count:
        raise ValueError("campaign feedback message batch count does not match the persisted horizon")

    per_message_source = _required_mapping(source, "per_message", "campaign_feedback_effect")
    if set(per_message_source) != set(message_ids):
        raise ValueError("campaign feedback per-message keys do not match persisted messages")
    normalized_messages: list[dict[str, Any]] = []
    all_added: set[str] = set()
    all_removed: set[str] = set()
    total_changed = 0
    for message_id in message_ids:
        entry = _required_mapping(per_message_source, message_id, "campaign_feedback_effect.per_message")
        title = str(_value(entry, "message_title", "")).strip()
        if title != message_titles[message_id]:
            raise ValueError(f"campaign feedback title does not match persisted message {message_id}")
        declared_changed = _required_int(entry, "changed_batch_count", f"campaign_feedback_effect.{message_id}")
        raw_batches = _required_sequence(entry, "batches", f"campaign_feedback_effect.{message_id}")
        if len(raw_batches) != horizon:
            raise ValueError(f"campaign feedback batches do not cover horizon for {message_id}")
        normalized_batches: list[dict[str, Any]] = []
        changed_count = 0
        overlap_counts: list[int] = []
        for index, batch in enumerate(raw_batches):
            context = f"campaign_feedback_effect.{message_id}.batches[{index}]"
            time_step = _required_int(batch, "time_step", context)
            if time_step != index:
                raise ValueError(f"campaign feedback batches are not ordered for {message_id}")
            eligible_users = _required_int(batch, "eligible_users", context)
            top_count = _required_int(batch, "top_count", context)
            top_overlap_count = _required_int(batch, "top_overlap_count", context)
            full_ids = _required_string_sequence(batch, "full_ranking_top_user_ids", context)
            no_feedback_ids = _required_string_sequence(batch, "no_feedback_top_user_ids", context)
            overlap = _required_string_sequence(batch, "top_overlap_user_ids", context)
            feedback_added = _required_string_sequence(batch, "feedback_added_user_ids", context)
            feedback_removed = _required_string_sequence(batch, "feedback_removed_user_ids", context)
            if top_count != min(delivery_capacity, eligible_users):
                raise ValueError(f"campaign feedback evidence must contain Top20 rankings for {context}")
            if top_count != len(full_ids) or top_count != len(no_feedback_ids):
                raise ValueError(f"campaign feedback ranking rows do not match top_count for {context}")
            if top_count > delivery_capacity or top_overlap_count < 0 or top_overlap_count > top_count:
                raise ValueError(f"campaign feedback ranking bounds are invalid for {context}")
            no_feedback_set = set(no_feedback_ids)
            full_set = set(full_ids)
            expected_overlap = [user_id for user_id in full_ids if user_id in no_feedback_set]
            expected_added = [user_id for user_id in full_ids if user_id not in no_feedback_set]
            expected_removed = [user_id for user_id in no_feedback_ids if user_id not in full_set]
            if overlap != expected_overlap or feedback_added != expected_added or feedback_removed != expected_removed:
                raise ValueError(f"campaign feedback set differences do not close for {context}")
            if top_overlap_count != len(overlap):
                raise ValueError(f"campaign feedback overlap count does not close for {context}")
            changed = _required_bool(batch, "top_selection_changed", context)
            if changed != bool(feedback_added or feedback_removed):
                raise ValueError(f"campaign feedback changed flag does not close for {context}")
            changed_count += int(changed)
            overlap_counts.append(top_overlap_count)
            all_added.update(feedback_added)
            all_removed.update(feedback_removed)
            normalized_batches.append(
                {
                    "time_step": time_step,
                    "eligible_users": eligible_users,
                    "top_count": top_count,
                    "top_overlap_count": top_overlap_count,
                    "top_selection_changed": changed,
                    "feedback_added_user_ids": feedback_added,
                    "feedback_removed_user_ids": feedback_removed,
                    "full_ranking_top_user_ids": full_ids,
                    "no_feedback_top_user_ids": no_feedback_ids,
                    "top_overlap_user_ids": overlap,
                }
            )
        if declared_changed != changed_count:
            raise ValueError(f"campaign feedback changed batch count does not close for {message_id}")
        total_changed += changed_count
        normalized_messages.append(
            {
                "message_id": message_id,
                "title": title,
                "changed_batch_count": changed_count,
                "overlap_range": {"min": min(overlap_counts), "max": max(overlap_counts)},
                "batches": normalized_batches,
            }
        )

    if changed_message_batch_count != total_changed:
        raise ValueError("campaign feedback overall changed batch count does not close")
    if set(added_ids) != all_added or set(removed_ids) != all_removed or set(changed_ids) != all_added | all_removed:
        raise ValueError("campaign feedback distinct user IDs do not close to batch evidence")
    return {
        "message_batch_count": message_batch_count,
        "changed_message_batch_count": changed_message_batch_count,
        "distinct_feedback_added_user_ids": added_ids,
        "distinct_feedback_removed_user_ids": removed_ids,
        "distinct_changed_user_ids": changed_ids,
        "flags": flags,
        "per_message": normalized_messages,
    }


def _trace_lineage_rows(payload: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, entry in enumerate(_required_sequence(payload, "field_lineage", "payload")):
        usage_stages = _required_sequence(entry, "usage_stages", f"field_lineage[{index}]")
        rows.append(
            {
                "field_name": str(_value(entry, "field_name", "")).strip(),
                "label": str(_value(entry, "label", "")).strip(),
                "source_artifact": str(_value(entry, "source_artifact", "")).strip(),
                "evidence_class": str(_value(entry, "evidence_class", "")).strip(),
                "prompt_visibility": str(_value(entry, "prompt_visibility", "")).strip(),
                "usage_stages": [str(stage) for stage in usage_stages],
                "description": str(_value(entry, "description", "")).strip(),
            }
        )
    if any(not row["field_name"] or not row["source_artifact"] for row in rows):
        raise ValueError("field lineage requires field names and source artifacts")
    return rows


def _trace_view_row(row: Any, messages_by_id: Mapping[str, Mapping[str, str]], index: int) -> dict[str, Any]:
    context = f"exposure_rows[{index}]"
    trace_id = str(_value(row, "trace_id", "")).strip()
    message_id = str(_value(row, "message_id", "")).strip()
    user_id = str(_value(row, "user_id", "")).strip()
    if not trace_id or not message_id or not user_id:
        raise ValueError(f"{context} requires trace_id, message_id and user_id")
    message = messages_by_id.get(message_id)
    if message is None:
        raise ValueError(f"{context} references an unknown message")
    ranking = _required_mapping(row, "ranking_evidence", context)
    primary_context = _safe_trace_mapping(row, "primary_context", context)
    shadow_context = _safe_trace_mapping(row, "shadow_context", context)
    primary_peer_context = _safe_trace_mapping(row, "primary_peer_context", context)
    shadow_peer_context = _safe_trace_mapping(row, "shadow_peer_context", context)
    primary_provider_metadata = _safe_trace_mapping(
        _required_mapping(row, "primary_decision", context),
        "provider_metadata",
        f"{context}.primary_decision",
    )
    shadow_provider_metadata = _safe_trace_mapping(
        _required_mapping(row, "shadow_decision", context),
        "provider_metadata",
        f"{context}.shadow_decision",
    )
    field_differences = _safe_trace_sequence(row, "field_differences", context)
    prompt_inclusion = _safe_trace_mapping(row, "prompt_field_inclusion", context)
    shadow_added_fields = _safe_trace_mapping(row, "shadow_added_fields", context)
    primary_status = str(_value(row, "primary_status", "")).strip()
    shadow_status = str(_value(row, "shadow_status", "")).strip()
    primary_action = str(_value(row, "primary_action", "")).strip()
    shadow_action = str(_value(row, "shadow_action", "")).strip()
    if primary_status == "provider_failed" and not primary_action:
        primary_action = "provider_failed"
    if shadow_status == "provider_failed" and not shadow_action:
        shadow_action = "provider_failed"
    if primary_action not in _TRACE_ACTIONS or shadow_action not in _TRACE_ACTIONS:
        raise ValueError(f"{context} contains an unsupported action")
    if not isinstance(_value(row, "primary_shadow_disagreement", None), bool):
        raise ValueError(f"{context}.primary_shadow_disagreement must be persisted boolean")
    dual_success = primary_status == "succeeded" and shadow_status == "succeeded"
    engage_disagreement = dual_success and ((primary_action != "ignore") != (shadow_action != "ignore"))
    return {
        "trace_id": trace_id,
        "pair_id": str(_value(row, "pair_id", trace_id)).strip(),
        "time_step": _required_int(row, "time_step", context),
        "message_id": message_id,
        "message_title": message["title"],
        "message_body": message["body"],
        "user_id": user_id,
        "latent_class": str(_value(row, "latent_class", "")).strip(),
        "is_seed": bool(_value(row, "is_seed", False)),
        "selection_reason": str(_value(row, "selection_reason", "")).strip(),
        "ranking_position": _required_int(row, "ranking_position", context),
        "personalized_delivery_score": _required_float(row, "personalized_delivery_score", context),
        "primary_status": primary_status,
        "primary_action": primary_action,
        "primary_probability": _safe_trace_value(_value(row, "primary_probability", None)),
        "primary_confidence": _safe_trace_value(_value(row, "primary_confidence", None)),
        "primary_reason": str(_value(row, "primary_reason", "")),
        "primary_decision_source": str(_value(row, "primary_decision_source", "")),
        "primary_provider_metadata": primary_provider_metadata,
        "primary_prompt_version": str(_value(row, "primary_prompt_version", "")),
        "shadow_status": shadow_status,
        "shadow_action": shadow_action,
        "shadow_probability": _safe_trace_value(_value(row, "shadow_probability", None)),
        "shadow_confidence": _safe_trace_value(_value(row, "shadow_confidence", None)),
        "shadow_reason": str(_value(row, "shadow_reason", "")),
        "shadow_decision_source": str(_value(row, "shadow_decision_source", "")),
        "shadow_provider_metadata": shadow_provider_metadata,
        "shadow_prompt_version": str(_value(row, "shadow_prompt_version", "")),
        "provider_status": str(_value(row, "provider_status", "")).strip(),
        "decision_difference": bool(_value(row, "primary_shadow_disagreement", False)),
        "disagreement": engage_disagreement,
        "primary_context": primary_context,
        "shadow_context": shadow_context,
        "primary_peer_context": primary_peer_context,
        "shadow_peer_context": shadow_peer_context,
        "shadow_added_fields": shadow_added_fields,
        "prompt_field_inclusion": prompt_inclusion,
        "field_differences": field_differences,
        "ranking_evidence": {
            "ranking_position": _required_int(ranking, "ranking_position", f"{context}.ranking_evidence"),
            "selection_reason": str(_value(ranking, "selection_reason", "")),
            "base_network_relevance": _required_float(ranking, "base_network_relevance", f"{context}.ranking_evidence"),
            "campaign_engaged_neighbor_count": _required_int(ranking, "campaign_engaged_neighbor_count", f"{context}.ranking_evidence"),
            "campaign_engaged_neighbor_signal": _required_float(ranking, "campaign_engaged_neighbor_signal", f"{context}.ranking_evidence"),
            "raw_message_user_fit": _required_float(ranking, "raw_message_user_fit", f"{context}.ranking_evidence"),
            "normalized_message_user_fit": _required_float(ranking, "normalized_message_user_fit", f"{context}.ranking_evidence"),
            "personalized_delivery_score": _required_float(ranking, "personalized_delivery_score", f"{context}.ranking_evidence"),
            "not_in_prompt": _value(ranking, "not_in_prompt", False),
        },
        "aggregate_evidence": _safe_trace_mapping(row, "aggregate_evidence", context),
    }


def _format_rate(numerator: object, denominator: object) -> str:
    numerator_int = _as_int(numerator)
    denominator_int = _as_int(denominator)
    rate = numerator_int / denominator_int if denominator_int else 0.0
    percent = f"{rate * 100:.1f}".rstrip("0").rstrip(".")
    return f"{_format_count(numerator_int)}/{_format_count(denominator_int)}={percent}%"


def _format_delta(value: object) -> str:
    formatted = f"{_as_float(value):.3f}"
    return formatted[1:] if formatted.startswith("0.") else formatted



def _run_evidence_data(payload: Any) -> dict[str, Any]:
    """Build the run presentation only from allowlisted, persisted payload fields."""
    run = _required_mapping(payload, "run", "payload")
    funnel = _required_mapping(payload, "campaign_funnel", "payload")
    allocation = _required_mapping(payload, "message_allocation", "payload")
    validation = _required_mapping(payload, "validation_summary", "payload")
    counts = _required_mapping(validation, "counts", "validation_summary")
    raw_messages = _required_sequence(payload, "messages", "payload")
    raw_users = _required_sequence(payload, "user_rows", "payload")
    raw_exposures = _required_sequence(payload, "exposure_rows", "payload")
    if not raw_messages or not raw_users:
        raise ValueError("run evidence requires persisted messages and user rows")

    messages: list[dict[str, str]] = []
    message_ids: set[str] = set()
    message_titles: dict[str, str] = {}
    for index, message in enumerate(raw_messages, start=1):
        message_id = str(_value(message, "message_id", "")).strip()
        title = str(_value(message, "title", "")).strip()
        body = str(_value(message, "body", "")).strip()
        audience = str(_value(message, "intended_audience_segment", "")).strip()
        if not message_id or not title or not body or not audience:
            raise ValueError(f"messages[{index}] is missing authoritative persisted fields")
        if message_id in message_ids:
            raise ValueError(f"duplicate persisted message id: {message_id}")
        message_ids.add(message_id)
        message_titles[message_id] = title
        messages.append({"message_id": message_id, "title": title, "body": body, "audience": audience})

    sample_users = _required_int(counts, "sample_users", "validation_summary.counts")
    eligible_pairs = _required_int(counts, "eligible_user_message_pairs", "validation_summary.counts")
    actual_exposures = _required_int(counts, "actual_exposures", "validation_summary.counts")
    if sample_users != len(raw_users) or actual_exposures != len(raw_exposures):
        raise ValueError("persisted row counts do not match validation counts")
    distinct_exposed_users = _required_int(counts, "distinct_exposed_users", "validation_summary.counts")
    distinct_exposure_user_ids = {
        str(_value(row, "user_id", "")).strip() for row in raw_exposures if str(_value(row, "user_id", "")).strip()
    }
    if distinct_exposed_users != len(distinct_exposure_user_ids):
        raise ValueError("distinct exposed users do not match persisted exposure rows")

    primary = _required_mapping(funnel, "primary", "campaign_funnel")
    shadow = _required_mapping(funnel, "shadow", "campaign_funnel")
    accounting = {
        "primary": {
            "attempted": _required_int(primary, "attempted", "campaign_funnel.primary"),
            "succeeded": _required_int(primary, "succeeded", "campaign_funnel.primary"),
            "failures": _required_int(primary, "provider_failed", "campaign_funnel.primary"),
        },
        "shadow": {
            "attempted": _required_int(shadow, "attempted", "campaign_funnel.shadow"),
            "succeeded": _required_int(shadow, "succeeded", "campaign_funnel.shadow"),
            "failures": _required_int(shadow, "provider_failed", "campaign_funnel.shadow"),
        },
    }

    coverage_source = _required_mapping(funnel, "campaign_exposure_coverage", "campaign_funnel")
    coverage = {str(key): _required_int(coverage_source, str(key), "campaign_exposure_coverage") for key in sorted(coverage_source, key=str)}
    if sum(coverage.values()) != sample_users:
        raise ValueError("exposure coverage does not sum to persisted sample users")
    observed_coverage = Counter(_required_int(row, "distinct_message_count", "user_rows[]") for row in raw_users)
    expected_coverage = {int(key): value for key, value in coverage.items()}
    if any(observed_coverage.get(key, 0) != value for key, value in expected_coverage.items()) or set(observed_coverage) - set(expected_coverage):
        raise ValueError("exposure coverage does not match persisted user rows")

    role_counts = Counter(str(_value(row, "sample_role", "")).strip() for row in raw_users)
    class_counts = Counter(str(_value(row, "latent_class", "")).strip() for row in raw_users)
    if "" in role_counts or "" in class_counts:
        raise ValueError("persisted user rows require sample_role and latent_class")
    role_order = [role for role in ("seed", "network_cohort", "ordinary") if role in role_counts]
    role_order.extend(sorted(set(role_counts) - set(role_order)))
    class_order = sorted(class_counts)

    response_source = _required_mapping(payload, "primary_audience_response", "payload")
    response_by_message = _required_mapping(response_source, "per_message", "primary_audience_response")
    per_message_source = _required_mapping(funnel, "per_message", "campaign_funnel")
    per_message: list[dict[str, Any]] = []
    for message in messages:
        message_id = message["message_id"]
        entry = _required_mapping(per_message_source, message_id, "campaign_funnel.per_message")
        response_entry = _required_mapping(response_by_message, message_id, "primary_audience_response.per_message")
        action_counts_source = _required_mapping(response_entry, "action_counts", f"primary_audience_response.{message_id}")
        action_counts = {
            action: _required_int(action_counts_source, action, f"primary_audience_response.{message_id}.action_counts")
            for action in _TRACE_ACTIONS
        }
        positive_actions = _required_int(response_entry, "positive_actions", f"primary_audience_response.{message_id}")
        decision_rate = _required_mapping(response_entry, "decision_engagement_rate", f"primary_audience_response.{message_id}")
        positive_numerator = _required_int(decision_rate, "numerator", f"primary_audience_response.{message_id}.decision_engagement_rate")
        positive_denominator = _required_int(decision_rate, "denominator", f"primary_audience_response.{message_id}.decision_engagement_rate")
        if positive_actions != sum(action_counts[action] for action in ("like", "comment", "share")):
            raise ValueError(f"positive action count does not close for {message_id}")
        if positive_numerator != positive_actions or positive_denominator != sum(action_counts[action] for action in ("like", "comment", "share", "ignore")):
            raise ValueError(f"positive rate denominator does not close for {message_id}")
        per_message.append(
            {
                "message_id": message_id,
                "title": message["title"],
                "exposures": _required_int(entry, "exposures", f"campaign_funnel.per_message.{message_id}"),
                "primary_successes": _required_int(entry, "primary_successes", f"campaign_funnel.per_message.{message_id}"),
                "shadow_successes": _required_int(entry, "shadow_successes", f"campaign_funnel.per_message.{message_id}"),
                "action_counts": action_counts,
                "positive_actions": positive_actions,
                "positive_numerator": positive_numerator,
                "positive_denominator": positive_denominator,
            }
        )

    overlap = _required_mapping(allocation, "overlap", "message_allocation")
    pairwise_source = _required_sequence(overlap, "pairwise", "message_allocation.overlap")
    pairwise: list[dict[str, Any]] = []
    for index, entry in enumerate(pairwise_source):
        left = str(_value(entry, "left_message_id", "")).strip()
        right = str(_value(entry, "right_message_id", "")).strip()
        if left not in message_ids or right not in message_ids or left == right:
            raise ValueError(f"message_allocation.overlap.pairwise[{index}] has invalid message ids")
        pairwise.append(
            {
                "left_message_id": left,
                "right_message_id": right,
                "overlap_count": _required_int(entry, "overlap_count", f"message_allocation.overlap.pairwise[{index}]"),
            }
        )
    class_matrix_source = _required_mapping(allocation, "class_message_matrix", "message_allocation")
    class_matrix: list[dict[str, Any]] = []
    for class_id in class_order:
        row = _required_mapping(class_matrix_source, class_id, "message_allocation.class_message_matrix")
        class_matrix.append(
            {
                "class_id": class_id,
                "values": [
                    _required_int(row, message["message_id"], f"class_message_matrix.{class_id}") for message in messages
                ],
            }
        )

    fit_source = _required_mapping(allocation, "fit_distribution_by_message", "message_allocation")
    fit_ranges: list[dict[str, Any]] = []
    for message in messages:
        message_id = message["message_id"]
        entry = _required_mapping(fit_source, message_id, "message_allocation.fit_distribution_by_message")
        normalized = _required_mapping(entry, "normalized_message_user_fit", f"fit_distribution.{message_id}")
        fit_ranges.append(
            {
                "message_id": message_id,
                "title": message["title"],
                "count": _required_int(normalized, "count", f"fit_distribution.{message_id}"),
                "min": _required_float(normalized, "min", f"fit_distribution.{message_id}"),
                "mean": _required_float(normalized, "mean", f"fit_distribution.{message_id}"),
                "max": _required_float(normalized, "max", f"fit_distribution.{message_id}"),
            }
        )

    batch_source = _required_sequence(allocation, "batch_capacity", "message_allocation")
    horizon = _required_int(run, "horizon", "run")
    delivery_capacity = _required_int(run, "delivery_capacity", "run")
    feedback = _feedback_effect_data(
        payload,
        message_ids=[message["message_id"] for message in messages],
        message_titles=message_titles,
        horizon=horizon,
        delivery_capacity=delivery_capacity,
    )
    if len(batch_source) != len(messages) * horizon:
        raise ValueError("persisted batch capacity rows do not match message count and horizon")
    batch_rows: list[dict[str, Any]] = []
    seen_batches: set[tuple[str, int]] = set()
    message_order = {message["message_id"]: index for index, message in enumerate(messages)}
    for index, row in enumerate(batch_source):
        message_id = str(_value(row, "message_id", "")).strip()
        if message_id not in message_ids:
            raise ValueError(f"batch_capacity[{index}] references an unknown message")
        time_step = _required_int(row, "time_step", f"batch_capacity[{index}]")
        identity = (message_id, time_step)
        if identity in seen_batches:
            raise ValueError(f"duplicate persisted batch row: {identity}")
        seen_batches.add(identity)
        batch_rows.append(
            {
                "message_id": message_id,
                "title": message_titles[message_id],
                "time_step": time_step,
                "selected_pairs": _required_int(row, "selected_pairs", f"batch_capacity[{index}]"),
                "configured_capacity": _required_int(row, "configured_capacity", f"batch_capacity[{index}]"),
                "eligible_users": _required_int(row, "eligible_users", f"batch_capacity[{index}]"),
                "below_delivery_capacity": _required_int(row, "below_delivery_capacity", f"batch_capacity[{index}]"),
                "cumulative_pairs": _required_int(row, "cumulative_pairs", f"batch_capacity[{index}]"),
            }
        )
    if {message_id for message_id, _ in seen_batches} != message_ids or any(
        sum(1 for batch_message_id, _ in seen_batches if batch_message_id == message_id) != horizon for message_id in message_ids
    ):
        raise ValueError("persisted batch rows do not cover every message and horizon")
    batch_rows.sort(key=lambda row: (message_order[row["message_id"]], row["time_step"]))

    prompt_tokens = _required_mapping(run, "prompt_tokens", "run")
    primary_token = str(_value(prompt_tokens, "primary", "")).strip()
    shadow_token = str(_value(prompt_tokens, "shadow", "")).strip()
    profile = str(_value(run, "configuration_profile", "")).strip()
    if not profile or not primary_token or not shadow_token:
        raise ValueError("run metadata requires configuration profile and prompt tokens")
    production_eligible = _value(run, "production_deploy_eligible", None)
    if not isinstance(production_eligible, bool):
        raise ValueError("run.production_deploy_eligible must be persisted boolean metadata")
    observed_model = _observed_model(payload)
    if not observed_model:
        raise ValueError("variant_provider_accounting must persist an observed model")
    downloads = _validated_downloads(payload)
    artifacts = [downloads[key] for key in _EDITORIAL_DOWNLOAD_KEYS]
    messages_by_id = {message["message_id"]: message for message in messages}
    trace_rows = [_trace_view_row(row, messages_by_id, index) for index, row in enumerate(raw_exposures)]
    trace_ids = [row["trace_id"] for row in trace_rows]
    if len(set(trace_ids)) != len(trace_ids):
        raise ValueError("persisted trace rows require unique trace_id values")
    sensitivity = _required_mapping(payload, "demographic_decision_sensitivity", "payload")
    paired_coverage = _required_mapping(sensitivity, "paired_decision_coverage", "demographic_decision_sensitivity")
    disagreement_rate = _required_mapping(sensitivity, "engage_disagreement_rate", "demographic_decision_sensitivity")
    mean_delta = _required_mapping(sensitivity, "mean_absolute_probability_delta", "demographic_decision_sensitivity")
    reason_screening = _required_mapping(sensitivity, "reason_screening", "demographic_decision_sensitivity")
    disagreement_count = sum(1 for row in trace_rows if row["disagreement"])
    if disagreement_count != _required_int(disagreement_rate, "numerator", "engage_disagreement_rate"):
        raise ValueError("persisted disagreement rows do not match sensitivity numerator")
    trace_sensitivity = {
        "paired_coverage": {
            "numerator": _required_int(paired_coverage, "numerator", "paired_decision_coverage"),
            "denominator": _required_int(paired_coverage, "denominator", "paired_decision_coverage"),
            "value": _required_float(paired_coverage, "value", "paired_decision_coverage"),
        },
        "disagreement": {
            "numerator": _required_int(disagreement_rate, "numerator", "engage_disagreement_rate"),
            "denominator": _required_int(disagreement_rate, "denominator", "engage_disagreement_rate"),
            "value": _required_float(disagreement_rate, "value", "engage_disagreement_rate"),
        },
        "mean_delta": _required_float(mean_delta, "value", "mean_absolute_probability_delta"),
        "flagged_reasons": _required_int(reason_screening, "flagged_pair_count", "reason_screening"),
    }
    field_lineage = _trace_lineage_rows(payload)

    return {
        "schema": str(_value(payload, "schema_version", "")),
        "profile": profile,
        "formal": production_eligible and profile == "production",
        "observed_model": observed_model,
        "primary_token": primary_token,
        "shadow_token": shadow_token,
        "artifacts": artifacts,
        "sample_users": sample_users,
        "eligible_pairs": eligible_pairs,
        "actual_exposures": actual_exposures,
        "distinct_exposed_users": distinct_exposed_users,
        "accounting": accounting,
        "coverage": coverage,
        "role_counts": {role: role_counts[role] for role in role_order},
        "class_counts": {class_id: class_counts[class_id] for class_id in class_order},
        "messages": messages,
        "per_message": per_message,
        "union_count": _required_int(overlap, "distinct_union_count", "message_allocation.overlap"),
        "three_way_count": _required_int(overlap, "three_way_intersection_count", "message_allocation.overlap"),
        "pairwise": pairwise,
        "class_matrix": class_matrix,
        "fit_ranges": fit_ranges,
        "batch_rows": batch_rows,
        "trace_rows": trace_rows,
        "trace_sensitivity": trace_sensitivity,
        "feedback": feedback,
        "downloads": downloads,
        "field_lineage": field_lineage,
    }


def _escaped(value: object, *, quote: bool = False) -> str:
    return html.escape(str(value), quote=quote)


def _copy(key: str, language: str = "zh-CN") -> str:
    return _EDITORIAL_CATALOG[language][key]


def _v2_copy(key: str, language: str = "zh-CN") -> str:
    return _EDITORIAL_V2_CATALOG[language][key]


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


def _v2_i18n(key: str, *, class_name: str = "") -> str:
    classes = f' class="{_escaped(class_name, quote=True)}"' if class_name else ""
    return (
        f'<span{classes} data-i18n="{_escaped(key, quote=True)}">'
        f"{_escaped(_v2_copy(key), quote=False)}</span>"
    )


def _asset_bytes(asset_key: str) -> bytes:
    asset = _EDITORIAL_ASSET_CATALOG[asset_key]
    return files("llm_abm_sim").joinpath("report_assets").joinpath(asset["file"]).read_bytes()


def _embedded_asset(asset_key: str) -> str:
    return "data:image/webp;base64," + b64encode(_asset_bytes(asset_key)).decode("ascii")


def _v2_embedded_asset(asset_key: str) -> str:
    asset = _EDITORIAL_V2_ASSET_CATALOG[asset_key]
    payload = files("llm_abm_sim").joinpath("report_assets").joinpath(asset["file"]).read_bytes()
    return "data:image/webp;base64," + b64encode(payload).decode("ascii")


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


def _v2_legend(section: str) -> str:
    items = _EDITORIAL_V2_LEGEND_ITEMS[section]
    rows: list[str] = []
    for item_id, copy_key, mark_tokens, encoding_axis in items:
        mark_classes = " ".join(f"editorial-mark-{token}" for token in mark_tokens.split())
        rows.append(
            f'<span class="editorial-legend-item" role="listitem" '
            f'data-legend-item="{_escaped(item_id, quote=True)}" '
            f'data-encoding-axis="{_escaped(encoding_axis, quote=True)}">'
            f'<i class="editorial-mark {mark_classes}" aria-hidden="true"><b></b><b></b><b></b></i>'
            f'{_v2_i18n(copy_key, class_name="editorial-legend-label")}</span>'
        )
    return (
        f'<div class="editorial-legend editorial-legend-v2" data-testid="mechanism-{_escaped(section, quote=True)}-legend" '
        f'data-legend-section="{_escaped(section, quote=True)}" role="list" '
        f'{_attribute_i18n("shell.legend_aria", "aria-label")}>'
        + "".join(rows)
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
    messages = _value(payload, "messages", [])
    message_count = len(messages) if isinstance(messages, Sequence) else 3
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
        return str(sorted(model_counts)[0])
    return ""


def _run_overview_section(data: Mapping[str, Any]) -> str:
    accounting = data["accounting"]
    status_key = "run.status.formal" if data["formal"] else "run.status.not_formal"
    coverage_sequence = "/".join(str(data["coverage"][key]) for key in sorted(data["coverage"], key=int))
    accounting_cards = "".join(
        f'<article data-testid="run-{variant}-accounting">'
        f'<h3>{_i18n(f"run.accounting.{variant}")}</h3>'
        f'<strong class="editorial-run-accounting-value">{_format_count(values["succeeded"])} / {_format_count(values["failures"])}</strong>'
        f'<p>{_i18n("run.accounting.succeeded")} / {_i18n("run.accounting.failures")}</p>'
        f'<dl class="editorial-source-list"><div><dt>{_i18n("run.accounting.attempted")}</dt><dd>{_format_count(values["attempted"])}</dd></div>'
        f'<div><dt>{_i18n("run.accounting.succeeded")}</dt><dd>{_format_count(values["succeeded"])}</dd></div>'
        f'<div><dt>{_i18n("run.accounting.failures")}</dt><dd>{_format_count(values["failures"])}</dd></div></dl></article>'
        for variant, values in accounting.items()
    )
    funnel_cards = "".join(
        f'<article><strong>{_format_count(value)}</strong>{_i18n(key, tag="span")}</article>'
        for key, value in (
            ("run.funnel.sample", data["sample_users"]),
            ("run.funnel.eligible", data["eligible_pairs"]),
            ("run.funnel.exposures", data["actual_exposures"]),
            ("run.funnel.distinct", data["distinct_exposed_users"]),
        )
    )
    coverage_rows = "".join(
        f'<li data-testid="run-coverage-{_escaped(key, quote=True)}"><strong>{_format_count(value)} / {_format_count(data["sample_users"])}</strong>{_i18n("run.coverage.messages")} · {key}</li>'
        for key, value in sorted(data["coverage"].items(), key=lambda item: int(item[0]))
    )
    return f'''
      <section id="run-overview" class="editorial-section editorial-run-section editorial-run-intro" data-section-anchor="overview" data-testid="run-intro" tabindex="-1">
        <div class="editorial-section-header">
          <div>{_i18n("run.overview.kicker", class_name="editorial-kicker")}{_i18n("run.overview.title", tag="h1")}</div>
          {_i18n("run.overview.lead", tag="p", class_name="editorial-lead")}
        </div>
        <div class="editorial-run-status-strip" data-testid="run-status-strip">
          <div data-testid="run-formal-status"><strong>{_i18n("run.status.label")}</strong><span class="editorial-run-status-value">{_i18n(status_key)}</span></div>
          <div><strong>{_i18n("run.status.profile")}</strong><code>{_escaped(data["profile"])}</code></div>
          <div><strong>{_i18n("run.status.schema")}</strong><code>{_escaped(data["schema"])}</code></div>
          <div><strong>{_i18n("run.status.model")}</strong><code>{_escaped(data["observed_model"])}</code></div>
        </div>
        <div class="editorial-metric-strip" data-testid="run-overview-metrics">
          <article data-testid="run-sample-users"><strong>{_format_count(data["sample_users"])}</strong>{_i18n("run.metric.sample", tag="span")}</article>
          <article data-testid="run-eligible-pairs"><strong>{_format_count(data["eligible_pairs"])}</strong>{_i18n("run.metric.eligible", tag="span")}</article>
          <article data-testid="run-actual-exposures"><strong>{_format_count(data["actual_exposures"])}</strong>{_i18n("run.metric.exposures", tag="span")}</article>
          <article data-testid="run-distinct-exposed-users"><strong>{_format_count(data["distinct_exposed_users"])}</strong>{_i18n("run.metric.distinct", tag="span")}</article>
        </div>
        <div class="editorial-run-summary-grid editorial-run-accounting-grid" data-testid="run-accounting">
          <div class="editorial-run-summary-heading"><h2>{_i18n("run.accounting.title")}</h2><p>{_i18n("run.status.tokens", tag="span")} <code>{_escaped(data["primary_token"])}</code> · <code>{_escaped(data["shadow_token"])}</code></p></div>
          {accounting_cards}
        </div>
        <div class="editorial-run-funnel" data-testid="run-campaign-funnel"><h2>{_i18n("run.funnel.title")}</h2><div class="editorial-run-funnel-grid">{funnel_cards}</div></div>
        <div class="editorial-run-coverage" data-testid="run-exposure-coverage">
          <div><h2>{_i18n("run.coverage.title")}</h2>{_i18n("run.coverage.subtitle", tag="p")}<code data-testid="run-coverage-sequence">{_escaped(coverage_sequence)}</code></div>
          <ul>{coverage_rows}</ul>
        </div>
        <div class="editorial-run-contract-grid">
          <article><h2>{_i18n("run.contract.title")}</h2>{_i18n("run.contract.body", tag="p")}<dl class="editorial-source-list"><div><dt>{_i18n("run.source.primary_token")}</dt><dd><code>{_escaped(data["primary_token"])}</code></dd></div><div><dt>{_i18n("run.source.shadow_token")}</dt><dd><code>{_escaped(data["shadow_token"])}</code></dd></div></dl></article>
          <article><h2>{_i18n("run.status.title")}</h2>{_i18n("run.status.body", tag="p")}<dl class="editorial-source-list"><div><dt>{_i18n("run.source.schema")}</dt><dd><code>{_escaped(data["schema"])}</code></dd></div><div><dt>{_i18n("run.source.model")}</dt><dd><code>{_escaped(data["observed_model"])}</code></dd></div></dl></article>
        </div>
      </section>
    '''


def _run_sample_section(data: Mapping[str, Any]) -> str:
    role_keys = {"seed": "run.sample.seed", "network_cohort": "run.sample.network", "ordinary": "run.sample.ordinary"}
    role_rows = "".join(
        f'<tr><th>{_i18n(role_keys[role]) if role in role_keys else _escaped(role)}</th><td>{_format_count(count)}</td></tr>'
        for role, count in data["role_counts"].items()
    )
    class_rows = "".join(f'<tr><th><code>{_escaped(class_id)}</code></th><td>{_format_count(count)}</td></tr>' for class_id, count in data["class_counts"].items())
    coverage_rows = "".join(
        f'<tr><th>{key} {_i18n("run.coverage.messages")}</th><td>{_format_count(value)}</td><td>{_format_count(data["sample_users"])}</td></tr>'
        for key, value in sorted(data["coverage"].items(), key=lambda item: int(item[0]))
    )
    message_cards = "".join(
        f'<article class="editorial-authoritative-message" data-testid="run-authoritative-message-{_escaped(message["message_id"], quote=True)}" data-message-id="{_escaped(message["message_id"], quote=True)}">'
        f'<header><code>{_escaped(message["message_id"])}</code><h3>{_escaped(message["title"])}</h3></header>'
        f'<dl class="editorial-source-list"><div><dt>{_i18n("run.message.audience")}</dt><dd>{_escaped(message["audience"])}</dd></div><div><dt>{_i18n("run.message.id")}</dt><dd><code>{_escaped(message["message_id"])}</code></dd></div></dl>'
        f'<div class="editorial-authoritative-body"><p class="editorial-source-label">{_i18n("run.message.body")}</p>{_paragraphs(message["body"])}</div></article>'
        for message in data["messages"]
    )
    return f'''
      <section id="run-sample" class="editorial-section editorial-run-section editorial-section-sample" data-section-anchor="sample" data-testid="run-sample-section" tabindex="-1">
        <div class="editorial-section-header"><div>{_i18n("run.sample.kicker", class_name="editorial-kicker")}{_i18n("run.sample.title", tag="h2")}</div>{_i18n("run.sample.lead", tag="p", class_name="editorial-lead")}</div>
        <div class="editorial-run-two-column">
          <article class="editorial-run-table-block" data-testid="run-sample-roles"><h2>{_i18n("run.sample.roles")}</h2><table><thead><tr><th>{_i18n("run.sample.role", tag="span")}</th><th>{_i18n("run.sample.count", tag="span")}</th></tr></thead><tbody>{role_rows}</tbody></table></article>
          <article class="editorial-run-table-block" data-testid="run-sample-classes"><h2>{_i18n("run.sample.classes")}</h2><table><thead><tr><th>{_i18n("run.sample.class", tag="span")}</th><th>{_i18n("run.sample.count", tag="span")}</th></tr></thead><tbody>{class_rows}</tbody></table></article>
        </div>
        <article class="editorial-run-table-block" data-testid="run-sample-coverage"><h2>{_i18n("run.sample.coverage")}</h2><table><thead><tr><th>{_i18n("run.coverage.messages", tag="span")}</th><th>{_i18n("run.sample.count", tag="span")}</th><th>{_i18n("run.funnel.sample", tag="span")}</th></tr></thead><tbody>{coverage_rows}</tbody></table></article>
        <div class="editorial-run-message-heading"><h2>{_i18n("run.sample.authoritative")}</h2>{_i18n("run.sample.authoritative.body", tag="p")}</div>
        <div class="editorial-authoritative-grid">{message_cards}</div>
      </section>
    '''


def _run_exposure_section(data: Mapping[str, Any]) -> str:
    message_options = "".join(
        f'<option value="{_escaped(message["message_id"], quote=True)}">{_escaped(message["title"])}</option>' for message in data["messages"]
    )
    summary_cards = "".join(
        f'<article data-testid="run-exposure-summary-{_escaped(message["message_id"], quote=True)}"><code>{_escaped(message["message_id"])}</code><strong>{_format_count(message["exposures"])}</strong><span>{_i18n("run.exposure.per_message")}</span></article>'
        for message in data["per_message"]
    )
    fit_rows = "".join(
        f'<tr data-testid="run-fit-range-{_escaped(fit["message_id"], quote=True)}"><th><code>{_escaped(fit["message_id"])}</code><span>{_escaped(fit["title"])}</span></th><td data-fit-min="{_format_fit(fit["min"])}">{_format_fit(fit["min"])}</td><td data-fit-mean="{_format_fit(fit["mean"])}">{_format_fit(fit["mean"])}</td><td data-fit-max="{_format_fit(fit["max"])}">{_format_fit(fit["max"])}</td></tr>'
        for fit in data["fit_ranges"]
    )
    pairwise_rows = "".join(
        f'<li data-testid="run-pairwise-{_escaped(pair["left_message_id"] + "-" + pair["right_message_id"], quote=True)}"><code>{_escaped(pair["left_message_id"])}</code> × <code>{_escaped(pair["right_message_id"])}</code><strong>{_format_count(pair["overlap_count"])}</strong></li>'
        for pair in data["pairwise"]
    )
    matrix_headers = "".join(f'<th><code>{_escaped(message["message_id"])}</code></th>' for message in data["messages"])
    matrix_rows = "".join(
        f'<tr data-testid="run-matrix-{_escaped(row["class_id"], quote=True)}"><th><code>{_escaped(row["class_id"])}</code></th>{"".join(f"<td>{_format_count(value)}</td>" for value in row["values"])}</tr>'
        for row in data["class_matrix"]
    )
    batch_json = json.dumps(data["batch_rows"], ensure_ascii=False, separators=(",", ":")).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return f'''
      <section id="run-exposure-ranking" class="editorial-section editorial-run-section editorial-section-ranking" data-section-anchor="exposure-ranking" data-testid="run-exposure-ranking-section" tabindex="-1">
        <div class="editorial-section-header"><div>{_i18n("run.exposure.kicker", class_name="editorial-kicker")}{_i18n("run.exposure.title", tag="h2")}</div>{_i18n("run.exposure.lead", tag="p", class_name="editorial-lead")}</div>
        <div class="editorial-run-exposure-summary" data-testid="run-exposure-summary"><h2>{_i18n("run.exposure.summary")}</h2><div class="editorial-run-exposure-summary-grid">{summary_cards}<article data-testid="run-exposure-union"><code>union</code><strong>{_format_count(data["union_count"])}</strong><span>{_i18n("run.exposure.union")}</span></article><article data-testid="run-exposure-three-way"><code>3-way</code><strong>{_format_count(data["three_way_count"])}</strong><span>{_i18n("run.exposure.three_way")}</span></article></div></div>
        <div class="editorial-run-two-column editorial-run-overlap-grid"><article class="editorial-run-table-block" data-testid="run-pairwise-overlap"><h2>{_i18n("run.exposure.pairwise")}</h2><ul class="editorial-overlap-list">{pairwise_rows}</ul></article><article class="editorial-run-table-block" data-testid="run-class-message-matrix"><h2>{_i18n("run.exposure.matrix")}</h2><div class="editorial-table-scroll"><table><thead><tr><th>{_i18n("run.sample.class", tag="span")}</th>{matrix_headers}</tr></thead><tbody>{matrix_rows}</tbody></table></div></article></div>
        <article class="editorial-run-table-block" data-testid="run-fit-ranges"><h2>{_i18n("run.exposure.fit")}</h2><table><thead><tr><th>{_i18n("run.exposure.message", tag="span")}</th><th>{_i18n("run.exposure.min", tag="span")}</th><th>{_i18n("run.exposure.mean", tag="span")}</th><th>{_i18n("run.exposure.max", tag="span")}</th></tr></thead><tbody>{fit_rows}</tbody></table><p class="editorial-table-note">{_i18n("run.exposure.fit_metric")}</p></article>
        <article class="editorial-run-table-block editorial-run-batch-block" data-testid="run-batch-table"><div class="editorial-run-table-heading"><div><h2>{_i18n("run.exposure.batch_table")}</h2><p>{_i18n("run.evidence.descriptive")}</p></div><label>{_i18n("run.exposure.selector", tag="span")}<select data-testid="run-exposure-message-select" data-i18n-aria-label="run.exposure.selector" aria-label="{_copy("run.exposure.selector")}"><option value="all" data-i18n="run.exposure.all_messages">{_copy("run.exposure.all_messages")}</option>{message_options}</select></label></div><script type="application/json" data-testid="run-exposure-rows-data">{batch_json}</script><div class="editorial-table-scroll"><table data-testid="run-exposure-table" data-i18n-aria-label="run.exposure.table_aria" aria-label="{_copy("run.exposure.table_aria")}"><thead><tr><th>{_i18n("run.exposure.message", tag="span")}</th><th>{_i18n("run.exposure.batch", tag="span")}</th><th>{_i18n("run.exposure.selected", tag="span")}</th><th>{_i18n("run.exposure.eligible_users", tag="span")}</th><th>{_i18n("run.exposure.capacity", tag="span")}</th><th>{_i18n("run.exposure.below", tag="span")}</th><th>{_i18n("run.exposure.cumulative", tag="span")}</th></tr></thead><tbody data-testid="run-exposure-table-body"></tbody></table></div><div class="editorial-pagination" data-testid="run-exposure-pagination" data-i18n-aria-label="run.exposure.pagination_aria" aria-label="{_copy("run.exposure.pagination_aria")}"><button type="button" data-run-exposure-page="previous">{_i18n("run.exposure.previous")}</button><output data-testid="run-exposure-page-status" aria-live="polite"></output><button type="button" data-run-exposure-page="next">{_i18n("run.exposure.next")}</button></div></article>
      </section>
    '''


def _run_feedback_section(feedback: Mapping[str, Any]) -> str:
    per_message = feedback["per_message"]
    summary_cards = "".join(
        f'<article data-testid="run-feedback-message-{_escaped(message["message_id"], quote=True)}">'
        f'<code>{_escaped(message["message_id"])}</code>'
        f'<strong>{_format_count(message["changed_batch_count"])} / {_format_count(len(message["batches"]))}</strong>'
        f'<span>{_i18n("run.feedback.changed")}</span>'
        f'<p>{_i18n("run.feedback.range")} <code>{message["overlap_range"]["min"]}–{message["overlap_range"]["max"]}</code></p>'
        "</article>"
        for message in per_message
    )
    message_options = "".join(
        f'<option value="{_escaped(message["message_id"], quote=True)}">{_escaped(message["title"])}</option>'
        for message in per_message
    )
    feedback_json = json.dumps(feedback, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f'''
      <section id="run-network-feedback" class="editorial-section editorial-run-section editorial-section-feedback" data-section-anchor="network-feedback" data-testid="run-network-feedback-section" tabindex="-1">
        <div class="editorial-section-header"><div>{_i18n("run.feedback.kicker", class_name="editorial-kicker")}{_i18n("run.feedback.title", tag="h2")}</div>{_i18n("run.feedback.lead", tag="p", class_name="editorial-lead")}</div>
        <div class="editorial-feedback-summary" data-testid="run-feedback-summary">
          <article data-testid="run-feedback-changed-total"><strong>{_format_count(feedback["changed_message_batch_count"])} / {_format_count(feedback["message_batch_count"])}</strong><span>{_i18n("run.feedback.changed")}</span><code>{_format_count(feedback["message_batch_count"])} {_i18n("run.feedback.batch_total")}</code></article>
          {summary_cards}
        </div>
        <div class="editorial-callout editorial-callout-amber" data-testid="run-feedback-caveat"><strong>{_i18n("run.feedback.descriptive")}</strong></div>
        <div class="editorial-feedback-tool" data-testid="run-feedback-tool">
          <div class="editorial-feedback-filter-heading"><h2>{_i18n("run.feedback.scope")}</h2><output data-testid="run-feedback-filtered-count" aria-live="polite"></output></div>
          <div class="editorial-feedback-filters">
            <label>{_i18n("run.feedback.message", tag="span")}<select data-testid="run-feedback-message-select" {_attribute_i18n("run.feedback.message", "aria-label")}><option value="all" data-i18n="run.feedback.all_messages">{_copy("run.feedback.all_messages")}</option>{message_options}</select></label>
            <label>{_i18n("run.feedback.scope", tag="span")}<select data-testid="run-feedback-scope-select" {_attribute_i18n("run.feedback.scope", "aria-label")}><option value="changed" data-i18n="run.feedback.changed_only">{_copy("run.feedback.changed_only")}</option><option value="all" data-i18n="run.feedback.all_batches">{_copy("run.feedback.all_batches")}</option></select></label>
          </div>
          <script type="application/json" data-testid="run-feedback-data">{feedback_json}</script>
          <div class="editorial-table-scroll"><table class="editorial-feedback-table" data-testid="run-feedback-table" {_attribute_i18n("run.feedback.table_aria", "aria-label")}><thead><tr><th>{_i18n("run.feedback.message", tag="span")}</th><th>{_i18n("run.feedback.batch", tag="span")}</th><th>{_i18n("run.feedback.eligible", tag="span")}</th><th>{_i18n("run.feedback.top_count", tag="span")}</th><th>{_i18n("run.feedback.overlap", tag="span")}</th><th>{_i18n("run.feedback.added", tag="span")}</th><th>{_i18n("run.feedback.removed", tag="span")}</th><th>{_i18n("run.feedback.details", tag="span")}</th></tr></thead><tbody data-testid="run-feedback-table-body"></tbody></table></div>
        </div>
      </section>
    '''


def _run_trace_section(data: Mapping[str, Any]) -> str:
    action_labels = {
        "like": "run.trace.action.like",
        "comment": "run.trace.action.comment",
        "share": "run.trace.action.share",
        "ignore": "run.trace.action.ignore",
        "provider_failed": "run.trace.action.provider_failed",
    }
    message_summary = "".join(
        f'<article class="editorial-trace-summary-card" data-testid="run-trace-summary-{_escaped(message["message_id"], quote=True)}">'
        f'<header><code>{_escaped(message["message_id"])}</code><h3>{_escaped(message["title"])}</h3></header>'
        f'<p class="editorial-trace-action-counts" data-testid="run-trace-actions-{_escaped(message["message_id"], quote=True)}">'
        + " · ".join(
            f'{_i18n(action_labels[action])} {_format_count(message["action_counts"][action])}' for action in _TRACE_ACTIONS
        )
        + "</p>"
        f'<strong data-testid="run-trace-positive-rate-{_escaped(message["message_id"], quote=True)}">{_format_rate(message["positive_numerator"], message["positive_denominator"])}</strong>'
        f'<span>{_i18n("run.trace.positive_rate")}</span></article>'
        for message in data["per_message"]
    )
    sensitivity = data["trace_sensitivity"]
    message_options = "".join(
        f'<option value="{_escaped(message["message_id"], quote=True)}">{_escaped(message["title"])}</option>' for message in data["messages"]
    )
    class_options = "".join(f'<option value="{_escaped(class_id, quote=True)}">{_escaped(class_id)}</option>' for class_id in data["class_counts"])
    batch_values = sorted({row["time_step"] for row in data["trace_rows"]})
    batch_options = "".join(f'<option value="{time_step}">{time_step}</option>' for time_step in batch_values)
    action_options = "".join(
        f'<option value="{_escaped(action, quote=True)}" data-i18n="{_escaped(action_labels[action], quote=True)}">{_copy(action_labels[action])}</option>'
        for action in _TRACE_ACTIONS
    )
    trace_json = json.dumps(data["trace_rows"], ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    lineage_json = json.dumps(data["field_lineage"], ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f'''
          <section id="run-llm-decision" class="editorial-section editorial-run-section editorial-section-decision" data-section-anchor="llm-decision" data-testid="run-llm-decision-section" tabindex="-1">
            <div class="editorial-section-header"><div>{_i18n("run.trace.kicker", class_name="editorial-kicker")}{_i18n("run.trace.title", tag="h2")}</div>{_i18n("run.trace.lead", tag="p", class_name="editorial-lead")}</div>
            <div class="editorial-trace-summary" data-testid="run-trace-summary"><h2>{_i18n("run.trace.summary")}</h2><div class="editorial-trace-summary-grid">{message_summary}</div></div>
            <div class="editorial-trace-sensitivity" data-testid="run-trace-sensitivity"><h2>{_i18n("run.trace.sensitivity")}</h2><div class="editorial-trace-sensitivity-grid">
              <article data-testid="run-trace-paired-coverage"><strong>{_format_rate(sensitivity["paired_coverage"]["numerator"], sensitivity["paired_coverage"]["denominator"])}</strong>{_i18n("run.trace.paired_coverage")}</article>
              <article data-testid="run-trace-disagreement-rate"><strong>{_format_rate(sensitivity["disagreement"]["numerator"], sensitivity["disagreement"]["denominator"])}</strong>{_i18n("run.trace.disagreement_rate")}</article>
              <article data-testid="run-trace-mean-delta"><strong>{_format_delta(sensitivity["mean_delta"])}</strong>{_i18n("run.trace.mean_delta")}</article>
              <article data-testid="run-trace-flagged-reasons"><strong>{_format_count(sensitivity["flagged_reasons"])}</strong>{_i18n("run.trace.flagged_reasons")}</article>
            </div></div>
            <div class="editorial-trace-tool" data-testid="run-trace-tool">
              <div class="editorial-trace-filter-heading"><h2>{_i18n("run.trace.filters")}</h2><output data-testid="run-trace-filtered-count" aria-live="polite"></output></div>
              <div class="editorial-trace-filters">
                <label>{_i18n("run.trace.search", tag="span")}<input type="search" data-testid="run-trace-search" data-i18n-placeholder="run.trace.search_placeholder" placeholder="{_copy("run.trace.search_placeholder")}" {_attribute_i18n("run.trace.search", "aria-label")}></label>
                <label>{_i18n("run.trace.message_filter", tag="span")}<select data-testid="run-trace-message-select" {_attribute_i18n("run.trace.message_filter", "aria-label")}><option value="all" data-i18n="run.trace.all_messages">{_copy("run.trace.all_messages")}</option>{message_options}</select></label>
                <label>{_i18n("run.trace.class_filter", tag="span")}<select data-testid="run-trace-class-select" {_attribute_i18n("run.trace.class_filter", "aria-label")}><option value="all" data-i18n="run.trace.all_classes">{_copy("run.trace.all_classes")}</option>{class_options}</select></label>
                <label>{_i18n("run.trace.batch_filter", tag="span")}<select data-testid="run-trace-batch-select" {_attribute_i18n("run.trace.batch_filter", "aria-label")}><option value="all" data-i18n="run.trace.all_batches">{_copy("run.trace.all_batches")}</option>{batch_options}</select></label>
                <label>{_i18n("run.trace.action_filter", tag="span")}<select data-testid="run-trace-action-select" {_attribute_i18n("run.trace.action_filter", "aria-label")}><option value="all" data-i18n="run.trace.all_actions">{_copy("run.trace.all_actions")}</option>{action_options}</select></label>
                <label>{_i18n("run.trace.provider_filter", tag="span")}<select data-testid="run-trace-provider-select" {_attribute_i18n("run.trace.provider_filter", "aria-label")}><option value="all" data-i18n="run.trace.all_provider_status">{_copy("run.trace.all_provider_status")}</option><option value="succeeded">succeeded</option><option value="provider_failed">provider_failed</option></select></label>
                <label>{_i18n("run.trace.disagreement_filter", tag="span")}<select data-testid="run-trace-disagreement-select" {_attribute_i18n("run.trace.disagreement_filter", "aria-label")}><option value="all" data-i18n="run.trace.all_disagreement">{_copy("run.trace.all_disagreement")}</option><option value="yes" data-i18n="run.trace.only_disagreement">{_copy("run.trace.only_disagreement")}</option><option value="no" data-i18n="run.trace.no_disagreement">{_copy("run.trace.no_disagreement")}</option></select></label>
              </div>
              <script type="application/json" data-testid="run-trace-rows-data">{trace_json}</script>
              <script type="application/json" data-testid="run-trace-lineage-data">{lineage_json}</script>
              <div class="editorial-table-scroll"><table class="editorial-trace-table" data-testid="run-trace-table" {_attribute_i18n("run.trace.table_aria", "aria-label")}><thead><tr><th>{_i18n("run.trace.message", tag="span")}</th><th>{_i18n("run.trace.user", tag="span")}</th><th>{_i18n("run.trace.batch", tag="span")}</th><th>{_i18n("run.trace.class", tag="span")}</th><th>{_i18n("run.trace.primary_action", tag="span")}</th><th>{_i18n("run.trace.provider", tag="span")}</th><th>{_i18n("run.trace.disagreement", tag="span")}</th><th>{_i18n("run.trace.ranking", tag="span")}</th></tr></thead><tbody data-testid="run-trace-table-body"></tbody></table></div>
              <p class="editorial-trace-empty" data-testid="run-trace-empty" hidden>{_i18n("run.trace.empty")}</p>
              <div class="editorial-trace-pagination" data-testid="run-trace-pagination" {_attribute_i18n("run.exposure.pagination_aria", "aria-label")}><label>{_i18n("run.trace.page_size", tag="span")}<select data-testid="run-trace-page-size" aria-label="{_copy("run.trace.page_size")}"><option value="25" selected>25</option><option value="50">50</option><option value="100">100</option></select></label><button type="button" data-trace-page="previous" aria-label="{_copy("run.trace.previous")}">{_i18n("run.trace.previous")}</button><div class="editorial-trace-page-numbers" data-testid="run-trace-page-numbers"></div><button type="button" data-trace-page="next" aria-label="{_copy("run.trace.next")}">{_i18n("run.trace.next")}</button><output data-testid="run-trace-page-status" aria-live="polite"></output></div>
            </div>
          </section>
    '''


def _run_downloads_section(downloads: Mapping[str, str]) -> str:
    groups: list[str] = []
    for group, keys in _EDITORIAL_DOWNLOAD_GROUPS:
        links = "".join(
            f'<a class="editorial-download-link" data-download-group="{_escaped(group, quote=True)}" data-download-key="{_escaped(key, quote=True)}" data-testid="download-{_escaped(key.replace("_", "-"), quote=True)}" href="{_escaped(downloads[key], quote=True)}"><span>{_i18n("run.downloads.link")}</span><code>{_escaped(downloads[key])}</code></a>'
            for key in keys
        )
        groups.append(
            f'<section class="editorial-download-group" data-testid="run-download-group-{_escaped(group, quote=True)}" data-download-group="{_escaped(group, quote=True)}">'
            f'<h3>{_i18n(f"run.downloads.group.{group}")}</h3><div class="editorial-download-links" role="list">{links}</div></section>'
        )
    return f'''
      <section class="editorial-section editorial-run-section editorial-downloads-section" data-testid="run-downloads-section">
        <div class="editorial-section-header"><div>{_i18n("run.downloads.kicker", class_name="editorial-kicker")}{_i18n("run.downloads.title", tag="h2")}</div>{_i18n("run.downloads.lead", tag="p", class_name="editorial-lead")}</div>
        <div class="editorial-download-groups">{"".join(groups)}</div>
      </section>
    '''


def _run_placeholder_section(anchor: str) -> str:
    return (
        f'<section id="run-{_escaped(anchor, quote=True)}" class="editorial-section editorial-run-section" '
        f'data-section-anchor="{_escaped(anchor, quote=True)}" data-testid="run-{_escaped(anchor, quote=True)}-section" tabindex="-1">'
        f'<div class="editorial-section-header"><div>{_i18n("run.kicker", class_name="editorial-kicker")}{_i18n("run.placeholder.title", tag="h2")}</div>{_i18n("run.placeholder.body", tag="p", class_name="editorial-lead")}</div>'
        f'<p class="editorial-run-anchor-note"><code>#run/{_escaped(anchor)}</code></p></section>'
    )


def _run_scaffold(payload: Any) -> str:
    data = _run_evidence_data(payload)
    return (
        '<div class="editorial-run-scaffold" data-testid="editorial-run-scaffold">'
        + _run_overview_section(data)
        + _run_sample_section(data)
        + _run_exposure_section(data)
        + _run_trace_section(data)
        + _run_feedback_section(data["feedback"])
        + _run_downloads_section(data["downloads"])
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
    .editorial-drawer-backdrop { min-width: 0; }
    .editorial-drawer-tabs { display: flex; gap: 4px; margin: 22px 0 0; border-bottom: 1px solid var(--editorial-rule); overflow-x: auto; }
    .editorial-drawer-tabs button { flex: 0 0 auto; min-height: 42px; padding: 8px 12px; border: 0; border-bottom: 3px solid transparent; background: transparent; color: var(--editorial-muted); font-size: 13px; font-weight: 650; white-space: nowrap; }
    .editorial-drawer-tabs button[aria-selected="true"] { border-bottom-color: var(--editorial-cobalt); color: var(--editorial-cobalt); }
    .editorial-drawer-panels { min-width: 0; }
    .editorial-drawer-panels > section[hidden] { display: none !important; }
    .editorial-drawer-identity { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 20px; }
    .editorial-drawer-identity article, .editorial-drawer-panel-block { min-width: 0; padding: 12px; border-top: 1px solid var(--editorial-rule); background: var(--editorial-cool-paper); }
    .editorial-drawer-identity strong, .editorial-drawer-panel-block > strong { display: block; margin-bottom: 4px; color: var(--editorial-muted); font-size: 11px; font-weight: 700; }
    .editorial-drawer-identity span, .editorial-drawer-panel-block > span { display: block; color: var(--editorial-ink); font-size: 13px; overflow-wrap: anywhere; }
    .editorial-drawer-panel { display: grid; gap: 16px; padding-top: 20px; }
    .editorial-drawer-panel h3 { margin: 0; color: var(--editorial-ink); font-size: 17px; }
    .editorial-drawer-panel p { margin: 0; color: var(--editorial-muted); line-height: 1.6; overflow-wrap: anywhere; }
    .editorial-drawer-panel dl { display: grid; gap: 10px; margin: 0; }
    .editorial-drawer-panel dl div { min-width: 0; padding-top: 9px; border-top: 1px solid var(--editorial-rule); }
    .editorial-drawer-panel dt { color: var(--editorial-muted); font-size: 11px; font-weight: 700; }
    .editorial-drawer-panel dd { margin: 3px 0 0; color: var(--editorial-ink); overflow-wrap: anywhere; }
    .editorial-drawer-decision-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .editorial-drawer-decision-card { min-width: 0; padding: 14px; border-top: 2px solid var(--editorial-cobalt); background: var(--editorial-cool-paper); }
    .editorial-drawer-decision-card:nth-child(2) { border-top-color: var(--editorial-amber); }
    .editorial-drawer-decision-card h3 { margin-bottom: 10px; font-size: 15px; }
    .editorial-drawer-message { padding: 14px; border-top: 2px solid var(--editorial-green); background: var(--editorial-cool-paper); }
    .editorial-drawer-message h3 { margin-bottom: 9px; font-size: 16px; }
    .editorial-drawer-message p { margin: 0 0 10px; color: var(--editorial-muted); font-size: 13px; }
    .editorial-drawer-context-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .editorial-drawer-context-grid pre { max-height: 260px; margin: 0; padding: 12px; overflow: auto; background: var(--editorial-cool-paper); color: var(--editorial-ink); font: 12px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
    .editorial-drawer-lineage-list { display: grid; gap: 12px; margin: 0; padding: 0; list-style: none; }
    .editorial-drawer-lineage-list li { min-width: 0; padding: 12px; border-top: 1px solid var(--editorial-rule); background: var(--editorial-cool-paper); }
    .editorial-drawer-lineage-list strong, .editorial-drawer-lineage-list code { display: block; overflow-wrap: anywhere; }
    .editorial-drawer-lineage-list code { margin-bottom: 5px; color: var(--editorial-cobalt); font-size: 12px; }
    .editorial-drawer-lineage-list p { margin-top: 6px; font-size: 12px; }
    .editorial-trace-summary, .editorial-trace-sensitivity, .editorial-trace-tool { max-width: 1280px; margin: 0 auto 32px; }
    .editorial-trace-summary h2, .editorial-trace-sensitivity h2, .editorial-trace-tool h2 { margin: 0 0 13px; font-size: 21px; line-height: 1.25; }
    .editorial-trace-summary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border-top: 1px solid var(--editorial-rule); border-bottom: 1px solid var(--editorial-rule); }
    .editorial-trace-summary-card { min-width: 0; padding: 16px; border-right: 1px solid var(--editorial-rule); }
    .editorial-trace-summary-card:last-child { border-right: 0; }
    .editorial-trace-summary-card header { min-width: 0; margin-bottom: 10px; }
    .editorial-trace-summary-card header code { display: block; color: var(--editorial-muted); font-size: 12px; overflow-wrap: anywhere; }
    .editorial-trace-summary-card header h3 { margin-top: 5px; font-size: 16px; overflow-wrap: anywhere; }
    .editorial-trace-summary-card p { margin: 0 0 12px; color: var(--editorial-muted); font-size: 12px; line-height: 1.55; overflow-wrap: anywhere; }
    .editorial-trace-summary-card strong { display: block; color: var(--editorial-ink); font-size: 21px; }
    .editorial-trace-summary-card > span { display: block; margin-top: 3px; color: var(--editorial-muted); font-size: 12px; }
    .editorial-trace-sensitivity { padding: 18px 0; border-top: 1px solid var(--editorial-rule); border-bottom: 1px solid var(--editorial-rule); }
    .editorial-trace-sensitivity-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .editorial-trace-sensitivity-grid article { min-width: 0; padding: 12px 16px; border-right: 1px solid var(--editorial-rule); }
    .editorial-trace-sensitivity-grid article:last-child { border-right: 0; }
    .editorial-trace-sensitivity-grid strong { display: block; margin-bottom: 5px; color: var(--editorial-ink); font-size: 22px; overflow-wrap: anywhere; }
    .editorial-trace-sensitivity-grid article > span { display: block; color: var(--editorial-muted); font-size: 12px; line-height: 1.4; }
    .editorial-trace-filter-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; }
    .editorial-trace-filter-heading output { color: var(--editorial-muted); font-size: 12px; }
    .editorial-trace-filters { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 0 0 18px; }
    .editorial-trace-filters label, .editorial-trace-pagination label { display: grid; gap: 6px; min-width: 0; color: var(--editorial-muted); font-size: 12px; font-weight: 650; }
    .editorial-trace-filters input, .editorial-trace-filters select, .editorial-trace-pagination select { width: 100%; min-width: 0; min-height: 38px; padding: 8px 10px; border: 1px solid var(--editorial-rule); background: var(--editorial-paper); color: var(--editorial-ink); }
    .editorial-trace-table { min-width: 880px; }
    .editorial-trace-table tbody tr { cursor: pointer; }
    .editorial-trace-table tbody tr:hover, .editorial-trace-table tbody tr:focus-visible { background: #eef5ff; outline: 2px solid rgba(11, 87, 208, .2); outline-offset: -2px; }
    .editorial-trace-table td { white-space: nowrap; }
    .editorial-trace-table td:first-child, .editorial-trace-table td:nth-child(2) { max-width: 180px; overflow-wrap: anywhere; white-space: normal; }
    .editorial-trace-empty[hidden] { display: none; }
    .editorial-trace-empty { margin: 16px 0; color: var(--editorial-muted); }
    .editorial-trace-pagination { display: grid; grid-template-columns: minmax(150px, .4fr) auto minmax(160px, 1fr) auto; align-items: end; gap: 10px; margin-top: 16px; }
    .editorial-trace-pagination > button { min-height: 38px; padding: 7px 12px; border: 1px solid var(--editorial-rule); background: var(--editorial-paper); color: var(--editorial-ink); white-space: nowrap; }
    .editorial-trace-pagination > button:disabled { cursor: not-allowed; opacity: .42; }
    .editorial-trace-page-numbers { display: flex; flex-wrap: wrap; justify-content: center; gap: 5px; min-width: 0; }
    .editorial-trace-page-numbers button { min-width: 34px; min-height: 34px; padding: 5px 8px; border: 1px solid var(--editorial-rule); background: var(--editorial-paper); color: var(--editorial-ink); font-size: 12px; }
    .editorial-trace-page-numbers button[aria-current="page"] { border-color: var(--editorial-cobalt); color: var(--editorial-cobalt); font-weight: 700; }
    .editorial-trace-page-numbers button:disabled { border-color: transparent; cursor: default; }
    .editorial-trace-pagination output { min-width: 0; color: var(--editorial-muted); font-size: 12px; text-align: center; }

.editorial-feedback-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); max-width: 1280px; margin: 0 auto 32px; border-top: 1px solid var(--editorial-rule); border-bottom: 1px solid var(--editorial-rule); }
    .editorial-feedback-summary article { min-width: 0; padding: 17px 18px; border-right: 1px solid var(--editorial-rule); }
    .editorial-feedback-summary article:last-child { border-right: 0; }
    .editorial-feedback-summary article:first-child { border-top: 3px solid var(--editorial-cobalt); }
    .editorial-feedback-summary article:nth-child(2) { border-top: 3px solid var(--editorial-green); }
    .editorial-feedback-summary article:nth-child(3) { border-top: 3px solid var(--editorial-cobalt); }
    .editorial-feedback-summary article:nth-child(4) { border-top: 3px solid var(--editorial-amber); }
    .editorial-feedback-summary article:nth-child(5) { border-top: 3px solid var(--editorial-green); }
    .editorial-feedback-summary code, .editorial-feedback-summary span, .editorial-feedback-summary p { display: block; color: var(--editorial-muted); font-size: 12px; line-height: 1.45; overflow-wrap: anywhere; }
    .editorial-feedback-summary strong { display: block; margin: 7px 0 4px; color: var(--editorial-ink); font-size: 24px; line-height: 1.1; }
    .editorial-feedback-summary p { margin: 13px 0 0; }
    .editorial-feedback-summary p code { display: inline; color: var(--editorial-cobalt); font-size: 13px; font-weight: 700; }
    .editorial-feedback-tool { max-width: 1280px; margin: 0 auto 32px; }
    .editorial-feedback-filter-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; margin-bottom: 13px; }
    .editorial-feedback-filter-heading h2 { margin: 0; font-size: 21px; line-height: 1.25; }
    .editorial-feedback-filter-heading output { color: var(--editorial-muted); font-size: 12px; }
    .editorial-feedback-filters { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-bottom: 18px; }
    .editorial-feedback-filters label { display: grid; gap: 6px; min-width: 0; color: var(--editorial-muted); font-size: 12px; font-weight: 650; }
    .editorial-feedback-filters select { width: 100%; min-width: 0; min-height: 38px; padding: 8px 10px; border: 1px solid var(--editorial-rule); background: var(--editorial-paper); color: var(--editorial-ink); }
    .editorial-feedback-table { min-width: 760px; }
    .editorial-feedback-table tbody tr { cursor: pointer; }
    .editorial-feedback-table tbody tr:hover, .editorial-feedback-table tbody tr:focus-visible { background: #eef5ff; outline: 2px solid rgba(11, 87, 208, .2); outline-offset: -2px; }
    .editorial-feedback-table td { white-space: nowrap; }
    .editorial-feedback-table td:first-child { max-width: 190px; overflow-wrap: anywhere; white-space: normal; }
    .editorial-feedback-table td:last-child button { min-height: 32px; padding: 5px 8px; border: 1px solid var(--editorial-rule); background: var(--editorial-paper); color: var(--editorial-cobalt); font-size: 12px; white-space: nowrap; }
    .editorial-downloads-section { background: #fbfdff; }
    .editorial-download-groups { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 28px 36px; max-width: 1280px; margin: 0 auto; }
    .editorial-download-group { min-width: 0; padding-top: 16px; border-top: 2px solid var(--editorial-cobalt); }
    .editorial-download-group:nth-child(2) { border-top-color: var(--editorial-green); }
    .editorial-download-group:nth-child(3) { border-top-color: var(--editorial-amber); }
    .editorial-download-group:nth-child(4) { border-top-color: var(--editorial-green); }
    .editorial-download-group h3 { margin: 0 0 12px; font-size: 18px; }
    .editorial-download-links { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .editorial-download-link { display: grid; gap: 5px; min-width: 0; padding: 11px 12px; border: 1px solid var(--editorial-rule); background: var(--editorial-paper); color: var(--editorial-ink); text-decoration: none; }
    .editorial-download-link:hover, .editorial-download-link:focus-visible { border-color: var(--editorial-cobalt); outline: 2px solid rgba(11, 87, 208, .16); outline-offset: 2px; }
    .editorial-download-link span { color: var(--editorial-muted); font-size: 11px; font-weight: 650; }
    .editorial-download-link code { color: var(--editorial-cobalt); font-size: 12px; overflow-wrap: anywhere; }

    .editorial-run-status-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0; max-width: 1280px; margin: 0 auto 28px; border-top: 1px solid var(--editorial-rule); border-bottom: 1px solid var(--editorial-rule); }
.editorial-run-status-strip > div { min-width: 0; padding: 15px 18px; border-right: 1px solid var(--editorial-rule); }
.editorial-run-status-strip > div:last-child { border-right: 0; }
.editorial-run-status-strip strong, .editorial-run-status-strip code, .editorial-run-status-value { display: block; overflow-wrap: anywhere; }
.editorial-run-status-strip strong { margin-bottom: 6px; color: var(--editorial-muted); font-size: 12px; font-weight: 650; }
.editorial-run-status-strip code { color: var(--editorial-ink); font-size: 12px; }
.editorial-run-status-value { color: var(--editorial-green); font-weight: 700; }
.editorial-run-accounting-grid { grid-template-columns: minmax(210px, .8fr) repeat(2, minmax(0, 1fr)); margin-bottom: 32px; }
.editorial-run-summary-heading { min-width: 0; padding: 20px; border-right: 1px solid var(--editorial-rule); }
.editorial-run-summary-heading h2, .editorial-run-funnel h2, .editorial-run-coverage h2, .editorial-run-contract-grid h2 { margin: 0 0 9px; font-size: 21px; line-height: 1.25; }
.editorial-run-summary-heading p, .editorial-run-contract-grid p, .editorial-run-coverage p { margin: 0; color: var(--editorial-muted); font-size: 13px; line-height: 1.6; }
.editorial-run-accounting-grid article { border-right: 1px solid var(--editorial-rule); }
.editorial-run-accounting-grid article:last-child { border-right: 0; }
.editorial-run-accounting-grid article h3 { margin-bottom: 8px; font-size: 16px; }
.editorial-run-accounting-grid article > p { margin: 0 0 12px; color: var(--editorial-muted); font-size: 12px; }
.editorial-run-accounting-value { display: block; margin-bottom: 4px; color: var(--editorial-ink); font-size: 27px; line-height: 1.1; }
.editorial-run-funnel, .editorial-run-coverage, .editorial-run-contract-grid { max-width: 1280px; margin: 0 auto 32px; }
.editorial-run-funnel-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border-top: 1px solid var(--editorial-rule); border-bottom: 1px solid var(--editorial-rule); }
.editorial-run-funnel-grid article { min-width: 0; padding: 17px 18px; border-right: 1px solid var(--editorial-rule); }
.editorial-run-funnel-grid article:last-child { border-right: 0; }
.editorial-run-funnel-grid strong { display: block; margin-bottom: 6px; font-size: 25px; }
.editorial-run-funnel-grid span { display: block; color: var(--editorial-muted); font-size: 12px; line-height: 1.4; }
.editorial-run-coverage { display: grid; grid-template-columns: minmax(230px, .7fr) minmax(0, 1.3fr); gap: 24px; padding: 20px 0; border-top: 1px solid var(--editorial-rule); border-bottom: 1px solid var(--editorial-rule); }
.editorial-run-coverage > div > code { display: inline-block; margin-top: 14px; color: var(--editorial-cobalt); font-size: 19px; font-weight: 700; }
.editorial-run-coverage ul { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 0; padding: 0; list-style: none; }
.editorial-run-coverage li { min-width: 0; padding: 13px; border-top: 2px solid var(--editorial-cobalt); background: var(--editorial-cool-paper); color: var(--editorial-muted); font-size: 12px; }
.editorial-run-coverage li strong { display: block; margin-bottom: 4px; color: var(--editorial-ink); font-size: 20px; }
.editorial-run-contract-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.editorial-run-contract-grid article { min-width: 0; padding-top: 17px; border-top: 2px solid var(--editorial-cobalt); }
.editorial-run-contract-grid article:last-child { border-top-color: var(--editorial-amber); }
.editorial-run-contract-grid .editorial-artifact-list ul { max-height: 150px; }
.editorial-run-two-column { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; max-width: 1280px; margin: 0 auto 28px; }
.editorial-run-table-block { min-width: 0; max-width: 1280px; margin: 0 auto 28px; }
.editorial-run-two-column .editorial-run-table-block { width: 100%; margin: 0; }
.editorial-run-table-block h2, .editorial-run-message-heading h2 { margin: 0 0 13px; font-size: 21px; line-height: 1.25; }
.editorial-run-table-block table { width: 100%; border-collapse: collapse; color: var(--editorial-ink); font-size: 13px; }
.editorial-run-table-block th, .editorial-run-table-block td { min-width: 0; padding: 11px 12px; border-top: 1px solid var(--editorial-rule); text-align: left; vertical-align: top; overflow-wrap: anywhere; }
.editorial-run-table-block thead th { color: var(--editorial-muted); font-size: 12px; font-weight: 650; }
.editorial-run-table-block tbody th { font-weight: 650; }
.editorial-run-table-block td { color: var(--editorial-ink); }
.editorial-run-table-block th span { display: inline; }
.editorial-run-table-block td code, .editorial-run-table-block th code { overflow-wrap: anywhere; }
.editorial-run-table-block .editorial-table-note { margin: 10px 0 0; color: var(--editorial-muted); font-size: 12px; }
.editorial-run-message-heading { max-width: 1280px; margin: 38px auto 16px; }
.editorial-run-message-heading p { margin: 0; color: var(--editorial-muted); font-size: 13px; }
.editorial-authoritative-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; max-width: 1280px; margin: 0 auto; }
.editorial-authoritative-message { min-width: 0; padding: 18px; border-top: 3px solid var(--editorial-cobalt); background: var(--editorial-paper); }
.editorial-authoritative-message:nth-child(2) { border-top-color: var(--editorial-green); }
.editorial-authoritative-message:nth-child(3) { border-top-color: var(--editorial-amber); }
.editorial-authoritative-message header { margin-bottom: 13px; }
.editorial-authoritative-message header code { color: var(--editorial-muted); font-size: 12px; }
.editorial-authoritative-message header h3 { margin-top: 6px; font-size: 18px; overflow-wrap: anywhere; }
.editorial-authoritative-message dd { color: var(--editorial-ink); }
.editorial-authoritative-body { margin-top: 17px; padding-top: 13px; border-top: 1px solid var(--editorial-rule); color: var(--editorial-muted); font-size: 13px; }
.editorial-authoritative-body p { margin: 0 0 10px; line-height: 1.65; }
.editorial-run-exposure-summary { max-width: 1280px; margin: 0 auto 28px; }
.editorial-run-exposure-summary h2 { margin: 0 0 13px; font-size: 21px; }
.editorial-run-exposure-summary-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); border-top: 1px solid var(--editorial-rule); border-bottom: 1px solid var(--editorial-rule); }
.editorial-run-exposure-summary-grid article { min-width: 0; padding: 16px; border-right: 1px solid var(--editorial-rule); }
.editorial-run-exposure-summary-grid article:last-child { border-right: 0; }
.editorial-run-exposure-summary-grid code { display: block; margin-bottom: 7px; color: var(--editorial-muted); font-size: 12px; overflow-wrap: anywhere; }
.editorial-run-exposure-summary-grid strong { display: block; margin-bottom: 5px; font-size: 25px; }
.editorial-run-exposure-summary-grid span { display: block; color: var(--editorial-muted); font-size: 12px; line-height: 1.4; }
.editorial-overlap-list { display: grid; gap: 0; margin: 0; padding: 0; list-style: none; }
.editorial-overlap-list li { display: flex; justify-content: space-between; gap: 12px; padding: 12px; border-top: 1px solid var(--editorial-rule); color: var(--editorial-muted); }
.editorial-overlap-list strong { color: var(--editorial-ink); }
.editorial-table-scroll { max-width: 100%; overflow-x: auto; }
.editorial-run-table-heading { display: flex; align-items: end; justify-content: space-between; gap: 24px; margin-bottom: 15px; }
.editorial-run-table-heading p { margin: 0; color: var(--editorial-muted); font-size: 13px; }
.editorial-run-table-heading label { display: grid; gap: 6px; min-width: min(300px, 100%); color: var(--editorial-muted); font-size: 12px; font-weight: 650; }
.editorial-run-table-heading select { width: 100%; min-width: 0; padding: 8px 10px; border: 1px solid var(--editorial-rule); background: var(--editorial-paper); color: var(--editorial-ink); }
.editorial-pagination { display: flex; align-items: center; justify-content: flex-end; gap: 12px; margin-top: 14px; }
.editorial-pagination button { min-height: 38px; padding: 7px 12px; border: 1px solid var(--editorial-rule); background: var(--editorial-paper); color: var(--editorial-ink); }
.editorial-pagination button:disabled { cursor: not-allowed; opacity: .42; }
.editorial-pagination output { min-width: 145px; color: var(--editorial-muted); font-size: 12px; text-align: center; }
.editorial-run-batch-block { margin-top: 36px; }
.editorial-run-section code { overflow-wrap: anywhere; }

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
  .editorial-rule-grid, .editorial-responsibility-grid, .editorial-feedback-grid, .editorial-drawer-decision-grid, .editorial-drawer-context-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.editorial-trace-summary-grid { grid-template-columns: 1fr; }
.editorial-trace-summary-card { border-right: 0; border-bottom: 1px solid var(--editorial-rule); }
.editorial-trace-summary-card:last-child { border-bottom: 0; }
.editorial-trace-filters { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.editorial-trace-sensitivity-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.editorial-trace-sensitivity-grid article:nth-child(2n) { border-right: 0; }
.editorial-trace-sensitivity-grid article:nth-child(-n + 2) { border-bottom: 1px solid var(--editorial-rule); }
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
@media (max-width: 820px) {
  .editorial-run-status-strip, .editorial-run-funnel-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .editorial-feedback-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .editorial-feedback-summary article:nth-child(2n) { border-right: 0; }
      .editorial-feedback-summary article:nth-child(-n + 4) { border-bottom: 1px solid var(--editorial-rule); }
      .editorial-download-groups { grid-template-columns: 1fr; }
  .editorial-run-status-strip > div:nth-child(2), .editorial-run-funnel-grid article:nth-child(2) { border-right: 0; }
  .editorial-run-status-strip > div:nth-child(-n + 2), .editorial-run-funnel-grid article:nth-child(-n + 2) { border-bottom: 1px solid var(--editorial-rule); }
  .editorial-run-accounting-grid { grid-template-columns: 1fr; }
  .editorial-run-summary-heading, .editorial-run-accounting-grid article { border-right: 0; border-bottom: 1px solid var(--editorial-rule); }
  .editorial-run-accounting-grid article:last-child { border-bottom: 0; }
  .editorial-run-coverage { grid-template-columns: 1fr; }
  .editorial-run-coverage ul { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .editorial-authoritative-grid { grid-template-columns: 1fr; }
  .editorial-run-exposure-summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .editorial-run-exposure-summary-grid article:nth-child(2n) { border-right: 0; }
  .editorial-run-exposure-summary-grid article:nth-child(-n + 4) { border-bottom: 1px solid var(--editorial-rule); }
}
@media (max-width: 680px) {
  .editorial-brand { min-width: 0; max-width: 220px; white-space: normal; font-size: 16px; line-height: 1.2; }
  .editorial-run-status-strip, .editorial-run-funnel-grid, .editorial-run-coverage ul, .editorial-run-exposure-summary-grid { grid-template-columns: 1fr; }
      .editorial-feedback-summary { grid-template-columns: 1fr; }
      .editorial-feedback-summary article { border-right: 0; border-bottom: 1px solid var(--editorial-rule); }
      .editorial-feedback-summary article:last-child { border-bottom: 0; }
      .editorial-feedback-filters { grid-template-columns: 1fr; }
      .editorial-download-links { grid-template-columns: 1fr; }
  .editorial-run-status-strip > div, .editorial-run-funnel-grid article, .editorial-run-exposure-summary-grid article { border-right: 0; border-bottom: 1px solid var(--editorial-rule); }
  .editorial-run-status-strip > div:last-child, .editorial-run-funnel-grid article:last-child, .editorial-run-exposure-summary-grid article:last-child { border-bottom: 0; }
  .editorial-run-two-column, .editorial-run-contract-grid { grid-template-columns: 1fr; }
.editorial-drawer-identity, .editorial-drawer-decision-grid, .editorial-drawer-context-grid { grid-template-columns: 1fr; }
.editorial-trace-filters, .editorial-trace-sensitivity-grid { grid-template-columns: 1fr; }
.editorial-trace-sensitivity-grid article { border-right: 0; border-bottom: 1px solid var(--editorial-rule); }
.editorial-trace-sensitivity-grid article:last-child { border-bottom: 0; }
.editorial-trace-pagination { grid-template-columns: 1fr 1fr; align-items: center; }
.editorial-trace-pagination label { grid-column: 1 / -1; }
.editorial-trace-page-numbers { grid-column: 1 / -1; grid-row: 3; }
.editorial-trace-pagination output { grid-column: 1 / -1; grid-row: 4; }
  .editorial-run-table-heading { display: grid; align-items: start; gap: 14px; }
  .editorial-run-table-heading label { min-width: 0; }
  .editorial-pagination { justify-content: space-between; gap: 6px; }
  .editorial-pagination output { min-width: 0; }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: .01ms !important; animation-iteration-count: 1 !important; scroll-behavior: auto !important; transition-duration: .01ms !important; }
}
"""


_EDITORIAL_V2_CSS = r"""
.editorial-report[data-editorial-version="v2"] .editorial-figure > img { background: #f8fafc; }
.editorial-report[data-editorial-version="v2"] .editorial-hotspot-layer {
  position: static;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 8px;
  width: auto;
  height: auto;
  aspect-ratio: auto;
  padding-top: 10px;
}
.editorial-report[data-editorial-version="v2"] .editorial-hotspot {
  position: static;
  min-width: 0;
  max-width: none;
  min-height: 56px;
  box-shadow: none;
}
.editorial-legend-v2 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  border: 1px solid var(--editorial-rule);
  background: var(--editorial-rule);
  color: var(--editorial-ink);
}
.editorial-legend-v2 .editorial-legend-item {
  display: grid;
  grid-template-columns: 58px minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  min-width: 0;
  min-height: 54px;
  padding: 10px 14px;
  background: var(--editorial-paper);
}
.editorial-legend-v2 .editorial-legend-item:last-child:nth-child(odd) { grid-column: 1 / -1; }
.editorial-legend-v2 .editorial-legend-label {
  display: block;
  min-width: 0;
  color: var(--editorial-ink);
  font-weight: 600;
  line-height: 1.35;
}
.editorial-mark {
  --mark-color: var(--editorial-ink);
  position: relative;
  display: block;
  width: 52px;
  height: 28px;
  color: var(--mark-color);
  flex: none;
}
.editorial-mark b { position: absolute; display: block; box-sizing: border-box; }
.editorial-mark-cobalt { --mark-color: #175cd3; }
.editorial-mark-green { --mark-color: #00875a; }
.editorial-mark-amber { --mark-color: #c76a00; }
.editorial-mark-channel::before {
  position: absolute;
  top: 13px;
  right: 7px;
  left: 5px;
  height: 3px;
  background: var(--mark-color);
  content: "";
}
.editorial-mark-channel::after {
  position: absolute;
  top: 8px;
  right: 1px;
  border-top: 6px solid transparent;
  border-bottom: 6px solid transparent;
  border-left: 8px solid var(--mark-color);
  content: "";
}
.editorial-mark-channel b:nth-child(1), .editorial-mark-channel b:nth-child(2) {
  top: 8px;
  width: 11px;
  height: 11px;
  border: 2px solid var(--mark-color);
  border-radius: 50%;
  background: var(--editorial-paper);
}
.editorial-mark-channel b:nth-child(1) { left: 4px; background: var(--mark-color); }
.editorial-mark-channel b:nth-child(2) { left: 25px; }
.editorial-mark-sample::before, .editorial-mark-sample::after {
  position: absolute;
  top: 3px;
  width: 7px;
  height: 22px;
  border-top: 2px solid var(--editorial-ink);
  border-bottom: 2px solid var(--editorial-ink);
  content: "";
}
.editorial-mark-sample::before { left: 2px; border-left: 2px solid var(--editorial-ink); }
.editorial-mark-sample::after { right: 2px; border-right: 2px solid var(--editorial-ink); }
.editorial-mark-sample b { width: 7px; height: 7px; border: 1.5px solid var(--editorial-ink); border-radius: 50%; }
.editorial-mark-sample b:nth-child(1) { top: 7px; left: 14px; }
.editorial-mark-sample b:nth-child(2) { top: 15px; left: 25px; }
.editorial-mark-sample b:nth-child(3) { top: 7px; left: 36px; }
.editorial-mark-eligible-pair::before { position: absolute; top: 13px; left: 10px; width: 34px; height: 3px; background: #175cd3; content: ""; }
.editorial-mark-eligible-pair b:nth-child(1) { top: 7px; left: 1px; width: 14px; height: 14px; border: 2px solid #5b6878; border-radius: 50%; background: var(--editorial-paper); }
.editorial-mark-eligible-pair b:nth-child(2) { top: 6px; left: 25px; width: 15px; height: 15px; border: 2px solid #175cd3; background: var(--editorial-paper); }
.editorial-mark-eligible-pair b:nth-child(3) { top: 10px; right: 1px; width: 8px; height: 8px; border-radius: 50%; background: #175cd3; }
.editorial-mark-queue::before { position: absolute; top: 13px; right: 2px; left: 2px; height: 3px; background: #175cd3; content: ""; }
.editorial-mark-queue b { top: 8px; width: 12px; height: 12px; border: 2px solid #5b6878; border-radius: 50%; background: var(--editorial-paper); }
.editorial-mark-queue b:nth-child(1) { left: 5px; }
.editorial-mark-queue b:nth-child(2) { left: 21px; }
.editorial-mark-queue b:nth-child(3) { left: 37px; }
.editorial-mark-gate::before { position: absolute; top: 2px; left: 14px; width: 25px; height: 24px; border: 2px solid var(--editorial-rule); background: var(--editorial-paper); content: ""; }
.editorial-mark-gate b:nth-child(1) { top: 7px; left: 20px; width: 12px; height: 14px; border-top: 2px solid #5b6878; border-right: 2px solid #5b6878; transform: rotate(45deg) skew(-8deg, -8deg); }
.editorial-mark-gate b:nth-child(2) { top: 6px; left: 35px; width: 2px; height: 17px; background: #5b6878; }
.editorial-mark-decision-pair::before, .editorial-mark-decision-pair::after { position: absolute; left: 6px; width: 38px; height: 0; content: ""; }
.editorial-mark-decision-pair::before { top: 8px; border-top: 3px solid var(--mark-color); }
.editorial-mark-decision-pair::after { top: 21px; border-top: 3px dashed var(--mark-color); }
.editorial-mark-decision-pair b:nth-child(1) { top: 4px; right: 0; width: 10px; height: 10px; border-radius: 50%; background: var(--mark-color); }
.editorial-mark-decision-pair b:nth-child(2) { top: 17px; right: 0; width: 10px; height: 10px; border: 2px solid var(--mark-color); border-radius: 50%; background: var(--editorial-paper); }
.editorial-mark-seed b:nth-child(1) { top: 4px; left: 15px; width: 21px; height: 21px; border: 3px solid #175cd3; border-radius: 50%; background: #175cd3; }
.editorial-mark-network::before, .editorial-mark-network::after { position: absolute; top: 13px; left: 7px; width: 38px; height: 2px; background: #00875a; content: ""; }
.editorial-mark-network::before { transform: rotate(24deg); }
.editorial-mark-network::after { transform: rotate(-24deg); }
.editorial-mark-network b { border: 2px solid #00875a; border-radius: 50%; background: var(--editorial-paper); }
.editorial-mark-network b:nth-child(1) { top: 7px; left: 20px; width: 15px; height: 15px; background: #00875a; }
.editorial-mark-network b:nth-child(2) { top: 1px; left: 1px; width: 12px; height: 12px; }
.editorial-mark-network b:nth-child(3) { right: 1px; bottom: 1px; width: 12px; height: 12px; }
.editorial-mark-ordinary b:nth-child(1) { top: 4px; left: 15px; width: 21px; height: 21px; border: 3px solid var(--editorial-ink); border-radius: 50%; background: var(--editorial-paper); }
.editorial-mark-top20::before { position: absolute; top: 13px; right: 2px; left: 2px; height: 3px; background: #175cd3; content: ""; }
.editorial-mark-top20::after { position: absolute; top: 3px; right: 3px; width: 18px; height: 20px; border-right: 2px solid var(--editorial-ink); border-bottom: 2px solid var(--editorial-ink); border-left: 2px solid var(--editorial-ink); content: ""; }
.editorial-mark-top20 b { top: 8px; width: 11px; height: 11px; border: 2px solid #5b6878; border-radius: 50%; background: var(--editorial-paper); }
.editorial-mark-top20 b:nth-child(1) { left: 5px; }
.editorial-mark-top20 b:nth-child(2) { left: 19px; }
.editorial-mark-top20 b:nth-child(3) { left: 33px; }
.editorial-mark-overlap::before, .editorial-mark-overlap::after { position: absolute; right: 2px; left: 2px; height: 3px; content: ""; }
.editorial-mark-overlap::before { top: 6px; background: #175cd3; }
.editorial-mark-overlap::after { top: 20px; background: #00875a; }
.editorial-mark-overlap b:nth-child(1), .editorial-mark-overlap b:nth-child(2) { left: 22px; width: 11px; height: 11px; border: 2px solid #5b6878; border-radius: 50%; background: var(--editorial-paper); }
.editorial-mark-overlap b:nth-child(1) { top: 1px; }
.editorial-mark-overlap b:nth-child(2) { top: 15px; }
.editorial-mark-overlap b:nth-child(3) { top: 8px; left: 26px; width: 2px; height: 12px; background: #5b6878; }
.editorial-mark-single-exposure::before { position: absolute; top: 13px; right: 3px; left: 2px; height: 3px; background: #5b6878; content: ""; }
.editorial-mark-single-exposure b:nth-child(1) { top: 5px; left: 15px; width: 18px; height: 18px; border: 2px solid #5b6878; background: var(--editorial-paper); }
.editorial-mark-single-exposure b:nth-child(2) { top: 7px; right: 1px; width: 14px; height: 14px; border-radius: 50%; background: #5b6878; }
.editorial-mark-primary::before, .editorial-mark-shadow::before { position: absolute; top: 13px; right: 6px; left: 3px; height: 0; content: ""; }
.editorial-mark-primary::before { border-top: 3px solid #5b6878; }
.editorial-mark-shadow::before { border-top: 3px dashed #5b6878; }
.editorial-mark-primary b:nth-child(1), .editorial-mark-shadow b:nth-child(1) { top: 7px; right: 0; width: 15px; height: 15px; border: 3px solid #5b6878; border-radius: 50%; }
.editorial-mark-primary b:nth-child(1) { background: #5b6878; }
.editorial-mark-shadow b:nth-child(1) { background: var(--editorial-paper); }
.editorial-mark-propagating { background: linear-gradient(#175cd3, #175cd3) 2px 5px / 44px 3px no-repeat, linear-gradient(#00875a, #00875a) 2px 13px / 44px 3px no-repeat, linear-gradient(#c76a00, #c76a00) 2px 21px / 44px 3px no-repeat; }
.editorial-mark-propagating b { left: 24px; width: 8px; height: 8px; border-radius: 50%; }
.editorial-mark-propagating b:nth-child(1) { top: 2px; background: #175cd3; }
.editorial-mark-propagating b:nth-child(2) { top: 10px; background: #00875a; }
.editorial-mark-propagating b:nth-child(3) { top: 18px; background: #c76a00; }
.editorial-mark-dedup::before, .editorial-mark-dedup::after { position: absolute; left: 12px; width: 22px; height: 2px; background: #5b6878; content: ""; }
.editorial-mark-dedup::before { top: 8px; transform: rotate(18deg); }
.editorial-mark-dedup::after { bottom: 8px; transform: rotate(-18deg); }
.editorial-mark-dedup b:nth-child(1), .editorial-mark-dedup b:nth-child(2) { left: 1px; width: 11px; height: 11px; border: 2px solid #5b6878; border-radius: 50%; background: var(--editorial-paper); }
.editorial-mark-dedup b:nth-child(1) { top: 1px; }
.editorial-mark-dedup b:nth-child(2) { bottom: 1px; }
.editorial-mark-dedup b:nth-child(3) { top: 5px; right: 1px; width: 19px; height: 19px; border: 5px double #5b6878; border-radius: 50%; background: var(--editorial-paper); }
.editorial-mark-reranking { background: linear-gradient(#175cd3, #175cd3) 2px 5px / 48px 3px no-repeat, linear-gradient(#00875a, #00875a) 2px 13px / 48px 3px no-repeat, linear-gradient(#c76a00, #c76a00) 2px 21px / 48px 3px no-repeat; }
.editorial-mark-reranking::after { position: absolute; top: 1px; right: 2px; width: 17px; height: 25px; border-right: 2px solid var(--editorial-ink); border-bottom: 2px solid var(--editorial-ink); border-left: 2px solid var(--editorial-ink); content: ""; }
.editorial-mark-reranking b { left: 10px; width: 9px; height: 9px; border: 2px solid #5b6878; border-radius: 50%; background: var(--editorial-paper); }
.editorial-mark-reranking b:nth-child(1) { top: 2px; }
.editorial-mark-reranking b:nth-child(2) { top: 10px; }
.editorial-mark-reranking b:nth-child(3) { top: 18px; }
.editorial-mark-no-feedback::before { position: absolute; top: 13px; right: 14px; left: 3px; border-top: 3px dashed #5b6878; content: ""; }
.editorial-mark-no-feedback::after { position: absolute; top: 4px; right: 12px; width: 3px; height: 21px; background: #5b6878; content: ""; }
.editorial-mark-no-feedback b:nth-child(1) { top: 6px; right: 0; width: 16px; height: 16px; border: 3px solid #5b6878; border-radius: 50%; background: var(--editorial-paper); }
@media (max-width: 680px) {
  .editorial-report[data-editorial-version="v2"] .editorial-hotspot-layer,
  .editorial-legend-v2 { grid-template-columns: 1fr; }
  .editorial-legend-v2 .editorial-legend-item { min-height: 50px; padding: 9px 11px; }
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
  const drawerIdentity = drawer?.querySelector('[data-testid="drawer-identity"]');
  const drawerTabButtons = [...(drawer?.querySelectorAll('[data-drawer-tab]') || [])];
  const drawerPanels = [...(drawer?.querySelectorAll('[data-drawer-panel]') || [])];
  const closeButton = drawer?.querySelector('[data-testid="editorial-drawer-close"]');
  const mechanismButtons = [...root.querySelectorAll('[data-mechanism-key]')];
  const exposureRowsData = root.querySelector('[data-testid="run-exposure-rows-data"]');
  const exposureTableBody = root.querySelector('[data-testid="run-exposure-table-body"]');
  const exposureSelect = root.querySelector('[data-testid="run-exposure-message-select"]');
  const exposurePageStatus = root.querySelector('[data-testid="run-exposure-page-status"]');
  const feedbackDataElement = root.querySelector('[data-testid="run-feedback-data"]');
   const feedbackTableBody = root.querySelector('[data-testid="run-feedback-table-body"]');
   const feedbackMessageSelect = root.querySelector('[data-testid="run-feedback-message-select"]');
   const feedbackScopeSelect = root.querySelector('[data-testid="run-feedback-scope-select"]');
   const feedbackFilteredCount = root.querySelector('[data-testid="run-feedback-filtered-count"]');
   const exposurePageButtons = [...root.querySelectorAll('[data-run-exposure-page]')];
  const traceRowsData = root.querySelector('[data-testid="run-trace-rows-data"]');
  const traceLineageData = root.querySelector('[data-testid="run-trace-lineage-data"]');
  const traceTableBody = root.querySelector('[data-testid="run-trace-table-body"]');
  const traceEmpty = root.querySelector('[data-testid="run-trace-empty"]');
  const traceFilteredCount = root.querySelector('[data-testid="run-trace-filtered-count"]');
  const tracePageStatus = root.querySelector('[data-testid="run-trace-page-status"]');
  const tracePageNumbers = root.querySelector('[data-testid="run-trace-page-numbers"]');
  const tracePageSize = root.querySelector('[data-testid="run-trace-page-size"]');
  const traceFilters = {
    search: root.querySelector('[data-testid="run-trace-search"]'),
    message: root.querySelector('[data-testid="run-trace-message-select"]'),
    class: root.querySelector('[data-testid="run-trace-class-select"]'),
    batch: root.querySelector('[data-testid="run-trace-batch-select"]'),
    action: root.querySelector('[data-testid="run-trace-action-select"]'),
    provider: root.querySelector('[data-testid="run-trace-provider-select"]'),
    disagreement: root.querySelector('[data-testid="run-trace-disagreement-select"]'),
  };
  let exposureRows = [];
  let feedbackData = { message_batch_count: 0, changed_message_batch_count: 0, flags: {}, per_message: [] };
   let traceRows = [];
  let traceLineage = [];
  try {
    exposureRows = exposureRowsData ? JSON.parse(exposureRowsData.textContent || '[]') : [];
     feedbackData = feedbackDataElement ? JSON.parse(feedbackDataElement.textContent || '{}') : feedbackData;
    traceRows = traceRowsData ? JSON.parse(traceRowsData.textContent || '[]') : [];
    traceLineage = traceLineageData ? JSON.parse(traceLineageData.textContent || '[]') : [];
  } catch (error) {
    exposureRows = [];
    traceRows = [];
    traceLineage = [];
    console.error('Persisted evidence rows could not be parsed', error);
  }
  const exposureState = { filter: 'all', page: 0, pageSize: 10 };
  const traceState = { search: '', message: 'all', class: 'all', batch: 'all', action: 'all', provider: 'all', disagreement: 'all', page: 0, pageSize: 25 };
  const state = { language: 'zh-CN', mode: 'mechanism', anchor: 'overview', drawerRecord: null, drawerTab: 'summary', returnFocus: null };
  let previousBodyOverflow = '';

  function copy(key) {
    return catalog[state.language][key] || key;
  }

  function syncHeaderOffset() {
    const height = Math.ceil(header?.getBoundingClientRect().height || 76);
    root.style.setProperty('--editorial-header-offset', `${height}px`);
    document.documentElement.style.setProperty('--editorial-header-offset', `${height}px`);
  }

  function renderExposurePage() {
    if (!exposureTableBody || !exposureSelect || !exposurePageStatus) return;
    const filtered = exposureState.filter === 'all'
      ? exposureRows
      : exposureRows.filter((row) => row.message_id === exposureState.filter);
    const pageCount = Math.max(1, Math.ceil(filtered.length / exposureState.pageSize));
    exposureState.page = Math.min(exposureState.page, pageCount - 1);
    const start = exposureState.page * exposureState.pageSize;
    const visibleRows = filtered.slice(start, start + exposureState.pageSize);
    exposureTableBody.replaceChildren();
    visibleRows.forEach((row) => {
      const tr = document.createElement('tr');
      tr.dataset.testid = `run-exposure-row-${row.message_id}-${row.time_step}`;
      tr.dataset.messageId = row.message_id;
      tr.dataset.timeStep = String(row.time_step);
      [
        row.title,
        String(row.time_step),
        String(row.selected_pairs),
        String(row.eligible_users),
        String(row.configured_capacity),
        String(row.below_delivery_capacity),
        String(row.cumulative_pairs),
      ].forEach((value) => {
        const td = document.createElement('td');
        td.textContent = value;
        tr.append(td);
      });
      exposureTableBody.append(tr);
    });
    const first = filtered.length ? start + 1 : 0;
    const last = Math.min(start + exposureState.pageSize, filtered.length);
    exposurePageStatus.textContent = `${copy('run.exposure.page')} ${exposureState.page + 1} / ${pageCount} · ${copy('run.exposure.rows')} ${first}-${last} / ${filtered.length}`;
    exposurePageButtons.forEach((button) => {
      button.disabled = button.dataset.runExposurePage === 'previous'
        ? exposureState.page === 0
        : exposureState.page >= pageCount - 1;
    });
  }

  function feedbackRowsForState() {
     const selectedMessage = feedbackMessageSelect?.value || 'all';
     const scope = feedbackScopeSelect?.value || 'changed';
     const rows = [];
     feedbackData.per_message.forEach((message) => {
       if (selectedMessage !== 'all' && message.message_id !== selectedMessage) return;
       message.batches.forEach((batch) => {
         if (scope === 'changed' && !batch.top_selection_changed) return;
         rows.push({ ...batch, message_id: message.message_id, message_title: message.title });
       });
     });
     return rows;
   }

   function renderFeedbackRows() {
     if (!feedbackTableBody) return;
     const rows = feedbackRowsForState();
     feedbackTableBody.replaceChildren();
     rows.forEach((row) => {
       const tr = document.createElement('tr');
       const feedbackKey = `${row.message_id}:${row.time_step}`;
       tr.tabIndex = 0;
       tr.dataset.testid = `run-feedback-row-${row.message_id}-${row.time_step}`;
       tr.dataset.feedbackKey = feedbackKey;
       tr.dataset.messageId = row.message_id;
       tr.dataset.timeStep = String(row.time_step);
       tr.setAttribute('aria-label', `${copy('run.feedback.details')}: ${feedbackKey}`);
       [
         `${row.message_id} · ${row.message_title}`,
         String(row.time_step),
         String(row.eligible_users),
         String(row.top_count),
         String(row.top_overlap_count),
         String(row.feedback_added_user_ids.length),
         String(row.feedback_removed_user_ids.length),
       ].forEach((value) => {
         const td = document.createElement('td');
         td.textContent = value;
         tr.append(td);
       });
       const detailCell = document.createElement('td');
       const detailButton = document.createElement('button');
       detailButton.type = 'button';
       detailButton.dataset.feedbackOpen = feedbackKey;
       detailButton.textContent = copy('run.feedback.details');
       detailCell.append(detailButton);
       tr.append(detailCell);
       feedbackTableBody.append(tr);
       if (state.drawerRecord?.kind === 'feedback' && state.drawerRecord.id === feedbackKey) state.returnFocus = tr;
     });
     if (feedbackFilteredCount) {
       feedbackFilteredCount.textContent = `${rows.length.toLocaleString()} ${copy('run.feedback.rows')}`;
     }
   }

   function filteredTraceRows() {
    const query = traceState.search.trim().toLowerCase();
    return traceRows.filter((row) => {
      const searchable = [row.trace_id, row.pair_id, row.message_id, row.message_title, row.user_id, row.latent_class, row.selection_reason]
        .join(' ')
        .toLowerCase();
      return (!query || searchable.includes(query))
        && (traceState.message === 'all' || row.message_id === traceState.message)
        && (traceState.class === 'all' || row.latent_class === traceState.class)
        && (traceState.batch === 'all' || String(row.time_step) === traceState.batch)
        && (traceState.action === 'all' || row.primary_action === traceState.action)
        && (traceState.provider === 'all' || row.provider_status === traceState.provider)
        && (traceState.disagreement === 'all'
          || (traceState.disagreement === 'yes' && row.disagreement)
          || (traceState.disagreement === 'no' && !row.disagreement));
    });
  }

  function tracePageTokens(pageCount, currentPage) {
    if (pageCount <= 7) return Array.from({ length: pageCount }, (_, index) => index);
    const pages = new Set([0, pageCount - 1, currentPage, currentPage - 1, currentPage + 1]);
    const sorted = [...pages].filter((page) => page >= 0 && page < pageCount).sort((left, right) => left - right);
    const tokens = [];
    sorted.forEach((page, index) => {
      if (index && page - sorted[index - 1] > 1) tokens.push(null);
      tokens.push(page);
    });
    return tokens;
  }

  function renderTracePage() {
    if (!traceTableBody || !tracePageStatus || !tracePageNumbers) return;
    const filtered = filteredTraceRows();
    const pageCount = Math.max(1, Math.ceil(filtered.length / traceState.pageSize));
    traceState.page = Math.min(traceState.page, pageCount - 1);
    const start = traceState.page * traceState.pageSize;
    const visibleRows = filtered.slice(start, start + traceState.pageSize);
    traceTableBody.replaceChildren();
    visibleRows.forEach((row) => {
      const tr = document.createElement('tr');
      tr.tabIndex = 0;
      tr.dataset.testid = `run-trace-row-${row.trace_id}`;
      tr.dataset.traceId = row.trace_id;
      tr.dataset.messageId = row.message_id;
      tr.dataset.timeStep = String(row.time_step);
      tr.setAttribute('aria-controls', 'trace-drawer');
      tr.setAttribute('aria-label', `${copy('run.trace.open_row')}: ${row.trace_id}`);
      [
        `${row.message_id} · ${row.message_title}`,
        row.user_id,
        String(row.time_step),
        row.latent_class,
        row.primary_action,
        row.provider_status,
        row.disagreement ? 'yes' : 'no',
        String(row.ranking_position),
      ].forEach((value) => {
        const td = document.createElement('td');
        td.textContent = value;
        tr.append(td);
      });
      traceTableBody.append(tr);
      if (state.drawerRecord?.kind === 'trace' && state.drawerRecord.id === row.trace_id) state.returnFocus = tr;
    });
    if (traceEmpty) traceEmpty.hidden = filtered.length > 0;
    if (traceFilteredCount) traceFilteredCount.textContent = `${filtered.length.toLocaleString()} ${copy('run.trace.rows')}`;
    const first = filtered.length ? start + 1 : 0;
    const last = Math.min(start + traceState.pageSize, filtered.length);
    tracePageStatus.textContent = `${copy('run.exposure.page')} ${traceState.page + 1} / ${pageCount} · ${copy('run.trace.rows')} ${first}-${last} / ${filtered.length}`;
    tracePageNumbers.replaceChildren();
    tracePageTokens(pageCount, traceState.page).forEach((token) => {
      const button = document.createElement('button');
      button.type = 'button';
      if (token === null) {
        button.textContent = '…';
        button.disabled = true;
        button.setAttribute('aria-hidden', 'true');
      } else {
        button.textContent = String(token + 1);
        button.dataset.tracePage = String(token);
        button.setAttribute('aria-label', `${token === 0 ? copy('run.trace.first_page') : token === pageCount - 1 ? copy('run.trace.last_page') : copy('run.exposure.page')} ${token + 1}`);
        if (token === traceState.page) button.setAttribute('aria-current', 'page');
      }
      tracePageNumbers.append(button);
    });
    const previous = root.querySelector('[data-trace-page="previous"]');
    const next = root.querySelector('[data-trace-page="next"]');
    if (previous) previous.disabled = traceState.page === 0;
    if (next) next.disabled = traceState.page >= pageCount - 1;
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
    if (state.drawerRecord) renderDrawer();
        renderFeedbackRows();
    renderExposurePage();
    renderTracePage();
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

  function setActiveNavigation(anchor, { updateState = true } = {}) {
    if (updateState) state.anchor = anchor;
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
    if (state.drawerRecord && location.mode !== state.mode) closeDrawer(false);
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

  function appendText(parent, tag, text, className = '') {
    const element = document.createElement(tag);
    element.textContent = text == null ? '' : String(text);
    if (className) element.className = className;
    parent.append(element);
    return element;
  }

  function appendDefinitionList(parent, entries) {
    const list = document.createElement('dl');
    entries.forEach(([label, value]) => {
      const item = document.createElement('div');
      appendText(item, 'dt', copy(label));
      appendText(item, 'dd', value);
      list.append(item);
    });
    parent.append(list);
    return list;
  }

  function appendJsonBlock(parent, label, value) {
    const block = document.createElement('div');
    block.className = 'editorial-drawer-panel-block';
    appendText(block, 'strong', copy(label));
    const pre = document.createElement('pre');
    pre.textContent = JSON.stringify(value ?? {}, null, 2);
    block.append(pre);
    parent.append(block);
    return block;
  }

  function appendParagraphs(parent, text) {
    String(text || '').split(/\n\n+/).filter(Boolean).forEach((paragraph) => appendText(parent, 'p', paragraph));
  }

  function renderIdentity(items) {
    if (!drawerIdentity) return;
    drawerIdentity.replaceChildren();
    items.forEach(([label, value]) => {
      const article = document.createElement('article');
      appendText(article, 'strong', copy(label));
      appendText(article, 'span', value);
      drawerIdentity.append(article);
    });
  }

  function panelElement(name) {
    return drawerPanels.find((panel) => panel.dataset.drawerPanel === name);
  }

  function renderMechanismDrawer(detail) {
    renderIdentity([['drawer.identity', detail.title]]);
    const summary = panelElement('summary');
    const decision = panelElement('decision');
    const context = panelElement('context');
    const lineage = panelElement('lineage');
    [summary, decision, context, lineage].forEach((panel) => panel?.replaceChildren());
    if (!summary || !decision || !context || !lineage) return;
    summary.className = decision.className = context.className = lineage.className = 'editorial-drawer-panel';
    appendText(summary, 'h3', copy('drawer.tab.summary'));
    appendText(summary, 'p', detail.definition);
    appendDefinitionList(summary, [
      ['drawer.provenance', detail.provenance],
      ['drawer.usage', detail.usage],
      ['drawer.limitation', detail.limitation],
    ]);
    appendText(decision, 'h3', copy('drawer.tab.decision'));
    appendText(decision, 'p', detail.definition);
    appendText(decision, 'p', detail.limitation);
    appendText(context, 'h3', copy('drawer.tab.context'));
    appendText(context, 'p', detail.definition);
    appendText(context, 'p', detail.limitation);
    appendText(lineage, 'h3', copy('drawer.tab.lineage'));
    appendDefinitionList(lineage, [
      ['drawer.field_provenance', detail.provenance],
      ['drawer.field_usage_stage', detail.usage],
      ['drawer.aggregate_source', 'mechanism contract'],
    ]);
  }

  function renderTraceDrawer(trace) {
    renderIdentity([
      ['drawer.message', `${trace.message_id} · ${trace.message_title}`],
      ['drawer.user', trace.user_id],
      ['drawer.batch', trace.time_step],
      ['drawer.class', trace.latent_class],
      ['drawer.seed', trace.is_seed ? 'true' : 'false'],
      ['drawer.identity', trace.trace_id],
    ]);
    const summary = panelElement('summary');
    const decision = panelElement('decision');
    const context = panelElement('context');
    const lineage = panelElement('lineage');
    [summary, decision, context, lineage].forEach((panel) => panel?.replaceChildren());
    if (!summary || !decision || !context || !lineage) return;
    summary.className = decision.className = context.className = lineage.className = 'editorial-drawer-panel';
    appendText(summary, 'h3', copy('drawer.provider_terminal'));
    appendDefinitionList(summary, [
      ['drawer.provider_terminal', trace.provider_status],
      ['drawer.primary', `${trace.primary_status} · ${trace.primary_action}`],
      ['drawer.shadow', `${trace.shadow_status} · ${trace.shadow_action}`],
    ]);
    const outcome = document.createElement('div');
    outcome.className = 'editorial-drawer-panel-block';
    appendText(outcome, 'strong', copy('drawer.paired_outcome'));
    appendDefinitionList(outcome, [
      ['drawer.primary', `${trace.primary_action} · ${trace.primary_probability ?? 'n/a'}`],
      ['drawer.shadow', `${trace.shadow_action} · ${trace.shadow_probability ?? 'n/a'}`],
      ['drawer.disagreement', trace.disagreement ? 'engage difference' : 'no engage difference'],
      ['drawer.field_differences', trace.decision_difference ? 'persisted field difference' : copy('drawer.no_differences')],
    ]);
    summary.append(outcome);
    const ranking = document.createElement('div');
    ranking.className = 'editorial-drawer-panel-block';
    appendText(ranking, 'strong', copy('drawer.ranking_summary'));
    appendDefinitionList(ranking, [
      ['drawer.ranking_summary', `#${trace.ranking_position} · ${trace.personalized_delivery_score}`],
      ['drawer.source', trace.selection_reason],
    ]);
    summary.append(ranking);
    const boundary = document.createElement('div');
    boundary.className = 'editorial-callout editorial-callout-amber';
    appendText(boundary, 'strong', copy('drawer.prompt_boundary'));
    appendText(boundary, 'p', copy('drawer.not_in_prompt'));
    summary.append(boundary);

    appendText(decision, 'h3', copy('drawer.tab.decision'));
    const decisionGrid = document.createElement('div');
    decisionGrid.className = 'editorial-drawer-decision-grid';
    [['drawer.primary', trace.primary_status, trace.primary_action, trace.primary_probability, trace.primary_confidence, trace.primary_decision_source, trace.primary_prompt_version], ['drawer.shadow', trace.shadow_status, trace.shadow_action, trace.shadow_probability, trace.shadow_confidence, trace.shadow_decision_source, trace.shadow_prompt_version]].forEach(([label, status, action, probability, confidence, source, token]) => {
      const card = document.createElement('article');
      card.className = 'editorial-drawer-decision-card';
      appendText(card, 'h3', copy(label));
      appendDefinitionList(card, [
        ['drawer.status', status],
        ['drawer.action', action],
        ['drawer.probability', probability ?? 'n/a'],
        ['drawer.confidence', confidence ?? 'n/a'],
        ['drawer.source', source],
        ['drawer.prompt_token', token],
      ]);
      decisionGrid.append(card);
    });
    decision.append(decisionGrid);
    appendJsonBlock(decision, 'drawer.shadow', trace.shadow_added_fields);

    appendText(context, 'h3', copy('drawer.tab.context'));
    const message = document.createElement('div');
    message.className = 'editorial-drawer-message';
    appendText(message, 'h3', trace.message_title);
    appendText(message, 'p', copy('drawer.authoritative'));
    appendParagraphs(message, trace.message_body);
    context.append(message);
    appendDefinitionList(context, [
      ['drawer.primary_reason', trace.primary_reason],
      ['drawer.shadow_reason', trace.shadow_reason],
    ]);
    const contextGrid = document.createElement('div');
    contextGrid.className = 'editorial-drawer-context-grid';
    appendJsonBlock(contextGrid, 'drawer.primary_context', trace.primary_context);
    appendJsonBlock(contextGrid, 'drawer.shadow_context', trace.shadow_context);
    appendJsonBlock(contextGrid, 'drawer.peer_context', { primary: trace.primary_peer_context, shadow: trace.shadow_peer_context });
    context.append(contextGrid);

    appendText(lineage, 'h3', copy('drawer.tab.lineage'));
    const differences = document.createElement('div');
    differences.className = 'editorial-drawer-panel-block';
    appendText(differences, 'strong', copy('drawer.field_differences'));
    const differenceList = document.createElement('ul');
    differenceList.className = 'editorial-drawer-lineage-list';
    if (trace.field_differences.length) {
      trace.field_differences.forEach((difference) => {
        const item = document.createElement('li');
        appendText(item, 'code', difference.field_name || 'field');
        appendText(item, 'strong', difference.label || '');
        appendText(item, 'p', `${difference.primary_display || ''} → ${difference.shadow_display || ''}`);
        appendText(item, 'p', difference.note || '');
        differenceList.append(item);
      });
    } else {
      appendText(differences, 'p', copy('drawer.no_differences'));
    }
    differences.append(differenceList);
    lineage.append(differences);
    const lineageList = document.createElement('ul');
    lineageList.className = 'editorial-drawer-lineage-list';
    traceLineage.forEach((entry) => {
      const item = document.createElement('li');
      appendText(item, 'code', entry.field_name);
      appendText(item, 'strong', entry.label);
      appendText(item, 'p', `${copy('drawer.field_provenance')}: ${entry.source_artifact} · ${entry.evidence_class} · ${entry.prompt_visibility}`);
      appendText(item, 'p', `${copy('drawer.field_usage_stage')}: ${entry.usage_stages.join(' / ')}`);
      appendText(item, 'p', entry.description);
      lineageList.append(item);
    });
    lineage.append(lineageList);
    appendJsonBlock(lineage, 'drawer.aggregate_evidence', trace.aggregate_evidence);
    appendDefinitionList(lineage, [['drawer.aggregate_source', 'concurrent_message_diagnostics.json']]);
  }

  function appendIdList(parent, label, values) {
     const block = document.createElement('div');
     block.className = 'editorial-drawer-panel-block';
     appendText(block, 'strong', copy(label));
     if (!values.length) {
       appendText(block, 'p', copy('drawer.feedback_no_ids'));
       parent.append(block);
       return block;
     }
     const list = document.createElement('ul');
     list.className = 'editorial-drawer-lineage-list';
     values.forEach((value) => {
       const item = document.createElement('li');
       appendText(item, 'code', value);
       list.append(item);
     });
     block.append(list);
     parent.append(block);
     return block;
   }

   function renderFeedbackDrawer(batch) {
     renderIdentity([
       ['drawer.feedback_batch', `${batch.message_id} · ${batch.message_title} · ${copy('run.feedback.batch')} ${batch.time_step}`],
       ['run.feedback.eligible', batch.eligible_users],
       ['run.feedback.overlap', `${batch.top_overlap_count} / ${batch.top_count}`],
       ['run.feedback.added', batch.feedback_added_user_ids.length],
       ['run.feedback.removed', batch.feedback_removed_user_ids.length],
       ['drawer.feedback_source', 'concurrent_campaign_diagnostics.json'],
     ]);
     const summary = panelElement('summary');
     const decision = panelElement('decision');
     const context = panelElement('context');
     const lineage = panelElement('lineage');
     [summary, decision, context, lineage].forEach((panel) => panel?.replaceChildren());
     if (!summary || !decision || !context || !lineage) return;
     summary.className = decision.className = context.className = lineage.className = 'editorial-drawer-panel';
     appendText(summary, 'h3', copy('drawer.feedback_summary'));
     appendDefinitionList(summary, [
       ['run.feedback.batch', batch.time_step],
       ['run.feedback.eligible', batch.eligible_users],
       ['run.feedback.top_count', batch.top_count],
       ['run.feedback.overlap', `${batch.top_overlap_count} / ${batch.top_count}`],
       ['run.feedback.added', batch.feedback_added_user_ids.length],
       ['run.feedback.removed', batch.feedback_removed_user_ids.length],
     ]);
     appendText(summary, 'p', copy('run.feedback.descriptive'));

     appendText(decision, 'h3', copy('drawer.feedback_full_ranking'));
     appendIdList(decision, 'drawer.feedback_full_ranking', batch.full_ranking_top_user_ids);
     appendIdList(decision, 'drawer.feedback_no_feedback_ranking', batch.no_feedback_top_user_ids);
     appendIdList(decision, 'drawer.feedback_overlap_ids', batch.top_overlap_user_ids);

     appendText(context, 'h3', copy('drawer.tab.context'));
     appendIdList(context, 'drawer.feedback_added_ids', batch.feedback_added_user_ids);
     appendIdList(context, 'drawer.feedback_removed_ids', batch.feedback_removed_user_ids);
     appendText(context, 'p', copy('run.feedback.lead'));

     appendText(lineage, 'h3', copy('drawer.tab.lineage'));
     appendJsonBlock(lineage, 'drawer.feedback_source', feedbackData.flags);
     appendDefinitionList(lineage, [['drawer.feedback_source', 'concurrent_campaign_diagnostics.json']]);
   }

   function selectDrawerTab(tab, focus = false) {
    if (!['summary', 'decision', 'context', 'lineage'].includes(tab)) return;
    state.drawerTab = tab;
    drawerTabButtons.forEach((button) => {
      const selected = button.dataset.drawerTab === tab;
      button.setAttribute('aria-selected', String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
    drawerPanels.forEach((panel) => {
      panel.hidden = panel.dataset.drawerPanel !== tab;
    });
    if (focus) drawerTabButtons.find((button) => button.dataset.drawerTab === tab)?.focus();
  }

  function renderDrawer() {
    if (!drawer || !state.drawerRecord || !drawerTitle) return;
    if (state.drawerRecord.kind === 'trace') {
      const trace = traceRows.find((row) => row.trace_id === state.drawerRecord.id);
      if (!trace) return closeDrawer(false);
      drawerTitle.textContent = `${trace.message_id} · ${trace.user_id}`;
      renderTraceDrawer(trace);
        } else if (state.drawerRecord.kind === 'feedback') {
          const feedbackRecord = feedbackData.per_message.flatMap((message) => message.batches.map((batch) => ({ ...batch, message_id: message.message_id, message_title: message.title }))).find((row) => `${row.message_id}:${row.time_step}` === state.drawerRecord.id);
          if (!feedbackRecord) return closeDrawer(false);
          drawerTitle.textContent = `${feedbackRecord.message_id} · ${copy('run.feedback.batch')} ${feedbackRecord.time_step}`;
          renderFeedbackDrawer(feedbackRecord);
        } else {
      const detail = details[state.drawerRecord.key]?.[state.language];
      if (!detail) return closeDrawer(false);
      drawerTitle.textContent = detail.title;
      renderMechanismDrawer(detail);
    }
    selectDrawerTab(state.drawerTab);
  }

  function openDrawer(record, trigger) {
    const normalized = typeof record === 'string' ? { kind: 'mechanism', key: record } : record;
    if (!drawer || (normalized.kind === 'mechanism' && !details[normalized.key]?.[state.language]) || (normalized.kind === 'trace' && !traceRows.some((row) => row.trace_id === normalized.id)) || (normalized.kind === 'feedback' && !feedbackData.per_message.some((message) => message.batches.some((batch) => `${message.message_id}:${batch.time_step}` === normalized.id)))) return;
    state.drawerRecord = normalized;
    state.drawerTab = 'summary';
    state.returnFocus = trigger;
    renderDrawer();
    drawer.hidden = false;
    drawer.setAttribute('aria-hidden', 'false');
    root.dataset.drawerState = 'open';
    previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    mechanismButtons.forEach((button) => button.setAttribute('aria-expanded', String(button === trigger)));
    traceTableBody?.querySelectorAll('tr[data-trace-id]').forEach((row) => row.setAttribute('aria-expanded', String(row === trigger)));
       feedbackTableBody?.querySelectorAll('tr[data-feedback-key]').forEach((row) => row.setAttribute('aria-expanded', String(row === trigger)));
    closeButton?.focus();
  }

  function closeDrawer(restoreFocus = true) {
    if (!drawer) return;
    const returnFocus = state.returnFocus;
    drawer.hidden = true;
    drawer.setAttribute('aria-hidden', 'true');
    root.dataset.drawerState = 'closed';
    document.body.style.overflow = previousBodyOverflow;
    mechanismButtons.forEach((button) => button.setAttribute('aria-expanded', 'false'));
    traceTableBody?.querySelectorAll('tr[data-trace-id]').forEach((row) => row.removeAttribute('aria-expanded'));
       feedbackTableBody?.querySelectorAll('tr[data-feedback-key]').forEach((row) => row.removeAttribute('aria-expanded'));
    state.drawerRecord = null;
    state.returnFocus = null;
    drawerIdentity?.replaceChildren();
    drawerPanels.forEach((panel) => panel.replaceChildren());
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

  exposureSelect?.addEventListener('change', () => {
    exposureState.filter = exposureSelect.value;
    exposureState.page = 0;
    renderExposurePage();
  });
  exposurePageButtons.forEach((button) => button.addEventListener('click', () => {
    const direction = button.dataset.runExposurePage === 'next' ? 1 : -1;
    exposureState.page = Math.max(0, exposureState.page + direction);
    renderExposurePage();
  }));
  feedbackMessageSelect?.addEventListener('change', () => renderFeedbackRows());
   feedbackScopeSelect?.addEventListener('change', () => renderFeedbackRows());
   feedbackTableBody?.addEventListener('click', (event) => {
     const row = event.target.closest('tr[data-feedback-key]');
     if (row) openDrawer({ kind: 'feedback', id: row.dataset.feedbackKey }, row);
   });
   feedbackTableBody?.addEventListener('keydown', (event) => {
     if (!['Enter', ' '].includes(event.key)) return;
     const row = event.target.closest('tr[data-feedback-key]');
     if (!row) return;
     event.preventDefault();
     openDrawer({ kind: 'feedback', id: row.dataset.feedbackKey }, row);
   });
   const resetTracePage = () => {
    traceState.page = 0;
    renderTracePage();
  };
  traceFilters.search?.addEventListener('input', () => {
    traceState.search = traceFilters.search.value;
    resetTracePage();
  });
  [['message', traceFilters.message], ['class', traceFilters.class], ['batch', traceFilters.batch], ['action', traceFilters.action], ['provider', traceFilters.provider], ['disagreement', traceFilters.disagreement]].forEach(([key, control]) => {
    control?.addEventListener('change', () => {
      traceState[key] = control.value;
      resetTracePage();
    });
  });
  tracePageSize?.addEventListener('change', () => {
    traceState.pageSize = Number(tracePageSize.value) || 25;
    resetTracePage();
  });
  root.querySelector('[data-trace-page="previous"]')?.addEventListener('click', () => {
    traceState.page = Math.max(0, traceState.page - 1);
    renderTracePage();
  });
  root.querySelector('[data-trace-page="next"]')?.addEventListener('click', () => {
    traceState.page += 1;
    renderTracePage();
  });
  tracePageNumbers?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-trace-page]');
    if (!button) return;
    traceState.page = Number(button.dataset.tracePage);
    renderTracePage();
  });
  mechanismButtons.forEach((button) => button.addEventListener('click', () => openDrawer({ kind: 'mechanism', key: button.dataset.mechanismKey }, button)));
  traceTableBody?.addEventListener('click', (event) => {
    const row = event.target.closest('tr[data-trace-id]');
    if (row) openDrawer({ kind: 'trace', id: row.dataset.traceId }, row);
  });
  traceTableBody?.addEventListener('keydown', (event) => {
    if (!['Enter', ' '].includes(event.key)) return;
    const row = event.target.closest('tr[data-trace-id]');
    if (!row) return;
    event.preventDefault();
    openDrawer({ kind: 'trace', id: row.dataset.traceId }, row);
  });
  drawerTabButtons.forEach((button, index) => {
    button.addEventListener('click', () => selectDrawerTab(button.dataset.drawerTab, true));
    button.addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      event.preventDefault();
      const offset = event.key === 'ArrowRight' ? 1 : -1;
      const next = drawerTabButtons[(index + offset + drawerTabButtons.length) % drawerTabButtons.length];
      selectDrawerTab(next.dataset.drawerTab, true);
    });
  });
  closeButton?.addEventListener('click', () => closeDrawer(true));
  drawer?.querySelector('.editorial-drawer-backdrop')?.addEventListener('click', () => closeDrawer(true));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && state.drawerRecord) {
      event.preventDefault();
      closeDrawer(true);
      return;
    }
    if (event.key !== 'Tab' || !state.drawerRecord) return;
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
      if (state.drawerRecord) return;
      entries.forEach((entry) => {
        if (entry.isIntersecting && !entry.target.closest('[hidden]')) visibleSections.add(entry.target);
        else visibleSections.delete(entry.target);
      });
      const current = [...visibleSections]
        .filter((section) => !section.closest('[hidden]'))
        .sort((left, right) => Math.abs(left.getBoundingClientRect().top - 96) - Math.abs(right.getBoundingClientRect().top - 96))[0];
      if (current) setActiveNavigation(current.dataset.sectionAnchor, { updateState: !window.location.hash });
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
    <aside id="trace-drawer" class="editorial-detail-drawer" data-testid="evidence-drawer" role="dialog" aria-modal="true" aria-labelledby="trace-drawer-title" aria-hidden="true" hidden>
      <div class="editorial-drawer-backdrop" aria-hidden="true"></div>
      <div class="editorial-drawer-surface">
        <div class="editorial-drawer-header">
          <h2 id="trace-drawer-title" data-testid="mechanism-detail-title">{_copy('drawer.detail')}</h2>
          <button class="editorial-drawer-close" type="button" data-testid="editorial-drawer-close" aria-label="{_copy('drawer.close')}" data-i18n-aria-label="drawer.close">×</button>
        </div>
        <div class="editorial-drawer-body" data-testid="shared-drawer-body">
          <div class="editorial-drawer-identity" data-testid="drawer-identity"></div>
          <div class="editorial-drawer-tabs" role="tablist" aria-label="{_copy('drawer.tabs_aria')}" data-i18n-aria-label="drawer.tabs_aria">
            <button type="button" role="tab" id="drawer-tab-summary" aria-controls="drawer-panel-summary" aria-selected="true" data-drawer-tab="summary" data-i18n="drawer.tab.summary">{_copy('drawer.tab.summary')}</button>
            <button type="button" role="tab" id="drawer-tab-decision" aria-controls="drawer-panel-decision" aria-selected="false" tabindex="-1" data-drawer-tab="decision" data-i18n="drawer.tab.decision">{_copy('drawer.tab.decision')}</button>
            <button type="button" role="tab" id="drawer-tab-context" aria-controls="drawer-panel-context" aria-selected="false" tabindex="-1" data-drawer-tab="context" data-i18n="drawer.tab.context">{_copy('drawer.tab.context')}</button>
            <button type="button" role="tab" id="drawer-tab-lineage" aria-controls="drawer-panel-lineage" aria-selected="false" tabindex="-1" data-drawer-tab="lineage" data-i18n="drawer.tab.lineage">{_copy('drawer.tab.lineage')}</button>
          </div>
          <div class="editorial-drawer-panels">
            <section id="drawer-panel-summary" role="tabpanel" aria-labelledby="drawer-tab-summary" data-drawer-panel="summary"></section>
            <section id="drawer-panel-decision" role="tabpanel" aria-labelledby="drawer-tab-decision" data-drawer-panel="decision" hidden></section>
            <section id="drawer-panel-context" role="tabpanel" aria-labelledby="drawer-tab-context" data-drawer-panel="context" hidden></section>
            <section id="drawer-panel-lineage" role="tabpanel" aria-labelledby="drawer-tab-lineage" data-drawer-panel="lineage" hidden></section>
          </div>
        </div>
      </div>
    </aside>
  </main>
  <script>{script}</script>
</body>
</html>
"""


def _replace_v2_fragment(value: str, old: str, new: str, *, expected: int, label: str) -> str:
    actual = value.count(old)
    if actual != expected:
        raise ValueError(f"Editorial v2 could not replace frozen {label}: expected {expected}, found {actual}")
    return value.replace(old, new)


def _render_editorial_v2(payload: ConcurrentMessageReportPayload) -> str:
    """Render the private Editorial v2 presentation from the frozen v1 shell."""
    rendered = _render_editorial_candidate(payload)
    rendered = _replace_v2_fragment(
        rendered,
        'class="editorial-report" data-testid="editorial-report"',
        'class="editorial-report" data-testid="editorial-report" data-editorial-version="v2"',
        expected=1,
        label="root",
    )
    rendered = _replace_v2_fragment(
        rendered,
        f"<style>{_EDITORIAL_CSS}</style>",
        f"<style>{_EDITORIAL_CSS}{_EDITORIAL_V2_CSS}</style>",
        expected=1,
        label="stylesheet",
    )

    v1_catalog_json = json.dumps(_EDITORIAL_CATALOG, ensure_ascii=False, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    v2_catalog_json = json.dumps(_EDITORIAL_V2_CATALOG, ensure_ascii=False, separators=(",", ":")).replace(
        "</", "<\\/"
    )
    rendered = _replace_v2_fragment(
        rendered,
        v1_catalog_json,
        v2_catalog_json,
        expected=1,
        label="language catalog",
    )

    for asset_key, v2_asset in _EDITORIAL_V2_ASSET_CATALOG.items():
        v1_asset = _EDITORIAL_ASSET_CATALOG[asset_key]
        rendered = _replace_v2_fragment(
            rendered,
            v1_asset["file"],
            v2_asset["file"],
            expected=2,
            label=f"{asset_key} filename",
        )
        rendered = _replace_v2_fragment(
            rendered,
            v1_asset["source_sha256"],
            v2_asset["source_sha256"],
            expected=1,
            label=f"{asset_key} source hash",
        )
        rendered = _replace_v2_fragment(
            rendered,
            _embedded_asset(asset_key),
            _v2_embedded_asset(asset_key),
            expected=1,
            label=f"{asset_key} embedded media",
        )
        rendered = _replace_v2_fragment(
            rendered,
            _legend(_EDITORIAL_V1_LEGEND_ITEMS[asset_key]),
            _v2_legend(asset_key),
            expected=1,
            label=f"{asset_key} legend",
        )
    return rendered


# Alias stays private so tests and design validation can call the default Editorial
# seam without adding a public renderer selector or a persisted renderer token.
_render_editorial_report = _render_editorial_v2
