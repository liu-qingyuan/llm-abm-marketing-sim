from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

_SCHEMA_VERSION = "concurrent-message-mechanism-presentation-v1"
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
