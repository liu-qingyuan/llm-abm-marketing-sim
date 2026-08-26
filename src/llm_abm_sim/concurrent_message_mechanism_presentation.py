from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

_SCHEMA_VERSION = "concurrent-message-mechanism-presentation-v1"
_FULL_POOL_SCHEMA_VERSION = "full-pool-mechanism-presentation-v1"
_FULL_POOL_TWO_STAGE_SCHEMA_VERSION = "full-pool-two-stage-mechanism-presentation-v1"
_SEMANTIC_SET_SCHEMA_VERSION = "mechanism-semantic-set-v1"
_LANE_ORDER = (
    "historical_data",
    "platform_recommendation",
    "simulated_user_decision",
)
_STABLE_ID = re.compile(r"[a-z][a-z0-9_]*")


@dataclass(frozen=True)
class _BilingualText:
    key: str
    zh_cn: str
    en_us: str

    def value(self, language: str) -> str:
        if language == "zh-CN":
            return self.zh_cn
        if language == "en-US":
            return self.en_us
        raise ValueError(f"unsupported mechanism presentation language: {language}")


_LANE_LABELS = {
    "historical_data": _BilingualText(
        "lane.historical_data",
        "历史数据层",
        "Historical Data Layer",
    ),
    "platform_recommendation": _BilingualText(
        "lane.platform_recommendation",
        "平台推荐层",
        "Platform Recommendation Layer",
    ),
    "simulated_user_decision": _BilingualText(
        "lane.simulated_user_decision",
        "模拟用户决策层",
        "Simulated User Decision Layer",
    ),
}


@dataclass(frozen=True)
class _MechanismNode:
    semantic_id: str
    label: _BilingualText
    lane: str
    stage: int
    shape: str = "rectangle"
    visual_role: str | None = None

    @property
    def label_key(self) -> str:
        return self.label.key


@dataclass(frozen=True)
class _MechanismEdge:
    semantic_id: str
    source: str
    target: str
    label: _BilingualText | None = None
    style: str = "solid"


@dataclass(frozen=True)
class _MechanismImageBrief:
    generate_raster: bool
    visual_system: str
    purpose: str
    composition: str
    required_marks: tuple[str, ...]
    forbidden_marks: tuple[str, ...]


@dataclass(frozen=True)
class _MechanismLanguageProjection:
    language: str
    keys: tuple[str, ...]
    values: tuple[str, ...]
    fallback_keys: tuple[str, ...]
    fallback_values: tuple[str, ...]

    def value(self, key: str) -> str:
        try:
            return self.values[self.keys.index(key)]
        except ValueError as exc:
            raise KeyError(key) from exc


@dataclass(frozen=True)
class _MechanismDiagram:
    diagram_id: str
    filename: str
    navigation_anchor: str
    title_key: str
    description_key: str
    lane_order: tuple[str, ...]
    stage_count: int
    node_budget: int
    nodes: tuple[_MechanismNode, ...]
    edges: tuple[_MechanismEdge, ...]
    projections: tuple[_MechanismLanguageProjection, ...]
    image_brief: _MechanismImageBrief


@dataclass(frozen=True)
class _MechanismArtifact:
    filename: str
    payload: bytes
    sha256: str


@dataclass(frozen=True)
class _MechanismPresentation:
    schema_version: str
    lane_order: tuple[str, ...]
    diagrams: tuple[_MechanismDiagram, ...]
    mermaid_artifacts: tuple[_MechanismArtifact, ...]
    semantic_set_identity_sha256: str


@dataclass(frozen=True)
class _DiagramDefinition:
    diagram_id: str
    filename: str
    navigation_anchor: str
    title: _BilingualText
    description: _BilingualText
    nodes: tuple[_MechanismNode, ...]
    edges: tuple[_MechanismEdge, ...]
    fallback: tuple[_BilingualText, ...]
    node_budget: int
    image_brief: _MechanismImageBrief


def _text(key: str, zh_cn: str, en_us: str) -> _BilingualText:
    return _BilingualText(key=key, zh_cn=zh_cn, en_us=en_us)


def _node(
    semantic_id: str,
    key: str,
    zh_cn: str,
    en_us: str,
    *,
    lane: str,
    stage: int,
    shape: str = "rectangle",
    visual_role: str | None = None,
) -> _MechanismNode:
    return _MechanismNode(
        semantic_id=semantic_id,
        label=_text(key, zh_cn, en_us),
        lane=lane,
        stage=stage,
        shape=shape,
        visual_role=visual_role,
    )


def _edge(
    semantic_id: str,
    source: str,
    target: str,
    *,
    label: _BilingualText | None = None,
    style: str = "solid",
) -> _MechanismEdge:
    return _MechanismEdge(
        semantic_id=semantic_id,
        source=source,
        target=target,
        label=label,
        style=style,
    )


def _image_brief(
    purpose: str,
    composition: str,
    required_marks: tuple[str, ...],
    *,
    generate_raster: bool = True,
) -> _MechanismImageBrief:
    return _MechanismImageBrief(
        generate_raster=generate_raster,
        visual_system=(
            "Horizontal flat 2D scientific-editorial composition on light paper, with dark ink lines "
            "and one restrained cobalt-blue accent."
        ),
        purpose=purpose,
        composition=composition,
        required_marks=required_marks,
        forbidden_marks=(
            "people or character illustrations",
            "3D, glow, photorealistic devices, or decorative nodes",
            "any text, letters, numerals, or labels rendered inside the image",
            "color-only encoding",
        ),
    )


def _definitions() -> tuple[_DiagramDefinition, ...]:
    sample_first = _DiagramDefinition(
        diagram_id="sample_first",
        filename="mechanism-sample-first.mmd",
        navigation_anchor="overview",
        title=_text("sample_first.title", "样本先存在", "Sample First"),
        description=_text(
            "sample_first.description",
            "研究样本在消息配对、平台队列和模拟决策之前，由既有 processed 数据确定。",
            "The Research Sample is fixed from existing processed data before message pairing, platform queues, or simulated decisions.",
        ),
        nodes=(
            _node(
                "eligible_user_pool",
                "sample_first.node.eligible_user_pool",
                "完整合格用户池",
                "Full Eligible User Pool",
                lane="historical_data",
                stage=1,
            ),
            _node(
                "influence_seed_union",
                "sample_first.node.influence_seed_union",
                "影响力种子并集",
                "Influence Seed Union",
                lane="historical_data",
                stage=2,
                shape="rounded",
            ),
            _node(
                "seed_direct_neighbors",
                "sample_first.node.seed_direct_neighbors",
                "种子的历史直接一跳邻居",
                "Seed Historical Direct Neighbors",
                lane="historical_data",
                stage=3,
            ),
            _node(
                "quota_regular_users",
                "sample_first.node.quota_regular_users",
                "按配额补足的普通用户",
                "Quota-Filled Regular Users",
                lane="historical_data",
                stage=4,
            ),
            _node(
                "research_sample_1000",
                "sample_first.node.research_sample_1000",
                "固定 1,000 人研究样本",
                "Fixed 1,000-User Research Sample",
                lane="historical_data",
                stage=5,
                shape="stadium",
            ),
        ),
        edges=(
            _edge("pool_to_seed_union", "eligible_user_pool", "influence_seed_union"),
            _edge("seed_union_to_neighbors", "influence_seed_union", "seed_direct_neighbors"),
            _edge("pool_to_quota_users", "eligible_user_pool", "quota_regular_users"),
            _edge("seed_union_to_sample", "influence_seed_union", "research_sample_1000"),
            _edge("neighbors_to_sample", "seed_direct_neighbors", "research_sample_1000"),
            _edge("quota_users_to_sample", "quota_regular_users", "research_sample_1000"),
        ),
        fallback=(
            _text(
                "sample_first.fallback.source",
                "完整合格用户池来自既有采集、清洗和派生的历史数据，不是 runtime live database。",
                "The full eligible pool comes from existing collected, cleaned, and derived historical data, not a runtime live database.",
            ),
            _text(
                "sample_first.fallback.selection",
                "先确定影响力种子并集和其历史直接邻居，再按来源配额补足普通用户。",
                "The influence seed union and its historical direct neighbors are selected before regular users fill source quotas.",
            ),
            _text(
                "sample_first.fallback.boundary",
                "固定 1,000 人研究样本先存在；合成标签不创建样本，分层补足也不表示总体代表性。",
                "The fixed 1,000-user Research Sample exists first; synthetic labels do not create it, and quota filling does not imply population representativeness.",
            ),
        ),
        node_budget=5,
        image_brief=_image_brief(
            "Show that the Research Sample exists before any message or queue.",
            "A left-to-right narrowing funnel in the historical-data lane, ending in one emphatic 1,000-user sample mark.",
            (
                "full eligible pool",
                "seed union",
                "historical direct neighbors",
                "quota-filled regular users",
                "one fixed Research Sample endpoint",
            ),
        ),
    )

    pair_formation = _DiagramDefinition(
        diagram_id="pair_formation",
        filename="mechanism-pair-formation.mmd",
        navigation_anchor="sample",
        title=_text("pair_formation.title", "用户与消息配对", "Pair Formation"),
        description=_text(
            "pair_formation.description",
            "同一固定研究样本分别与 M1、M2、M3 形成三条 pair 路径。",
            "The same fixed Research Sample forms three separate pair paths with M1, M2, and M3.",
        ),
        nodes=(
            _node(
                "research_sample_1000",
                "pair_formation.node.research_sample_1000",
                "已存在的 1,000 人研究样本",
                "Existing 1,000-User Research Sample",
                lane="historical_data",
                stage=1,
                shape="stadium",
            ),
            _node(
                "eligible_pairs_m1",
                "pair_formation.node.eligible_pairs_m1",
                "样本 × M1 = 1,000 个配对",
                "Sample × M1 = 1,000 Pairs",
                lane="platform_recommendation",
                stage=2,
                visual_role="message_m1",
            ),
            _node(
                "eligible_pairs_m2",
                "pair_formation.node.eligible_pairs_m2",
                "样本 × M2 = 1,000 个配对",
                "Sample × M2 = 1,000 Pairs",
                lane="platform_recommendation",
                stage=2,
                shape="rounded",
                visual_role="message_m2",
            ),
            _node(
                "eligible_pairs_m3",
                "pair_formation.node.eligible_pairs_m3",
                "样本 × M3 = 1,000 个配对",
                "Sample × M3 = 1,000 Pairs",
                lane="platform_recommendation",
                stage=2,
                shape="hexagon",
                visual_role="message_m3",
            ),
            _node(
                "eligible_pairs_total_3000",
                "pair_formation.node.eligible_pairs_total_3000",
                "1,000 位用户 × 3 条消息 = 3,000 个合格配对",
                "1,000 Users × 3 Messages = 3,000 Eligible Pairs",
                lane="platform_recommendation",
                stage=3,
                shape="stadium",
            ),
        ),
        edges=(
            _edge("sample_to_m1_pairs", "research_sample_1000", "eligible_pairs_m1"),
            _edge("sample_to_m2_pairs", "research_sample_1000", "eligible_pairs_m2", style="dashed"),
            _edge("sample_to_m3_pairs", "research_sample_1000", "eligible_pairs_m3", style="thick"),
            _edge("m1_pairs_to_total", "eligible_pairs_m1", "eligible_pairs_total_3000"),
            _edge("m2_pairs_to_total", "eligible_pairs_m2", "eligible_pairs_total_3000", style="dashed"),
            _edge("m3_pairs_to_total", "eligible_pairs_m3", "eligible_pairs_total_3000", style="thick"),
        ),
        fallback=(
            _text(
                "pair_formation.fallback.sample_first",
                "配对只消费已经固定的研究样本，不生成或筛选新的用户。",
                "Pairing consumes the already fixed Research Sample; it does not create or select new users.",
            ),
            _text(
                "pair_formation.fallback.denominator",
                "每位用户分别与三条消息形成 pair，因此合格分母是 3,000 个 user × message pair。",
                "Every user pairs separately with all three messages, so the eligible denominator is 3,000 user × message pairs.",
            ),
            _text(
                "pair_formation.fallback.scope",
                "本图不表示 queue、exposure、Decision、消息正文或设计受众。",
                "This view does not represent queues, exposures, Decisions, message copy, or intended audiences.",
            ),
        ),
        node_budget=5,
        image_brief=_image_brief(
            "Make the 3,000-pair denominator obvious without implying that pairing creates users.",
            "One stable sample mark fans into three visually distinct M1/M2/M3 paths and reconverges at the denominator.",
            (
                "one pre-existing 1,000-user sample",
                "three 1,000-pair paths",
                "M1/M2/M3 distinguished by shape and line style",
                "one 3,000 eligible-pair total",
            ),
        ),
    )

    shared_seed_edge = _text(
        "independent_delivery.edge.shared_seed",
        "相同 seeds；分别补足 Top20",
        "Same Seeds; Fill Top20 Independently",
    )
    independent_delivery = _DiagramDefinition(
        diagram_id="independent_delivery",
        filename="mechanism-independent-delivery.mmd",
        navigation_anchor="exposure-ranking",
        title=_text("independent_delivery.title", "三条消息独立投放", "Independent Delivery"),
        description=_text(
            "independent_delivery.description",
            "Batch 0 共享同一 seeds，但三条消息各自维护 30 × Top20 的投放容量。",
            "Batch 0 shares the same seeds, while each message maintains its own 30 × Top20 delivery capacity.",
        ),
        nodes=(
            _node(
                "shared_seed_launch",
                "independent_delivery.node.shared_seed_launch",
                "Batch 0 共同种子启动",
                "Batch 0 Shared Seed Launch",
                lane="platform_recommendation",
                stage=1,
                shape="stadium",
            ),
            _node(
                "message_1_capacity_600",
                "independent_delivery.node.message_1_capacity_600",
                "M1 独立队列：30 × Top20 = 600 容量",
                "M1 Independent Queue: 30 × Top20 = 600 Capacity",
                lane="platform_recommendation",
                stage=2,
                visual_role="message_m1",
            ),
            _node(
                "message_2_capacity_600",
                "independent_delivery.node.message_2_capacity_600",
                "M2 独立队列：30 × Top20 = 600 容量",
                "M2 Independent Queue: 30 × Top20 = 600 Capacity",
                lane="platform_recommendation",
                stage=2,
                shape="rounded",
                visual_role="message_m2",
            ),
            _node(
                "message_3_capacity_600",
                "independent_delivery.node.message_3_capacity_600",
                "M3 独立队列：30 × Top20 = 600 容量",
                "M3 Independent Queue: 30 × Top20 = 600 Capacity",
                lane="platform_recommendation",
                stage=2,
                shape="hexagon",
                visual_role="message_m3",
            ),
            _node(
                "independent_capacity_overlap",
                "independent_delivery.node.independent_capacity_overlap",
                "三份容量互不共享；跨消息受众可重叠",
                "Three Capacities Are Not Shared; Cross-Message Audiences May Overlap",
                lane="platform_recommendation",
                stage=3,
                shape="stadium",
            ),
        ),
        edges=(
            _edge(
                "shared_seed_to_m1_capacity",
                "shared_seed_launch",
                "message_1_capacity_600",
                label=shared_seed_edge,
            ),
            _edge(
                "shared_seed_to_m2_capacity",
                "shared_seed_launch",
                "message_2_capacity_600",
                label=shared_seed_edge,
                style="dashed",
            ),
            _edge(
                "shared_seed_to_m3_capacity",
                "shared_seed_launch",
                "message_3_capacity_600",
                label=shared_seed_edge,
                style="thick",
            ),
            _edge("m1_capacity_to_overlap", "message_1_capacity_600", "independent_capacity_overlap"),
            _edge(
                "m2_capacity_to_overlap",
                "message_2_capacity_600",
                "independent_capacity_overlap",
                style="dashed",
            ),
            _edge(
                "m3_capacity_to_overlap",
                "message_3_capacity_600",
                "independent_capacity_overlap",
                style="thick",
            ),
        ),
        fallback=(
            _text(
                "independent_delivery.fallback.batch_zero",
                "Batch 0 为三条消息使用相同的种子并集；不足 Top20 时，各消息按自己的排序分别补足。",
                "Batch 0 uses the same seed union for all three messages; when it is below Top20, each message fills independently from its own ranking.",
            ),
            _text(
                "independent_delivery.fallback.capacity",
                "M1、M2、M3 各有 30 批 × Top20 = 600 的独立容量，不共享一个 20-slot quota。",
                "M1, M2, and M3 each have an independent 30 batches × Top20 = 600 capacity; they do not share one 20-slot quota.",
            ),
            _text(
                "independent_delivery.fallback.overlap",
                "同一用户可以跨消息进入多个队列，但同一 user × message pair 最多曝光一次。",
                "A user may enter multiple message queues, but the same user × message pair can be exposed at most once.",
            ),
            _text(
                "independent_delivery.fallback.ranking",
                "0.50 / 0.30 / 0.20 权重、完整精度与 user_id tie-break 属于方法说明，不改变三份独立容量。",
                "The 0.50 / 0.30 / 0.20 weights, full precision, and user_id tie-break belong to the method disclosure and do not alter the three independent capacities.",
            ),
        ),
        node_budget=5,
        image_brief=_image_brief(
            "Show three independent delivery capacities without suggesting a shared 20-slot quota.",
            "A compact shared-seed launch fans into three equal M1/M2/M3 queue tracks, then ends in one overlap boundary note.",
            (
                "shared Batch 0 seed launch",
                "three independent 600-capacity tracks",
                "M1/M2/M3 distinguished by shape and line style",
                "cross-message overlap allowed",
            ),
        ),
    )

    same_exposure = _text(
        "exposure_decisions.edge.same_exposure",
        "同一次曝光",
        "Same Exposure",
    )
    exposure_decisions = _DiagramDefinition(
        diagram_id="exposure_decisions",
        filename="mechanism-exposure-decisions.mmd",
        navigation_anchor="llm-decision",
        title=_text("exposure_decisions.title", "曝光与配对决策", "Exposure & Decisions"),
        description=_text(
            "exposure_decisions.description",
            "只有通过曝光门的 pair 才形成 Primary 与仅报告 Shadow；两者来自同一次曝光。",
            "Only a pair that passes the Exposure Gate forms Primary and report-only Shadow Decisions; both come from the same exposure.",
        ),
        nodes=(
            _node(
                "eligible_pair",
                "exposure_decisions.node.eligible_pair",
                "合格的用户 × 消息配对",
                "Eligible User × Message Pair",
                lane="platform_recommendation",
                stage=1,
            ),
            _node(
                "per_message_queue",
                "exposure_decisions.node.per_message_queue",
                "对应消息的独立队列",
                "Per-Message Queue",
                lane="platform_recommendation",
                stage=2,
            ),
            _node(
                "exposure_gate",
                "exposure_decisions.node.exposure_gate",
                "曝光门",
                "Exposure Gate",
                lane="platform_recommendation",
                stage=3,
                shape="diamond",
            ),
            _node(
                "exposed_pair",
                "exposure_decisions.node.exposed_pair",
                "已曝光配对",
                "Exposed Pair",
                lane="simulated_user_decision",
                stage=4,
                shape="stadium",
            ),
            _node(
                "primary_campaign_decision",
                "exposure_decisions.node.primary_campaign_decision",
                "主要活动决策",
                "Primary Campaign Decision",
                lane="simulated_user_decision",
                stage=5,
            ),
            _node(
                "report_only_shadow_decision",
                "exposure_decisions.node.report_only_shadow_decision",
                "仅报告的人口属性影子决策",
                "Report-Only Demographic Shadow Decision",
                lane="simulated_user_decision",
                stage=5,
                shape="rounded",
            ),
        ),
        edges=(
            _edge("eligible_pair_to_queue", "eligible_pair", "per_message_queue"),
            _edge("queue_to_exposure_gate", "per_message_queue", "exposure_gate"),
            _edge("exposure_gate_to_exposed_pair", "exposure_gate", "exposed_pair"),
            _edge(
                "exposed_pair_to_primary",
                "exposed_pair",
                "primary_campaign_decision",
                label=same_exposure,
            ),
            _edge(
                "exposed_pair_to_shadow",
                "exposed_pair",
                "report_only_shadow_decision",
                label=same_exposure,
                style="dashed",
            ),
        ),
        fallback=(
            _text(
                "exposure_decisions.fallback.no_pre_exposure_decision",
                "没有获得曝光的 pair 不调用 Decision Adapter。",
                "A pair that is not exposed does not call the Decision Adapter.",
            ),
            _text(
                "exposure_decisions.fallback.same_exposure",
                "Primary 与 Demographic Shadow 是同一次实际曝光后的配对决策，不是第二次曝光。",
                "Primary and Demographic Shadow are paired Decisions after the same actual exposure, not a second exposure.",
            ),
            _text(
                "exposure_decisions.fallback.shadow_boundary",
                "Shadow 只进入报告，不写入 action、ranking、feedback 或 runtime state。",
                "Shadow is report-only and does not write action, ranking, feedback, or runtime state.",
            ),
        ),
        node_budget=6,
        image_brief=_image_brief(
            "Make exposure visibly precede both paired Decisions and prevent Shadow from looking like a second exposure.",
            "A five-stage chain crosses from the platform lane into the simulated-user lane and ends in a solid Primary / dashed Shadow fork.",
            (
                "eligible pair",
                "per-message queue",
                "Exposure Gate",
                "one exposed-pair mark",
                "same-exposure Primary and report-only Shadow fork",
            ),
        ),
    )

    feedback_boundary = _DiagramDefinition(
        diagram_id="feedback_boundary",
        filename="mechanism-feedback-boundary.mmd",
        navigation_anchor="network-feedback",
        title=_text("feedback_boundary.title", "反馈边界", "Feedback Boundary"),
        description=_text(
            "feedback_boundary.description",
            "只有成功 Primary 的正向行为在 full-batch barrier 后按 user_id 去重，并只进入下一批排序上下文。",
            "Only positive actions from succeeded Primary Decisions cross the full-batch barrier, deduplicate by user_id, and enter next-batch ranking contexts.",
        ),
        nodes=(
            _node(
                "primary_succeeded_positive",
                "feedback_boundary.node.primary_succeeded_positive",
                "成功的主要决策：like / comment / share",
                "Succeeded Primary: Like / Comment / Share",
                lane="simulated_user_decision",
                stage=1,
                shape="stadium",
            ),
            _node(
                "shadow_terminal_no_feedback",
                "feedback_boundary.node.shadow_terminal_no_feedback",
                "影子决策：无反馈出口",
                "Shadow: No Feedback Exit",
                lane="simulated_user_decision",
                stage=1,
                shape="rounded",
            ),
            _node(
                "ignore_terminal_no_feedback",
                "feedback_boundary.node.ignore_terminal_no_feedback",
                "ignore：无反馈出口",
                "Ignore: No Feedback Exit",
                lane="simulated_user_decision",
                stage=1,
                shape="rounded",
            ),
            _node(
                "provider_failed_terminal_no_feedback",
                "feedback_boundary.node.provider_failed_terminal_no_feedback",
                "provider_failed：无反馈出口",
                "provider_failed: No Feedback Exit",
                lane="simulated_user_decision",
                stage=1,
                shape="rounded",
            ),
            _node(
                "pending_positive_user_ids",
                "feedback_boundary.node.pending_positive_user_ids",
                "待提交的正向 user_id 集合",
                "Pending Positive user_id Set",
                lane="platform_recommendation",
                stage=2,
            ),
            _node(
                "full_batch_barrier",
                "feedback_boundary.node.full_batch_barrier",
                "全部已选配对到达必需终态",
                "All Selected Pairs Reach Required Terminals",
                lane="platform_recommendation",
                stage=2,
                shape="diamond",
            ),
            _node(
                "campaign_user_id_commit",
                "feedback_boundary.node.campaign_user_id_commit",
                "关闭整批屏障后，跨消息按 user_id 去重提交",
                "After Full-Batch Barrier: Deduplicate by user_id Across Messages and Commit",
                lane="platform_recommendation",
                stage=3,
                shape="stadium",
            ),
            _node(
                "next_batch_ranking_contexts",
                "feedback_boundary.node.next_batch_ranking_contexts",
                "仅成为下一批的三条排序上下文",
                "Next Batch's Three Ranking Contexts Only",
                lane="platform_recommendation",
                stage=4,
            ),
        ),
        edges=(
            _edge(
                "positive_primary_to_pending",
                "primary_succeeded_positive",
                "pending_positive_user_ids",
                label=_text(
                    "feedback_boundary.edge.positive_only",
                    "仅成功 Primary 正向行为",
                    "Succeeded Positive Primary Only",
                ),
            ),
            _edge("pending_to_commit", "pending_positive_user_ids", "campaign_user_id_commit"),
            _edge("barrier_to_commit", "full_batch_barrier", "campaign_user_id_commit"),
            _edge(
                "commit_to_next_batch_contexts",
                "campaign_user_id_commit",
                "next_batch_ranking_contexts",
                label=_text(
                    "feedback_boundary.edge.next_batch_only",
                    "下一批生效",
                    "Effective Next Batch Only",
                ),
            ),
        ),
        fallback=(
            _text(
                "feedback_boundary.fallback.eligible_feedback",
                "只有 terminal status 为 succeeded 且 action 为 like、comment 或 share 的 Primary 可以进入 pending set。",
                "Only a Primary with terminal status succeeded and action like, comment, or share may enter the pending set.",
            ),
            _text(
                "feedback_boundary.fallback.stop_paths",
                "Shadow、ignore 与 provider_failed 没有 outgoing feedback edge。",
                "Shadow, ignore, and provider_failed have no outgoing feedback edge.",
            ),
            _text(
                "feedback_boundary.fallback.barrier",
                "全部 selected pairs 达到 required terminals 后才关闭 full-batch barrier。",
                "The full-batch barrier closes only after all selected pairs reach their required terminals.",
            ),
            _text(
                "feedback_boundary.fallback.commit",
                "barrier 关闭后跨消息按 user_id 去重提交；结果只改变下一批 ranking contexts，不注入 queue，也不回写同批排序。",
                "After the barrier closes, user_id values deduplicate across messages and commit only to next-batch ranking contexts; they do not inject queues or rewrite the same batch.",
            ),
        ),
        node_budget=8,
        image_brief=_image_brief(
            "Show the exact positive-Primary feedback boundary and make all non-propagating terminals visibly stop.",
            "A split terminal row has one positive path and three capped stop paths; the positive path joins a full-batch barrier before one deduplicated next-batch arrow.",
            (
                "succeeded positive Primary path",
                "capped Shadow, ignore, and provider_failed stop marks",
                "full-batch barrier",
                "cross-message user_id deduplication",
                "next-batch-only ranking context",
            ),
        ),
    )

    real_batch = _DiagramDefinition(
        diagram_id="real_batch",
        filename="real-batch-mechanism.mmd",
        navigation_anchor="real-batch",
        title=_text("real_batch.title", "真实批次机制", "Real-Batch Mechanism"),
        description=_text(
            "real_batch.description",
            "八个节点概括固定输入、三条独立 Top20、同次曝光决策、barrier 后提交和下一批上下文。",
            "Eight nodes summarize fixed inputs, three independent Top20 selections, same-exposure Decisions, post-barrier commit, and next-batch contexts.",
        ),
        nodes=(
            _node(
                "fixed_research_inputs",
                "real_batch.node.fixed_research_inputs",
                "固定研究输入",
                "Fixed Research Inputs",
                lane="historical_data",
                stage=1,
            ),
            _node(
                "remaining_eligible_pairs",
                "real_batch.node.remaining_eligible_pairs",
                "剩余合格配对",
                "Remaining Eligible Pairs",
                lane="platform_recommendation",
                stage=2,
            ),
            _node(
                "batch_start_snapshot",
                "real_batch.node.batch_start_snapshot",
                "批次开始快照",
                "Batch-Start Snapshot",
                lane="platform_recommendation",
                stage=3,
            ),
            _node(
                "per_message_top20_selection",
                "real_batch.node.per_message_top20_selection",
                "M1 / M2 / M3 各自 Top20",
                "Independent M1 / M2 / M3 Top20",
                lane="platform_recommendation",
                stage=4,
                shape="stadium",
            ),
            _node(
                "exposure_gate",
                "real_batch.node.exposure_gate",
                "曝光门",
                "Exposure Gate",
                lane="platform_recommendation",
                stage=5,
                shape="diamond",
            ),
            _node(
                "same_exposure_decision_pair",
                "real_batch.node.same_exposure_decision_pair",
                "同次曝光：主要决策 + 仅报告影子决策",
                "Same Exposure: Primary + Report-Only Shadow",
                lane="simulated_user_decision",
                stage=6,
            ),
            _node(
                "barrier_deduplicated_commit",
                "real_batch.node.barrier_deduplicated_commit",
                "整批屏障后按 user_id 去重提交",
                "Post-Barrier user_id-Deduplicated Commit",
                lane="platform_recommendation",
                stage=7,
                shape="stadium",
            ),
            _node(
                "next_batch_ranking_contexts",
                "real_batch.node.next_batch_ranking_contexts",
                "下一批排序上下文",
                "Next-Batch Ranking Contexts",
                lane="platform_recommendation",
                stage=8,
            ),
        ),
        edges=(
            _edge("fixed_inputs_to_remaining_pairs", "fixed_research_inputs", "remaining_eligible_pairs"),
            _edge("remaining_pairs_to_snapshot", "remaining_eligible_pairs", "batch_start_snapshot"),
            _edge("snapshot_to_top20", "batch_start_snapshot", "per_message_top20_selection"),
            _edge("top20_to_exposure_gate", "per_message_top20_selection", "exposure_gate"),
            _edge("exposure_gate_to_decisions", "exposure_gate", "same_exposure_decision_pair"),
            _edge(
                "positive_primary_to_barrier_commit",
                "same_exposure_decision_pair",
                "barrier_deduplicated_commit",
                label=_text(
                    "real_batch.edge.positive_primary_only",
                    "仅成功 Primary 正向行为",
                    "Succeeded Positive Primary Only",
                ),
            ),
            _edge(
                "barrier_commit_to_next_contexts",
                "barrier_deduplicated_commit",
                "next_batch_ranking_contexts",
                label=_text(
                    "real_batch.edge.next_batch_only",
                    "仅下一批",
                    "Next Batch Only",
                ),
            ),
        ),
        fallback=(
            _text(
                "real_batch.fallback.batch_zero",
                "Batch 0 使用共同 seeds，并为每条消息分别补足 Top20。",
                "Batch 0 uses shared seeds and fills each message to Top20 independently.",
            ),
            _text(
                "real_batch.fallback.stop_paths",
                "只有成功 Primary 正向行为进入 pending feedback；Shadow、ignore 和 provider_failed 停止。",
                "Only succeeded positive Primary actions enter pending feedback; Shadow, ignore, and provider_failed stop.",
            ),
            _text(
                "real_batch.fallback.robustness",
                "Historical Formal 使用 Primary + Shadow；Robustness factorial 为 Primary-only，这一差异不建立第二条并行主流程。",
                "Historical Formal uses Primary + Shadow, while the Robustness factorial is Primary-only; this difference does not create a second parallel main flow.",
            ),
            _text(
                "real_batch.fallback.next_batch",
                "full-batch barrier 后的去重集合只影响下一批 ranking contexts。",
                "The deduplicated set after the full-batch barrier affects next-batch ranking contexts only.",
            ),
        ),
        node_budget=8,
        image_brief=_image_brief(
            "Provide the deterministic eight-node real-batch reader path without creating another raster asset.",
            "One compact three-lane semantic flow from fixed inputs to next-batch contexts.",
            (
                "exactly eight semantic nodes",
                "one grouped three-message Top20 node",
                "same-exposure Primary plus report-only Shadow",
                "post-barrier user_id-deduplicated commit",
            ),
            generate_raster=False,
        ),
    )

    return (
        sample_first,
        pair_formation,
        independent_delivery,
        exposure_decisions,
        feedback_boundary,
        real_batch,
    )


def _full_pool_definition() -> _DiagramDefinition:
    return _DiagramDefinition(
        diagram_id="full_pool_main",
        filename="full-pool-mechanism.mmd",
        navigation_anchor="full-pool-main",
        title=_text(
            "full_pool_main.title",
            "全池主实验机制",
            "Full-Pool Main Experiment Mechanism",
        ),
        description=_text(
            "full_pool_main.description",
            "36,400 位合格用户与三条消息形成 109,200 个配对，在 30 个完整批次中全部曝光并执行 Primary-only 决策；排序只改变曝光批次与顺序。",
            "36,400 eligible users form 109,200 pairs with three messages. Every pair is exposed and receives one Primary-only decision across 30 complete batches; ranking changes batch and order only.",
        ),
        nodes=(
            _node(
                "full_eligible_pool_36400",
                "full_pool_main.node.full_eligible_pool_36400",
                "36,400 位完整合格用户",
                "36,400 Full Eligible Users",
                lane="historical_data",
                stage=1,
            ),
            _node(
                "eligible_pairs_109200",
                "full_pool_main.node.eligible_pairs_109200",
                "109,200 个 user × message 配对",
                "109,200 User × Message Pairs",
                lane="platform_recommendation",
                stage=2,
            ),
            _node(
                "independent_queues_30_batches",
                "full_pool_main.node.independent_queues_30_batches",
                "三条独立队列 · 30 批 · 每条 1,214 / 最后一批 1,194",
                "Three Independent Queues · 30 Batches · 1,214 Each / Final 1,194",
                lane="platform_recommendation",
                stage=3,
                shape="rounded",
            ),
            _node(
                "exposure_gate",
                "full_pool_main.node.exposure_gate",
                "曝光闸门 · 每个配对仅一次",
                "Exposure Gate · One Exposure per Pair",
                lane="platform_recommendation",
                stage=4,
                shape="diamond",
            ),
            _node(
                "primary_only_decision",
                "full_pool_main.node.primary_only_decision",
                "Primary-only 决策 · 不运行 Shadow",
                "Primary-only Decision · No Shadow",
                lane="simulated_user_decision",
                stage=5,
            ),
            _node(
                "full_batch_barrier",
                "full_pool_main.node.full_batch_barrier",
                "完整批次屏障 · 正向 Primary 按 user_id 去重",
                "Full-Batch Barrier · Positive Primary Deduplicated by user_id",
                lane="platform_recommendation",
                stage=6,
                shape="hexagon",
            ),
            _node(
                "next_batch_ranking_context",
                "full_pool_main.node.next_batch_ranking_context",
                "仅进入下一批排序上下文",
                "Next-Batch Ranking Context Only",
                lane="platform_recommendation",
                stage=7,
            ),
            _node(
                "complete_three_message_coverage",
                "full_pool_main.node.complete_three_message_coverage",
                "完整三消息覆盖 · below capacity = 0",
                "Complete Three-Message Coverage · Below Capacity = 0",
                lane="platform_recommendation",
                stage=8,
                shape="stadium",
            ),
        ),
        edges=(
            _edge(
                "full_pool_to_pairs",
                "full_eligible_pool_36400",
                "eligible_pairs_109200",
                label=_text(
                    "full_pool_main.edge.full_pool_to_pairs",
                    "每位用户 × 三条消息",
                    "Each User × Three Messages",
                ),
            ),
            _edge(
                "pairs_to_queues",
                "eligible_pairs_109200",
                "independent_queues_30_batches",
                label=_text(
                    "full_pool_main.edge.pairs_to_queues",
                    "按消息维护剩余配对",
                    "Maintain Remaining Pairs per Message",
                ),
            ),
            _edge(
                "queues_to_exposure",
                "independent_queues_30_batches",
                "exposure_gate",
                label=_text(
                    "full_pool_main.edge.queues_to_exposure",
                    "排序选择本批曝光顺序",
                    "Ranking Selects This Batch and Order",
                ),
            ),
            _edge(
                "exposure_to_primary",
                "exposure_gate",
                "primary_only_decision",
                label=_text(
                    "full_pool_main.edge.exposure_to_primary",
                    "曝光后才执行决策",
                    "Decide Only After Exposure",
                ),
            ),
            _edge(
                "primary_to_barrier",
                "primary_only_decision",
                "full_batch_barrier",
                label=_text(
                    "full_pool_main.edge.primary_to_barrier",
                    "全部终态关闭；仅成功正向行为提交",
                    "Close Every Terminal; Commit Succeeded Positive Actions Only",
                ),
            ),
            _edge(
                "barrier_to_next_batch",
                "full_batch_barrier",
                "next_batch_ranking_context",
                label=_text(
                    "full_pool_main.edge.barrier_to_next_batch",
                    "同批结束后提交",
                    "Commit After the Full Batch",
                ),
            ),
            _edge(
                "next_batch_feedback",
                "next_batch_ranking_context",
                "independent_queues_30_batches",
                label=_text(
                    "full_pool_main.edge.next_batch_feedback",
                    "下一批重新排序",
                    "Rerank the Next Batch",
                ),
                style="dashed",
            ),
            _edge(
                "barrier_to_complete_coverage",
                "full_batch_barrier",
                "complete_three_message_coverage",
                label=_text(
                    "full_pool_main.edge.barrier_to_complete_coverage",
                    "30 批关闭后",
                    "After 30 Batches Close",
                ),
                style="thick",
            ),
        ),
        fallback=(
            _text(
                "full_pool_main.fallback.denominator",
                "完整合格用户池包含 36,400 位用户；三条消息形成 109,200 个 eligible pairs。",
                "The full eligible pool contains 36,400 users; three messages form 109,200 eligible pairs.",
            ),
            _text(
                "full_pool_main.fallback.schedule",
                "每条消息在前 29 批最多曝光 1,214 个剩余配对，最后一批曝光 1,194 个。",
                "Each message exposes up to 1,214 remaining pairs in the first 29 batches and 1,194 in the final batch.",
            ),
            _text(
                "full_pool_main.fallback.primary_only",
                "每次曝光只执行 Primary Decision；不运行新的 Demographic Shadow。",
                "Each exposure executes one Primary Decision; no new Demographic Shadow is run.",
            ),
            _text(
                "full_pool_main.fallback.feedback",
                "只有成功的 like、comment 或 share 在完整批次屏障后按 user_id 去重，并进入下一批排序上下文；ignore 与 provider_failed 不传播。",
                "Only succeeded like, comment, or share actions are deduplicated by user_id after the full-batch barrier and enter the next-batch ranking context; ignore and provider_failed do not propagate.",
            ),
            _text(
                "full_pool_main.fallback.coverage",
                "所有配对最终获得一次曝光和一个 Primary terminal，因此排序只改变曝光批次与顺序，不改变最终覆盖。",
                "Every pair ultimately receives one exposure and one Primary terminal, so ranking changes exposure batch and order, not final coverage.",
            ),
        ),
        node_budget=8,
        image_brief=_image_brief(
            "Provide one deterministic end-to-end Full-Pool semantic master without generating a raster asset.",
            "One three-lane flow from the 36,400-user denominator through complete three-message coverage and the next-batch feedback loop.",
            (
                "exactly eight semantic nodes",
                "36,400 users and 109,200 pairs",
                "three independent 30-batch queues with 1,214 / 1,194 capacity",
                "Primary-only decision and full-batch feedback boundary",
                "complete three-message coverage",
            ),
            generate_raster=False,
        ),
    )


def _full_pool_two_stage_definition() -> _DiagramDefinition:
    return _DiagramDefinition(
        diagram_id="full_pool_two_stage_main",
        filename="full-pool-mechanism.mmd",
        navigation_anchor="full-pool-main",
        title=_text(
            "full_pool_two_stage_main.title",
            "全池两阶段互动实现机制",
            "Full-Pool Two-Stage Engagement Realization",
        ),
        description=_text(
            "full_pool_two_stage_main.description",
            "36,400 位用户与三条消息形成 109,200 次单次曝光。Provider Judgment 只表达互动意向；ABM 通过稳定概率抽样形成 realized action，只有 realized positive 在完整批次屏障后进入下一批反馈。",
            "36,400 users and three messages form 109,200 single exposures. Provider Judgment expresses engagement intent only; the ABM uses a stable probability draw to form the realized action, and only realized positives enter next-batch feedback after the full-batch barrier.",
        ),
        nodes=(
            _node(
                "full_eligible_pool_36400",
                "full_pool_two_stage_main.node.full_eligible_pool_36400",
                "36,400 位完整合格用户",
                "36,400 Full Eligible Users",
                lane="historical_data",
                stage=1,
            ),
            _node(
                "eligible_pairs_109200",
                "full_pool_two_stage_main.node.eligible_pairs_109200",
                "109,200 个 user × message 配对",
                "109,200 User × Message Pairs",
                lane="platform_recommendation",
                stage=2,
            ),
            _node(
                "independent_queues_30_batches",
                "full_pool_two_stage_main.node.independent_queues_30_batches",
                "三条独立队列 · 30 批 · 1,214 / 1,194",
                "Three Independent Queues · 30 Batches · 1,214 / 1,194",
                lane="platform_recommendation",
                stage=3,
                shape="rounded",
            ),
            _node(
                "exposure_gate",
                "full_pool_two_stage_main.node.exposure_gate",
                "曝光闸门 · 每个配对仅一次",
                "Exposure Gate · One Exposure per Pair",
                lane="platform_recommendation",
                stage=4,
                shape="diamond",
            ),
            _node(
                "provider_judgment",
                "full_pool_two_stage_main.node.provider_judgment",
                "Provider Judgment · 互动意向与概率",
                "Provider Judgment · Intent and Probability",
                lane="simulated_user_decision",
                stage=5,
            ),
            _node(
                "judgment_gate",
                "full_pool_two_stage_main.node.judgment_gate",
                "ignore 或正向意向闸门",
                "Ignore or Positive-Intent Gate",
                lane="simulated_user_decision",
                stage=6,
                shape="diamond",
            ),
            _node(
                "stable_probability_draw",
                "full_pool_two_stage_main.node.stable_probability_draw",
                "稳定概率抽样 · source × user × message",
                "Stable Probability Draw · Source × User × Message",
                lane="simulated_user_decision",
                stage=7,
                shape="rounded",
            ),
            _node(
                "realized_outcome",
                "full_pool_two_stage_main.node.realized_outcome",
                "Realized action 或 ignore",
                "Realized Action or Ignore",
                lane="simulated_user_decision",
                stage=8,
            ),
            _node(
                "full_batch_barrier",
                "full_pool_two_stage_main.node.full_batch_barrier",
                "完整批次屏障",
                "Full-Batch Barrier",
                lane="platform_recommendation",
                stage=9,
                shape="hexagon",
            ),
            _node(
                "realized_feedback",
                "full_pool_two_stage_main.node.realized_feedback",
                "Realized Feedback · 仅提交正向用户",
                "Realized Feedback · Positive Users Only",
                lane="platform_recommendation",
                stage=10,
            ),
            _node(
                "next_batch_ranking_context",
                "full_pool_two_stage_main.node.next_batch_ranking_context",
                "下一批重新排序上下文",
                "Next-Batch Reranking Context",
                lane="platform_recommendation",
                stage=11,
            ),
            _node(
                "realized_projection",
                "full_pool_two_stage_main.node.realized_projection",
                "单次曝光 realized projection",
                "Single-Exposure Realized Projection",
                lane="platform_recommendation",
                stage=12,
                shape="stadium",
            ),
        ),
        edges=(
            _edge(
                "full_pool_to_pairs",
                "full_eligible_pool_36400",
                "eligible_pairs_109200",
                label=_text(
                    "full_pool_two_stage_main.edge.full_pool_to_pairs",
                    "每位用户 × 三条消息",
                    "Each User × Three Messages",
                ),
            ),
            _edge(
                "pairs_to_queues",
                "eligible_pairs_109200",
                "independent_queues_30_batches",
                label=_text(
                    "full_pool_two_stage_main.edge.pairs_to_queues",
                    "按消息维护剩余配对",
                    "Maintain Remaining Pairs per Message",
                ),
            ),
            _edge(
                "queues_to_exposure",
                "independent_queues_30_batches",
                "exposure_gate",
                label=_text(
                    "full_pool_two_stage_main.edge.queues_to_exposure",
                    "排序决定曝光批次与顺序",
                    "Ranking Sets Exposure Batch and Order",
                ),
            ),
            _edge(
                "exposure_to_provider_judgment",
                "exposure_gate",
                "provider_judgment",
                label=_text(
                    "full_pool_two_stage_main.edge.exposure_to_provider_judgment",
                    "曝光后形成结构化 Judgment",
                    "Form Structured Judgment After Exposure",
                ),
            ),
            _edge(
                "judgment_to_gate",
                "provider_judgment",
                "judgment_gate",
                label=_text(
                    "full_pool_two_stage_main.edge.judgment_to_gate",
                    "读取 engage、action 与 probability",
                    "Read Engage, Action, and Probability",
                ),
            ),
            _edge(
                "provider_ignore_to_outcome",
                "judgment_gate",
                "realized_outcome",
                label=_text(
                    "full_pool_two_stage_main.edge.provider_ignore_to_outcome",
                    "Provider ignore · 不抽样",
                    "Provider Ignore · No Draw",
                ),
                style="dashed",
            ),
            _edge(
                "positive_gate_to_draw",
                "judgment_gate",
                "stable_probability_draw",
                label=_text(
                    "full_pool_two_stage_main.edge.positive_gate_to_draw",
                    "正向意向才进入概率闸门",
                    "Positive Intent Enters Probability Gate",
                ),
            ),
            _edge(
                "draw_to_outcome",
                "stable_probability_draw",
                "realized_outcome",
                label=_text(
                    "full_pool_two_stage_main.edge.draw_to_outcome",
                    "pass 保留 action；fail 变为 ignore",
                    "Pass Keeps Action; Fail Becomes Ignore",
                ),
            ),
            _edge(
                "outcome_to_barrier",
                "realized_outcome",
                "full_batch_barrier",
                label=_text(
                    "full_pool_two_stage_main.edge.outcome_to_barrier",
                    "整批 outcomes 全部关闭",
                    "Close Every Outcome in the Batch",
                ),
            ),
            _edge(
                "barrier_to_realized_feedback",
                "full_batch_barrier",
                "realized_feedback",
                label=_text(
                    "full_pool_two_stage_main.edge.barrier_to_realized_feedback",
                    "按 user_id 去重提交",
                    "Commit Deduplicated by user_id",
                ),
            ),
            _edge(
                "feedback_to_next_batch",
                "realized_feedback",
                "next_batch_ranking_context",
                label=_text(
                    "full_pool_two_stage_main.edge.feedback_to_next_batch",
                    "仅影响下一批",
                    "Affects the Next Batch Only",
                ),
            ),
            _edge(
                "next_batch_feedback",
                "next_batch_ranking_context",
                "independent_queues_30_batches",
                label=_text(
                    "full_pool_two_stage_main.edge.next_batch_feedback",
                    "下一批重新排序",
                    "Rerank the Next Batch",
                ),
                style="dashed",
            ),
            _edge(
                "next_batch_to_projection",
                "next_batch_ranking_context",
                "realized_projection",
                label=_text(
                    "full_pool_two_stage_main.edge.next_batch_to_projection",
                    "30 批关闭后投影 realized facts",
                    "Project Realized Facts After 30 Batches Close",
                ),
                style="thick",
            ),
        ),
        fallback=(
            _text(
                "full_pool_two_stage_main.fallback.denominator",
                "36,400 位用户与三条消息形成 109,200 个 user × message exposures；每个配对只曝光一次。",
                "36,400 users and three messages form 109,200 user × message exposures; every pair is exposed once.",
            ),
            _text(
                "full_pool_two_stage_main.fallback.judgment",
                "Provider Judgment 记录互动意向、概率、action、confidence 与意向理由，但不等于已经实现的行动。",
                "Provider Judgment records engagement intent, probability, action, confidence, and an intent reason; it is not an already realized action.",
            ),
            _text(
                "full_pool_two_stage_main.fallback.ignore",
                "Provider ignore 不生成 draw，并直接成为 realized ignore。",
                "Provider ignore creates no draw and directly becomes realized ignore.",
            ),
            _text(
                "full_pool_two_stage_main.fallback.draw",
                "Provider 正向 Judgment 才按 source、user、message 稳定键抽样；pass 保留原 action，fail 变为 ignore。",
                "Only a positive Provider Judgment is drawn using the stable source, user, and message key; pass keeps the original action and fail becomes ignore.",
            ),
            _text(
                "full_pool_two_stage_main.fallback.feedback",
                "完整批次关闭后只提交 realized-positive 用户；Provider ignore 与 draw fail 都不进入下一批反馈。",
                "After the full batch closes, only realized-positive users are committed; Provider ignore and draw fail never enter next-batch feedback.",
            ),
            _text(
                "full_pool_two_stage_main.fallback.projection",
                "当前 Primary 结果只按单次 exposure 的 realized like、comment、share 与 ignore 投影。",
                "The current Primary result projects realized like, comment, share, and ignore by single exposure only.",
            ),
        ),
        node_budget=12,
        image_brief=_image_brief(
            "Provide one deterministic end-to-end two-stage Full-Pool semantic master without generating a raster asset.",
            "A visible chain from the full denominator through Provider Judgment, stable realization, full-batch feedback, next-batch ranking, and realized projection.",
            (
                "exactly twelve semantic nodes",
                "Provider Judgment distinct from ABM Realization",
                "Provider ignore bypasses the draw",
                "stable source-user-message draw",
                "realized-positive feedback after the full-batch barrier",
                "single-exposure realized projection",
            ),
            generate_raster=False,
        ),
    )


def _projection(definition: _DiagramDefinition, language: str) -> _MechanismLanguageProjection:
    texts: list[_BilingualText] = [
        definition.title,
        definition.description,
        *(_LANE_LABELS[lane] for lane in _LANE_ORDER),
        *(node.label for node in definition.nodes),
        *(edge.label for edge in definition.edges if edge.label is not None),
        *definition.fallback,
    ]
    unique: dict[str, _BilingualText] = {}
    for text in texts:
        previous = unique.get(text.key)
        if previous is not None and previous != text:
            raise ValueError(f"mechanism projection key has crossed translations: {text.key}")
        unique[text.key] = text
    keys = tuple(unique)
    values = tuple(unique[key].value(language) for key in keys)
    return _MechanismLanguageProjection(
        language=language,
        keys=keys,
        values=values,
        fallback_keys=tuple(text.key for text in definition.fallback),
        fallback_values=tuple(text.value(language) for text in definition.fallback),
    )


def _mermaid_label(text: _BilingualText) -> str:
    return f"{text.zh_cn}<br/>{text.en_us}".replace('"', "&quot;")


def _node_markup(node: _MechanismNode) -> str:
    label = _mermaid_label(node.label)
    if node.shape == "rounded":
        return f'{node.semantic_id}(["{label}"])'
    if node.shape == "stadium":
        return f'{node.semantic_id}(["{label}"])'
    if node.shape == "hexagon":
        return f'{node.semantic_id}{{{{"{label}"}}}}'
    if node.shape == "diamond":
        return f'{node.semantic_id}{{"{label}"}}'
    if node.shape != "rectangle":
        raise ValueError(f"unsupported mechanism node shape: {node.shape}")
    return f'{node.semantic_id}["{label}"]'


def _edge_markup(edge: _MechanismEdge) -> str:
    arrows = {"solid": "-->", "dashed": "-.->", "thick": "==>"}
    try:
        arrow = arrows[edge.style]
    except KeyError as exc:
        raise ValueError(f"unsupported mechanism edge style: {edge.style}") from exc
    label = f'|"{_mermaid_label(edge.label)}"|' if edge.label is not None else ""
    return f"{edge.source} {arrow}{label} {edge.target}"


def _mermaid_bytes(definition: _DiagramDefinition) -> bytes:
    metadata = [
        f"  %% diagram-id: {definition.diagram_id}",
        f"  %% dom-title-key: {definition.title.key}",
        f"  %% dom-description-key: {definition.description.key}",
        *(f"  %% dom-node-key: {node.semantic_id}={node.label.key}" for node in definition.nodes),
        *(
            f"  %% dom-edge-key: {edge.semantic_id}={edge.label.key}"
            for edge in definition.edges
            if edge.label is not None
        ),
        *(f"  %% fallback-key: {text.key}" for text in definition.fallback),
        f"  %% image-raster-generation-required: {str(definition.image_brief.generate_raster).lower()}",
        f"  %% image-visual-system: {definition.image_brief.visual_system}",
        f"  %% image-purpose: {definition.image_brief.purpose}",
        f"  %% image-composition: {definition.image_brief.composition}",
        *(f"  %% image-required-mark: {mark}" for mark in definition.image_brief.required_marks),
        *(f"  %% image-forbidden-mark: {mark}" for mark in definition.image_brief.forbidden_marks),
    ]
    lines = [
        "---",
        f"title: {definition.title.zh_cn} / {definition.title.en_us}",
        "---",
        "flowchart LR",
        *metadata,
        "  classDef historical_data fill:#f4f1e8,stroke:#1f2933,color:#1f2933,stroke-width:1px;",
        "  classDef platform_recommendation fill:#eef3fb,stroke:#2459a9,color:#1f2933,stroke-width:1.5px;",
        "  classDef simulated_user_decision fill:#ffffff,stroke:#1f2933,color:#1f2933,stroke-width:1.5px;",
        "  classDef message_m1 fill:#eef3fb,stroke:#2459a9,stroke-width:2px;",
        "  classDef message_m2 fill:#ffffff,stroke:#2459a9,stroke-width:2px,stroke-dasharray:6 4;",
        "  classDef message_m3 fill:#f4f1e8,stroke:#2459a9,stroke-width:3px;",
    ]
    for lane in _LANE_ORDER:
        lines.extend(
            (
                f'  subgraph {lane}_lane["{_mermaid_label(_LANE_LABELS[lane])}"]',
                "    direction TB",
            )
        )
        lines.extend(f"    {_node_markup(node)}" for node in definition.nodes if node.lane == lane)
        lines.append("  end")
    for edge in definition.edges:
        lines.extend((f"  %% semantic-edge: {edge.semantic_id}", f"  {_edge_markup(edge)}"))
    for node in definition.nodes:
        classes = [node.lane]
        if node.visual_role is not None:
            classes.append(node.visual_role)
        lines.append(f"  class {node.semantic_id} {','.join(classes)};")
    return ("\n".join(lines) + "\n").encode()


def _validate_definitions(definitions: tuple[_DiagramDefinition, ...]) -> None:
    expected = (
        ("sample_first", "mechanism-sample-first.mmd"),
        ("pair_formation", "mechanism-pair-formation.mmd"),
        ("independent_delivery", "mechanism-independent-delivery.mmd"),
        ("exposure_decisions", "mechanism-exposure-decisions.mmd"),
        ("feedback_boundary", "mechanism-feedback-boundary.mmd"),
        ("real_batch", "real-batch-mechanism.mmd"),
    )
    if tuple((definition.diagram_id, definition.filename) for definition in definitions) != expected:
        raise ValueError("mechanism diagram order or filename set is crossed")
    if tuple(definition.image_brief.generate_raster for definition in definitions) != (
        True,
        True,
        True,
        True,
        True,
        False,
    ):
        raise ValueError("mechanism raster-generation boundary is crossed")

    for index, definition in enumerate(definitions):
        nodes = {node.semantic_id: node for node in definition.nodes}
        edge_ids = {edge.semantic_id for edge in definition.edges}
        if len(nodes) != len(definition.nodes) or len(edge_ids) != len(definition.edges):
            raise ValueError(f"duplicate semantic ID in {definition.diagram_id}")
        if any(_STABLE_ID.fullmatch(semantic_id) is None for semantic_id in (*nodes, *edge_ids)):
            raise ValueError(f"unstable semantic ID in {definition.diagram_id}")
        if len(definition.nodes) > definition.node_budget:
            raise ValueError(f"node budget exceeded in {definition.diagram_id}")
        stages = {node.stage for node in definition.nodes}
        if stages != set(range(1, max(stages) + 1)):
            raise ValueError(f"stages are not contiguous in {definition.diagram_id}")
        if index < 5 and max(stages) > 5:
            raise ValueError(f"stage budget exceeded in {definition.diagram_id}")
        if index == 5 and len(definition.nodes) > 8:
            raise ValueError("real-batch node budget exceeded")
        if any(node.lane not in _LANE_ORDER for node in definition.nodes):
            raise ValueError(f"unknown lane ownership in {definition.diagram_id}")
        if any(edge.source not in nodes or edge.target not in nodes for edge in definition.edges):
            raise ValueError(f"edge endpoint is missing in {definition.diagram_id}")
        texts = (
            definition.title,
            definition.description,
            *(_LANE_LABELS[lane] for lane in _LANE_ORDER),
            *(node.label for node in definition.nodes),
            *(edge.label for edge in definition.edges if edge.label is not None),
            *definition.fallback,
        )
        if any(not text.key or not text.zh_cn.strip() or not text.en_us.strip() for text in texts):
            raise ValueError(f"bilingual projection is incomplete in {definition.diagram_id}")


def _validate_full_pool_definition(definition: _DiagramDefinition) -> None:
    if (
        definition.diagram_id != "full_pool_main"
        or definition.filename != "full-pool-mechanism.mmd"
        or definition.node_budget != 8
        or definition.image_brief.generate_raster
    ):
        raise ValueError("Full-Pool mechanism identity or raster boundary is crossed")
    nodes = {node.semantic_id: node for node in definition.nodes}
    edge_ids = {edge.semantic_id for edge in definition.edges}
    if len(nodes) != len(definition.nodes) or len(edge_ids) != len(definition.edges):
        raise ValueError("duplicate Full-Pool mechanism semantic ID")
    if len(nodes) > definition.node_budget:
        raise ValueError("Full-Pool mechanism node budget exceeded")
    if any(_STABLE_ID.fullmatch(semantic_id) is None for semantic_id in (*nodes, *edge_ids)):
        raise ValueError("Full-Pool mechanism has an unstable semantic ID")
    if {node.stage for node in definition.nodes} != set(range(1, 9)):
        raise ValueError("Full-Pool mechanism stages are not complete")
    if any(node.lane not in _LANE_ORDER for node in definition.nodes):
        raise ValueError("Full-Pool mechanism has unknown lane ownership")
    if any(edge.source not in nodes or edge.target not in nodes for edge in definition.edges):
        raise ValueError("Full-Pool mechanism edge endpoint is missing")
    texts = (
        definition.title,
        definition.description,
        *(_LANE_LABELS[lane] for lane in _LANE_ORDER),
        *(node.label for node in definition.nodes),
        *(edge.label for edge in definition.edges if edge.label is not None),
        *definition.fallback,
    )
    if any(not text.key or not text.zh_cn.strip() or not text.en_us.strip() for text in texts):
        raise ValueError("Full-Pool mechanism bilingual projection is incomplete")


def _validate_full_pool_two_stage_definition(definition: _DiagramDefinition) -> None:
    if (
        definition.diagram_id != "full_pool_two_stage_main"
        or definition.filename != "full-pool-mechanism.mmd"
        or definition.node_budget != 12
        or definition.image_brief.generate_raster
    ):
        raise ValueError("two-stage Full-Pool mechanism identity or raster boundary is crossed")
    nodes = {node.semantic_id: node for node in definition.nodes}
    edges = {edge.semantic_id: edge for edge in definition.edges}
    if len(nodes) != 12 or len(edges) != len(definition.edges):
        raise ValueError("two-stage Full-Pool mechanism semantic IDs are incomplete")
    if any(_STABLE_ID.fullmatch(semantic_id) is None for semantic_id in (*nodes, *edges)):
        raise ValueError("two-stage Full-Pool mechanism has an unstable semantic ID")
    if {node.stage for node in definition.nodes} != set(range(1, 13)):
        raise ValueError("two-stage Full-Pool mechanism stages are not complete")
    if any(node.lane not in _LANE_ORDER for node in definition.nodes):
        raise ValueError("two-stage Full-Pool mechanism has unknown lane ownership")
    if any(edge.source not in nodes or edge.target not in nodes for edge in definition.edges):
        raise ValueError("two-stage Full-Pool mechanism edge endpoint is missing")
    texts = (
        definition.title,
        definition.description,
        *(_LANE_LABELS[lane] for lane in _LANE_ORDER),
        *(node.label for node in definition.nodes),
        *(edge.label for edge in definition.edges if edge.label is not None),
        *definition.fallback,
    )
    if any(not text.key or not text.zh_cn.strip() or not text.en_us.strip() for text in texts):
        raise ValueError("two-stage Full-Pool mechanism bilingual projection is incomplete")


def _semantic_set_identity(artifacts: tuple[_MechanismArtifact, ...]) -> str:
    identity_document = {
        "schema_version": _SEMANTIC_SET_SCHEMA_VERSION,
        "masters": [
            {"filename": artifact.filename, "sha256": artifact.sha256}
            for artifact in artifacts
        ],
    }
    identity_bytes = (
        json.dumps(identity_document, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    return hashlib.sha256(identity_bytes).hexdigest()


class _MechanismPresentationInterface:
    """Package-internal Interface owning every mechanism semantic projection."""

    def build_full_pool_master(self) -> _MechanismPresentation:
        """Build the additive Full-Pool master without changing the historical set."""
        definition = _full_pool_definition()
        _validate_full_pool_definition(definition)
        diagram = _MechanismDiagram(
            diagram_id=definition.diagram_id,
            filename=definition.filename,
            navigation_anchor=definition.navigation_anchor,
            title_key=definition.title.key,
            description_key=definition.description.key,
            lane_order=_LANE_ORDER,
            stage_count=max(node.stage for node in definition.nodes),
            node_budget=definition.node_budget,
            nodes=definition.nodes,
            edges=definition.edges,
            projections=tuple(
                _projection(definition, language) for language in ("zh-CN", "en-US")
            ),
            image_brief=definition.image_brief,
        )
        payload = _mermaid_bytes(definition)
        artifact = _MechanismArtifact(
            filename=definition.filename,
            payload=payload,
            sha256=hashlib.sha256(payload).hexdigest(),
        )
        return _MechanismPresentation(
            schema_version=_FULL_POOL_SCHEMA_VERSION,
            lane_order=_LANE_ORDER,
            diagrams=(diagram,),
            mermaid_artifacts=(artifact,),
            semantic_set_identity_sha256=_semantic_set_identity((artifact,)),
        )

    def build_full_pool_two_stage_master(self) -> _MechanismPresentation:
        """Build v13 two-stage semantics without changing the legacy Full-Pool master."""
        definition = _full_pool_two_stage_definition()
        _validate_full_pool_two_stage_definition(definition)
        diagram = _MechanismDiagram(
            diagram_id=definition.diagram_id,
            filename=definition.filename,
            navigation_anchor=definition.navigation_anchor,
            title_key=definition.title.key,
            description_key=definition.description.key,
            lane_order=_LANE_ORDER,
            stage_count=max(node.stage for node in definition.nodes),
            node_budget=definition.node_budget,
            nodes=definition.nodes,
            edges=definition.edges,
            projections=tuple(
                _projection(definition, language) for language in ("zh-CN", "en-US")
            ),
            image_brief=definition.image_brief,
        )
        payload = _mermaid_bytes(definition)
        artifact = _MechanismArtifact(
            filename=definition.filename,
            payload=payload,
            sha256=hashlib.sha256(payload).hexdigest(),
        )
        return _MechanismPresentation(
            schema_version=_FULL_POOL_TWO_STAGE_SCHEMA_VERSION,
            lane_order=_LANE_ORDER,
            diagrams=(diagram,),
            mermaid_artifacts=(artifact,),
            semantic_set_identity_sha256=_semantic_set_identity((artifact,)),
        )

    def build(self) -> _MechanismPresentation:
        definitions = _definitions()
        _validate_definitions(definitions)
        diagrams = tuple(
            _MechanismDiagram(
                diagram_id=definition.diagram_id,
                filename=definition.filename,
                navigation_anchor=definition.navigation_anchor,
                title_key=definition.title.key,
                description_key=definition.description.key,
                lane_order=_LANE_ORDER,
                stage_count=max(node.stage for node in definition.nodes),
                node_budget=definition.node_budget,
                nodes=definition.nodes,
                edges=definition.edges,
                projections=tuple(
                    _projection(definition, language) for language in ("zh-CN", "en-US")
                ),
                image_brief=definition.image_brief,
            )
            for definition in definitions
        )
        artifacts = tuple(
            _MechanismArtifact(
                filename=definition.filename,
                payload=(payload := _mermaid_bytes(definition)),
                sha256=hashlib.sha256(payload).hexdigest(),
            )
            for definition in definitions
        )
        return _MechanismPresentation(
            schema_version=_SCHEMA_VERSION,
            lane_order=_LANE_ORDER,
            diagrams=diagrams,
            mermaid_artifacts=artifacts,
            semantic_set_identity_sha256=_semantic_set_identity(artifacts),
        )


_MECHANISM_PRESENTATION = _MechanismPresentationInterface()

__all__: list[str] = []
