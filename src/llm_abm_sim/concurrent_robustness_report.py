from __future__ import annotations

import base64
import binascii
import csv
import gzip
import hashlib
import html
import io
import json
import math
import os
import re
import shutil
import tempfile
import zlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from .concurrent_message_editorial_candidate import _render_editorial_v4
from .concurrent_message_mechanism_presentation import _MECHANISM_PRESENTATION
from .concurrent_message_renderer import render_report
from .concurrent_message_report import (
    CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON,
    CONCURRENT_MESSAGE_REPORT_HTML,
    ConcurrentMessageArtifactClosure,
    close_concurrent_message_artifacts,
)
from .full_pool_formal_experiment import (
    FullPoolExperimentError,
    _ClosedFullPoolSource,
    _read_closed_full_pool_source,
)
from .full_pool_presentation import (
    _FULL_POOL_MASTER,
    _FULL_POOL_SOURCE_DIR,
    _HISTORICAL_DIR,
    _HISTORICAL_MERMAID_FILENAMES,
    _TRACE_INDEX_PATH,
    _TRACE_INDEX_SCHEMA,
    _TRACE_PARTITION_SCHEMA,
    _FullPoolPresentationError,
)
from .full_pool_presentation import (
    compose_full_pool_presentation_bundle as _compose_full_pool_presentation_bundle,
)
from .full_pool_presentation import (
    validate_full_pool_presentation_bundle as _validate_full_pool_presentation_bundle,
)
from .prompt_contracts import CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY

if TYPE_CHECKING:
    from .concurrent_robustness_study import ConcurrentRobustnessManifest

_REPORT_PAYLOAD_SCHEMA = "concurrent-robustness-report-payload-v1"
_REPORT_PAYLOAD_V2_SCHEMA = "concurrent-robustness-report-payload-v2"
_FULL_POOL_REPORT_PAYLOAD_SCHEMA = "full-pool-three-lineage-report-payload-v1"
_FULL_POOL_CANDIDATE_MANIFEST_SCHEMA = "full-pool-three-lineage-candidate-manifest-v1"
_FULL_POOL_RELEASE_EVIDENCE_SCHEMA = "full-pool-three-lineage-release-evidence-v1"
_FULL_POOL_PRESENTATION_INVENTORY_SCHEMA = "full-pool-presentation-inventory-v1"
_FULL_POOL_MECHANISM_SET_SCHEMA = "full-pool-mechanism-set-v1"
_FULL_POOL_CANDIDATE_TYPE = "full_pool_three_lineage_presentation_candidate"
_FULL_POOL_COUNT_FIELDS = frozenset(
    {
        "candidate_ranking_rows",
        "committed_batches",
        "distinct_users",
        "eligible_pairs",
        "exposures",
        "primary_terminals",
        "provider_failed_terminals",
        "below_delivery_capacity_pairs",
    }
)
_FULL_POOL_TRACE_INDEX_FIELDS = frozenset(
    {
        "schema_version",
        "source_schema_version",
        "source_identity",
        "source_manifest_sha256",
        "contract_sha256",
        "message_order",
        "batch_order",
        "terminal_count",
        "terminal_identity_sha256",
        "partition_count",
        "partitions",
    }
)
_FULL_POOL_TRACE_PARTITION_FIELDS = frozenset(
    {
        "message_id",
        "time_step",
        "relative_path",
        "sha256",
        "bytes",
        "row_count",
        "terminal_identity_sha256",
    }
)
_FULL_POOL_TRACE_PARTITION_DOCUMENT_FIELDS = frozenset(
    {
        "schema_version",
        "source_identity",
        "source_manifest_sha256",
        "message_id",
        "time_step",
        "row_count",
        "terminal_identity_sha256",
        "rows",
    }
)
_IMPLEMENTATION_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{7,40}$")
_REPORT_PAYLOAD_V1_FIELDS = frozenset(
    {
        "schema_version",
        "title",
        "source_lineage",
        "ranking_weight",
        "prompt_model",
        "row_counts",
        "trace_row_count",
        "downloads",
        "claim_boundary",
        "production_deploy_eligible",
    }
)
_REPORT_PAYLOAD_V2_FIELDS = _REPORT_PAYLOAD_V1_FIELDS | {"mechanism_presentation"}
_MECHANISM_PRESENTATION_FIELDS = frozenset(
    {"schema_version", "semantic_set_identity_sha256", "masters"}
)
_REPORT_MANIFEST_SCHEMA = "concurrent-robustness-report-candidate-manifest-v1"
_RELEASE_EVIDENCE_SCHEMA = "concurrent-robustness-report-release-evidence-v1"
_STUDY_MANIFEST_SCHEMA = "concurrent-robustness-study-artifact-manifest-v1"
_STUDY_VALIDATION_SCHEMA = "concurrent-robustness-complete-validation-v1"
_CLOSED_STUDY_ROOT_SUFFIX = ".study-root"
_WEIGHT_SCHEMA = "concurrent-ranking-weight-sensitivity-v1"
_PROMPT_MODEL_SCHEMA = "concurrent-prompt-model-robustness-analysis-v1"
_CLAIM_AUDIT_SCHEMA = "concurrent-robustness-claim-audit-v1"
_TRACE_ENVELOPE_SCHEMA = "concurrent-robustness-trace-envelope-v1"
_TRACE_ENCODING = "gzip+base64"
_TRACE_ROW_COUNT = 1800
_MAX_TRACE_UNCOMPRESSED_BYTES = 20 * 1024 * 1024
_MAX_TRACE_COMPRESSED_BYTES = 4 * 1024 * 1024
_MAX_REPORT_HTML_BYTES = 3 * 1024 * 1024
_TRACE_ENVELOPE_FIELDS = {
    "schema",
    "encoding",
    "uncompressed_byte_length",
    "sha256",
    "row_count",
    "payload",
}
_TRACE_SCRIPT_OPEN = '<script type="application/json" data-testid="run-trace-rows-data">'
_TRACE_SCRIPT_PATTERN = re.compile(
    r'<script\b(?=[^>]*\bdata-testid="run-trace-rows-data")[^>]*>(.*?)</script>',
    re.DOTALL,
)

_STUDY_FILES = {
    "artifact_manifest.json",
    "claim_audit.json",
    "prompt_model_analysis.json",
    "prompt_model_cell_evidence.json",
    "ranking_weight_sensitivity.json",
    "study_manifest.json",
    "validation_report.json",
}
_STUDY_HASHED_FILES = _STUDY_FILES - {"artifact_manifest.json"}

_REPORT_PAYLOAD = "concurrent_robustness_report_payload.json"
_WEIGHT_JSON = "ranking_weight_sensitivity.json"
_PROMPT_MODEL_JSON = "prompt_model_analysis.json"
_CLAIM_AUDIT_JSON = "robustness_claim_audit.json"
_STUDY_VALIDATION_JSON = "robustness_study_validation.json"
_WEIGHT_MESSAGE_CSV = "ranking_weight_message_summary.csv"
_WEIGHT_BATCH_CSV = "ranking_weight_batch_diagnostics.csv"
_SHARED_SEED_CSV = "prompt_model_shared_seed_summary.csv"
_PROMPT_MESSAGE_CSV = "prompt_model_message_summary.csv"
_PROMPT_TRAJECTORY_CSV = "prompt_model_trajectory_summary.csv"
_PROMPT_GROWTH_CSV = "prompt_model_campaign_growth.csv"
_THRESHOLD_CSV = "prompt_model_practical_thresholds.csv"
_RELEASE_EVIDENCE_JSON = "release_evidence.json"
_PROJECT_EVIDENCE_MMD = "project-evidence-chain.mmd"
_BATCH_MECHANISM_MMD = "real-batch-mechanism.mmd"
_PROMPT_MODEL_FACTORIAL_MMD = "prompt-model-factorial.mmd"
_READER_MERMAID_DOWNLOADS = {
    "project_evidence_chain_mermaid": _PROJECT_EVIDENCE_MMD,
    "batch_mechanism_mermaid": _BATCH_MECHANISM_MMD,
    "prompt_model_factorial_mermaid": _PROMPT_MODEL_FACTORIAL_MMD,
}
_SEMANTIC_MERMAID_DOWNLOADS = {
    "mechanism_sample_first_mermaid": "mechanism-sample-first.mmd",
    "mechanism_pair_formation_mermaid": "mechanism-pair-formation.mmd",
    "mechanism_independent_delivery_mermaid": "mechanism-independent-delivery.mmd",
    "mechanism_exposure_decisions_mermaid": "mechanism-exposure-decisions.mmd",
    "mechanism_feedback_boundary_mermaid": "mechanism-feedback-boundary.mmd",
    "real_batch_mechanism_mermaid": _BATCH_MECHANISM_MMD,
    "prompt_model_factorial_mermaid": _PROMPT_MODEL_FACTORIAL_MMD,
}

_WEIGHT_MESSAGE_FIELDS = (
    "scenario_id",
    "message_id",
    "transfer_from",
    "transfer_to",
    "transfer_mass",
    "base_network_relevance_weight",
    "campaign_engaged_neighbor_signal_weight",
    "normalized_message_user_fit_weight",
    "mean_jaccard_distance",
    "auc_jaccard_distance",
    "first_divergent_batch",
)
_WEIGHT_BATCH_FIELDS = (
    "scenario_id",
    "message_id",
    "time_step",
    "jaccard_distance",
    "entered_user_count",
    "exited_user_count",
    "first_divergent_rank",
    "mean_absolute_rank_delta",
    "max_absolute_rank_delta",
)
_SHARED_SEED_FIELDS = (
    "cell_id",
    "prompt_variant",
    "requested_model",
    "message_id",
    "observation_count",
    "engage_rate",
    "mean_probability",
    "mean_confidence",
)
_PROMPT_MESSAGE_FIELDS = (
    "cell_id",
    "prompt_variant",
    "requested_model",
    "message_id",
    "actual_exposures",
    "successful_primary_decisions",
    "provider_failures",
    "positive_actions",
    "exposure_engagement_rate",
    "decision_engagement_rate",
    "mean_probability_successful_decisions",
    "first_divergent_batch_from_baseline_cell",
    "terminal_audience_overlap_count_with_baseline_cell",
    "terminal_audience_jaccard_similarity_with_baseline_cell",
    "terminal_audience_jaccard_distance_from_baseline_cell",
    "terminal_unique_positive_users",
)
_PROMPT_TRAJECTORY_FIELDS = (
    "cell_id",
    "prompt_variant",
    "requested_model",
    "message_id",
    "time_step",
    "batch_actual_exposures",
    "batch_successful_primary_decisions",
    "batch_provider_failures",
    "batch_positive_actions",
    "batch_exposure_engagement_rate",
    "batch_decision_engagement_rate",
    "cumulative_actual_exposures",
    "cumulative_successful_primary_decisions",
    "cumulative_provider_failures",
    "cumulative_positive_actions",
    "cumulative_exposure_engagement_rate",
    "cumulative_decision_engagement_rate",
    "batch_audience_jaccard_distance_from_baseline_cell",
    "cumulative_audience_jaccard_distance_from_baseline_cell",
)
_PROMPT_GROWTH_FIELDS = (
    "cell_id",
    "prompt_variant",
    "requested_model",
    "time_step",
    "cumulative_campaign_deduplicated_positive_user_count",
)
_THRESHOLD_FIELDS = (
    "comparison_id",
    "domain",
    "metric",
    "observed_difference",
    "absolute_difference",
    "threshold",
    "classification",
)

_COMPONENT_LABELS = {
    "base_network_relevance": "Network relevance",
    "campaign_engaged_neighbor_signal": "Campaign feedback",
    "normalized_message_user_fit": "Message–user fit",
}
_SERIES_STYLES = (
    {"color": "#155e75", "dash": "", "marker": "circle"},
    {"color": "#b45309", "dash": "12 6", "marker": "square"},
    {"color": "#4d7c0f", "dash": "3 5", "marker": "triangle"},
    {"color": "#7c3aed", "dash": "16 5 3 5", "marker": "diamond"},
    {"color": "#be123c", "dash": "8 4", "marker": "cross"},
    {"color": "#334155", "dash": "2 4", "marker": "plus"},
)
_PROMPT_STYLES = {
    "P0": _SERIES_STYLES[0],
    "P1": _SERIES_STYLES[1],
    "P2": _SERIES_STYLES[2],
    "P3": _SERIES_STYLES[3],
}

_PROMPT_PRESENTATION_COPY = {
    "zh-CN": {
        "prompt.title": "Prompt-Model 稳健性",
        "prompt.lead": "每个 model panel 只显示 P0-P3 四条曲线。后续路径是描述性结果；只有共享 seed 的 Batch 0 Decisions 构成预声明直接配对 panel。",
        "prompt.panel_note": "四条曲线对应相同声明信息集与输出合同的受控 Prompt 变体。",
        "contract.title": "Prompt-Model 实验合同",
        "contract.lead": "P0-P3 是相同声明信息集与输出合同的受控变体，不代表结果相同或统计等价。",
        "contract.cells": "独立 execution cells",
        "contract.slices": "message-level reporting slices",
        "contract.dimension_note": "Message 是每个 cell 内的报告维度，不是额外独立运行。",
        "contract.token": "Stable token",
        "contract.hash_summary": "展开 canonical hash",
        "contract.details": "实现身份",
        "contract.models": "该 Prompt 与 {model_count} 个 qualified models 各形成一个 cell。",
        "variant.baseline.label": "baseline",
        "variant.baseline.body": "基线 Prompt，复用当前 Primary Prompt contract。",
        "variant.wording_only.label": "wording-only",
        "variant.wording_only.body": "只改变措辞，不改变字段顺序、task、action semantics 或输出 schema。",
        "variant.information_order_only.label": "information-order-only",
        "variant.information_order_only.body": "只重排同一信息，不增加、删除或替换声明可见字段。",
        "variant.structured_rubric_only.label": "structured-rubric-only",
        "variant.structured_rubric_only.body": "只增加结构化核对 rubric；不请求、不输出也不持久化 chain-of-thought。",
        "common.summary": "共同声明信息集与输出合同",
        "common.note": "以下内容直接投影自 PromptContractRegistry。页面不展示 per-user rendered Prompt、raw Provider payload 或 raw response。",
        "common.fields": "LLM 可见字段 allowlist",
        "common.task": "Task semantics",
        "common.actions": "Action semantics",
        "common.output": "Structured output contract",
        "common.output_fields": "Required fields",
        "common.output_actions": "Action values",
        "common.engage_rules": "Engage-action rules",
        "scope.direct.title": "Batch 0 direct comparison",
        "scope.direct.body": "共享 seed 的同一 user-message panel 用于预声明直接配对比较。",
        "scope.paths.title": "Later realized path",
        "scope.paths.body": "Batch 1 起每个 execution cell 只有一条 realized path；路径不是重复运行或随机性估计。",
        "scope.shadow.title": "Primary-only factorial",
        "scope.shadow.body": "{cell_count} cells 只运行 Primary。Historical Demographic Shadow 保留在历史 Formal source，不属于该 factorial。",
        "diagram.heading": "从受控 Prompt 到报告切片",
        "diagram.lead": "Prompt 与 model 定义 execution cell；message 只展开同一 cell 的报告视图。",
        "diagram.title": "Prompt-Model factorial 设计",
        "diagram.description": "{prompt_count} 个受控 Prompt 与 {model_count} 个 qualified models 形成 {cell_count} 个独立 cells。每个 cell 共享 sample、graph、messages、seeds 和 ranking policy，形成一条 realized path，并按 {message_count} 条 message 展开 {slice_count} 个报告切片。",
        "diagram.node.Contract": "相同声明字段、task、action semantics 与输出 schema",
        "diagram.node.P0": "P0 baseline",
        "diagram.node.P1": "P1 wording-only",
        "diagram.node.P2": "P2 information-order-only",
        "diagram.node.P3": "P3 structured-rubric-only",
        "diagram.node.Models": "{model_count} 个 qualified models",
        "diagram.node.Cross": "Cartesian product",
        "diagram.node.Cells": "{cell_count} 个独立 Prompt-Model cells",
        "diagram.node.Runtime": "相同 sample、graph、messages、seeds 与 ranking policy",
        "diagram.node.Count": "每 cell {per_cell} 个 Primary judgments",
        "diagram.node.Total": "{total} 个 logical judgments",
        "diagram.node.Direct": "Batch 0 shared-seed direct panel",
        "diagram.node.Paths": "每 cell 一条 {horizon}-batch realized path",
        "diagram.node.Views": "{slice_count} 个 message-level reporting slices",
        "diagram.source.summary": "查看 Mermaid 语义母版",
        "diagram.source.note": "页面不运行 Mermaid。两种语言使用相同 node IDs；源代码只用于审核和设计交接。",
        "diagram.fallback.title": "文本路径",
        "diagram.fallback.contract": "共同合同只分出 P0 baseline、P1 wording-only、P2 information-order-only 与 P3 structured-rubric-only。",
        "diagram.fallback.cells": "{prompt_count} 个 Prompt 与 {model_count} 个 qualified models 做 Cartesian product，形成 {cell_count} 个独立 execution cells。",
        "diagram.fallback.runtime": "每个 cell 使用相同 sample、graph、三条 messages、seeds 与 ranking policy，完成一条 realized path。",
        "diagram.fallback.reporting": "Batch 0 是直接配对 panel；{cell_count} cells 再按 {message_count} 条 message 展开 {slice_count} 个 reporting slices，message 不是额外运行。",
    },
    "en-US": {
        "prompt.title": "Prompt-Model robustness",
        "prompt.lead": "Each model panel shows only the four P0-P3 series. Later paths are descriptive; only shared-seed Batch 0 Decisions form the predeclared direct paired panel.",
        "prompt.panel_note": "The four series are controlled Prompt variants with the same declared information and output contract.",
        "contract.title": "Prompt-Model experiment contract",
        "contract.lead": "P0-P3 are controlled variants with the same declared information and output contract. This does not claim equal results or statistical equivalence.",
        "contract.cells": "independent execution cells",
        "contract.slices": "message-level reporting slices",
        "contract.dimension_note": "Message is a reporting dimension inside each cell, not an additional independent run.",
        "contract.token": "Stable token",
        "contract.hash_summary": "Show canonical hash",
        "contract.details": "Implementation identity",
        "contract.models": "This Prompt forms one cell with each of the {model_count} qualified models.",
        "variant.baseline.label": "baseline",
        "variant.baseline.body": "The baseline Prompt reuses the current Primary Prompt contract.",
        "variant.wording_only.label": "wording-only",
        "variant.wording_only.body": "Changes wording only, without changing field order, task, action semantics, or output schema.",
        "variant.information_order_only.label": "information-order-only",
        "variant.information_order_only.body": "Reorders the same information only, without adding, removing, or replacing declared visible fields.",
        "variant.structured_rubric_only.label": "structured-rubric-only",
        "variant.structured_rubric_only.body": "Adds only a structured checking rubric. It does not request, output, or persist chain-of-thought.",
        "common.summary": "Shared declared information and output contract",
        "common.note": "The content below is projected directly from PromptContractRegistry. The page does not expose per-user rendered Prompts, raw Provider payloads, or raw responses.",
        "common.fields": "LLM-visible field allowlist",
        "common.task": "Task semantics",
        "common.actions": "Action semantics",
        "common.output": "Structured output contract",
        "common.output_fields": "Required fields",
        "common.output_actions": "Action values",
        "common.engage_rules": "Engage-action rules",
        "scope.direct.title": "Batch 0 direct comparison",
        "scope.direct.body": "The same shared-seed user-message panel supports the predeclared direct paired comparison.",
        "scope.paths.title": "Later realized path",
        "scope.paths.body": "From Batch 1, each execution cell has one realized path. A path is not a repeated run or an estimate of model randomness.",
        "scope.shadow.title": "Primary-only factorial",
        "scope.shadow.body": "The {cell_count} cells run Primary only. Historical Demographic Shadow remains in the historical Formal source and is outside this factorial.",
        "diagram.heading": "From controlled Prompts to reporting slices",
        "diagram.lead": "Prompt and model define an execution cell. Message only expands reporting views inside that cell.",
        "diagram.title": "Prompt-Model factorial design",
        "diagram.description": "{prompt_count} controlled Prompts and {model_count} qualified models form {cell_count} independent cells. Every cell shares the sample, graph, messages, seeds, and ranking policy, produces one realized path, and expands across {message_count} messages into {slice_count} reporting slices.",
        "diagram.node.Contract": "Same declared fields, task, action semantics, and output schema",
        "diagram.node.P0": "P0 baseline",
        "diagram.node.P1": "P1 wording-only",
        "diagram.node.P2": "P2 information-order-only",
        "diagram.node.P3": "P3 structured-rubric-only",
        "diagram.node.Models": "{model_count} qualified models",
        "diagram.node.Cross": "Cartesian product",
        "diagram.node.Cells": "{cell_count} independent Prompt-Model cells",
        "diagram.node.Runtime": "Same sample, graph, messages, seeds, and ranking policy",
        "diagram.node.Count": "{per_cell} Primary judgments per cell",
        "diagram.node.Total": "{total} logical judgments",
        "diagram.node.Direct": "Batch 0 shared-seed direct panel",
        "diagram.node.Paths": "One realized {horizon}-batch path per cell",
        "diagram.node.Views": "{slice_count} message-level reporting slices",
        "diagram.source.summary": "View the Mermaid semantic master",
        "diagram.source.note": "The page does not run Mermaid. Both languages use the same node IDs; source code is provided only for review and design handoff.",
        "diagram.fallback.title": "Text path",
        "diagram.fallback.contract": "The shared contract branches only into P0 baseline, P1 wording-only, P2 information-order-only, and P3 structured-rubric-only.",
        "diagram.fallback.cells": "{prompt_count} Prompts cross {model_count} qualified models to form {cell_count} independent execution cells.",
        "diagram.fallback.runtime": "Each cell uses the same sample, graph, three messages, seeds, and ranking policy to complete one realized path.",
        "diagram.fallback.reporting": "Batch 0 is the direct paired panel. The {cell_count} cells then expand across {message_count} messages into {slice_count} reporting slices; message is not another run.",
    },
}

_READER_DIAGRAM_COPY = {
    "zh-CN": {
        "project.heading": "项目证据如何抵达当前网页",
        "project.lead": "从固定研究输入到不可变发布，每条箭头都对应一个可验证的运行或发布边界。",
        "project.title": "项目证据链",
        "project.description": "Research Sample、互动图与三条 message 进入 Concurrent runtime。曝光后的 DecisionInput 由结构化 Decision function 返回结果，Historical Formal evidence 与 Robustness study root 再由 Report Module 组合并完成不可变发布。",
        "project.node.Inputs": "Research Sample、互动图与三条 messages",
        "project.node.Runner": "Concurrent 实验生命周期",
        "project.node.Kernel": "批次排序与曝光",
        "project.node.Adapter": "结构化 Decision function",
        "project.node.Formal": "Historical Formal source",
        "project.node.Study": "Robustness evidence study",
        "project.node.Weight": "{weight_point_count} 个 Ranking Weight points\n零 Provider calls",
        "project.node.Matrix": "P0-P3 × {model_count} models\nPrimary-only",
        "project.node.Root": "Immutable study root",
        "project.node.Report": "Report Module",
        "project.node.Release": "Immutable release closure",
        "project.node.Canonical": "Canonical webpage",
        "project.edge.decision_input": "曝光后形成 DecisionInput",
        "project.edge.decision": "返回 Structured Decision",
        "project.edge.persist": "持久化 runtime evidence",
        "project.legend.runtime": "Runtime 调用路径",
        "project.legend.evidence": "已关闭 evidence",
        "project.legend.release": "不可变发布路径",
        "project.source.summary": "查看项目证据链 Mermaid 语义母版",
        "project.source.note": "页面不运行 Mermaid。Mermaid 与 inline SVG 使用相同 node 和 edge IDs，供审核与设计交接。",
        "project.fallback.title": "项目证据链文本路径",
        "project.fallback.inputs": "固定 Research Sample、互动图和三条 messages 进入 Concurrent 实验生命周期与批次 runtime。",
        "project.fallback.decision": "只有 exposure 后的 DecisionInput 才进入结构化 Decision function；Decision 返回 runtime。",
        "project.fallback.formal": "实验 runtime 持久化 Historical Formal source；Robustness evidence study 从该 source 生成 Ranking Weight 与 Primary-only Prompt-Model evidence。",
        "project.fallback.root": "两个 Robustness 分支共同关闭为 immutable study root。",
        "project.fallback.publish": "Report Module 同时读取 Historical Formal source 与 study root；Release 完成不可变闭包后发布 canonical webpage。",
        "batch.heading": "一个真实批次如何关闭并反馈",
        "batch.lead": "三条 message 独立排序，selected pairs 全部到达当前 mode 的 required terminal 后，campaign feedback 才能提交给下一批。",
        "batch.title": "Concurrent Message 真实批次机制",
        "batch.description": "Batch start 先冻结 campaign snapshot。Batch 0 使用同一 seed union，并按 message 独立补足 Top20；后续是三条独立 Per-Message Top20。每个 user-message pair 最多 exposure 一次，ranking 先于 exposure 与 Decision。只有 terminal succeeded Primary 的 like、comment 或 share 按 user_id 跨 message 去重，并在 full-batch barrier 关闭后成为下一批的 ranking context。",
        "batch.node.Input": "固定 sample、互动图与三条 messages",
        "batch.node.Freeze": "Batch start 冻结 campaign snapshot",
        "batch.node.Batch": "Batch 0？",
        "batch.node.Seed": "Shared Seed Launch\n三条 message 使用相同 seeds",
        "batch.node.Fill": "各 message 独立补足到 Top{delivery_capacity}",
        "batch.node.Rank1": "Message 1 独立 Per-Message Top{delivery_capacity}\noverlap allowed",
        "batch.node.Rank2": "Message 2 独立 Per-Message Top{delivery_capacity}\noverlap allowed",
        "batch.node.Rank3": "Message 3 独立 Per-Message Top{delivery_capacity}\noverlap allowed",
        "batch.node.Exposure": "Per-message exposure\n每个 user-message pair 最多一次",
        "batch.node.Primary": "Primary Decision",
        "batch.node.Shadow": "Shadow Decision\n仅 Historical Formal，report-only",
        "batch.node.HistoricalMode": "Historical required terminals\nPrimary + Shadow",
        "batch.node.RobustnessMode": "Robustness required terminals\nPrimary-only",
        "batch.node.Positive": "terminal succeeded Primary\naction ∈ like / comment / share？",
        "batch.node.Terminal": "所有 selected pairs 到达 required terminal set",
        "batch.node.Collect": "收集 positive user_id",
        "batch.node.NoFeedback": "ignore / provider_failed\n不产生 campaign feedback",
        "batch.node.Pending": "完成 pending set\n允许为空",
        "batch.node.Barrier": "Full-batch barrier closed",
        "batch.node.Join": "AND：barrier closed + pending set finalized",
        "batch.node.Commit": "Commit campaign set\n按 user_id 跨 message 去重",
        "batch.node.Next1": "下一批 Message 1 独立 ranking context",
        "batch.node.Next2": "下一批 Message 2 独立 ranking context",
        "batch.node.Next3": "下一批 Message 3 独立 ranking context",
        "batch.edge.yes": "是",
        "batch.edge.no": "否",
        "batch.edge.historical": "仅 Historical Formal",
        "batch.edge.positive": "是：加入 user_id",
        "batch.edge.no_feedback": "否：不反馈",
        "batch.edge.next": "仅下一批 ranking context",
        "batch.legend.ranking": "三条独立 ranking channel",
        "batch.legend.required": "Required runtime flow",
        "batch.legend.shadow": "Historical report-only flow",
        "batch.legend.next": "Next-batch context only",
        "batch.source.summary": "查看真实批次机制 Mermaid 语义母版",
        "batch.source.note": "页面不运行 Mermaid。Edge metadata 明确 condition、timing、effect 与 provenance；不存在 Shadow、ignore 或 provider_failed 指向 campaign set 的 feedback edge。",
        "batch.fallback.title": "真实批次机制文本路径",
        "batch.fallback.freeze": "每批先冻结 campaign snapshot；Batch 0 使用相同 seed union，并由每条 message 独立补足到 Top{delivery_capacity}。",
        "batch.fallback.rank": "Batch 1 起三条 Per-Message Top{delivery_capacity} 分别排序，允许跨 message overlap；ranking 总在 exposure 与 Decision 之前。",
        "batch.fallback.exposure": "同一 user-message pair 最多 exposure 一次。Historical Formal 要求 Primary + Shadow terminal；Robustness cell 只要求 Primary terminal。",
        "batch.fallback.feedback": "只有 terminal succeeded Primary 的 like、comment、share 能贡献 pending set；Shadow、ignore 与 provider_failed 不反馈。",
        "batch.fallback.barrier": "所有 selected pairs 通过 full-batch barrier，且 pending set 完成后，才按 user_id 跨 message 去重并 commit campaign set。",
        "batch.fallback.next": "Committed campaign set 只作为下一批三条独立 rankings 的 context；它不注入 queue，也不回写 same-batch ranking。",
    },
    "en-US": {
        "project.heading": "How project evidence reaches this webpage",
        "project.lead": "From fixed research inputs to immutable publication, every arrow maps to a verifiable runtime or release boundary.",
        "project.title": "Project evidence chain",
        "project.description": "The Research Sample, interaction graph, and three messages enter the Concurrent runtime. After exposure, the Structured Decision function returns a result for each DecisionInput. Historical Formal evidence and the Robustness study root are then composed by the Report Module and closed into an immutable release.",
        "project.node.Inputs": "Research Sample, interaction graph, and three messages",
        "project.node.Runner": "Concurrent experiment lifecycle",
        "project.node.Kernel": "Batch ranking and exposure",
        "project.node.Adapter": "Structured Decision function",
        "project.node.Formal": "Historical Formal source",
        "project.node.Study": "Robustness evidence study",
        "project.node.Weight": "{weight_point_count} Ranking Weight points\nzero Provider calls",
        "project.node.Matrix": "P0-P3 × {model_count} models\nPrimary-only",
        "project.node.Root": "Immutable study root",
        "project.node.Report": "Report Module",
        "project.node.Release": "Immutable release closure",
        "project.node.Canonical": "Canonical webpage",
        "project.edge.decision_input": "DecisionInput after exposure",
        "project.edge.decision": "Structured Decision returned",
        "project.edge.persist": "Persisted runtime evidence",
        "project.legend.runtime": "Runtime call path",
        "project.legend.evidence": "Closed evidence",
        "project.legend.release": "Immutable publication path",
        "project.source.summary": "View the project evidence-chain Mermaid semantic master",
        "project.source.note": "The page does not run Mermaid. The Mermaid source and inline SVG share the same node and edge IDs for review and design handoff.",
        "project.fallback.title": "Project evidence-chain text path",
        "project.fallback.inputs": "The fixed Research Sample, interaction graph, and three messages enter the Concurrent experiment lifecycle and batch runtime.",
        "project.fallback.decision": "Only a post-exposure DecisionInput reaches the Structured Decision function; the Decision returns to the runtime.",
        "project.fallback.formal": "The experiment runtime persists the Historical Formal source. The Robustness evidence study derives Ranking Weight and Primary-only Prompt-Model evidence from that source.",
        "project.fallback.root": "The two Robustness branches close into one immutable study root.",
        "project.fallback.publish": "The Report Module reads both the Historical Formal source and the study root. Release closes immutable evidence before publishing the canonical webpage.",
        "batch.heading": "How one real batch closes and feeds forward",
        "batch.lead": "Three messages rank independently. Campaign feedback can be committed to the next batch only after every selected pair reaches the required terminal for the current mode.",
        "batch.title": "Concurrent Message real batch mechanism",
        "batch.description": "Batch start freezes the campaign snapshot. Batch 0 uses one shared seed union with independent per-message fill to Top20; later batches use three independent Per-Message Top20 rankings. Each user-message pair is exposed at most once, and ranking precedes exposure and Decision. Only terminal succeeded Primary like, comment, or share actions are deduplicated by user_id across messages and become next-batch ranking context after the full-batch barrier closes.",
        "batch.node.Input": "Fixed sample, interaction graph, and three messages",
        "batch.node.Freeze": "Freeze campaign snapshot at batch start",
        "batch.node.Batch": "Batch 0?",
        "batch.node.Seed": "Shared Seed Launch\nthe same seeds for all three messages",
        "batch.node.Fill": "Independent per-message fill to Top{delivery_capacity}",
        "batch.node.Rank1": "Message 1 independent Per-Message Top{delivery_capacity}\noverlap allowed",
        "batch.node.Rank2": "Message 2 independent Per-Message Top{delivery_capacity}\noverlap allowed",
        "batch.node.Rank3": "Message 3 independent Per-Message Top{delivery_capacity}\noverlap allowed",
        "batch.node.Exposure": "Per-message exposure\nonce per user-message pair",
        "batch.node.Primary": "Primary Decision",
        "batch.node.Shadow": "Shadow Decision\nHistorical Formal only, report-only",
        "batch.node.HistoricalMode": "Historical required terminals\nPrimary + Shadow",
        "batch.node.RobustnessMode": "Robustness required terminals\nPrimary-only",
        "batch.node.Positive": "terminal succeeded Primary\naction in like / comment / share?",
        "batch.node.Terminal": "Every selected pair reaches its required terminal set",
        "batch.node.Collect": "Collect positive user_id values",
        "batch.node.NoFeedback": "ignore / provider_failed\nno campaign feedback",
        "batch.node.Pending": "Finalize the pending set\nit may be empty",
        "batch.node.Barrier": "Full-batch barrier closed",
        "batch.node.Join": "AND: barrier closed + pending set finalized",
        "batch.node.Commit": "Commit campaign set\ndeduplicated by user_id across messages",
        "batch.node.Next1": "Next-batch Message 1 independent ranking context",
        "batch.node.Next2": "Next-batch Message 2 independent ranking context",
        "batch.node.Next3": "Next-batch Message 3 independent ranking context",
        "batch.edge.yes": "yes",
        "batch.edge.no": "no",
        "batch.edge.historical": "Historical Formal only",
        "batch.edge.positive": "yes: add user_id",
        "batch.edge.no_feedback": "no: no feedback",
        "batch.edge.next": "next-batch ranking context only",
        "batch.legend.ranking": "Three independent ranking channels",
        "batch.legend.required": "Required runtime flow",
        "batch.legend.shadow": "Historical report-only flow",
        "batch.legend.next": "Next-batch context only",
        "batch.source.summary": "View the real batch-mechanism Mermaid semantic master",
        "batch.source.note": "The page does not run Mermaid. Edge metadata states condition, timing, effect, and provenance. No feedback edge connects Shadow, ignore, or provider_failed to the campaign set.",
        "batch.fallback.title": "Real batch-mechanism text path",
        "batch.fallback.freeze": "Each batch first freezes the campaign snapshot. Batch 0 uses the same seed union, then each message independently fills to Top{delivery_capacity}.",
        "batch.fallback.rank": "From Batch 1, three Per-Message Top{delivery_capacity} rankings run independently and allow cross-message overlap. Ranking always precedes exposure and Decision.",
        "batch.fallback.exposure": "A user-message pair is exposed at most once. Historical Formal requires Primary + Shadow terminals; a Robustness cell requires Primary only.",
        "batch.fallback.feedback": "Only terminal succeeded Primary like, comment, or share actions can contribute to the pending set. Shadow, ignore, and provider_failed never feed back.",
        "batch.fallback.barrier": "Only after every selected pair passes the full-batch barrier and the pending set is finalized may the campaign set be deduplicated by user_id across messages and committed.",
        "batch.fallback.next": "The committed campaign set is context for three independent next-batch rankings only. It neither injects users into a queue nor rewrites same-batch ranking.",
    },
}


_SEMANTIC_ROBUSTNESS_COPY = {
    "zh-CN": {
        "semantic.hero.kicker": "增量稳健性证据",
        "semantic.hero.title": "在不改写历史运行的前提下检验排序政策与 Prompt-Model 稳健性",
        "semantic.hero.lead": "固定同一份样本、互动图与每个 cell 的单条已实现路径。这些描述性比较不使用 ground truth，也不作因果、Calibration 或统计等价声明。",
        "semantic.lineage.formal.label": "Historical Concurrent Formal 来源",
        "semantic.lineage.formal.body": "机制、本次运行、字段 lineage、Demographic Shadow 比较与 Primary + Shadow barrier 继续由这份历史证据提供。",
        "semantic.lineage.study.label": "不可变完整 study root",
        "semantic.lineage.study.body": "排序权重与 Primary-only 4 Prompt × 4 model 证据来自此处，没有重新运行 Shadow 条件。",
        "semantic.lineage.shadow_warning": "Demographic Shadow 证据仍绑定历史 Formal 来源，不属于 factorial Prompt-Model 结果。",
        "semantic.weight.title": "排序权重敏感性",
        "semantic.weight.lead": "19 个预声明 simplex points 按六条转移曲线分组展示，candidate sets 与 feedback 保持冻结。",
        "semantic.weight.family.label": "可见权重转移组",
        "semantic.weight.family.network_feedback": "网络相关性与活动反馈",
        "semantic.weight.family.network_fit": "网络相关性与消息用户匹配",
        "semantic.weight.family.feedback_fit": "活动反馈与消息用户匹配",
        "semantic.weight.chart.title": "Top K Jaccard 距离",
        "semantic.weight.panel.note": "按冻结批次展示 Top K Jaccard 距离；精确表保留排名移动。",
        "semantic.weight.message_rows": "message-level Jaccard 精确摘要",
        "semantic.weight.batch_rows": "逐批进入、退出与排名移动精确诊断",
        "semantic.prompt.message.label": "消息",
        "semantic.prompt.metric.label": "动态指标",
        "semantic.prompt.denominator_aria": "Prompt-Model 分母",
        "semantic.prompt.metric.engagement": "累计曝光互动率",
        "semantic.prompt.metric.audience": "累计受众 Jaccard 距离",
        "semantic.prompt.shared.title": "共享 seed 的直接决策",
        "semantic.prompt.shared.lead": "二元 engage 是主要比较；probability 与 confidence 为辅助指标。表格跟随所选消息。",
        "semantic.prompt.growth.title": "活动层正向用户增长",
        "semantic.prompt.growth.lead": "增长按跨消息用户去重，因此单独展示，不误写成某条消息的结果。",
        "semantic.prompt.growth.panel": "跨消息去重的成功 Primary 正向用户。",
        "semantic.prompt.message_rows": "逐消息动态精确摘要",
        "semantic.prompt.threshold_rows": "practical-threshold 精确分类",
        "semantic.threshold.meaningful": "达到 practical threshold",
        "semantic.threshold.small": "小幅观测差异",
        "semantic.threshold.note": "低于 threshold 仅表示观测差异较小，不能建立统计等价。",
        "semantic.downloads.title": "已批准的稳健性下载",
        "semantic.downloads.lead": "配套 JSON、CSV 与 Mermaid 文件绑定本 candidate 的 schema、行数、hash 和精确值；不包含 raw Prompt、Provider payload、response 或 credential。",
        "semantic.chart.batch_axis": "批次序号",
        "semantic.chart.series_aria": "当前可见序列",
        "semantic.trace.loading": "正在加载持久化 trace 数据。",
        "semantic.trace.ready": "Trace 已就绪",
        "semantic.trace.rows": "条持久化记录",
        "semantic.trace.error": "Trace 数据不可用，筛选器与 drawer 保持禁用。",
        "semantic.common.rows": "行",
    },
    "en-US": {
        "semantic.hero.kicker": "Additive robustness evidence",
        "semantic.hero.title": "Ranking policy and Prompt-Model robustness without relabelling the historical run",
        "semantic.hero.lead": "One fixed sample, one fixed interaction graph, and one realized path per cell. These descriptive comparisons use no ground truth and make no causal, Calibration, or statistical-equivalence claim.",
        "semantic.lineage.formal.label": "Historical Concurrent Formal source",
        "semantic.lineage.formal.body": "Mechanism, Run Evidence, field lineage, Demographic Shadow comparison, and the Primary + Shadow barrier remain sourced here.",
        "semantic.lineage.study.label": "Immutable complete study root",
        "semantic.lineage.study.body": "Ranking Weight and Primary-only 4 Prompt × 4 model evidence come from this root. No Shadow condition was rerun.",
        "semantic.lineage.shadow_warning": "Demographic Shadow evidence remains bound to the historical Formal source; it is not a factorial Prompt-Model result.",
        "semantic.weight.title": "Ranking Weight Sensitivity",
        "semantic.weight.lead": "Nineteen predeclared simplex points are grouped into six transfer curves while candidate sets and feedback stay frozen.",
        "semantic.weight.family.label": "Visible weight-transfer family",
        "semantic.weight.family.network_feedback": "Network relevance and campaign feedback",
        "semantic.weight.family.network_fit": "Network relevance and message-user fit",
        "semantic.weight.family.feedback_fit": "Campaign feedback and message-user fit",
        "semantic.weight.chart.title": "Top K Jaccard distance",
        "semantic.weight.panel.note": "Top K Jaccard distance by frozen batch; rank movement remains in the exact-value table.",
        "semantic.weight.message_rows": "Exact message-level Jaccard summaries",
        "semantic.weight.batch_rows": "Exact per-batch entered, exited, and rank-movement diagnostics",
        "semantic.prompt.message.label": "Message",
        "semantic.prompt.metric.label": "Dynamic metric",
        "semantic.prompt.denominator_aria": "Prompt-Model denominators",
        "semantic.prompt.metric.engagement": "Cumulative exposure engagement rate",
        "semantic.prompt.metric.audience": "Cumulative audience Jaccard distance",
        "semantic.prompt.shared.title": "Shared-seed direct Decisions",
        "semantic.prompt.shared.lead": "Binary engage is primary; probability and confidence are secondary. Rows follow the selected message.",
        "semantic.prompt.growth.title": "Campaign-level positive-user growth",
        "semantic.prompt.growth.lead": "Growth is deduplicated across messages, so it stays outside message panels rather than being mislabelled as a message-specific outcome.",
        "semantic.prompt.growth.panel": "Campaign-deduplicated successful Primary-positive users.",
        "semantic.prompt.message_rows": "Exact per-message dynamic summaries",
        "semantic.prompt.threshold_rows": "Exact practical-threshold classifications",
        "semantic.threshold.meaningful": "practically meaningful",
        "semantic.threshold.small": "small observed difference",
        "semantic.threshold.note": "Below-threshold values are small observed differences only; they do not establish equivalence.",
        "semantic.downloads.title": "Approved robustness downloads",
        "semantic.downloads.lead": "Companion JSON, CSV, and Mermaid files bind to this candidate's schemas, row counts, hashes, and exact values. No raw Prompt, Provider payload, response, or credential is included.",
        "semantic.chart.batch_axis": "Batch index",
        "semantic.chart.series_aria": "Visible series",
        "semantic.trace.loading": "Loading persisted trace data.",
        "semantic.trace.ready": "Trace ready",
        "semantic.trace.rows": "persisted rows",
        "semantic.trace.error": "Trace data is unavailable. Filters and the drawer remain disabled.",
        "semantic.common.rows": "rows",
    },
}


_SEMANTIC_ZH_COPY = {
    "prompt.title": "提示词—模型稳健性",
    "prompt.lead": "每个模型面板只显示 P0–P3 四条曲线。后续路径属于描述性结果；只有共享种子的第 0 批次决策构成预声明直接配对面板。",
    "prompt.panel_note": "四条曲线对应相同声明信息集与输出合同的受控提示词变体。",
    "contract.title": "提示词—模型实验合同",
    "contract.lead": "P0–P3 是相同声明信息集与输出合同的受控变体，不代表结果相同或统计等价。",
    "contract.cells": "独立实验单元",
    "contract.slices": "逐消息报告切片",
    "contract.dimension_note": "消息是每个实验单元内的报告维度，不是额外独立运行。",
    "contract.token": "稳定版本标识",
    "contract.hash_summary": "展开规范哈希",
    "contract.details": "实现身份",
    "contract.models": "该提示词与 4 个合格模型各形成一个实验单元。",
    "variant.baseline.label": "基线",
    "variant.baseline.body": "基线提示词复用当前主决策提示词合同。",
    "variant.wording_only.label": "仅措辞变化",
    "variant.wording_only.body": "只改变措辞，不改变字段顺序、任务、行为语义或输出模式。",
    "variant.information_order_only.label": "仅信息顺序变化",
    "variant.information_order_only.body": "只重排同一信息，不增加、删除或替换声明可见字段。",
    "variant.structured_rubric_only.label": "仅结构化量表变化",
    "variant.structured_rubric_only.body": "只增加结构化核对量表；不请求、不输出也不持久化思维链。",
    "common.summary": "共同声明信息集与输出合同",
    "common.note": "以下内容直接投影自提示词合同注册表。页面不展示逐用户渲染提示词、原始 Provider 载荷或原始响应。",
    "common.fields": "LLM 可见字段允许列表",
    "common.task": "任务语义",
    "common.actions": "行为语义",
    "common.output": "结构化输出合同",
    "common.output_fields": "必需字段",
    "common.output_actions": "行为取值",
    "common.engage_rules": "互动判断—行为规则",
    "scope.direct.title": "第 0 批次直接比较",
    "scope.direct.body": "共享种子的同一用户—消息面板用于预声明直接配对比较。",
    "scope.paths.title": "后续已实现路径",
    "scope.paths.body": "从第 1 批次起，每个实验单元只有一条已实现路径；该路径不是重复运行或随机性估计。",
    "scope.shadow.title": "仅主决策析因实验",
    "scope.shadow.body": "16 个实验单元只运行主决策。历史人口属性影子决策保留在历史正式运行来源中，不属于该析因实验。",
    "diagram.heading": "从受控提示词到报告切片",
    "diagram.lead": "提示词与模型定义实验单元；消息只展开同一实验单元的报告视图。",
    "diagram.title": "提示词—模型析因设计",
    "diagram.description": "4 个受控提示词与 4 个合格模型形成 16 个独立实验单元。每个实验单元共享样本、互动图、消息、随机种子和排序政策，形成一条已实现路径，并按 3 条消息展开 48 个报告切片。",
    "diagram.node.Contract": "相同声明字段、任务、行为语义与输出模式",
    "diagram.node.P0": "P0 基线",
    "diagram.node.P1": "P1 仅措辞变化",
    "diagram.node.P2": "P2 仅信息顺序变化",
    "diagram.node.P3": "P3 仅结构化量表变化",
    "diagram.node.Models": "4 个合格模型",
    "diagram.node.Cross": "笛卡尔积",
    "diagram.node.Cells": "16 个独立提示词—模型实验单元",
    "diagram.node.Runtime": "相同样本、互动图、消息、随机种子与排序政策",
    "diagram.node.Count": "每个实验单元 1,800 个主决策判断",
    "diagram.node.Total": "28,800 个逻辑判断",
    "diagram.node.Direct": "第 0 批次共享种子直接比较面板",
    "diagram.node.Paths": "每个实验单元一条 30 批已实现路径",
    "diagram.node.Views": "48 个逐消息报告切片",
    "diagram.source.summary": "查看 Mermaid 语义母版",
    "diagram.source.note": "页面不运行 Mermaid。两种语言使用相同节点 ID；源代码只用于审核和设计交接。",
    "diagram.fallback.title": "文本路径",
    "diagram.fallback.contract": "共同合同只分出 P0 基线、P1 仅措辞变化、P2 仅信息顺序变化与 P3 仅结构化量表变化。",
    "diagram.fallback.cells": "4 个提示词与 4 个合格模型做笛卡尔积，形成 16 个独立实验单元。",
    "diagram.fallback.runtime": "每个实验单元使用相同样本、互动图、三条消息、随机种子与排序政策，完成一条已实现路径。",
    "diagram.fallback.reporting": "第 0 批次是直接配对面板；16 个实验单元再按 3 条消息展开 48 个报告切片，消息不是额外运行。",
    "semantic.hero.title": "在不改写历史运行的前提下检验排序政策与提示词—模型稳健性",
    "semantic.hero.lead": "固定同一份样本、互动图与每个实验单元的一条已实现路径。这些描述性比较不使用真实标签，也不作因果、校准或统计等价声明。",
    "semantic.lineage.formal.label": "历史并行消息正式运行来源",
    "semantic.lineage.formal.body": "机制、本次运行、字段来源链、人口属性影子比较与主决策—影子决策屏障继续由这份历史证据提供。",
    "semantic.lineage.study.label": "不可变完整研究根目录",
    "semantic.lineage.study.body": "排序权重与仅主决策的 4 提示词 × 4 模型证据来自此处，没有重新运行影子条件。",
    "semantic.lineage.shadow_warning": "人口属性影子证据仍绑定历史正式运行来源，不属于提示词—模型析因结果。",
    "semantic.weight.lead": "19 个预声明单纯形点按六条转移曲线分组展示，候选集与反馈保持冻结。",
    "semantic.weight.chart.title": "Top K Jaccard 距离",
    "semantic.weight.panel.note": "按冻结批次展示 Top K Jaccard 距离；精确表保留排名移动。",
    "semantic.weight.message_rows": "逐消息 Jaccard 精确摘要",
    "semantic.prompt.denominator_aria": "提示词—模型分母",
    "semantic.prompt.shared.title": "共享种子的直接决策",
    "semantic.prompt.shared.lead": "二元互动判断是主要比较；概率与置信度为辅助指标。表格跟随所选消息。",
    "semantic.prompt.growth.panel": "跨消息去重的成功主决策正向用户。",
    "semantic.prompt.threshold_rows": "实用阈值精确分类",
    "semantic.threshold.meaningful": "达到实用阈值",
    "semantic.threshold.note": "低于阈值仅表示观测差异较小，不能建立统计等价。",
    "semantic.downloads.lead": "配套 JSON、CSV 与 Mermaid 文件绑定本候选的模式、行数、哈希和精确值；不包含原始提示词、Provider 载荷、响应或凭证。",
    "semantic.trace.loading": "正在加载持久化决策轨迹数据。",
    "semantic.trace.ready": "决策轨迹已就绪",
    "semantic.trace.error": "决策轨迹数据不可用，筛选器与详情抽屉保持禁用。",
}


class _RobustnessReportPathError(ValueError):
    pass


class _RobustnessReportConflictError(ValueError):
    pass


class _RobustnessReportClosureError(ValueError):
    pass


@dataclass(frozen=True)
class _ClosedStudy:
    root: Path
    root_manifest: dict[str, Any]
    ranking: dict[str, Any]
    prompt_model: dict[str, Any]
    claims: dict[str, Any]
    validation: dict[str, Any]
    file_hashes: dict[str, str]


@dataclass(frozen=True)
class _ReportRows:
    weight_messages: list[dict[str, Any]]
    weight_batches: list[dict[str, Any]]
    shared_seed: list[dict[str, Any]]
    prompt_messages: list[dict[str, Any]]
    prompt_trajectories: list[dict[str, Any]]
    prompt_growth: list[dict[str, Any]]
    thresholds: list[dict[str, Any]]

    def counts(self) -> dict[str, int]:
        return {
            "ranking_weight_message_summary": len(self.weight_messages),
            "ranking_weight_batch_diagnostics": len(self.weight_batches),
            "prompt_model_shared_seed_summary": len(self.shared_seed),
            "prompt_model_message_summary": len(self.prompt_messages),
            "prompt_model_trajectory_summary": len(self.prompt_trajectories),
            "prompt_model_campaign_growth": len(self.prompt_growth),
            "prompt_model_practical_thresholds": len(self.thresholds),
        }


@dataclass(frozen=True)
class _PromptContractDisclosure:
    variant_id: str
    controlled_change: str
    prompt_version: str
    canonical_hash: str
    model_count: int


@dataclass(frozen=True)
class _PromptModelPresentation:
    contracts: tuple[_PromptContractDisclosure, ...]
    visible_field_allowlist: tuple[str, ...]
    task_semantics: tuple[str, ...]
    action_semantics: tuple[str, ...]
    output_schema_version: str
    output_fields: tuple[str, ...]
    output_action_values: tuple[str, ...]
    engage_action_rules: tuple[str, ...]
    prompt_count: int
    model_count: int
    cell_count: int
    message_count: int
    reporting_slice_count: int
    logical_judgments_per_cell: int
    logical_judgment_count: int
    horizon: int
    delivery_capacity: int
    weight_point_count: int


@dataclass(frozen=True)
class _DiagramNode:
    node_id: str
    label_key: str
    x: int
    y: int
    width: int
    height: int
    kind: str
    provenance: str
    mark_id: str = ""


@dataclass(frozen=True)
class _DiagramEdge:
    edge_id: str
    source: str
    target: str
    path: str
    condition: str
    timing: str
    effect: str
    provenance: str
    direction: str = "forward"
    style: str = "solid"
    label_key: str = ""
    label_x: int = 0
    label_y: int = 0
    label_width: int = 0
    mark_id: str = ""


@dataclass(frozen=True)
class _ProductionPresentationFacts:
    """Release-approved facts that the Report Module may present but must not decide."""

    release_id: str
    release_contract_schema: str
    canonical_endpoint: str
    production_evidence_schema: str
    formal_logical_judgments: int
    formal_physical_attempts: int
    provider_transport: str
    subscription_billed_cost_usd: float
    approved_downloads: Mapping[str, str]


@dataclass(frozen=True)
class _FullPoolProductionPresentationFacts:
    """v8 release facts presented by Report without moving eligibility knowledge here."""

    release_id: str
    release_contract_schema: str
    canonical_endpoint: str
    production_evidence_schema: str
    implementation_commit: str
    full_pool_source_identity: str
    full_pool_source_manifest_sha256: str
    distinct_users: int
    eligible_pairs: int
    exposures: int
    primary_terminals: int
    committed_batches: int
    candidate_ranking_rows: int
    campaign_exposure_coverage: int
    provider_failed_terminals: int
    logical_judgments: int
    physical_attempts: int
    provider_transport: str
    requested_model: str
    qualified_observed_model: str
    usage_complete_response_count: int
    subscription_billed_cost_usd: float
    approved_downloads: Mapping[str, str]


@dataclass(frozen=True)
class _PresentationBundle:
    report_payload: bytes
    report_html: bytes


@dataclass(frozen=True)
class _SemanticPresentationCandidate:
    """Non-persisted v4 projection awaiting the additive payload contract."""

    report_html: bytes
    mermaid_artifacts: Mapping[str, bytes]
    companion_artifacts: Mapping[str, bytes]
    production_deploy_eligible: bool
    provider_calls_during_composition: int
    image_generation_triggered: bool


@dataclass(frozen=True)
class _CandidateProjection:
    formal: ConcurrentMessageArtifactClosure
    study: _ClosedStudy
    manifest: ConcurrentRobustnessManifest
    manifest_sha256: str
    rows: _ReportRows
    prompt_model_presentation: _PromptModelPresentation
    report_payload: dict[str, Any]
    payloads: dict[str, bytes]


@dataclass(frozen=True)
class _FullPoolCandidateInputs:
    source: _ClosedFullPoolSource
    projection: _CandidateProjection
    bundle: Path
    historical_candidate: Path


@dataclass(frozen=True)
class _FullPoolCandidateFacts:
    root: Path
    manifest_sha256: str
    candidate_identity_sha256: str
    candidate_content_identity_sha256: str
    report_sha256: str
    payload_sha256: str
    evidence_sha256: str
    report_payload_schema_version: str
    implementation_commit: str
    source_lineage: Mapping[str, Any]
    source_lineage_identity_sha256: str
    presentation_bundle_identity_sha256: str
    presentation_inventory_identity_sha256: str
    mechanism_set_identity_sha256: str
    trace_index_sha256: str
    artifact_hashes: Mapping[str, str]
    approved_downloads: Mapping[str, str]


class _ReportPresentationInterface:
    """Package-internal seam for deterministic report composition and presentation stages."""

    def compose_candidate(
        self,
        *,
        formal_root: str | Path,
        study_root: str | Path,
        destination_dir: str | Path,
        reuse_existing: bool = False,
    ) -> Path:
        """Close two immutable lineages and create or reproduce one candidate atomically."""
        formal_path = Path(formal_root)
        study_path = Path(study_root)
        workspace_path = _workspace_root_for_study(study_path)
        manifest, manifest_payload, manifest_sha256 = _load_study_manifest(study_path)
        if reuse_existing and os.path.lexists(destination_dir):
            candidate, _ = self._validate_candidate_from_inputs(
                formal_root=formal_path,
                study_root=study_path,
                workspace_root=workspace_path,
                manifest=manifest,
                manifest_payload=manifest_payload,
                manifest_sha256=manifest_sha256,
                candidate_dir=destination_dir,
            )
            return candidate
        return self._compose_candidate_from_inputs(
            formal_root=formal_path,
            study_root=study_path,
            workspace_root=workspace_path,
            manifest=manifest,
            manifest_payload=manifest_payload,
            manifest_sha256=manifest_sha256,
            destination_dir=destination_dir,
        )

    def compose_semantic_candidate(
        self,
        *,
        formal_root: str | Path,
        study_root: str | Path,
        candidate_dir: str | Path,
    ) -> _SemanticPresentationCandidate:
        """Project validated v1 evidence into a non-promotable semantic candidate.

        This Interface intentionally returns HTML and seven Mermaid artifacts in
        memory. The additive payload and closure remain owned by the next release
        stage; this projection cannot authorize production deployment.
        """
        formal_path = Path(formal_root)
        study_path = Path(study_root)
        workspace_path = _workspace_root_for_study(study_path)
        manifest, manifest_payload, manifest_sha256 = _load_study_manifest(study_path)
        candidate, projection = self._validate_candidate_from_inputs(
            formal_root=formal_path,
            study_root=study_path,
            workspace_root=workspace_path,
            manifest=manifest,
            manifest_payload=manifest_payload,
            manifest_sha256=manifest_sha256,
            candidate_dir=candidate_dir,
        )
        candidate_before = _directory_file_hashes(candidate)
        semantic_candidate = _build_semantic_presentation_candidate(projection)
        if candidate_before != _directory_file_hashes(candidate):
            raise _RobustnessReportClosureError("semantic projection mutated the validation candidate")
        _assert_formal_unchanged(projection.formal, dict(projection.formal.artifact_hashes))
        _assert_study_unchanged(projection.study, dict(projection.study.file_hashes))
        return semantic_candidate

    def compose_presentation_candidate(
        self,
        *,
        formal_root: str | Path,
        study_root: str | Path,
        candidate_dir: str | Path,
        destination_dir: str | Path,
    ) -> Path:
        """Atomically materialize the approved semantic projection as payload v2."""
        formal_path = Path(formal_root)
        study_path = Path(study_root)
        workspace_path = _workspace_root_for_study(study_path)
        manifest, manifest_payload, manifest_sha256 = _load_study_manifest(study_path)
        candidate, projection = self._validate_candidate_from_inputs(
            formal_root=formal_path,
            study_root=study_path,
            workspace_root=workspace_path,
            manifest=manifest,
            manifest_payload=manifest_payload,
            manifest_sha256=manifest_sha256,
            candidate_dir=candidate_dir,
        )
        candidate_before = _directory_file_hashes(candidate)
        formal_before = dict(projection.formal.artifact_hashes)
        study_before = dict(projection.study.file_hashes)
        semantic_candidate = _build_semantic_presentation_candidate(projection)
        report_payload = _build_semantic_report_payload(projection.report_payload)
        payloads = _semantic_candidate_payloads(
            projection=projection,
            semantic_candidate=semantic_candidate,
            report_payload=report_payload,
        )
        destination = _publish_candidate_payloads(
            destination_dir=destination_dir,
            protected_roots=(formal_path, study_path, workspace_path, candidate),
            output_identity=manifest.output_identity,
            payloads=payloads,
            row_counts=projection.rows.counts(),
        )
        if candidate_before != _directory_file_hashes(candidate):
            raise _RobustnessReportClosureError("payload v2 composition mutated the payload v1 candidate")
        _assert_formal_unchanged(projection.formal, formal_before)
        _assert_study_unchanged(projection.study, study_before)
        return destination

    def compose_full_pool_presentation_bundle(
        self,
        *,
        full_pool_source_root: str | Path,
        full_pool_manifest_sha256: str,
        historical_formal_root: str | Path,
        historical_study_root: str | Path,
        historical_candidate_dir: str | Path,
        destination_dir: str | Path,
    ) -> Path:
        """Compose one closed, zero-call, non-promotable Full-Pool presentation bundle."""
        full_pool_path = Path(full_pool_source_root)
        formal_path = Path(historical_formal_root)
        study_path = Path(historical_study_root)
        workspace_path = _workspace_root_for_study(study_path)
        try:
            source = _read_closed_full_pool_source(
                full_pool_path,
                manifest_sha256=full_pool_manifest_sha256,
            )
            validation_source = (
                source.manifest.get("production_deploy_eligible") is False
                and source.manifest.get("provider_calls") == 0
                and source.manifest.get("live_api_triggered") is False
                and source.aggregates.get("production_deploy_eligible") is False
            )
            source_provider_calls = source.manifest.get("provider_calls")
            formal_source = (
                source.manifest.get("production_deploy_eligible") is True
                and source.manifest.get("evidence_profile") == "formal_live"
                and isinstance(source_provider_calls, int)
                and not isinstance(source_provider_calls, bool)
                and source_provider_calls > 0
                and source.manifest.get("live_api_triggered") is True
                and source.aggregates.get("production_deploy_eligible") is True
            )
            if not validation_source and not formal_source:
                raise ValueError(
                    "Full-Pool presentation composition requires an exact closed Validation or Formal source"
                )
            manifest, manifest_payload, manifest_sha256 = _load_study_manifest(study_path)
            candidate, projection = self._validate_candidate_from_inputs(
                formal_root=formal_path,
                study_root=study_path,
                workspace_root=workspace_path,
                manifest=manifest,
                manifest_payload=manifest_payload,
                manifest_sha256=manifest_sha256,
                candidate_dir=historical_candidate_dir,
            )
            historical_payload = _read_json(candidate / _REPORT_PAYLOAD)
            if (
                _validate_report_payload_contract(
                    historical_payload,
                    production=False,
                    candidate=candidate,
                )
                != _REPORT_PAYLOAD_V2_SCHEMA
            ):
                raise ValueError(
                    "Full-Pool presentation requires the approved semantic v7 historical candidate"
                )
            historical_mermaid = {
                path.name
                for path in candidate.glob("*.mmd")
                if path.is_file() and not path.is_symlink()
            }
            if historical_mermaid != set(_SEMANTIC_MERMAID_DOWNLOADS.values()):
                raise ValueError("historical Mermaid inventory is incomplete or crossed")
            destination = _validate_destination(
                Path(destination_dir),
                protected_roots=(
                    source.root,
                    formal_path,
                    study_path,
                    workspace_path,
                    candidate,
                ),
            )
            source_before = _directory_file_hashes(source.root)
            candidate_before = _directory_file_hashes(candidate)
            formal_before = dict(projection.formal.artifact_hashes)
            study_before = dict(projection.study.file_hashes)
            created = _compose_full_pool_presentation_bundle(
                source=source,
                historical_candidate=candidate,
                historical_inventory=candidate_before,
                destination=destination,
            )
            _validate_full_pool_presentation_bundle(
                created,
                source=source,
                historical_candidate=candidate,
            )
            if source_before != _directory_file_hashes(source.root):
                raise _RobustnessReportClosureError(
                    "Full-Pool presentation composition mutated its closed source"
                )
            if candidate_before != _directory_file_hashes(candidate):
                raise _RobustnessReportClosureError(
                    "Full-Pool presentation composition mutated its historical candidate"
                )
            _assert_formal_unchanged(projection.formal, formal_before)
            _assert_study_unchanged(projection.study, study_before)
            return created
        except (
            _RobustnessReportPathError,
            _RobustnessReportConflictError,
            _RobustnessReportClosureError,
        ):
            raise
        except (
            FileNotFoundError,
            FullPoolExperimentError,
            _FullPoolPresentationError,
            OSError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise _RobustnessReportClosureError(
                "Full-Pool presentation bundle composition failed closed"
            ) from exc

    def validate_full_pool_presentation_bundle(
        self,
        bundle_dir: str | Path,
        *,
        full_pool_source_root: str | Path,
        full_pool_manifest_sha256: str,
        historical_candidate_dir: str | Path,
    ) -> None:
        """Validate one materialized Full-Pool bundle against explicit immutable inputs."""
        try:
            source = _read_closed_full_pool_source(
                full_pool_source_root,
                manifest_sha256=full_pool_manifest_sha256,
            )
            candidate = Path(historical_candidate_dir)
            historical_payload = _read_json(candidate / _REPORT_PAYLOAD)
            if (
                _validate_report_payload_contract(
                    historical_payload,
                    production=False,
                    candidate=candidate,
                )
                != _REPORT_PAYLOAD_V2_SCHEMA
            ):
                raise ValueError("historical candidate is not semantic v7")
            _validate_full_pool_presentation_bundle(
                Path(bundle_dir),
                source=source,
                historical_candidate=candidate,
            )
        except _RobustnessReportClosureError:
            raise
        except (
            FileNotFoundError,
            FullPoolExperimentError,
            _FullPoolPresentationError,
            OSError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise _RobustnessReportClosureError(
                "Full-Pool presentation bundle failed validation"
            ) from exc

    def compose_full_pool_candidate(
        self,
        *,
        full_pool_source_root: str | Path,
        full_pool_manifest_sha256: str,
        historical_formal_root: str | Path,
        historical_study_root: str | Path,
        presentation_bundle_dir: str | Path,
        implementation_commit: str,
        destination_dir: str | Path,
    ) -> Path:
        """Atomically bind one presentation bundle to three immutable evidence lineages."""
        inputs = self._prepare_full_pool_candidate_inputs(
            full_pool_source_root=full_pool_source_root,
            full_pool_manifest_sha256=full_pool_manifest_sha256,
            historical_formal_root=historical_formal_root,
            historical_study_root=historical_study_root,
            presentation_bundle_dir=presentation_bundle_dir,
        )
        if not _IMPLEMENTATION_COMMIT_PATTERN.fullmatch(implementation_commit):
            raise _RobustnessReportClosureError("Full-Pool candidate implementation commit is invalid")
        protected_roots = (
            inputs.source.root,
            inputs.projection.formal.run_dir,
            inputs.projection.study.root,
            _workspace_root_for_study(inputs.projection.study.root),
            inputs.bundle,
        )
        snapshots = {
            root: _directory_file_hashes(root)
            for root in (
                inputs.source.root,
                inputs.projection.formal.run_dir,
                inputs.projection.study.root,
                inputs.bundle,
            )
        }
        destination = _validate_destination(Path(destination_dir), protected_roots=protected_roots)
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{destination.name}.full-pool-candidate.",
                suffix=".staging",
                dir=destination.parent,
            )
        )
        installed = False
        try:
            shutil.copytree(inputs.bundle, staging, dirs_exist_ok=True, copy_function=shutil.copyfile)
            if _directory_file_hashes(staging) != _directory_file_hashes(inputs.bundle):
                raise _RobustnessReportClosureError("Full-Pool presentation bundle changed during copy")
            contracts = _build_full_pool_candidate_contracts(inputs, implementation_commit)
            for relative_path, payload in contracts.items():
                target = staging / relative_path
                if target.exists() or target.is_symlink():
                    raise _RobustnessReportClosureError("Full-Pool candidate contract path already exists")
                target.write_bytes(payload)
            _validate_full_pool_candidate_directory(
                staging,
                inputs=inputs,
                implementation_commit=implementation_commit,
            )
            if os.path.lexists(destination):
                raise _RobustnessReportConflictError(
                    "Full-Pool candidate destination appeared during publication"
                )
            os.replace(staging, destination)
            installed = True
            _validate_full_pool_candidate_directory(
                destination,
                inputs=inputs,
                implementation_commit=implementation_commit,
            )
            _assert_full_pool_candidate_inputs_unchanged(snapshots)
            installed = False
            return destination
        except Exception:
            if staging.is_dir() and not staging.is_symlink():
                shutil.rmtree(staging, ignore_errors=True)
            if installed and destination.is_dir() and not destination.is_symlink():
                shutil.rmtree(destination, ignore_errors=True)
            raise

    def validate_full_pool_candidate(
        self,
        candidate_dir: str | Path,
        *,
        full_pool_source_root: str | Path,
        full_pool_manifest_sha256: str,
        historical_formal_root: str | Path,
        historical_study_root: str | Path,
        presentation_bundle_dir: str | Path,
        implementation_commit: str,
    ) -> _FullPoolCandidateFacts:
        """Reread and validate one three-lineage candidate against explicit inputs."""
        if not _IMPLEMENTATION_COMMIT_PATTERN.fullmatch(implementation_commit):
            raise _RobustnessReportClosureError("Full-Pool candidate implementation commit is invalid")
        inputs = self._prepare_full_pool_candidate_inputs(
            full_pool_source_root=full_pool_source_root,
            full_pool_manifest_sha256=full_pool_manifest_sha256,
            historical_formal_root=historical_formal_root,
            historical_study_root=historical_study_root,
            presentation_bundle_dir=presentation_bundle_dir,
        )
        candidate = Path(candidate_dir)
        try:
            absolute = Path(os.path.abspath(candidate))
            resolved = candidate.resolve(strict=True)
            if (
                ".." in candidate.parts
                or absolute != resolved
                or candidate.is_symlink()
                or not resolved.is_dir()
            ):
                raise ValueError("Full-Pool candidate must be one explicit real directory")
            protected_roots = (
                inputs.source.root,
                inputs.projection.formal.run_dir,
                inputs.projection.study.root,
                _workspace_root_for_study(inputs.projection.study.root),
                inputs.bundle,
            )
            if any(
                resolved == root
                or resolved.is_relative_to(root)
                or root.is_relative_to(resolved)
                for root in protected_roots
            ):
                raise ValueError("Full-Pool candidate overlaps immutable input evidence")
            snapshots = {
                root: _directory_file_hashes(root)
                for root in (
                    inputs.source.root,
                    inputs.projection.formal.run_dir,
                    inputs.projection.study.root,
                    inputs.bundle,
                )
            }
            facts = _validate_full_pool_candidate_directory(
                resolved,
                inputs=inputs,
                implementation_commit=implementation_commit,
            )
            _assert_full_pool_candidate_inputs_unchanged(snapshots)
            return facts
        except _RobustnessReportClosureError:
            raise
        except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise _RobustnessReportClosureError(
                "Full-Pool three-lineage candidate failed closure validation"
            ) from exc

    def materialize_full_pool_production(
        self,
        *,
        full_pool_source_root: str | Path,
        full_pool_manifest_sha256: str,
        historical_formal_root: str | Path,
        historical_study_root: str | Path,
        presentation_bundle_dir: str | Path,
        candidate_dir: str | Path,
        implementation_commit: str,
        stage_facts: _FullPoolProductionPresentationFacts,
    ) -> _PresentationBundle:
        """Materialize v8 payload and HTML from one independently closed candidate."""
        candidate_facts = self.validate_full_pool_candidate(
            candidate_dir,
            full_pool_source_root=full_pool_source_root,
            full_pool_manifest_sha256=full_pool_manifest_sha256,
            historical_formal_root=historical_formal_root,
            historical_study_root=historical_study_root,
            presentation_bundle_dir=presentation_bundle_dir,
            implementation_commit=implementation_commit,
        )
        candidate = candidate_facts.root
        candidate_before = _directory_file_hashes(candidate)
        bundle = _build_full_pool_production_presentation(
            candidate,
            candidate_facts=candidate_facts,
            stage_facts=stage_facts,
        )
        self.validate_full_pool_production_bundle(
            bundle,
            candidate_dir=candidate,
            stage_facts=stage_facts,
        )
        if _directory_file_hashes(candidate) != candidate_before:
            raise _RobustnessReportClosureError(
                "Full-Pool production materialization mutated its candidate"
            )
        return bundle

    def validate_full_pool_production_bundle(
        self,
        bundle: _PresentationBundle,
        *,
        candidate_dir: str | Path,
        stage_facts: _FullPoolProductionPresentationFacts,
    ) -> None:
        """Validate v8 payload, HTML markers, downloads, size, and deterministic bytes."""
        try:
            _validate_full_pool_production_presentation(
                bundle,
                candidate=Path(candidate_dir),
                stage_facts=stage_facts,
            )
        except _RobustnessReportClosureError:
            raise
        except (OSError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _RobustnessReportClosureError(
                "Full-Pool production presentation failed validation"
            ) from exc

    def _prepare_full_pool_candidate_inputs(
        self,
        *,
        full_pool_source_root: str | Path,
        full_pool_manifest_sha256: str,
        historical_formal_root: str | Path,
        historical_study_root: str | Path,
        presentation_bundle_dir: str | Path,
    ) -> _FullPoolCandidateInputs:
        try:
            source = _read_closed_full_pool_source(
                full_pool_source_root,
                manifest_sha256=full_pool_manifest_sha256,
            )
            formal_path = Path(historical_formal_root)
            study_path = Path(historical_study_root)
            workspace_path = _workspace_root_for_study(study_path)
            manifest, manifest_payload, manifest_sha256 = _load_study_manifest(study_path)
            bundle = Path(presentation_bundle_dir)
            historical_candidate = bundle / _HISTORICAL_DIR
            _, projection = self._validate_candidate_from_inputs(
                formal_root=formal_path,
                study_root=study_path,
                workspace_root=workspace_path,
                manifest=manifest,
                manifest_payload=manifest_payload,
                manifest_sha256=manifest_sha256,
                candidate_dir=historical_candidate,
            )
            _validate_full_pool_presentation_bundle(
                bundle,
                source=source,
                historical_candidate=historical_candidate,
            )
            return _FullPoolCandidateInputs(
                source=source,
                projection=projection,
                bundle=bundle.resolve(strict=True),
                historical_candidate=historical_candidate.resolve(strict=True),
            )
        except _RobustnessReportClosureError:
            raise
        except (
            FileNotFoundError,
            FullPoolExperimentError,
            _FullPoolPresentationError,
            OSError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise _RobustnessReportClosureError(
                "Full-Pool candidate inputs failed independent three-lineage closure"
            ) from exc

    def materialize_production(
        self,
        *,
        formal_root: str | Path,
        study_root: str | Path,
        candidate_dir: str | Path,
        stage_facts: _ProductionPresentationFacts,
    ) -> _PresentationBundle:
        """Render production presentation bytes from an immutable candidate and approved facts."""
        formal_path = Path(formal_root)
        study_path = Path(study_root)
        workspace_path = _workspace_root_for_study(study_path)
        manifest, manifest_payload, manifest_sha256 = _load_study_manifest(study_path)
        candidate, projection = self._validate_candidate_from_inputs(
            formal_root=formal_path,
            study_root=study_path,
            workspace_root=workspace_path,
            manifest=manifest,
            manifest_payload=manifest_payload,
            manifest_sha256=manifest_sha256,
            candidate_dir=candidate_dir,
        )
        candidate_before = {path.name: _sha256_file(path) for path in candidate.iterdir()}
        approved_downloads = _validate_production_facts(stage_facts)
        report_payload = _read_json(candidate / _REPORT_PAYLOAD)
        if report_payload.get("production_deploy_eligible") is not False:
            raise _RobustnessReportClosureError("candidate report payload is not validation-only")
        candidate_downloads = _string_mapping(report_payload.get("downloads"), "candidate downloads")
        if set(candidate_downloads) != set(approved_downloads):
            raise _RobustnessReportClosureError("production presentation changed the approved download keys")
        if report_payload.get("schema_version") == _REPORT_PAYLOAD_V2_SCHEMA:
            _validate_semantic_downloads(approved_downloads)
        report_payload["downloads"] = approved_downloads
        report_payload["production_deploy_eligible"] = True
        report_payload["production_release"] = _production_release_payload(stage_facts)
        if report_payload.get("schema_version") == _REPORT_PAYLOAD_V2_SCHEMA:
            report_html = _render_semantic_additive_report(
                _render_editorial_v4(projection.formal.report_payload),
                payload=report_payload,
                prompt_model_presentation=projection.prompt_model_presentation,
                stage_facts=stage_facts,
            )
        else:
            report_html = _render_additive_report(
                render_report(projection.formal.report_payload),
                payload=report_payload,
                prompt_model_presentation=projection.prompt_model_presentation,
                stage_facts=stage_facts,
            )
        bundle = _PresentationBundle(
            report_payload=_json_bytes(report_payload),
            report_html=report_html.encode("utf-8"),
        )
        self.validate_bundle(bundle, stage_facts=stage_facts)
        if candidate_before != {path.name: _sha256_file(path) for path in candidate.iterdir()}:
            raise _RobustnessReportClosureError("production presentation mutated the validation candidate")
        _assert_formal_unchanged(projection.formal, dict(projection.formal.artifact_hashes))
        _assert_study_unchanged(projection.study, dict(projection.study.file_hashes))
        return bundle

    def validate_bundle(
        self,
        bundle: _PresentationBundle,
        *,
        stage_facts: _ProductionPresentationFacts | None = None,
    ) -> None:
        """Validate payload, DOM stage, selectors, links, copy, and offline presentation safety."""
        try:
            _validate_presentation_bundle(bundle, stage_facts=stage_facts)
        except _RobustnessReportClosureError:
            raise
        except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _RobustnessReportClosureError("report presentation bundle failed validation") from exc

    def _compose_candidate_from_inputs(
        self,
        *,
        formal_root: Path,
        study_root: Path,
        workspace_root: Path,
        manifest: ConcurrentRobustnessManifest,
        manifest_payload: bytes,
        manifest_sha256: str,
        destination_dir: str | Path,
    ) -> Path:
        projection = _build_candidate_projection(
            formal_root=formal_root,
            study_root=study_root,
            manifest=manifest,
            manifest_payload=manifest_payload,
            manifest_sha256=manifest_sha256,
        )
        formal_before = dict(projection.formal.artifact_hashes)
        study_before = dict(projection.study.file_hashes)
        destination = _publish_candidate_payloads(
            destination_dir=destination_dir,
            protected_roots=(formal_root, study_root, workspace_root),
            output_identity=manifest.output_identity,
            payloads=projection.payloads,
            row_counts=projection.rows.counts(),
        )
        _assert_formal_unchanged(projection.formal, formal_before)
        _assert_study_unchanged(projection.study, study_before)
        return destination

    def _validate_candidate_from_inputs(
        self,
        *,
        formal_root: Path,
        study_root: Path,
        workspace_root: Path,
        manifest: ConcurrentRobustnessManifest,
        manifest_payload: bytes,
        manifest_sha256: str,
        candidate_dir: str | Path,
    ) -> tuple[Path, _CandidateProjection]:
        candidate = Path(candidate_dir)
        try:
            if ".." in candidate.parts:
                raise ValueError("candidate contains an unsafe parent traversal")
            absolute = Path(os.path.abspath(candidate))
            resolved = candidate.resolve(strict=True)
            if absolute != resolved or candidate.is_symlink() or not resolved.is_dir():
                raise ValueError("candidate is not a real directory")
            protected = tuple(root.resolve(strict=True) for root in (formal_root, study_root, workspace_root))
            if any(
                resolved == root or resolved.is_relative_to(root) or root.is_relative_to(resolved)
                for root in protected
            ):
                raise ValueError("candidate overlaps a protected source root")
            projection = _build_candidate_projection(
                formal_root=formal_root,
                study_root=study_root,
                manifest=manifest,
                manifest_payload=manifest_payload,
                manifest_sha256=manifest_sha256,
            )
            formal_before = dict(projection.formal.artifact_hashes)
            study_before = dict(projection.study.file_hashes)
            expected_payloads = projection.payloads
            persisted_payload = _read_json(resolved / _REPORT_PAYLOAD)
            if persisted_payload.get("schema_version") == _REPORT_PAYLOAD_V2_SCHEMA:
                semantic_candidate = _build_semantic_presentation_candidate(projection)
                semantic_payload = _build_semantic_report_payload(projection.report_payload)
                expected_payloads = _semantic_candidate_payloads(
                    projection=projection,
                    semantic_candidate=semantic_candidate,
                    report_payload=semantic_payload,
                )
            _validate_candidate(
                resolved,
                expected_payloads=expected_payloads,
                expected_row_counts=projection.rows.counts(),
            )
            _assert_formal_unchanged(projection.formal, formal_before)
            _assert_study_unchanged(projection.study, study_before)
            return resolved, projection
        except (_RobustnessReportPathError, _RobustnessReportConflictError, _RobustnessReportClosureError):
            raise
        except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise _RobustnessReportClosureError("existing robustness report candidate failed closure") from exc


_REPORT_PRESENTATION = _ReportPresentationInterface()


_FULL_POOL_PRODUCTION_PRESENTATION_SCHEMA = "full-pool-production-presentation-v1"
_FULL_POOL_PRODUCTION_RELEASE_FIELDS = frozenset(
    {
        "schema_version",
        "release_contract_schema",
        "release_id",
        "canonical_endpoint",
        "production_evidence_schema",
        "implementation_commit",
        "full_pool_source_identity",
        "full_pool_source_manifest_sha256",
        "counts",
        "provider",
        "production_deploy_eligible",
    }
)
_FULL_POOL_PRODUCTION_COUNT_FIELDS = frozenset(
    {
        "distinct_users",
        "eligible_pairs",
        "exposures",
        "primary_terminals",
        "committed_batches",
        "candidate_ranking_rows",
        "campaign_exposure_coverage",
        "provider_failed_terminals",
    }
)
_FULL_POOL_PRODUCTION_PROVIDER_FIELDS = frozenset(
    {
        "logical_judgments",
        "physical_attempts",
        "transport",
        "requested_model",
        "qualified_observed_model",
        "usage_complete_response_count",
        "subscription_billed_cost_usd",
    }
)


def _validate_full_pool_production_stage_facts(
    stage_facts: _FullPoolProductionPresentationFacts,
    *,
    candidate_facts: _FullPoolCandidateFacts | None = None,
) -> dict[str, str]:
    if not isinstance(stage_facts, _FullPoolProductionPresentationFacts):
        raise _RobustnessReportClosureError("Full-Pool production facts use an invalid Interface")
    strict_integer_values = (
        stage_facts.distinct_users,
        stage_facts.eligible_pairs,
        stage_facts.exposures,
        stage_facts.primary_terminals,
        stage_facts.committed_batches,
        stage_facts.candidate_ranking_rows,
        stage_facts.campaign_exposure_coverage,
        stage_facts.provider_failed_terminals,
        stage_facts.logical_judgments,
        stage_facts.physical_attempts,
        stage_facts.usage_complete_response_count,
    )
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}", stage_facts.release_id)
        or stage_facts.release_contract_schema != "abm-report-release-contract-v8"
        or stage_facts.canonical_endpoint != "https://abm.q1ngyuan.top/"
        or stage_facts.production_evidence_schema
        != "full-pool-production-release-evidence-v1"
        or not _IMPLEMENTATION_COMMIT_PATTERN.fullmatch(stage_facts.implementation_commit)
        or not stage_facts.full_pool_source_identity
        or not _is_sha256(stage_facts.full_pool_source_manifest_sha256)
        or any(type(value) is not int or value < 0 for value in strict_integer_values)
        or not stage_facts.provider_transport
        or not stage_facts.requested_model
        or not stage_facts.qualified_observed_model
        or type(stage_facts.subscription_billed_cost_usd) is not float
        or stage_facts.subscription_billed_cost_usd < 0.0
    ):
        raise _RobustnessReportClosureError(
            "Full-Pool production presentation facts are invalid or crossed"
        )
    approved_downloads = _strict_string_mapping(
        stage_facts.approved_downloads,
        "Full-Pool production approved downloads",
    )
    if candidate_facts is not None:
        full_pool_lineage = _mapping(
            candidate_facts.source_lineage.get("full_pool"),
            "Full-Pool candidate source lineage",
        )
        if (
            stage_facts.implementation_commit != candidate_facts.implementation_commit
            or stage_facts.full_pool_source_identity != full_pool_lineage.get("source_identity")
            or stage_facts.full_pool_source_manifest_sha256
            != full_pool_lineage.get("manifest_sha256")
            or approved_downloads != dict(candidate_facts.approved_downloads)
        ):
            raise _RobustnessReportClosureError(
                "Full-Pool production facts are crossed with the closed candidate"
            )
    return approved_downloads


def _full_pool_production_release_payload(
    stage_facts: _FullPoolProductionPresentationFacts,
) -> dict[str, Any]:
    return {
        "schema_version": _FULL_POOL_PRODUCTION_PRESENTATION_SCHEMA,
        "release_contract_schema": stage_facts.release_contract_schema,
        "release_id": stage_facts.release_id,
        "canonical_endpoint": stage_facts.canonical_endpoint,
        "production_evidence_schema": stage_facts.production_evidence_schema,
        "implementation_commit": stage_facts.implementation_commit,
        "full_pool_source_identity": stage_facts.full_pool_source_identity,
        "full_pool_source_manifest_sha256": stage_facts.full_pool_source_manifest_sha256,
        "counts": {
            "distinct_users": stage_facts.distinct_users,
            "eligible_pairs": stage_facts.eligible_pairs,
            "exposures": stage_facts.exposures,
            "primary_terminals": stage_facts.primary_terminals,
            "committed_batches": stage_facts.committed_batches,
            "candidate_ranking_rows": stage_facts.candidate_ranking_rows,
            "campaign_exposure_coverage": stage_facts.campaign_exposure_coverage,
            "provider_failed_terminals": stage_facts.provider_failed_terminals,
        },
        "provider": {
            "logical_judgments": stage_facts.logical_judgments,
            "physical_attempts": stage_facts.physical_attempts,
            "transport": stage_facts.provider_transport,
            "requested_model": stage_facts.requested_model,
            "qualified_observed_model": stage_facts.qualified_observed_model,
            "usage_complete_response_count": stage_facts.usage_complete_response_count,
            "subscription_billed_cost_usd": stage_facts.subscription_billed_cost_usd,
        },
        "production_deploy_eligible": True,
    }


def _build_full_pool_production_presentation(
    candidate: Path,
    *,
    candidate_facts: _FullPoolCandidateFacts,
    stage_facts: _FullPoolProductionPresentationFacts,
) -> _PresentationBundle:
    _validate_full_pool_production_stage_facts(
        stage_facts,
        candidate_facts=candidate_facts,
    )
    payload = _read_json(candidate / _REPORT_PAYLOAD)
    if (
        payload.get("schema_version") != _FULL_POOL_REPORT_PAYLOAD_SCHEMA
        or payload.get("production_deploy_eligible") is not False
        or "production_release" in payload
    ):
        raise _RobustnessReportClosureError(
            "Full-Pool production source is not an exact non-deployable candidate"
        )
    production_payload = json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))
    production_payload["production_release"] = _full_pool_production_release_payload(stage_facts)
    production_payload["production_deploy_eligible"] = True

    candidate_html = (candidate / CONCURRENT_MESSAGE_REPORT_HTML).read_bytes()
    false_marker = (
        b'<main class="full-pool-presentation" data-testid="full-pool-presentation" '
        b'data-production-deploy-eligible="false"'
    )
    true_marker = (
        b'<main class="full-pool-presentation" data-testid="full-pool-presentation" '
        b'data-production-deploy-eligible="true"'
    )
    if candidate_html.count(false_marker) != 1 or true_marker in candidate_html:
        raise _RobustnessReportClosureError(
            "Full-Pool candidate production marker is missing, duplicated, or crossed"
        )
    production_html = candidate_html.replace(false_marker, true_marker, 1)
    return _PresentationBundle(
        report_payload=_json_bytes(production_payload),
        report_html=production_html,
    )


def _validate_full_pool_production_presentation(
    bundle: _PresentationBundle,
    *,
    candidate: Path,
    stage_facts: _FullPoolProductionPresentationFacts,
) -> None:
    if not isinstance(bundle, _PresentationBundle):
        raise _RobustnessReportClosureError("Full-Pool production bundle has an invalid type")
    absolute = Path(os.path.abspath(candidate))
    resolved = candidate.resolve(strict=True)
    if absolute != resolved or candidate.is_symlink() or not resolved.is_dir():
        raise _RobustnessReportClosureError("Full-Pool production candidate is not a real directory")
    candidate_manifest = _read_json(resolved / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON)
    candidate_payload = _read_json(resolved / _REPORT_PAYLOAD)
    source_lineage = _mapping(candidate_payload.get("source_lineage"), "Full-Pool source lineage")
    full_pool_lineage = _mapping(source_lineage.get("full_pool"), "Full-Pool source lineage")
    synthetic_facts = _FullPoolCandidateFacts(
        root=resolved,
        manifest_sha256=_sha256_file(resolved / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON),
        candidate_identity_sha256=str(candidate_manifest.get("candidate_identity_sha256", "")),
        candidate_content_identity_sha256=str(
            candidate_manifest.get("candidate_content_identity_sha256", "")
        ),
        report_sha256=_sha256_file(resolved / CONCURRENT_MESSAGE_REPORT_HTML),
        payload_sha256=_sha256_file(resolved / _REPORT_PAYLOAD),
        evidence_sha256=_sha256_file(resolved / _RELEASE_EVIDENCE_JSON),
        report_payload_schema_version=str(candidate_payload.get("schema_version", "")),
        implementation_commit=str(candidate_manifest.get("implementation_commit", "")),
        source_lineage=source_lineage,
        source_lineage_identity_sha256=str(
            candidate_manifest.get("source_lineage_identity_sha256", "")
        ),
        presentation_bundle_identity_sha256=str(
            candidate_manifest.get("presentation_bundle_identity_sha256", "")
        ),
        presentation_inventory_identity_sha256=str(
            candidate_manifest.get("presentation_inventory_identity_sha256", "")
        ),
        mechanism_set_identity_sha256=str(
            candidate_manifest.get("mechanism_set_identity_sha256", "")
        ),
        trace_index_sha256=str(candidate_manifest.get("trace_index_sha256", "")),
        artifact_hashes={},
        approved_downloads=_strict_string_mapping(
            candidate_manifest.get("approved_downloads"),
            "Full-Pool candidate approved downloads",
        ),
    )
    _validate_full_pool_production_stage_facts(
        stage_facts,
        candidate_facts=synthetic_facts,
    )
    expected = _build_full_pool_production_presentation(
        resolved,
        candidate_facts=synthetic_facts,
        stage_facts=stage_facts,
    )
    if bundle != expected:
        raise _RobustnessReportClosureError(
            "Full-Pool production payload or HTML differs from deterministic materialization"
        )
    if len(bundle.report_html) >= 3 * 1024 * 1024:
        raise _RobustnessReportClosureError("Full-Pool production report exceeds the 3 MiB gate")
    report = bundle.report_html.decode("utf-8")
    production_root = (
        '<main class="full-pool-presentation" data-testid="full-pool-presentation" '
        'data-production-deploy-eligible="true"'
    )
    candidate_root = (
        '<main class="full-pool-presentation" data-testid="full-pool-presentation" '
        'data-production-deploy-eligible="false"'
    )
    if (
        report.count(production_root) != 1
        or candidate_root in report
        or 'data-provider-calls-during-composition="0"' not in report
        or 'data-canonical-deployment-triggered="false"' not in report
    ):
        raise _RobustnessReportClosureError(
            "Full-Pool production HTML status markers are missing or crossed"
        )
    payload = json.loads(bundle.report_payload)
    release = _mapping(payload.get("production_release"), "Full-Pool production release")
    counts = _mapping(release.get("counts"), "Full-Pool production counts")
    provider = _mapping(release.get("provider"), "Full-Pool production Provider facts")
    if (
        set(payload) != set(candidate_payload) | {"production_release"}
        or payload.get("production_deploy_eligible") is not True
        or set(release) != _FULL_POOL_PRODUCTION_RELEASE_FIELDS
        or set(counts) != _FULL_POOL_PRODUCTION_COUNT_FIELDS
        or set(provider) != _FULL_POOL_PRODUCTION_PROVIDER_FIELDS
        or release != _full_pool_production_release_payload(stage_facts)
        or full_pool_lineage.get("source_identity")
        != stage_facts.full_pool_source_identity
    ):
        raise _RobustnessReportClosureError(
            "Full-Pool production payload fields or source identity are crossed"
        )


def _full_pool_candidate_source_lineage(inputs: _FullPoolCandidateInputs) -> dict[str, Any]:
    source = inputs.source
    counts = _mapping(source.manifest.get("counts"), "Full-Pool source counts")
    if set(counts) != _FULL_POOL_COUNT_FIELDS or any(
        type(value) is not int or value < 0 for value in counts.values()
    ):
        raise _RobustnessReportClosureError("Full-Pool source counts are missing, extra, or invalid")
    provider_accounting = _mapping(
        source.aggregates.get("provider_accounting"),
        "Full-Pool Provider accounting",
    )
    if (
        source.manifest.get("counts") != counts
        or source.aggregates.get("counts") != counts
        or source.manifest.get("provider_calls") != provider_accounting.get("external_request_invocations")
        or source.manifest.get("physical_provider_attempts") != provider_accounting.get("physical_attempts")
    ):
        raise _RobustnessReportClosureError("Full-Pool source accounting is crossed")
    execution = source.contract.formal_execution
    full_pool = {
        "source_path": source.root.as_posix(),
        "source_schema_version": source.manifest.get("source_schema_version"),
        "manifest_schema_version": source.manifest.get("schema_version"),
        "contract_schema_version": source.contract.schema_version,
        "source_identity": source.source_identity,
        "manifest_sha256": source.manifest_sha256,
        "contract_sha256": source.manifest.get("contract_sha256"),
        "source_hash": source.manifest.get("source_hash"),
        "profile": source.manifest.get("profile"),
        "evidence_profile": source.manifest.get("evidence_profile"),
        "requested_model": execution.requested_model if execution is not None else None,
        "counts": counts,
        "provider_accounting": provider_accounting,
        "provider_calls": source.manifest.get("provider_calls"),
        "live_api_triggered": source.manifest.get("live_api_triggered"),
        "source_production_deploy_eligible": source.manifest.get("production_deploy_eligible"),
        "evidence_scope": ["full_pool_main_experiment", "primary_only"],
    }

    projection = inputs.projection
    formal = projection.formal
    terminal_rows = formal.source_evidence.terminal_rows
    primary_terminals = sum(row.get("decision_variant") == "primary" for row in terminal_rows)
    shadow_terminals = sum(row.get("decision_variant") == "shadow" for row in terminal_rows)
    formal_manifest_sha256 = formal.artifact_hashes.get(CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON)
    if not _is_sha256(formal_manifest_sha256):
        raise _RobustnessReportClosureError("historical Formal manifest hash is missing")
    historical_counts = {
        "distinct_users": len(formal.source_evidence.sample_manifest_rows),
        "exposures": len(formal.source_evidence.pair_rows),
        "primary_terminals": primary_terminals,
        "shadow_terminals": shadow_terminals,
        "trace_rows": len(formal.decision_trace_document.rows),
    }
    historical_source_kind = projection.manifest.source.kind
    historical_sample_size = projection.manifest.sample.sample_size
    if (
        historical_counts["exposures"] != historical_counts["primary_terminals"]
        or historical_counts["exposures"] != historical_counts["shadow_terminals"]
        or historical_counts["exposures"] != historical_counts["trace_rows"]
        or historical_counts["distinct_users"] != historical_sample_size
        or (historical_source_kind == "formal" and historical_sample_size != 1_000)
    ):
        raise _RobustnessReportClosureError("historical Formal source denominators are crossed")
    denominator_scope = (
        "one_thousand_user_primary_shadow_only"
        if historical_source_kind == "formal"
        else "scaled_validation_primary_shadow_only"
    )
    historical_formal = {
        "source_path": formal.run_dir.resolve(strict=True).as_posix(),
        "source_id": projection.manifest.source.source_id,
        "source_kind": historical_source_kind,
        "manifest_schema_version": formal.manifest.schema_version,
        "manifest_sha256": formal_manifest_sha256,
        "report_payload_schema_version": formal.report_payload.schema_version,
        "primary_prompt_token": formal.manifest.primary_prompt_token,
        "shadow_prompt_token": formal.manifest.shadow_prompt_token,
        "counts": historical_counts,
        "denominator_scope": denominator_scope,
        "evidence_scope": ["historical_primary_shadow", "demographic_sensitivity"],
    }

    study = projection.study
    study_manifest_sha256 = projection.manifest_sha256
    requested_models = sorted(
        {cell.requested_model for cell in projection.manifest.prompt_model_cells}
    )
    robustness_study = {
        "source_path": study.root.as_posix(),
        "output_identity": projection.manifest.output_identity,
        "manifest_schema_version": projection.manifest.schema_version,
        "manifest_sha256": study_manifest_sha256,
        "artifact_manifest_schema_version": study.root_manifest.get("schema_version"),
        "artifact_manifest_sha256": study.file_hashes.get("artifact_manifest.json"),
        "root_identity_sha256": study.root_manifest.get("root_identity_sha256"),
        "sample_size": projection.manifest.sample.sample_size,
        "ranking_weight_point_count": len(projection.manifest.weight_points),
        "prompt_model_cell_count": len(projection.manifest.prompt_model_cells),
        "requested_models": requested_models,
        "row_counts": projection.rows.counts(),
        "evidence_scope": ["ranking_weight_sensitivity", "prompt_model_primary_only"],
    }
    lineage = {
        "full_pool": full_pool,
        "historical_formal": historical_formal,
        "robustness_study": robustness_study,
    }
    if any(
        not _is_sha256(value)
        for value in (
            full_pool["manifest_sha256"],
            full_pool["contract_sha256"],
            full_pool["source_hash"],
            historical_formal["manifest_sha256"],
            robustness_study["manifest_sha256"],
            robustness_study["artifact_manifest_sha256"],
            robustness_study["root_identity_sha256"],
        )
    ):
        raise _RobustnessReportClosureError("three-lineage identity hash is invalid")
    return lineage


def _full_pool_artifact_records(root: Path, hashes: Mapping[str, str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for relative_path, sha256 in sorted(hashes.items()):
        pure = PurePosixPath(relative_path)
        target = root / relative_path
        if (
            "\\" in relative_path
            or pure.is_absolute()
            or pure.as_posix() != relative_path
            or "." in pure.parts
            or ".." in pure.parts
            or target.is_symlink()
            or not target.is_file()
            or not _is_sha256(sha256)
        ):
            raise _RobustnessReportClosureError("Full-Pool artifact path or hash is unsafe")
        records.append(
            {
                "relative_path": relative_path,
                "sha256": sha256,
                "bytes": target.stat().st_size,
            }
        )
    return records


def _full_pool_approved_downloads(inputs: _FullPoolCandidateInputs) -> dict[str, str]:
    historical_payload = _read_json(inputs.historical_candidate / _REPORT_PAYLOAD)
    historical_downloads = _strict_string_mapping(
        historical_payload.get("downloads"),
        "historical approved downloads",
    )
    downloads = {
        "full_pool_trace_index": _TRACE_INDEX_PATH,
        "full_pool_mechanism_mermaid": _FULL_POOL_MASTER,
        "full_pool_source_manifest": f"{_FULL_POOL_SOURCE_DIR}/manifest.json",
        "full_pool_candidate_rows": f"{_FULL_POOL_SOURCE_DIR}/candidate_rows.jsonl",
        "full_pool_pair_rows": f"{_FULL_POOL_SOURCE_DIR}/pair_rows.jsonl",
        "full_pool_terminal_rows": f"{_FULL_POOL_SOURCE_DIR}/terminal_rows.jsonl",
        **{
            f"historical_{key}": f"{_HISTORICAL_DIR}/{relative_path}"
            for key, relative_path in historical_downloads.items()
        },
    }
    report = (inputs.bundle / CONCURRENT_MESSAGE_REPORT_HTML).read_text(encoding="utf-8")
    observed_hrefs = {
        html.unescape(match)
        for match in re.findall(
            r'<a\b(?=[^>]*\bdownload\b)[^>]*\bhref="([^"]+)"',
            report,
            re.IGNORECASE,
        )
    }
    for index, relative_path in enumerate(sorted(observed_hrefs - set(downloads.values()))):
        downloads[f"linked_artifact_{index:03d}"] = relative_path
    if len(set(downloads.values())) != len(downloads):
        raise _RobustnessReportClosureError("Full-Pool approved download paths are duplicated")
    bundle_hashes = _directory_file_hashes(inputs.bundle)
    for relative_path in downloads.values():
        pure = PurePosixPath(relative_path)
        if (
            pure.is_absolute()
            or pure.as_posix() != relative_path
            or ".." in pure.parts
            or relative_path not in bundle_hashes
        ):
            raise _RobustnessReportClosureError("Full-Pool approved download escapes its bundle inventory")
    if observed_hrefs != set(downloads.values()):
        raise _RobustnessReportClosureError("Full-Pool approved downloads differ from report hrefs")
    return downloads


def _full_pool_presentation_inventory(inputs: _FullPoolCandidateInputs) -> dict[str, Any]:
    bundle_hashes = _directory_file_hashes(inputs.bundle)
    bundle_records = _full_pool_artifact_records(inputs.bundle, bundle_hashes)
    bundle_identity = _sha256_bytes(_json_bytes(dict(sorted(bundle_hashes.items()))))

    expected_mermaid = {
        _FULL_POOL_MASTER,
        *(f"{_HISTORICAL_DIR}/{name}" for name in _HISTORICAL_MERMAID_FILENAMES),
    }
    actual_mermaid = {path for path in bundle_hashes if path.endswith(".mmd")}
    if actual_mermaid != expected_mermaid:
        raise _RobustnessReportClosureError("Full-Pool mechanism inventory is incomplete or extra")
    mermaid_records = _full_pool_artifact_records(
        inputs.bundle,
        {path: bundle_hashes[path] for path in sorted(actual_mermaid)},
    )
    historical_mechanism = _MECHANISM_PRESENTATION.build()
    full_pool_mechanism = _MECHANISM_PRESENTATION.build_full_pool_master()
    mechanism_identity_document = {
        "schema_version": _FULL_POOL_MECHANISM_SET_SCHEMA,
        "historical_semantic_set_identity_sha256": historical_mechanism.semantic_set_identity_sha256,
        "full_pool_semantic_set_identity_sha256": full_pool_mechanism.semantic_set_identity_sha256,
        "masters": mermaid_records,
    }
    mechanism_presentation = {
        **mechanism_identity_document,
        "mechanism_set_identity_sha256": _sha256_bytes(
            _json_bytes(mechanism_identity_document)
        ),
    }

    index_path = inputs.bundle / _TRACE_INDEX_PATH
    index = _read_json(index_path)
    if set(index) != _FULL_POOL_TRACE_INDEX_FIELDS:
        raise _RobustnessReportClosureError("Full-Pool trace index fields are missing or unexpected")
    raw_partitions = _object_sequence(index.get("partitions"), "Full-Pool trace partitions")
    partition_paths: set[str] = set()
    partition_identities: set[tuple[str, int]] = set()
    terminal_ids: set[str] = set()
    ordered_terminal_ids: list[str] = []
    partition_rows = 0
    partitions: list[dict[str, Any]] = []
    for entry in raw_partitions:
        if set(entry) != _FULL_POOL_TRACE_PARTITION_FIELDS:
            raise _RobustnessReportClosureError("Full-Pool trace partition fields are missing or unexpected")
        relative_path = entry.get("relative_path")
        message_id = entry.get("message_id")
        time_step = entry.get("time_step")
        row_count = entry.get("row_count")
        byte_count = entry.get("bytes")
        if (
            not isinstance(relative_path, str)
            or not relative_path
            or not isinstance(message_id, str)
            or not message_id
            or type(time_step) is not int
            or time_step < 0
            or type(row_count) is not int
            or row_count <= 0
            or type(byte_count) is not int
            or byte_count <= 0
            or relative_path in partition_paths
            or (message_id, time_step) in partition_identities
            or relative_path not in bundle_hashes
            or bundle_hashes[relative_path] != entry.get("sha256")
            or (inputs.bundle / relative_path).stat().st_size != byte_count
            or not _is_sha256(entry.get("terminal_identity_sha256"))
        ):
            raise _RobustnessReportClosureError("Full-Pool trace partition inventory is crossed")
        partition_document = _read_json(inputs.bundle / relative_path)
        if (
            set(partition_document) != _FULL_POOL_TRACE_PARTITION_DOCUMENT_FIELDS
            or partition_document.get("schema_version") != _TRACE_PARTITION_SCHEMA
            or partition_document.get("source_identity") != inputs.source.source_identity
            or partition_document.get("source_manifest_sha256") != inputs.source.manifest_sha256
            or partition_document.get("message_id") != message_id
            or partition_document.get("time_step") != time_step
            or partition_document.get("row_count") != row_count
            or partition_document.get("terminal_identity_sha256")
            != entry.get("terminal_identity_sha256")
        ):
            raise _RobustnessReportClosureError("Full-Pool trace partition document is crossed")
        rows = _object_sequence(
            partition_document.get("rows"),
            "Full-Pool trace partition rows",
        )
        row_terminal_ids: list[str] = []
        for row in rows:
            terminal_id = row.get("terminal_row_id")
            if (
                not isinstance(terminal_id, str)
                or not terminal_id
                or terminal_id in terminal_ids
            ):
                raise _RobustnessReportClosureError(
                    "Full-Pool trace contains a missing or duplicate terminal identity"
                )
            terminal_ids.add(terminal_id)
            row_terminal_ids.append(terminal_id)
        partition_terminal_identity = hashlib.sha256(
            json.dumps(
                row_terminal_ids,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if (
            len(rows) != row_count
            or partition_terminal_identity != entry.get("terminal_identity_sha256")
        ):
            raise _RobustnessReportClosureError(
                "Full-Pool trace partition row count or terminal identity is crossed"
            )
        partition_paths.add(relative_path)
        partition_identities.add((message_id, time_step))
        ordered_terminal_ids.extend(row_terminal_ids)
        partition_rows += len(rows)
        partitions.append(entry)
    terminal_count = index.get("terminal_count")
    index_terminal_identity = hashlib.sha256(
        json.dumps(
            ordered_terminal_ids,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if (
        index.get("schema_version") != _TRACE_INDEX_SCHEMA
        or index.get("source_identity") != inputs.source.source_identity
        or index.get("source_manifest_sha256") != inputs.source.manifest_sha256
        or index.get("contract_sha256") != inputs.source.manifest.get("contract_sha256")
        or type(terminal_count) is not int
        or terminal_count != inputs.source.contract.expected_primary_terminals
        or partition_rows != terminal_count
        or index.get("partition_count") != len(partitions)
        or len(terminal_ids) != terminal_count
        or index.get("terminal_identity_sha256") != index_terminal_identity
    ):
        raise _RobustnessReportClosureError("Full-Pool trace denominator or source identity is crossed")
    trace = {
        "schema_version": index.get("schema_version"),
        "index": _full_pool_artifact_records(
            inputs.bundle,
            {_TRACE_INDEX_PATH: bundle_hashes[_TRACE_INDEX_PATH]},
        )[0],
        "source_identity": index.get("source_identity"),
        "source_manifest_sha256": index.get("source_manifest_sha256"),
        "terminal_count": terminal_count,
        "terminal_identity_sha256": index.get("terminal_identity_sha256"),
        "partition_count": len(partitions),
        "partitions": partitions,
    }
    report_record = _full_pool_artifact_records(
        inputs.bundle,
        {CONCURRENT_MESSAGE_REPORT_HTML: bundle_hashes[CONCURRENT_MESSAGE_REPORT_HTML]},
    )[0]
    return {
        "schema_version": _FULL_POOL_PRESENTATION_INVENTORY_SCHEMA,
        "bundle_path": inputs.bundle.as_posix(),
        "bundle_identity_sha256": bundle_identity,
        "bundle_artifacts": bundle_records,
        "report": report_record,
        "mechanism_presentation": mechanism_presentation,
        "trace": trace,
        "approved_downloads": _full_pool_approved_downloads(inputs),
    }


def _build_full_pool_candidate_contracts(
    inputs: _FullPoolCandidateInputs,
    implementation_commit: str,
) -> dict[str, bytes]:
    source_lineage = _full_pool_candidate_source_lineage(inputs)
    source_lineage_identity = _sha256_bytes(_json_bytes(source_lineage))
    presentation = _full_pool_presentation_inventory(inputs)
    presentation_identity = _sha256_bytes(_json_bytes(presentation))
    historical_lineage = _mapping(
        source_lineage.get("historical_formal"),
        "historical Formal source lineage",
    )
    payload = {
        "schema_version": _FULL_POOL_REPORT_PAYLOAD_SCHEMA,
        "title": "Full-Pool Main Experiment · Three-Lineage Presentation Candidate",
        "implementation_commit": implementation_commit,
        "source_lineage": source_lineage,
        "source_lineage_identity_sha256": source_lineage_identity,
        "presentation": presentation,
        "presentation_inventory_identity_sha256": presentation_identity,
        "claim_boundary": {
            "full_pool_scope": "primary_only_main_experiment",
            "historical_formal_scope": historical_lineage.get("denominator_scope"),
            "robustness_study_scope": "ranking_weight_and_prompt_model_only",
            "denominators_must_not_mix": True,
            "causal_claim": False,
            "population_or_model_single_factor_claim": False,
        },
        "provider_calls_during_composition": 0,
        "image_generation_triggered": False,
        "production_deploy_eligible": False,
    }
    payload_bytes = _json_bytes(payload)
    payload_sha256 = _sha256_bytes(payload_bytes)
    bundle_hashes = _directory_file_hashes(inputs.bundle)
    content_hashes = {
        **bundle_hashes,
        _REPORT_PAYLOAD: payload_sha256,
    }
    content_identity = _sha256_bytes(_json_bytes(dict(sorted(content_hashes.items()))))
    mechanism = _mapping(
        presentation.get("mechanism_presentation"),
        "Full-Pool mechanism presentation",
    )
    trace = _mapping(presentation.get("trace"), "Full-Pool trace presentation")
    trace_index = _mapping(trace.get("index"), "Full-Pool trace index artifact")
    release_evidence = {
        "schema_version": _FULL_POOL_RELEASE_EVIDENCE_SCHEMA,
        "candidate_type": _FULL_POOL_CANDIDATE_TYPE,
        "implementation_commit": implementation_commit,
        "source_lineage": source_lineage,
        "source_lineage_identity_sha256": source_lineage_identity,
        "report_payload_schema_version": _FULL_POOL_REPORT_PAYLOAD_SCHEMA,
        "report_payload_sha256": payload_sha256,
        "presentation_bundle_identity_sha256": presentation.get("bundle_identity_sha256"),
        "presentation_inventory_identity_sha256": presentation_identity,
        "mechanism_set_identity_sha256": mechanism.get("mechanism_set_identity_sha256"),
        "trace_index_sha256": trace_index.get("sha256"),
        "candidate_content_identity_sha256": content_identity,
        "approved_downloads": presentation.get("approved_downloads"),
        "provider_calls_during_composition": 0,
        "image_generation_triggered": False,
        "canonical_deployment_triggered": False,
        "production_deploy_eligible": False,
    }
    evidence_bytes = _json_bytes(release_evidence)
    evidence_sha256 = _sha256_bytes(evidence_bytes)
    artifact_hashes = {
        **content_hashes,
        _RELEASE_EVIDENCE_JSON: evidence_sha256,
    }
    artifact_sizes = {
        row["relative_path"]: row["bytes"]
        for row in _full_pool_artifact_records(inputs.bundle, bundle_hashes)
    }
    artifact_sizes[_REPORT_PAYLOAD] = len(payload_bytes)
    artifact_sizes[_RELEASE_EVIDENCE_JSON] = len(evidence_bytes)
    artifacts = [
        {
            "relative_path": relative_path,
            "sha256": sha256,
            "bytes": artifact_sizes[relative_path],
        }
        for relative_path, sha256 in sorted(artifact_hashes.items())
    ]
    candidate_identity = _sha256_bytes(
        _json_bytes(dict(sorted(artifact_hashes.items())))
    )
    manifest = {
        "schema_version": _FULL_POOL_CANDIDATE_MANIFEST_SCHEMA,
        "candidate_type": _FULL_POOL_CANDIDATE_TYPE,
        "implementation_commit": implementation_commit,
        "source_lineage": source_lineage,
        "source_lineage_identity_sha256": source_lineage_identity,
        "report_payload_schema_version": _FULL_POOL_REPORT_PAYLOAD_SCHEMA,
        "report_payload_sha256": payload_sha256,
        "presentation_bundle_identity_sha256": presentation.get("bundle_identity_sha256"),
        "presentation_inventory_identity_sha256": presentation_identity,
        "mechanism_set_identity_sha256": mechanism.get("mechanism_set_identity_sha256"),
        "trace_index_sha256": trace_index.get("sha256"),
        "candidate_content_identity_sha256": content_identity,
        "candidate_identity_sha256": candidate_identity,
        "artifacts": artifacts,
        "approved_downloads": presentation.get("approved_downloads"),
        "provider_calls_during_composition": 0,
        "image_generation_triggered": False,
        "canonical_deployment_triggered": False,
        "production_deploy_eligible": False,
    }
    return {
        _REPORT_PAYLOAD: payload_bytes,
        _RELEASE_EVIDENCE_JSON: evidence_bytes,
        CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON: _json_bytes(manifest),
    }


def _validate_full_pool_candidate_directory(
    candidate: Path,
    *,
    inputs: _FullPoolCandidateInputs,
    implementation_commit: str,
) -> _FullPoolCandidateFacts:
    try:
        absolute = Path(os.path.abspath(candidate))
        resolved = candidate.resolve(strict=True)
        if absolute != resolved or candidate.is_symlink() or not resolved.is_dir():
            raise ValueError("Full-Pool candidate is not one real directory")
        actual_hashes = _directory_file_hashes(resolved)
        bundle_hashes = _directory_file_hashes(inputs.bundle)
        contracts = _build_full_pool_candidate_contracts(inputs, implementation_commit)
        expected_paths = set(bundle_hashes) | set(contracts)
        if set(actual_hashes) != expected_paths:
            raise ValueError("Full-Pool candidate has missing or extra artifacts")
        if any(actual_hashes[path] != sha256 for path, sha256 in bundle_hashes.items()):
            raise ValueError("Full-Pool candidate presentation bytes differ from its closed bundle")
        for relative_path, expected in contracts.items():
            target = resolved / relative_path
            if target.read_bytes() != expected:
                raise ValueError(f"Full-Pool candidate contract is not reproducible: {relative_path}")

        payload = _read_json(resolved / _REPORT_PAYLOAD)
        evidence = _read_json(resolved / _RELEASE_EVIDENCE_JSON)
        manifest = _read_json(resolved / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON)
        if (
            payload.get("schema_version") != _FULL_POOL_REPORT_PAYLOAD_SCHEMA
            or evidence.get("schema_version") != _FULL_POOL_RELEASE_EVIDENCE_SCHEMA
            or manifest.get("schema_version") != _FULL_POOL_CANDIDATE_MANIFEST_SCHEMA
            or payload.get("production_deploy_eligible") is not False
            or evidence.get("production_deploy_eligible") is not False
            or manifest.get("production_deploy_eligible") is not False
            or payload.get("provider_calls_during_composition") != 0
            or evidence.get("provider_calls_during_composition") != 0
            or manifest.get("provider_calls_during_composition") != 0
        ):
            raise ValueError("Full-Pool candidate schema, eligibility, or Provider accounting is crossed")
        artifacts = _object_sequence(manifest.get("artifacts"), "Full-Pool candidate artifacts")
        if any(set(row) != {"relative_path", "sha256", "bytes"} for row in artifacts):
            raise ValueError("Full-Pool candidate artifact fields are missing or unexpected")
        artifact_paths: list[str] = []
        for row in artifacts:
            raw_relative_path = row.get("relative_path")
            if not isinstance(raw_relative_path, str) or not raw_relative_path:
                raise ValueError("Full-Pool candidate artifact path is invalid")
            artifact_paths.append(raw_relative_path)
        if artifact_paths != sorted(artifact_paths) or len(set(artifact_paths)) != len(artifact_paths):
            raise ValueError("Full-Pool candidate artifact inventory is duplicated or non-canonical")
        expected_artifact_paths = expected_paths - {CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON}
        if set(artifact_paths) != expected_artifact_paths:
            raise ValueError("Full-Pool candidate manifest inventory is incomplete")
        for row in artifacts:
            relative_path = str(row["relative_path"])
            target = resolved / relative_path
            if (
                row.get("sha256") != actual_hashes[relative_path]
                or row.get("bytes") != target.stat().st_size
            ):
                raise ValueError("Full-Pool candidate artifact hash or size is crossed")
        artifact_hashes = {
            str(row["relative_path"]): str(row["sha256"])
            for row in artifacts
        }
        candidate_identity = _sha256_bytes(
            _json_bytes(dict(sorted(artifact_hashes.items())))
        )
        if manifest.get("candidate_identity_sha256") != candidate_identity:
            raise ValueError("Full-Pool candidate identity is crossed")
        content_hashes = {
            path: sha256
            for path, sha256 in artifact_hashes.items()
            if path != _RELEASE_EVIDENCE_JSON
        }
        content_identity = _sha256_bytes(_json_bytes(dict(sorted(content_hashes.items()))))
        if (
            manifest.get("candidate_content_identity_sha256") != content_identity
            or evidence.get("candidate_content_identity_sha256") != content_identity
        ):
            raise ValueError("Full-Pool candidate content identity is crossed")
        presentation = _mapping(payload.get("presentation"), "Full-Pool presentation inventory")
        mechanism = _mapping(
            presentation.get("mechanism_presentation"),
            "Full-Pool mechanism presentation",
        )
        trace = _mapping(presentation.get("trace"), "Full-Pool trace inventory")
        trace_index = _mapping(trace.get("index"), "Full-Pool trace index")
        approved_downloads = _strict_string_mapping(
            payload.get("presentation", {}).get("approved_downloads")
            if isinstance(payload.get("presentation"), Mapping)
            else None,
            "Full-Pool approved downloads",
        )
        forbidden_fragments = (
            ".env",
            "credential",
            "cookie",
            "raw_prompt",
            "raw_response",
            "raw_provider_payload",
            "raw_profile_payload",
            "full_pool_attempt_ledger",
            "full_pool_execution_status",
            "full_pool_execution_identity",
        )
        if any(
            any(fragment in path.lower() for fragment in forbidden_fragments)
            for path in actual_hashes
        ):
            raise ValueError("Full-Pool candidate contains an operational or forbidden raw artifact")
        return _FullPoolCandidateFacts(
            root=resolved,
            manifest_sha256=actual_hashes[CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON],
            candidate_identity_sha256=candidate_identity,
            candidate_content_identity_sha256=content_identity,
            report_sha256=actual_hashes[CONCURRENT_MESSAGE_REPORT_HTML],
            payload_sha256=actual_hashes[_REPORT_PAYLOAD],
            evidence_sha256=actual_hashes[_RELEASE_EVIDENCE_JSON],
            report_payload_schema_version=str(payload["schema_version"]),
            implementation_commit=implementation_commit,
            source_lineage=_mapping(payload.get("source_lineage"), "Full-Pool source lineage"),
            source_lineage_identity_sha256=str(payload["source_lineage_identity_sha256"]),
            presentation_bundle_identity_sha256=str(presentation["bundle_identity_sha256"]),
            presentation_inventory_identity_sha256=str(
                payload["presentation_inventory_identity_sha256"]
            ),
            mechanism_set_identity_sha256=str(mechanism["mechanism_set_identity_sha256"]),
            trace_index_sha256=str(trace_index["sha256"]),
            artifact_hashes=artifact_hashes,
            approved_downloads=approved_downloads,
        )
    except _RobustnessReportClosureError:
        raise
    except (FileNotFoundError, OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise _RobustnessReportClosureError(
            "Full-Pool three-lineage candidate artifacts failed exact closure"
        ) from exc


def _assert_full_pool_candidate_inputs_unchanged(
    snapshots: Mapping[Path, Mapping[str, str]],
) -> None:
    if any(_directory_file_hashes(root) != dict(before) for root, before in snapshots.items()):
        raise _RobustnessReportClosureError("Full-Pool candidate composition mutated immutable input evidence")


def _strict_string_mapping(value: object, label: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str)
        or not key
        or not isinstance(item, str)
        or not item
        for key, item in value.items()
    ):
        raise ValueError(f"{label} must be a non-empty string mapping")
    return dict(value)


def _workspace_root_for_study(study_root: Path) -> Path:
    if not study_root.name.endswith(_CLOSED_STUDY_ROOT_SUFFIX):
        raise _RobustnessReportPathError("immutable study root does not identify its protected workspace")
    workspace_name = study_root.name[: -len(_CLOSED_STUDY_ROOT_SUFFIX)]
    if not workspace_name:
        raise _RobustnessReportPathError("immutable study root has an invalid workspace identity")
    return study_root.with_name(workspace_name)


def _load_study_manifest(
    study_root: Path,
) -> tuple[ConcurrentRobustnessManifest, bytes, str]:
    try:
        from .concurrent_robustness_study import ConcurrentRobustnessManifest as ManifestModel

        manifest_path = study_root / "study_manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError("study manifest is not a regular file")
        payload = manifest_path.read_bytes()
        manifest = ManifestModel.model_validate_json(payload)
        return manifest, payload, _sha256_bytes(payload)
    except _RobustnessReportClosureError:
        raise
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise _RobustnessReportClosureError("immutable study lineage has an invalid manifest") from exc


def _validate_destination(destination: Path, *, protected_roots: Sequence[Path]) -> Path:
    if ".." in destination.parts:
        raise _RobustnessReportPathError("robustness report destination must not contain '..'")
    if os.path.lexists(destination):
        raise _RobustnessReportConflictError("robustness report destination already exists")
    absolute = Path(os.path.abspath(destination))
    try:
        resolved = destination.resolve(strict=False)
    except OSError as exc:
        raise _RobustnessReportPathError("robustness report destination cannot be resolved safely") from exc
    if absolute != resolved:
        raise _RobustnessReportPathError("robustness report destination must not contain symlink components")

    roots: list[Path] = []
    for root in protected_roots:
        try:
            root_absolute = Path(os.path.abspath(root))
            root_resolved = root.resolve(strict=True)
        except OSError as exc:
            raise _RobustnessReportPathError("robustness report source root cannot be resolved safely") from exc
        if root_absolute != root_resolved or root.is_symlink() or not root_resolved.is_dir():
            raise _RobustnessReportPathError("robustness report source roots must be real directories")
        roots.append(root_resolved)
        if (
            resolved == root_resolved
            or resolved.is_relative_to(root_resolved)
            or root_resolved.is_relative_to(resolved)
        ):
            raise _RobustnessReportPathError("robustness report destination must not overlap a source root")

    existing_parent = destination.parent
    while not os.path.lexists(existing_parent):
        parent = existing_parent.parent
        if parent == existing_parent:
            break
        existing_parent = parent
    if not existing_parent.is_dir() or existing_parent.is_symlink():
        raise _RobustnessReportPathError("robustness report destination parent must be a regular directory")
    if any(os.stat(root).st_dev != os.stat(existing_parent).st_dev for root in roots):
        raise _RobustnessReportPathError("robustness report sources and destination must share a filesystem")
    return resolved


def _directory_file_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            if path.is_dir() and not path.is_symlink():
                continue
            raise _RobustnessReportClosureError("candidate contains a symlink or non-regular artifact")
        hashes[path.relative_to(root).as_posix()] = _sha256_file(path)
    return hashes


def _publish_candidate_payloads(
    *,
    destination_dir: str | Path,
    protected_roots: Sequence[Path],
    output_identity: str,
    payloads: Mapping[str, bytes],
    row_counts: Mapping[str, int],
) -> Path:
    destination = _validate_destination(
        Path(destination_dir),
        protected_roots=protected_roots,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.parent.is_symlink():
        raise _RobustnessReportPathError("robustness report destination parent must not be a symlink")
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.{output_identity}.",
            suffix=".staging",
            dir=destination.parent,
        )
    )
    installed = False
    try:
        if os.stat(staging).st_dev != os.stat(destination.parent).st_dev:
            raise _RobustnessReportPathError("robustness report staging must share the destination filesystem")
        for relative_path, payload in payloads.items():
            target = staging / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        _validate_candidate(
            staging,
            expected_payloads=payloads,
            expected_row_counts=row_counts,
        )
        if os.path.lexists(destination):
            raise _RobustnessReportConflictError("robustness report destination appeared during publication")
        os.replace(staging, destination)
        installed = True
        _validate_candidate(
            destination,
            expected_payloads=payloads,
            expected_row_counts=row_counts,
        )
        installed = False
        return destination
    except Exception:
        if os.path.lexists(staging):
            shutil.rmtree(staging, ignore_errors=True)
        if installed and os.path.lexists(destination):
            shutil.rmtree(destination, ignore_errors=True)
        raise


def _build_candidate_projection(
    *,
    formal_root: Path,
    study_root: Path,
    manifest: ConcurrentRobustnessManifest,
    manifest_payload: bytes,
    manifest_sha256: str,
) -> _CandidateProjection:
    try:
        formal = close_concurrent_message_artifacts(formal_root)
    except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise _RobustnessReportClosureError("historical Concurrent Formal closure failed") from exc
    formal_manifest_hash = formal.artifact_hashes.get(CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON)
    if formal_manifest_hash is None or formal_manifest_hash != manifest.source.manifest_sha256:
        raise _RobustnessReportClosureError("historical Formal source is crossed with the robustness manifest")
    closed_study = _close_study_root(
        study_root,
        manifest=manifest,
        manifest_payload=manifest_payload,
        manifest_sha256=manifest_sha256,
        formal_manifest_sha256=formal_manifest_hash,
    )
    rows = _build_report_rows(closed_study, manifest)
    prompt_model_presentation = _build_prompt_model_presentation(manifest)
    report_payload = _build_report_payload(
        formal=formal,
        study=closed_study,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        rows=rows,
    )
    payloads = _candidate_payloads(
        formal=formal,
        study=closed_study,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        rows=rows,
        prompt_model_presentation=prompt_model_presentation,
        report_payload=report_payload,
    )
    return _CandidateProjection(
        formal=formal,
        study=closed_study,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        rows=rows,
        prompt_model_presentation=prompt_model_presentation,
        report_payload=report_payload,
        payloads=payloads,
    )


def _close_study_root(
    root: Path,
    *,
    manifest: ConcurrentRobustnessManifest,
    manifest_payload: bytes,
    manifest_sha256: str,
    formal_manifest_sha256: str,
) -> _ClosedStudy:
    try:
        absolute = Path(os.path.abspath(root))
        resolved = root.resolve(strict=True)
        if absolute != resolved or root.is_symlink() or not resolved.is_dir():
            raise ValueError("study root is not a real directory")
        entries = list(resolved.iterdir())
        if any(path.is_symlink() or not path.is_file() for path in entries):
            raise ValueError("study root contains a non-regular artifact")
        if {path.name for path in entries} != _STUDY_FILES:
            raise ValueError("study root has missing or extra artifacts")
        if (resolved / "study_manifest.json").read_bytes() != manifest_payload:
            raise ValueError("study manifest bytes are crossed")

        file_hashes = {path.name: _sha256_file(path) for path in entries}
        root_manifest = _read_json(resolved / "artifact_manifest.json")
        if root_manifest.get("schema_version") != _STUDY_MANIFEST_SCHEMA:
            raise ValueError("study artifact manifest schema is unsupported")
        if root_manifest.get("root_type") != "immutable_closed_study" or root_manifest.get("status") != "complete":
            raise ValueError("study root is not an immutable complete root")
        artifacts = _string_sequence(root_manifest.get("artifacts"), "study artifact inventory")
        hashes = _string_mapping(root_manifest.get("sha256"), "study artifact hashes")
        if set(artifacts) != _STUDY_HASHED_FILES or set(hashes) != _STUDY_HASHED_FILES:
            raise ValueError("study artifact manifest inventory is incomplete")
        for relative_path, expected_hash in hashes.items():
            if not _is_sha256(expected_hash) or file_hashes[relative_path] != expected_hash:
                raise ValueError("study artifact hash mismatch")
        identity_payload = _json_bytes(dict(sorted(hashes.items())))
        if root_manifest.get("root_identity_sha256") != _sha256_bytes(identity_payload):
            raise ValueError("study root identity hash is crossed")
        if root_manifest.get("manifest_sha256") != manifest_sha256:
            raise ValueError("study manifest hash is crossed")
        if root_manifest.get("source_manifest_sha256") != formal_manifest_sha256:
            raise ValueError("study Formal source link is crossed")
        if root_manifest.get("production_deploy_eligible") is not False:
            raise ValueError("study root must remain non-deployable")
        if root_manifest.get("report_candidate") is not None:
            raise ValueError("study analysis closure cannot already expose a report candidate")

        ranking = _read_json(resolved / "ranking_weight_sensitivity.json")
        prompt_model = _read_json(resolved / "prompt_model_analysis.json")
        claims = _read_json(resolved / "claim_audit.json")
        validation = _read_json(resolved / "validation_report.json")
        _validate_study_documents(
            ranking=ranking,
            prompt_model=prompt_model,
            claims=claims,
            validation=validation,
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            formal_manifest_sha256=formal_manifest_sha256,
        )
        return _ClosedStudy(
            root=resolved,
            root_manifest=root_manifest,
            ranking=ranking,
            prompt_model=prompt_model,
            claims=claims,
            validation=validation,
            file_hashes=file_hashes,
        )
    except _RobustnessReportClosureError:
        raise
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise _RobustnessReportClosureError(
            "immutable complete study root failed independent schema, row-count, and hash closure"
        ) from exc


def _validate_study_documents(
    *,
    ranking: Mapping[str, Any],
    prompt_model: Mapping[str, Any],
    claims: Mapping[str, Any],
    validation: Mapping[str, Any],
    manifest: ConcurrentRobustnessManifest,
    manifest_sha256: str,
    formal_manifest_sha256: str,
) -> None:
    if ranking.get("schema_version") != _WEIGHT_SCHEMA or ranking.get("manifest_sha256") != manifest_sha256:
        raise ValueError("ranking-weight evidence is crossed or unsupported")
    source = _mapping(ranking.get("source"), "ranking-weight source")
    if source.get("manifest_sha256") != formal_manifest_sha256:
        raise ValueError("ranking-weight source link is crossed")
    scenarios = _object_sequence(ranking.get("scenarios"), "ranking-weight scenarios")
    if len(scenarios) != 19:
        raise ValueError("ranking-weight evidence requires 19 scenarios")
    expected_scenarios = [point.scenario_id for point in manifest.weight_points]
    if [str(row.get("scenario_id")) for row in scenarios] != expected_scenarios:
        raise ValueError("ranking-weight scenario order is crossed")
    horizon = manifest.ranking_contract.horizon
    for scenario in scenarios:
        messages = _object_sequence(scenario.get("messages"), "ranking-weight messages")
        if [str(row.get("message_id")) for row in messages] != list(manifest.message_ids):
            raise ValueError("ranking-weight message order is crossed")
        for message in messages:
            batches = _object_sequence(message.get("batches"), "ranking-weight batches")
            if len(batches) != horizon or [int(row.get("time_step", -1)) for row in batches] != list(range(horizon)):
                raise ValueError("ranking-weight batch rows are incomplete")
    counts = _mapping(ranking.get("counts"), "ranking-weight counts")
    if counts != {
        "scenario_count": 19,
        "message_count": len(manifest.message_ids),
        "batch_count_per_message": horizon,
        "scenario_message_batch_count": 19 * len(manifest.message_ids) * horizon,
    }:
        raise ValueError("ranking-weight row counts do not close")

    if prompt_model.get("schema_version") != _PROMPT_MODEL_SCHEMA:
        raise ValueError("Prompt–Model analysis schema is unsupported")
    if prompt_model.get("manifest_sha256") != manifest_sha256 or int(prompt_model.get("cell_count", -1)) != 16:
        raise ValueError("Prompt–Model analysis identity is crossed")
    realized = _mapping(prompt_model.get("realized_paths"), "Prompt–Model realized paths")
    message_summaries = _object_sequence(realized.get("message_summaries"), "message summaries")
    trajectories = _object_sequence(realized.get("message_batch_trajectories"), "message trajectories")
    growth = _object_sequence(realized.get("campaign_deduplicated_positive_user_growth"), "campaign growth")
    if len(message_summaries) != 16 * len(manifest.message_ids):
        raise ValueError("Prompt–Model message summary count does not close")
    if len(trajectories) != 16 * len(manifest.message_ids) * horizon:
        raise ValueError("Prompt–Model trajectory row count does not close")
    if len(growth) != 16 * horizon:
        raise ValueError("Prompt–Model growth row count does not close")
    direct = _mapping(prompt_model.get("shared_seed_direct_decisions"), "shared-seed Decisions")
    exact_rows = _object_sequence(direct.get("exact_value_rows"), "shared-seed exact rows")
    if int(direct.get("exact_value_row_count", -1)) != len(exact_rows):
        raise ValueError("shared-seed exact row count does not close")
    if str(prompt_model.get("conditional_scope")) != "fixed_sample_fixed_graph_one_realized_path_per_cell":
        raise ValueError("Prompt–Model conditional scope is unsupported")

    if claims.get("schema_version") != _CLAIM_AUDIT_SCHEMA or claims.get("status") != "passed":
        raise ValueError("claim audit did not pass")
    if claims.get("ground_truth_used") is not False or claims.get("causal_claims_allowed") is not False:
        raise ValueError("claim audit boundary is crossed")
    if claims.get("statistical_equivalence_claims_allowed") is not False:
        raise ValueError("claim audit equivalence boundary is crossed")
    if validation.get("schema_version") != _STUDY_VALIDATION_SCHEMA or validation.get("status") != "complete":
        raise ValueError("study validation is not complete")
    if validation.get("manifest_sha256") != manifest_sha256:
        raise ValueError("study validation manifest hash is crossed")
    if validation.get("source_manifest_sha256") != formal_manifest_sha256:
        raise ValueError("study validation Formal source is crossed")
    if validation.get("production_deploy_eligible") is not False or validation.get("report_candidate") is not None:
        raise ValueError("study validation cannot authorize a report release")
    validation_counts = _mapping(validation.get("counts"), "study validation counts")
    if int(validation_counts.get("cell_count", -1)) != 16:
        raise ValueError("study validation cell count does not close")
    if int(validation_counts.get("message_count", -1)) != len(manifest.message_ids):
        raise ValueError("study validation message count does not close")
    if int(validation_counts.get("realized_logical_judgments", -1)) != manifest.request_caps.logical_judgment_cap:
        raise ValueError("study validation logical judgments do not close")


def _build_report_rows(study: _ClosedStudy, manifest: ConcurrentRobustnessManifest) -> _ReportRows:
    weight_messages: list[dict[str, Any]] = []
    weight_batches: list[dict[str, Any]] = []
    for scenario in _object_sequence(study.ranking["scenarios"], "ranking scenarios"):
        weights = _mapping(scenario.get("weights"), "ranking scenario weights")
        for message in _object_sequence(scenario.get("messages"), "ranking scenario messages"):
            weight_messages.append(
                {
                    "scenario_id": scenario["scenario_id"],
                    "message_id": message["message_id"],
                    "transfer_from": scenario.get("transfer_from"),
                    "transfer_to": scenario.get("transfer_to"),
                    "transfer_mass": scenario["transfer_mass"],
                    "base_network_relevance_weight": weights["base_network_relevance"],
                    "campaign_engaged_neighbor_signal_weight": weights["campaign_engaged_neighbor_signal"],
                    "normalized_message_user_fit_weight": weights["normalized_message_user_fit"],
                    "mean_jaccard_distance": message["curve_mean_jaccard_distance"],
                    "auc_jaccard_distance": message["curve_auc_jaccard_distance"],
                    "first_divergent_batch": message.get("first_divergent_batch"),
                }
            )
            for batch in _object_sequence(message.get("batches"), "ranking scenario batches"):
                rank_deltas = _object_sequence(batch.get("rank_deltas"), "rank deltas")
                absolute_deltas = [abs(int(row["rank_delta"])) for row in rank_deltas]
                weight_batches.append(
                    {
                        "scenario_id": scenario["scenario_id"],
                        "message_id": message["message_id"],
                        "time_step": batch["time_step"],
                        "jaccard_distance": batch["jaccard_distance"],
                        "entered_user_count": len(_sequence(batch.get("entered_user_ids"), "entered users")),
                        "exited_user_count": len(_sequence(batch.get("exited_user_ids"), "exited users")),
                        "first_divergent_rank": batch.get("first_divergent_rank"),
                        "mean_absolute_rank_delta": _round(sum(absolute_deltas) / len(absolute_deltas)) if absolute_deltas else 0.0,
                        "max_absolute_rank_delta": max(absolute_deltas, default=0),
                    }
                )

    cell_identity = {
        cell.cell_id: {"prompt_variant": cell.prompt_variant, "requested_model": cell.requested_model}
        for cell in manifest.prompt_model_cells
    }
    direct = _mapping(study.prompt_model["shared_seed_direct_decisions"], "shared-seed direct analysis")
    grouped_direct: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in _object_sequence(direct.get("exact_value_rows"), "shared-seed exact rows"):
        grouped_direct[(str(row["cell_id"]), str(row["message_id"]))].append(row)
    shared_seed: list[dict[str, Any]] = []
    for cell in manifest.prompt_model_cells:
        for message_id in manifest.message_ids:
            rows = grouped_direct[(cell.cell_id, message_id)]
            if not rows:
                raise _RobustnessReportClosureError("shared-seed report rows are incomplete")
            shared_seed.append(
                {
                    "cell_id": cell.cell_id,
                    "prompt_variant": cell.prompt_variant,
                    "requested_model": cell.requested_model,
                    "message_id": message_id,
                    "observation_count": len(rows),
                    "engage_rate": _round(sum(int(bool(row["engage"])) for row in rows) / len(rows)),
                    "mean_probability": _round(sum(float(row["probability"]) for row in rows) / len(rows)),
                    "mean_confidence": _round(sum(float(row["confidence"]) for row in rows) / len(rows)),
                }
            )

    realized = _mapping(study.prompt_model["realized_paths"], "Prompt–Model realized paths")
    prompt_messages = [
        {**cell_identity[str(row["cell_id"])], **dict(row)}
        for row in _object_sequence(realized.get("message_summaries"), "message summaries")
    ]
    prompt_trajectories = [
        {
            **cell_identity[str(row["cell_id"])],
            **{field: row.get(field) for field in _PROMPT_TRAJECTORY_FIELDS if field not in {"prompt_variant", "requested_model"}},
        }
        for row in _object_sequence(realized.get("message_batch_trajectories"), "message trajectories")
    ]
    prompt_growth = [
        {
            **cell_identity[str(row["cell_id"])],
            "cell_id": row["cell_id"],
            "time_step": row["time_step"],
            "cumulative_campaign_deduplicated_positive_user_count": row[
                "cumulative_campaign_deduplicated_positive_user_count"
            ],
        }
        for row in _object_sequence(
            realized.get("campaign_deduplicated_positive_user_growth"),
            "campaign growth",
        )
    ]
    thresholds = [
        {field: row.get(field) for field in _THRESHOLD_FIELDS}
        for row in _object_sequence(
            study.prompt_model.get("practical_threshold_classifications"),
            "practical threshold rows",
        )
    ]
    report_rows = _ReportRows(
        weight_messages=weight_messages,
        weight_batches=weight_batches,
        shared_seed=shared_seed,
        prompt_messages=prompt_messages,
        prompt_trajectories=prompt_trajectories,
        prompt_growth=prompt_growth,
        thresholds=thresholds,
    )
    expected_counts = {
        "ranking_weight_message_summary": 19 * len(manifest.message_ids),
        "ranking_weight_batch_diagnostics": 19 * len(manifest.message_ids) * manifest.ranking_contract.horizon,
        "prompt_model_shared_seed_summary": 16 * len(manifest.message_ids),
        "prompt_model_message_summary": 16 * len(manifest.message_ids),
        "prompt_model_trajectory_summary": 16 * len(manifest.message_ids) * manifest.ranking_contract.horizon,
        "prompt_model_campaign_growth": 16 * manifest.ranking_contract.horizon,
        "prompt_model_practical_thresholds": len(thresholds),
    }
    if report_rows.counts() != expected_counts:
        raise _RobustnessReportClosureError("report companion table row counts do not close")
    return report_rows


def _build_prompt_model_presentation(
    manifest: ConcurrentRobustnessManifest,
) -> _PromptModelPresentation:
    contracts = CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.all()
    if len(contracts) != 4:
        raise _RobustnessReportClosureError("Prompt disclosure requires exactly four registry contracts")
    baseline = contracts[0]
    shared_contract_fields = (
        "visible_field_allowlist",
        "task_semantics",
        "action_semantics",
        "output_schema",
    )
    if any(
        any(getattr(contract, field) != getattr(baseline, field) for field in shared_contract_fields)
        for contract in contracts[1:]
    ):
        raise _RobustnessReportClosureError("Prompt variants do not share one declared information and output contract")

    manifest_cells = tuple(manifest.prompt_model_cells)
    model_ids = tuple(dict.fromkeys(cell.requested_model for cell in manifest_cells))
    disclosure_rows: list[_PromptContractDisclosure] = []
    for contract in contracts:
        cells = tuple(cell for cell in manifest_cells if cell.prompt_variant == contract.variant_id)
        if (
            tuple(cell.requested_model for cell in cells) != model_ids
            or any(cell.prompt_version != contract.prompt_version for cell in cells)
            or any(cell.prompt_canonical_hash != contract.canonical_hash for cell in cells)
        ):
            raise _RobustnessReportClosureError("Prompt disclosure is crossed with the verified Manifest identity")
        disclosure_rows.append(
            _PromptContractDisclosure(
                variant_id=contract.variant_id,
                controlled_change=CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.controlled_change(
                    contract.variant_id
                ),
                prompt_version=contract.prompt_version,
                canonical_hash=contract.canonical_hash,
                model_count=len(cells),
            )
        )

    prompt_count = len(disclosure_rows)
    model_count = len(model_ids)
    cell_count = len(manifest_cells)
    message_count = len(manifest.message_ids)
    if cell_count != prompt_count * model_count or model_count != 4 or message_count != 3:
        raise _RobustnessReportClosureError("Prompt-Model presentation denominator does not close")
    output_schema = baseline.output_schema
    return _PromptModelPresentation(
        contracts=tuple(disclosure_rows),
        visible_field_allowlist=baseline.visible_field_allowlist,
        task_semantics=baseline.task_semantics,
        action_semantics=baseline.action_semantics,
        output_schema_version=output_schema.schema_version,
        output_fields=output_schema.required_fields,
        output_action_values=output_schema.action_values,
        engage_action_rules=output_schema.engage_action_rules,
        prompt_count=prompt_count,
        model_count=model_count,
        cell_count=cell_count,
        message_count=message_count,
        reporting_slice_count=cell_count * message_count,
        logical_judgments_per_cell=manifest.request_caps.logical_judgments_per_cell,
        logical_judgment_count=manifest.request_caps.logical_judgment_cap,
        horizon=manifest.ranking_contract.horizon,
        delivery_capacity=manifest.ranking_contract.delivery_capacity,
        weight_point_count=len(manifest.weight_points),
    )


def _prompt_presentation_catalog(
    presentation: _PromptModelPresentation,
) -> dict[str, dict[str, str]]:
    expected_keys = set(_PROMPT_PRESENTATION_COPY["zh-CN"])
    if set(_PROMPT_PRESENTATION_COPY) != {"zh-CN", "en-US"} or any(
        set(copy) != expected_keys for copy in _PROMPT_PRESENTATION_COPY.values()
    ):
        raise _RobustnessReportClosureError("Prompt presentation language catalog is asymmetric")
    values = {
        "prompt_count": str(presentation.prompt_count),
        "model_count": str(presentation.model_count),
        "cell_count": str(presentation.cell_count),
        "message_count": str(presentation.message_count),
        "slice_count": str(presentation.reporting_slice_count),
        "per_cell": f"{presentation.logical_judgments_per_cell:,}",
        "total": f"{presentation.logical_judgment_count:,}",
        "horizon": str(presentation.horizon),
    }
    return {
        language: {key: text.format(**values) for key, text in copy.items()}
        for language, copy in _PROMPT_PRESENTATION_COPY.items()
    }


def _presentation_catalog(
    presentation: _PromptModelPresentation,
) -> dict[str, dict[str, str]]:
    prompt_catalog = _prompt_presentation_catalog(presentation)
    expected_reader_keys = set(_READER_DIAGRAM_COPY["zh-CN"])
    if set(_READER_DIAGRAM_COPY) != {"zh-CN", "en-US"} or any(
        set(copy) != expected_reader_keys for copy in _READER_DIAGRAM_COPY.values()
    ):
        raise _RobustnessReportClosureError("Reader diagram language catalog is asymmetric")
    values = {
        "delivery_capacity": str(presentation.delivery_capacity),
        "model_count": str(presentation.model_count),
        "weight_point_count": str(presentation.weight_point_count),
    }
    return {
        language: {
            **prompt_catalog[language],
            **{key: text.format(**values) for key, text in _READER_DIAGRAM_COPY[language].items()},
        }
        for language in ("zh-CN", "en-US")
    }


def _semantic_presentation_catalog(
    presentation: _PromptModelPresentation,
) -> dict[str, dict[str, str]]:
    prompt_catalog = _prompt_presentation_catalog(presentation)
    expected = set(_SEMANTIC_ROBUSTNESS_COPY["zh-CN"])
    if set(_SEMANTIC_ROBUSTNESS_COPY) != {"zh-CN", "en-US"} or any(
        set(copy) != expected for copy in _SEMANTIC_ROBUSTNESS_COPY.values()
    ):
        raise _RobustnessReportClosureError("semantic robustness language catalog is asymmetric")
    catalog = {
        language: {
            **prompt_catalog[language],
            **_SEMANTIC_ROBUSTNESS_COPY[language],
        }
        for language in ("zh-CN", "en-US")
    }
    unknown_overrides = set(_SEMANTIC_ZH_COPY) - set(catalog["zh-CN"])
    if unknown_overrides:
        raise _RobustnessReportClosureError(
            f"semantic Chinese overrides contain unknown keys: {sorted(unknown_overrides)}"
        )
    catalog["zh-CN"].update(_SEMANTIC_ZH_COPY)
    if set(catalog["zh-CN"]) != set(catalog["en-US"]):
        raise _RobustnessReportClosureError("semantic presentation language catalog is asymmetric")
    return catalog


def _robustness_i18n(
    catalog: Mapping[str, Mapping[str, str]],
    key: str,
    *,
    tag: str = "span",
    class_name: str = "",
    attrs: str = "",
) -> str:
    default = _mapping(catalog.get("zh-CN"), "zh-CN Prompt presentation copy")
    if key not in default:
        raise _RobustnessReportClosureError(f"Prompt presentation copy key is missing: {key}")
    classes = f' class="{_escape(class_name, quote=True)}"' if class_name else ""
    return (
        f'<{tag}{classes} data-robustness-i18n="{_escape(key, quote=True)}"{attrs}>'
        f"{_escape(default[key])}</{tag}>"
    )


def _robustness_i18n_attribute(
    catalog: Mapping[str, Mapping[str, str]],
    key: str,
    attribute: str,
) -> str:
    default = _mapping(catalog.get("zh-CN"), "zh-CN Prompt presentation copy")
    if key not in default:
        raise _RobustnessReportClosureError(f"Prompt presentation copy key is missing: {key}")
    return (
        f'data-robustness-i18n-{_escape(attribute, quote=True)}="{_escape(key, quote=True)}" '
        f'{attribute}="{_escape(default[key], quote=True)}"'
    )


def _contract_token_list(values: Sequence[str], *, stable_tokens: bool = False) -> str:
    marker = ' data-stable-token="contract-value"' if stable_tokens else ""
    return "".join(f"<li><code{marker}>{_escape(value)}</code></li>" for value in values)


def _prompt_contract_disclosure(
    presentation: _PromptModelPresentation,
    catalog: Mapping[str, Mapping[str, str]],
    *,
    stable_tokens: bool = False,
) -> str:
    stable_marker = ' data-stable-token="contract-value"' if stable_tokens else ""
    rows: list[str] = []
    for contract in presentation.contracts:
        row_id = f"prompt-contract-row-{contract.variant_id.lower()}"
        label_key = f"variant.{contract.controlled_change}.label"
        body_key = f"variant.{contract.controlled_change}.body"
        rows.append(
            f'<article id="{row_id}" class="robustness-prompt-contract-row" role="listitem" '
            f'data-testid="{row_id}" data-prompt-variant="{contract.variant_id}" '
            f'data-controlled-change="{contract.controlled_change}" '
            f'data-prompt-version="{_escape(contract.prompt_version, quote=True)}" '
            f'data-prompt-canonical-hash="{_escape(contract.canonical_hash, quote=True)}" '
            f'data-model-count="{contract.model_count}">'
            '<header><div class="robustness-prompt-identity">'
            f'{_legend_sample(_PROMPT_STYLES[contract.variant_id])}'
            f'<strong{stable_marker}>{contract.variant_id}</strong>'
            f'{_robustness_i18n(catalog, label_key, class_name="robustness-prompt-change")}'
            "</div>"
            f'{_robustness_i18n(catalog, body_key, tag="p")}</header>'
            '<details class="robustness-prompt-details">'
            f'<summary>{_robustness_i18n(catalog, "contract.details")}</summary>'
            '<dl class="robustness-prompt-token"><div>'
            f'<dt>{_robustness_i18n(catalog, "contract.token")}</dt>'
            f'<dd><code{stable_marker}>{_escape(contract.prompt_version)}</code></dd></div></dl>'
            '<div class="robustness-prompt-hash">'
            f'<strong>{_robustness_i18n(catalog, "contract.hash_summary")}</strong>'
            f'<code{stable_marker}>{_escape(contract.canonical_hash)}</code></div>'
            f'{_robustness_i18n(catalog, "contract.models", tag="p", class_name="robustness-prompt-model-note")}'
            "</details></article>"
        )

    cells_formula = (
        f"{presentation.prompt_count} Prompt × {presentation.model_count} model = "
        f"{presentation.cell_count} execution cells"
    )
    slices_formula = (
        f"{presentation.cell_count} cells × {presentation.message_count} messages = "
        f"{presentation.reporting_slice_count} message-level reporting slices"
    )
    shared_contract = (
        '<details class="robustness-shared-contract" data-testid="prompt-model-shared-contract" open>'
        f'<summary>{_robustness_i18n(catalog, "common.summary")}</summary>'
        f'{_robustness_i18n(catalog, "common.note", tag="p")}'
        '<div class="robustness-shared-contract-grid">'
        '<section><h4>'
        f'{_robustness_i18n(catalog, "common.fields")}</h4><ul>'
        f'{_contract_token_list(presentation.visible_field_allowlist, stable_tokens=stable_tokens)}</ul></section>'
        '<section><h4>'
        f'{_robustness_i18n(catalog, "common.task")}</h4><ul>'
        f'{_contract_token_list(presentation.task_semantics, stable_tokens=stable_tokens)}</ul>'
        '<h4>'
        f'{_robustness_i18n(catalog, "common.actions")}</h4><ul>'
        f'{_contract_token_list(presentation.action_semantics, stable_tokens=stable_tokens)}</ul></section>'
        '<section><h4>'
        f'{_robustness_i18n(catalog, "common.output")}</h4>'
        f'<p><code{stable_marker}>{_escape(presentation.output_schema_version)}</code></p>'
        '<dl class="robustness-output-contract">'
        f'<div><dt>{_robustness_i18n(catalog, "common.output_fields")}</dt>'
        f'<dd><code{stable_marker}>{_escape(" / ".join(presentation.output_fields))}</code></dd></div>'
        f'<div><dt>{_robustness_i18n(catalog, "common.output_actions")}</dt>'
        f'<dd><code{stable_marker}>{_escape(" / ".join(presentation.output_action_values))}</code></dd></div>'
        f'<div><dt>{_robustness_i18n(catalog, "common.engage_rules")}</dt>'
        f'<dd><code{stable_marker}>{_escape("; ".join(presentation.engage_action_rules))}</code></dd></div>'
        "</dl></section></div></details>"
    )
    scope_rows = "".join(
        '<article><h4>'
        f'{_robustness_i18n(catalog, f"scope.{scope}.title")}</h4>'
        f'{_robustness_i18n(catalog, f"scope.{scope}.body", tag="p")}</article>'
        for scope in ("direct", "paths", "shadow")
    )
    contract_title = _robustness_i18n(
        catalog,
        "contract.title",
        tag="h3",
        attrs=' id="prompt-model-contract-title"',
    )
    denominator_aria = (
        _robustness_i18n_attribute(
            catalog,
            "semantic.prompt.denominator_aria",
            "aria-label",
        )
        if stable_tokens
        else 'aria-label="Prompt-Model denominators"'
    )
    return (
        '<section class="robustness-prompt-contract" data-testid="prompt-model-contract-disclosure" '
        'aria-labelledby="prompt-model-contract-title">'
        '<div class="robustness-contract-heading">'
        f'{contract_title}{_robustness_i18n(catalog, "contract.lead", tag="p")}</div>'
        f'<div class="robustness-denominator-grid" {denominator_aria}>'
        f'<article data-testid="prompt-model-cell-denominator"><strong{stable_marker}>{_escape(cells_formula)}</strong>'
        f'{_robustness_i18n(catalog, "contract.cells")}</article>'
        f'<article data-testid="prompt-model-slice-denominator"><strong{stable_marker}>{_escape(slices_formula)}</strong>'
        f'{_robustness_i18n(catalog, "contract.slices")}</article></div>'
        f'{_robustness_i18n(catalog, "contract.dimension_note", tag="p", class_name="robustness-dimension-note")}'
        f'<div class="robustness-prompt-contract-grid" role="list">{"".join(rows)}</div>'
        f"{shared_contract}"
        f'<div class="robustness-factorial-scope">{scope_rows}</div>'
        "</section>"
    )


def _diagram_svg_node(
    catalog: Mapping[str, Mapping[str, str]],
    node: _DiagramNode,
) -> str:
    label = _robustness_i18n(
        catalog,
        node.label_key,
        tag="div",
        class_name="robustness-semantic-node-label",
        attrs=' xmlns="http://www.w3.org/1999/xhtml"',
    )
    mark = (
        f' id="{_escape(node.mark_id, quote=True)}" '
        f'data-diagram-mark-id="{_escape(node.mark_id, quote=True)}"'
        if node.mark_id
        else ""
    )
    return (
        f'<g class="robustness-semantic-node robustness-semantic-node-{_escape(node.kind, quote=True)}" '
        f'data-diagram-node-id="{_escape(node.node_id, quote=True)}" '
        f'data-node-kind="{_escape(node.kind, quote=True)}" '
        f'data-provenance="{_escape(node.provenance, quote=True)}" '
        f'transform="translate({node.x} {node.y})">'
        f'<rect{mark} width="{node.width}" height="{node.height}" rx="8" ry="8"/>'
        f'<foreignObject x="10" y="8" width="{node.width - 20}" height="{node.height - 16}">'
        f"{label}</foreignObject></g>"
    )


def _diagram_svg_edge(
    catalog: Mapping[str, Mapping[str, str]],
    edge: _DiagramEdge,
    *,
    marker_id: str,
) -> str:
    mark = (
        f' id="{_escape(edge.mark_id, quote=True)}" '
        f'data-diagram-mark-id="{_escape(edge.mark_id, quote=True)}"'
        if edge.mark_id
        else ""
    )
    path = (
        f'<path{mark} class="robustness-semantic-edge robustness-semantic-edge-{_escape(edge.style, quote=True)}" '
        f'data-diagram-edge-id="{_escape(edge.edge_id, quote=True)}" '
        f'data-from="{_escape(edge.source, quote=True)}" data-to="{_escape(edge.target, quote=True)}" '
        f'data-direction="{_escape(edge.direction, quote=True)}" '
        f'data-condition="{_escape(edge.condition, quote=True)}" '
        f'data-timing="{_escape(edge.timing, quote=True)}" '
        f'data-effect="{_escape(edge.effect, quote=True)}" '
        f'data-provenance="{_escape(edge.provenance, quote=True)}" '
        f'd="{_escape(edge.path, quote=True)}" marker-end="url(#{_escape(marker_id, quote=True)})"/>'
    )
    if not edge.label_key:
        return path
    label = _robustness_i18n(
        catalog,
        edge.label_key,
        tag="div",
        class_name="robustness-semantic-edge-label",
        attrs=' xmlns="http://www.w3.org/1999/xhtml"',
    )
    return (
        f"{path}<foreignObject class=\"robustness-semantic-edge-label-box\" "
        f'x="{edge.label_x}" y="{edge.label_y}" width="{edge.label_width}" height="36">'
        f"{label}</foreignObject>"
    )


def _mermaid_label(value: str) -> str:
    return " ".join(value.replace('"', "'").split())


def _diagram_mermaid_source(
    catalog: Mapping[str, Mapping[str, str]],
    language: str,
    *,
    title_key: str,
    description_key: str,
    nodes: Sequence[_DiagramNode],
    edges: Sequence[_DiagramEdge],
) -> str:
    copy = _mapping(catalog.get(language), f"{language} presentation copy")
    node_lines = [
        f'    {node.node_id}["{_mermaid_label(str(copy[node.label_key]))}"]'
        for node in nodes
    ]
    edge_lines: list[str] = []
    metadata_lines: list[str] = []
    for edge in edges:
        connector = "-.->" if edge.style == "dotted" else "-->"
        label = f'|"{_mermaid_label(str(copy[edge.label_key]))}"|' if edge.label_key else ""
        edge_lines.append(
            f"    {edge.source} {edge.edge_id}@{connector}{label} {edge.target}"
        )
        metadata_lines.append(
            "    %% edge "
            f"{edge.edge_id} from={edge.source} to={edge.target} direction={edge.direction} "
            f"condition={edge.condition} timing={edge.timing} effect={edge.effect} "
            f"provenance={edge.provenance}"
        )
    node_metadata = [
        f"    %% node {node.node_id} kind={node.kind} provenance={node.provenance}"
        for node in nodes
    ]
    return "\n".join(
        [
            "flowchart TB",
            f'    accTitle: {_mermaid_label(str(copy[title_key]))}',
            f'    accDescr: {_mermaid_label(str(copy[description_key]))}',
            *node_lines,
            *edge_lines,
            *node_metadata,
            *metadata_lines,
        ]
    )


def _project_evidence_chain_semantics() -> tuple[tuple[_DiagramNode, ...], tuple[_DiagramEdge, ...]]:
    nodes = (
        _DiagramNode("Inputs", "project.node.Inputs", 20, 40, 190, 70, "input", "concurrent-message-source-contract"),
        _DiagramNode("Runner", "project.node.Runner", 260, 40, 230, 70, "runtime", "ConcurrentMessageExperimentRunner"),
        _DiagramNode("Kernel", "project.node.Kernel", 540, 40, 230, 70, "runtime", "_ConcurrentRuntimeKernel"),
        _DiagramNode("Adapter", "project.node.Adapter", 920, 40, 240, 70, "adapter", "LLMDecisionAdapter"),
        _DiagramNode("Formal", "project.node.Formal", 260, 245, 230, 70, "evidence", "concurrent-formal-source", "project-mark-evidence"),
        _DiagramNode("Study", "project.node.Study", 540, 245, 230, 70, "study", "ConcurrentRobustnessStudy"),
        _DiagramNode("Weight", "project.node.Weight", 820, 190, 220, 82, "analysis", "concurrent-ranking-weight-sensitivity-v1"),
        _DiagramNode("Matrix", "project.node.Matrix", 820, 300, 260, 82, "analysis", "concurrent-prompt-model-robustness-analysis-v1"),
        _DiagramNode("Root", "project.node.Root", 1110, 245, 230, 70, "evidence", "concurrent-robustness-study-artifact-manifest-v1"),
        _DiagramNode("Report", "project.node.Report", 540, 480, 230, 70, "report", "_ReportPresentationInterface"),
        _DiagramNode("Release", "project.node.Release", 830, 480, 230, 70, "release", "abm-report-release-contract-v5", "project-mark-release"),
        _DiagramNode("Canonical", "project.node.Canonical", 1120, 480, 220, 70, "canonical", "canonical-endpoint-contract"),
    )
    edges = (
        _DiagramEdge("project-edge-inputs-runner", "Inputs", "Runner", "M210 75 H254", "fixed_inputs_closed", "run_preflight", "initialize_runner", "concurrent-message-source-contract", mark_id="project-mark-runtime"),
        _DiagramEdge("project-edge-runner-kernel", "Runner", "Kernel", "M490 75 H534", "preflight_passed", "runtime", "execute_concurrent_batches", "ConcurrentMessageExperimentRunner"),
        _DiagramEdge("project-edge-kernel-adapter", "Kernel", "Adapter", "M770 61 H914", "user_message_pair_exposed", "after_exposure", "create_decision_input", "_ConcurrentRuntimeKernel", label_key="project.edge.decision_input", label_x=775, label_y=17, label_width=138),
        _DiagramEdge("project-edge-adapter-kernel", "Adapter", "Kernel", "M920 94 H776", "structured_decision_valid", "decision_return", "register_terminal_decision", "LLMDecisionAdapter", direction="reverse", label_key="project.edge.decision", label_x=780, label_y=101, label_width=134),
        _DiagramEdge("project-edge-runner-formal", "Runner", "Formal", "M375 110 V239", "all_required_terminals_closed", "post_run", "persist_runtime_evidence", "ConcurrentMessageExperimentRunner", label_key="project.edge.persist", label_x=386, label_y=154, label_width=150),
        _DiagramEdge("project-edge-formal-study", "Formal", "Study", "M490 280 H534", "formal_source_closed", "study_preflight", "validate_and_start_study", "ConcurrentRobustnessStudy"),
        _DiagramEdge("project-edge-study-weight", "Study", "Weight", "M770 266 H794 V231 H814", "weight_manifest_closed", "offline_study", "produce_weight_sensitivity", "concurrent-ranking-weight-sensitivity-v1"),
        _DiagramEdge("project-edge-study-matrix", "Study", "Matrix", "M770 294 H794 V341 H814", "all_prompt_model_cells_terminal", "formal_study", "produce_primary_only_matrix", "concurrent-prompt-model-robustness-analysis-v1"),
        _DiagramEdge("project-edge-weight-root", "Weight", "Root", "M1040 231 H1070 V266 H1104", "weight_evidence_valid", "study_closure", "include_weight_evidence", "concurrent-robustness-study-artifact-manifest-v1"),
        _DiagramEdge("project-edge-matrix-root", "Matrix", "Root", "M1080 341 H1092 V294 H1104", "matrix_evidence_valid", "study_closure", "include_prompt_model_evidence", "concurrent-robustness-study-artifact-manifest-v1"),
        _DiagramEdge("project-edge-formal-report", "Formal", "Report", "M375 315 V430 H655 V474", "formal_lineage_closed", "report_composition", "supply_historical_evidence", "_ReportPresentationInterface"),
        _DiagramEdge("project-edge-root-report", "Root", "Report", "M1225 315 V430 H655 V474", "study_lineage_closed", "report_composition", "supply_robustness_evidence", "_ReportPresentationInterface"),
        _DiagramEdge("project-edge-report-release", "Report", "Release", "M770 515 H824", "presentation_bundle_valid", "release_closure", "close_inventory_and_hashes", "abm-report-release-contract-v5"),
        _DiagramEdge("project-edge-release-canonical", "Release", "Canonical", "M1060 515 H1114", "immutable_release_accepted", "deployment", "publish_canonical_webpage", "canonical-endpoint-contract"),
    )
    return nodes, edges


def _project_evidence_chain_diagram(
    catalog: Mapping[str, Mapping[str, str]],
) -> str:
    nodes, edges = _project_evidence_chain_semantics()
    source_blocks = "".join(
        f'<pre data-robustness-language-variant="{language}"{shepherd}><code class="language-mermaid">'
        f'{_escape(_diagram_mermaid_source(catalog, language, title_key="project.title", description_key="project.description", nodes=nodes, edges=edges))}'
        "</code></pre>"
        for language, shepherd in (("zh-CN", ""), ("en-US", " hidden"))
    )
    fallback_rows = "".join(
        f'<li>{_robustness_i18n(catalog, f"project.fallback.{key}")}</li>'
        for key in ("inputs", "decision", "formal", "root", "publish")
    )
    legend = "".join(
        '<li class="robustness-semantic-legend-item" '
        f'data-legend-mark-id="project-mark-{mark}"><span class="robustness-semantic-legend-swatch robustness-semantic-legend-swatch-{mark}" aria-hidden="true"></span>'
        f'{_robustness_i18n(catalog, f"project.legend.{label}")}</li>'
        for mark, label in (("runtime", "runtime"), ("evidence", "evidence"), ("release", "release"))
    )
    heading = _robustness_i18n(
        catalog,
        "project.heading",
        tag="h2",
        attrs=' id="project-evidence-chain-heading"',
    )
    title = _robustness_i18n(
        catalog,
        "project.title",
        tag="title",
        attrs=' id="project-evidence-chain-svg-title"',
    )
    description = _robustness_i18n(
        catalog,
        "project.description",
        tag="desc",
        attrs=' id="project-evidence-chain-svg-description"',
    )
    return (
        '<div class="robustness-reader-diagram" data-testid="project-evidence-chain-diagram-section" '
        'aria-labelledby="project-evidence-chain-heading">'
        '<div class="robustness-reader-heading">'
        f'{heading}{_robustness_i18n(catalog, "project.lead", tag="p")}</div>'
        '<figure class="robustness-reader-figure">'
        '<div class="robustness-reader-scroll" tabindex="0" '
        f'{_robustness_i18n_attribute(catalog, "project.title", "aria-label")}>'
        '<svg data-testid="project-evidence-chain-diagram" viewBox="0 0 1380 590" role="img" '
        'aria-labelledby="project-evidence-chain-svg-title" '
        'aria-describedby="project-evidence-chain-svg-description project-evidence-chain-fallback" focusable="false">'
        '<defs><marker id="project-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"/></marker></defs>'
        f'{title}{description}'
        f'<g class="robustness-semantic-edges">{"".join(_diagram_svg_edge(catalog, edge, marker_id="project-arrow") for edge in edges)}</g>'
        f'<g class="robustness-semantic-nodes">{"".join(_diagram_svg_node(catalog, node) for node in nodes)}</g>'
        '</svg></div>'
        f'<ul class="robustness-semantic-legend" data-testid="project-evidence-chain-legend">{legend}</ul>'
        '<figcaption id="project-evidence-chain-fallback" class="robustness-reader-fallback" data-testid="project-evidence-chain-fallback">'
        f'{_robustness_i18n(catalog, "project.fallback.title", tag="h3")}<ol>{fallback_rows}</ol></figcaption>'
        '</figure>'
        '<details class="robustness-mermaid-source" data-testid="project-evidence-chain-mermaid-source">'
        f'<summary>{_robustness_i18n(catalog, "project.source.summary")}</summary>'
        f'{_robustness_i18n(catalog, "project.source.note", tag="p")}{source_blocks}</details>'
        '</div>'
    )


def _batch_mechanism_semantics() -> tuple[tuple[_DiagramNode, ...], tuple[_DiagramEdge, ...]]:
    nodes = (
        _DiagramNode("Input", "batch.node.Input", 530, 20, 440, 60, "input", "concurrent-message-source-contract"),
        _DiagramNode("Freeze", "batch.node.Freeze", 530, 100, 440, 60, "freeze", "_ConcurrentRuntimeKernel.plan_batch"),
        _DiagramNode("Batch", "batch.node.Batch", 630, 185, 240, 60, "gate", "shared-seed-launch-contract"),
        _DiagramNode("Seed", "batch.node.Seed", 40, 285, 280, 64, "seed", "SharedSeedLaunch"),
        _DiagramNode("Fill", "batch.node.Fill", 40, 370, 280, 64, "ranking", "per-message-fill-contract"),
        _DiagramNode("Rank1", "batch.node.Rank1", 400, 310, 280, 64, "ranking", "PerMessagePersonalizedTop20", "batch-mark-ranking"),
        _DiagramNode("Rank2", "batch.node.Rank2", 740, 310, 280, 64, "ranking", "PerMessagePersonalizedTop20"),
        _DiagramNode("Rank3", "batch.node.Rank3", 1080, 310, 280, 64, "ranking", "PerMessagePersonalizedTop20"),
        _DiagramNode("Exposure", "batch.node.Exposure", 510, 455, 480, 70, "exposure", "MessageLevelSingleExposure"),
        _DiagramNode("Primary", "batch.node.Primary", 330, 565, 300, 64, "decision", "PrimaryCampaignDecision"),
        _DiagramNode("Shadow", "batch.node.Shadow", 870, 565, 300, 64, "shadow", "DemographicShadowDecision"),
        _DiagramNode("HistoricalMode", "batch.node.HistoricalMode", 1150, 550, 320, 64, "mode", "historical-formal-terminal-contract"),
        _DiagramNode("RobustnessMode", "batch.node.RobustnessMode", 1150, 640, 320, 64, "mode", "primary-only-terminal-contract"),
        _DiagramNode("Positive", "batch.node.Positive", 80, 680, 340, 72, "gate", "positive-primary-action-contract"),
        _DiagramNode("Terminal", "batch.node.Terminal", 590, 690, 400, 72, "terminal", "required-terminal-contract"),
        _DiagramNode("Pending", "batch.node.Pending", 250, 800, 340, 64, "feedback", "pending-feedback-set-contract"),
        _DiagramNode("Barrier", "batch.node.Barrier", 720, 800, 340, 64, "barrier", "full-batch-barrier-contract"),
        _DiagramNode("Commit", "batch.node.Commit", 470, 900, 430, 72, "commit", "campaign-user-id-deduplication-contract"),
        _DiagramNode("Next1", "batch.node.Next1", 70, 1040, 360, 70, "next", "PerMessagePersonalizedTop20"),
        _DiagramNode("Next2", "batch.node.Next2", 570, 1040, 360, 70, "next", "PerMessagePersonalizedTop20"),
        _DiagramNode("Next3", "batch.node.Next3", 1070, 1040, 360, 70, "next", "PerMessagePersonalizedTop20"),
    )
    edges = (
        _DiagramEdge("batch-edge-input-freeze", "Input", "Freeze", "M750 80 V94", "fixed_inputs_closed", "batch_start", "freeze_campaign_snapshot", "_ConcurrentRuntimeKernel.plan_batch"),
        _DiagramEdge("batch-edge-freeze-batch", "Freeze", "Batch", "M750 160 V179", "snapshot_frozen", "before_ranking", "select_launch_policy", "_ConcurrentRuntimeKernel.plan_batch"),
        _DiagramEdge("batch-edge-batch-seed", "Batch", "Seed", "M630 215 H180 V279", "batch_index_equals_zero", "batch_zero_selection", "use_same_seed_union_for_three_messages", "SharedSeedLaunch", label_key="batch.edge.yes", label_x=390, label_y=185, label_width=54),
        _DiagramEdge("batch-edge-seed-fill", "Seed", "Fill", "M180 349 V364", "seed_union_below_delivery_capacity", "batch_zero_before_exposure", "fill_each_message_independently_to_top_k", "SharedSeedLaunch"),
        _DiagramEdge("batch-edge-seed-exposure", "Seed", "Exposure", "M320 317 H450 V490 H504", "seed_union_reaches_delivery_capacity", "batch_zero_before_exposure", "select_shared_seed_pairs", "SharedSeedLaunch"),
        _DiagramEdge("batch-edge-fill-exposure", "Fill", "Exposure", "M320 402 H470 V508 H504", "per_message_fill_complete", "before_exposure", "select_message_local_pairs", "PerMessagePersonalizedTop20"),
        _DiagramEdge("batch-edge-batch-rank1", "Batch", "Rank1", "M690 245 V280 H540 V304", "batch_index_greater_than_zero", "before_exposure", "rank_message_1_independently", "PerMessagePersonalizedTop20", label_key="batch.edge.no", label_x=555, label_y=250, label_width=54),
        _DiagramEdge("batch-edge-batch-rank2", "Batch", "Rank2", "M750 245 V304", "batch_index_greater_than_zero", "before_exposure", "rank_message_2_independently", "PerMessagePersonalizedTop20"),
        _DiagramEdge("batch-edge-batch-rank3", "Batch", "Rank3", "M810 245 V280 H1220 V304", "batch_index_greater_than_zero", "before_exposure", "rank_message_3_independently", "PerMessagePersonalizedTop20"),
        _DiagramEdge("batch-edge-rank1-exposure", "Rank1", "Exposure", "M540 374 V420 H630 V449", "message_1_top_k_selected", "ranking_before_exposure", "expose_selected_message_1_pairs", "PlatformEnvironment"),
        _DiagramEdge("batch-edge-rank2-exposure", "Rank2", "Exposure", "M880 374 V449", "message_2_top_k_selected", "ranking_before_exposure", "expose_selected_message_2_pairs", "PlatformEnvironment"),
        _DiagramEdge("batch-edge-rank3-exposure", "Rank3", "Exposure", "M1220 374 V420 H870 V449", "message_3_top_k_selected", "ranking_before_exposure", "expose_selected_message_3_pairs", "PlatformEnvironment"),
        _DiagramEdge("batch-edge-exposure-primary", "Exposure", "Primary", "M650 525 V559", "user_message_pair_exposed_once", "after_exposure", "request_primary_decision", "PrimaryCampaignDecision", mark_id="batch-mark-required"),
        _DiagramEdge("batch-edge-exposure-shadow", "Exposure", "Shadow", "M850 525 V545 H1020 V559", "historical_formal_mode", "after_same_exposure", "request_report_only_shadow", "DemographicShadowDecision", style="dotted", label_key="batch.edge.historical", label_x=875, label_y=530, label_width=150, mark_id="batch-mark-shadow"),
        _DiagramEdge("batch-edge-historical-terminal", "HistoricalMode", "Terminal", "M1150 582 H1100 V720 H996", "historical_formal_mode", "terminal_closure", "require_primary_and_shadow", "historical-formal-terminal-contract", style="dotted"),
        _DiagramEdge("batch-edge-robustness-terminal", "RobustnessMode", "Terminal", "M1150 672 H1080 V740 H996", "robustness_cell_mode", "terminal_closure", "require_primary_only", "primary-only-terminal-contract", style="dotted"),
        _DiagramEdge("batch-edge-primary-positive", "Primary", "Positive", "M480 629 V650 H250 V674", "terminal_status_succeeded", "after_primary_terminal", "test_positive_action", "PrimaryCampaignDecision"),
        _DiagramEdge("batch-edge-primary-terminal", "Primary", "Terminal", "M630 597 H700 V684", "primary_terminal_recorded", "terminal_closure", "contribute_required_primary_terminal", "required-terminal-contract"),
        _DiagramEdge("batch-edge-shadow-terminal", "Shadow", "Terminal", "M870 597 H880 V684", "historical_formal_mode_and_shadow_terminal_recorded", "terminal_closure", "contribute_required_shadow_terminal_only", "required-terminal-contract", style="dotted"),
        _DiagramEdge("batch-edge-positive-pending", "Positive", "Pending", "M250 752 V780 H420 V794", "action_in_like_comment_share", "pending_set_finalize", "add_user_id_then_deduplicate_pending_set", "campaign-positive-user-contract", label_key="batch.edge.positive", label_x=260, label_y=755, label_width=150),
        _DiagramEdge("batch-edge-primary-pending-empty", "Primary", "Pending", "M420 629 V770 H420 V794", "terminal_action_ignore_or_provider_failed", "pending_set_finalize", "no_campaign_feedback_allow_empty_pending_set", "non-propagating-terminal-contract", label_key="batch.edge.no_feedback", label_x=425, label_y=720, label_width=126),
        _DiagramEdge("batch-edge-terminal-barrier", "Terminal", "Barrier", "M790 762 V794", "all_selected_pairs_reached_required_terminal_set", "end_of_full_batch", "close_full_batch_barrier", "full-batch-barrier-contract"),
        _DiagramEdge("batch-edge-pending-commit", "Pending", "Commit", "M420 864 V880 H685 V894", "pending_set_finalized", "batch_commit_gate", "satisfy_pending_operand", "batch-commit-join-contract"),
        _DiagramEdge("batch-edge-barrier-commit", "Barrier", "Commit", "M890 864 V880 H685 V894", "full_batch_barrier_closed", "batch_commit_gate", "satisfy_terminal_operand_and_commit_unique_user_ids", "batch-commit-join-contract"),
        _DiagramEdge("batch-edge-commit-next1", "Commit", "Next1", "M580 972 V1010 H250 V1034", "next_batch_exists", "next_batch_before_ranking", "ranking_context_only_no_queue_injection_no_same_batch_writeback", "CampaignEngagementRankingSignal", label_key="batch.edge.next", label_x=300, label_y=978, label_width=220, mark_id="batch-mark-next"),
        _DiagramEdge("batch-edge-commit-next2", "Commit", "Next2", "M685 972 V1034", "next_batch_exists", "next_batch_before_ranking", "ranking_context_only_no_queue_injection_no_same_batch_writeback", "CampaignEngagementRankingSignal"),
        _DiagramEdge("batch-edge-commit-next3", "Commit", "Next3", "M790 972 V1010 H1250 V1034", "next_batch_exists", "next_batch_before_ranking", "ranking_context_only_no_queue_injection_no_same_batch_writeback", "CampaignEngagementRankingSignal"),
    )
    return nodes, edges


def _batch_mechanism_diagram(
    catalog: Mapping[str, Mapping[str, str]],
) -> str:
    nodes, edges = _batch_mechanism_semantics()
    source_blocks = "".join(
        f'<pre data-robustness-language-variant="{language}"{hidden}><code class="language-mermaid">'
        f'{_escape(_diagram_mermaid_source(catalog, language, title_key="batch.title", description_key="batch.description", nodes=nodes, edges=edges))}'
        "</code></pre>"
        for language, hidden in (("zh-CN", ""), ("en-US", " hidden"))
    )
    fallback_rows = "".join(
        f'<li>{_robustness_i18n(catalog, f"batch.fallback.{key}")}</li>'
        for key in ("freeze", "rank", "exposure", "feedback", "barrier", "next")
    )
    legend = "".join(
        '<li class="robustness-semantic-legend-item" '
        f'data-legend-mark-id="batch-mark-{mark}"><span class="robustness-semantic-legend-swatch robustness-semantic-legend-swatch-{mark}" aria-hidden="true"></span>'
        f'{_robustness_i18n(catalog, f"batch.legend.{mark}")}</li>'
        for mark in ("ranking", "required", "shadow", "next")
    )
    heading = _robustness_i18n(
        catalog,
        "batch.heading",
        tag="h2",
        attrs=' id="batch-mechanism-heading"',
    )
    title = _robustness_i18n(
        catalog,
        "batch.title",
        tag="title",
        attrs=' id="batch-mechanism-svg-title"',
    )
    description = _robustness_i18n(
        catalog,
        "batch.description",
        tag="desc",
        attrs=' id="batch-mechanism-svg-description"',
    )
    return (
        '<div class="robustness-reader-diagram robustness-batch-diagram" data-testid="batch-mechanism-diagram-section" '
        'aria-labelledby="batch-mechanism-heading">'
        '<div class="robustness-reader-heading">'
        f'{heading}{_robustness_i18n(catalog, "batch.lead", tag="p")}</div>'
        '<figure class="robustness-reader-figure">'
        '<div class="robustness-reader-scroll" tabindex="0" '
        f'{_robustness_i18n_attribute(catalog, "batch.title", "aria-label")}>'
        '<svg data-testid="batch-mechanism-diagram" viewBox="0 0 1500 1150" role="img" '
        'aria-labelledby="batch-mechanism-svg-title" '
        'aria-describedby="batch-mechanism-svg-description batch-mechanism-fallback" focusable="false">'
        '<defs><marker id="batch-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"/></marker></defs>'
        f'{title}{description}'
        f'<g class="robustness-semantic-edges">{"".join(_diagram_svg_edge(catalog, edge, marker_id="batch-arrow") for edge in edges)}</g>'
        f'<g class="robustness-semantic-nodes">{"".join(_diagram_svg_node(catalog, node) for node in nodes)}</g>'
        '</svg></div>'
        f'<ul class="robustness-semantic-legend robustness-semantic-legend-four" data-testid="batch-mechanism-legend">{legend}</ul>'
        '<figcaption id="batch-mechanism-fallback" class="robustness-reader-fallback" data-testid="batch-mechanism-fallback">'
        f'{_robustness_i18n(catalog, "batch.fallback.title", tag="h3")}<ol>{fallback_rows}</ol></figcaption>'
        '</figure>'
        '<details class="robustness-mermaid-source" data-testid="batch-mechanism-mermaid-source">'
        f'<summary>{_robustness_i18n(catalog, "batch.source.summary")}</summary>'
        f'{_robustness_i18n(catalog, "batch.source.note", tag="p")}{source_blocks}</details>'
        '</div>'
    )


def _prompt_model_nodes() -> tuple[_DiagramNode, ...]:
    return (
        _DiagramNode("Contract", "diagram.node.Contract", 180, 25, 600, 76, "contract", "PromptContractRegistry"),
        _DiagramNode("P0", "diagram.node.P0", 20, 145, 180, 76, "prompt", "PromptContractRegistry.P0"),
        _DiagramNode("P1", "diagram.node.P1", 220, 145, 180, 76, "prompt", "PromptContractRegistry.P1"),
        _DiagramNode("P2", "diagram.node.P2", 420, 145, 180, 76, "prompt", "PromptContractRegistry.P2"),
        _DiagramNode("P3", "diagram.node.P3", 620, 145, 210, 76, "prompt", "PromptContractRegistry.P3"),
        _DiagramNode("Models", "diagram.node.Models", 900, 145, 260, 76, "model", "ConcurrentRobustnessManifest.prompt_model_cells"),
        _DiagramNode("Cross", "diagram.node.Cross", 465, 270, 270, 76, "operator", "ConcurrentRobustnessManifest.prompt_model_cells"),
        _DiagramNode("Cells", "diagram.node.Cells", 465, 380, 270, 76, "result", "ConcurrentRobustnessManifest.prompt_model_cells"),
        _DiagramNode("Runtime", "diagram.node.Runtime", 355, 490, 490, 86, "contract", "ConcurrentRobustnessManifest.ranking_contract"),
        _DiagramNode("Direct", "diagram.node.Direct", 120, 630, 280, 76, "direct", "prompt-model-shared-seed-panel"),
        _DiagramNode("Paths", "diagram.node.Paths", 460, 630, 300, 76, "path", "prompt-model-realized-paths"),
        _DiagramNode("Views", "diagram.node.Views", 840, 630, 300, 76, "result", "prompt-model-reporting-projection"),
    )


def _prompt_model_edges() -> tuple[_DiagramEdge, ...]:
    return (
        _DiagramEdge("edge_contract_p0", "Contract", "P0", "M480 101 V125 H110 V139", "variant_p0_declared", "contract_projection", "define_baseline_prompt", "PromptContractRegistry"),
        _DiagramEdge("edge_contract_p1", "Contract", "P1", "M480 101 V125 H310 V139", "variant_p1_declared", "contract_projection", "change_wording_only", "PromptContractRegistry"),
        _DiagramEdge("edge_contract_p2", "Contract", "P2", "M480 101 V139", "variant_p2_declared", "contract_projection", "change_information_order_only", "PromptContractRegistry"),
        _DiagramEdge("edge_contract_p3", "Contract", "P3", "M480 101 V125 H725 V139", "variant_p3_declared", "contract_projection", "add_structured_rubric_only", "PromptContractRegistry"),
        _DiagramEdge("edge_p0_cross", "P0", "Cross", "M110 221 V245 H500 V264", "prompt_variant_declared", "cell_construction", "cross_with_models", "ConcurrentRobustnessManifest.prompt_model_cells"),
        _DiagramEdge("edge_p1_cross", "P1", "Cross", "M310 221 V250 H545 V264", "prompt_variant_declared", "cell_construction", "cross_with_models", "ConcurrentRobustnessManifest.prompt_model_cells"),
        _DiagramEdge("edge_p2_cross", "P2", "Cross", "M510 221 V264", "prompt_variant_declared", "cell_construction", "cross_with_models", "ConcurrentRobustnessManifest.prompt_model_cells"),
        _DiagramEdge("edge_p3_cross", "P3", "Cross", "M725 221 V264", "prompt_variant_declared", "cell_construction", "cross_with_models", "ConcurrentRobustnessManifest.prompt_model_cells"),
        _DiagramEdge("edge_models_cross", "Models", "Cross", "M1030 221 V308 H741", "qualified_model_identity_closed", "cell_construction", "cross_with_prompts", "ConcurrentRobustnessManifest.prompt_model_cells"),
        _DiagramEdge("edge_cross_cells", "Cross", "Cells", "M600 346 V374", "cartesian_product_complete", "manifest_closure", "form_independent_execution_cells", "ConcurrentRobustnessManifest.prompt_model_cells"),
        _DiagramEdge("edge_cells_runtime", "Cells", "Runtime", "M600 456 V484", "cell_identity_valid", "cell_execution", "apply_shared_runtime_contract", "ConcurrentRobustnessStudy"),
        _DiagramEdge("edge_runtime_direct", "Runtime", "Direct", "M500 576 V605 H260 V624", "batch_zero_shared_seed_panel", "batch_zero", "form_direct_paired_panel", "prompt-model-shared-seed-panel"),
        _DiagramEdge("edge_runtime_paths", "Runtime", "Paths", "M700 576 V605 H610 V624", "cell_runtime_complete", "batches_one_to_terminal", "form_one_realized_path_per_cell", "prompt-model-realized-paths"),
        _DiagramEdge("edge_direct_views", "Direct", "Views", "M400 668 H834", "direct_panel_closed", "report_projection", "expand_across_messages", "prompt-model-reporting-projection"),
        _DiagramEdge("edge_paths_views", "Paths", "Views", "M760 668 H834", "realized_paths_closed", "report_projection", "expand_across_messages", "prompt-model-reporting-projection"),
    )


def _prompt_model_mermaid_source(
    catalog: Mapping[str, Mapping[str, str]],
    language: str,
) -> str:
    return _diagram_mermaid_source(
        catalog,
        language,
        title_key="diagram.title",
        description_key="diagram.description",
        nodes=_prompt_model_nodes(),
        edges=_prompt_model_edges(),
    )


def _reader_mermaid_artifacts(
    catalog: Mapping[str, Mapping[str, str]],
) -> dict[str, bytes]:
    project_nodes, project_edges = _project_evidence_chain_semantics()
    batch_nodes, batch_edges = _batch_mechanism_semantics()
    sources = {
        _PROJECT_EVIDENCE_MMD: _diagram_mermaid_source(
            catalog,
            "en-US",
            title_key="project.title",
            description_key="project.description",
            nodes=project_nodes,
            edges=project_edges,
        ),
        _BATCH_MECHANISM_MMD: _diagram_mermaid_source(
            catalog,
            "en-US",
            title_key="batch.title",
            description_key="batch.description",
            nodes=batch_nodes,
            edges=batch_edges,
        ),
        _PROMPT_MODEL_FACTORIAL_MMD: _prompt_model_mermaid_source(catalog, "en-US"),
    }
    return {path: f"{source}\n".encode() for path, source in sources.items()}


def _semantic_reader_mermaid_artifacts(
    presentation: _PromptModelPresentation,
) -> dict[str, bytes]:
    mechanism = _MECHANISM_PRESENTATION.build()
    prompt_catalog = _prompt_presentation_catalog(presentation)
    artifacts = {
        artifact.filename: artifact.payload
        for artifact in mechanism.mermaid_artifacts
    }
    artifacts[_PROMPT_MODEL_FACTORIAL_MMD] = (
        f'{_prompt_model_mermaid_source(prompt_catalog, "en-US")}\n'.encode()
    )
    if tuple(artifacts) != tuple(_SEMANTIC_MERMAID_DOWNLOADS.values()):
        raise _RobustnessReportClosureError("semantic Mermaid artifact order is crossed")
    return artifacts


def _build_semantic_presentation_candidate(
    projection: _CandidateProjection,
) -> _SemanticPresentationCandidate:
    semantic_payload = _build_semantic_report_payload(projection.report_payload)
    rendered = _render_semantic_additive_report(
        _render_editorial_v4(projection.formal.report_payload),
        payload=semantic_payload,
        prompt_model_presentation=projection.prompt_model_presentation,
    )
    mermaid_artifacts = _semantic_reader_mermaid_artifacts(
        projection.prompt_model_presentation
    )
    candidate = _SemanticPresentationCandidate(
        report_html=rendered.encode("utf-8"),
        mermaid_artifacts=mermaid_artifacts,
        companion_artifacts={
            path: payload
            for path, payload in projection.payloads.items()
            if path not in {
                CONCURRENT_MESSAGE_REPORT_HTML,
                *_READER_MERMAID_DOWNLOADS.values(),
                *mermaid_artifacts,
            }
        },
        production_deploy_eligible=False,
        provider_calls_during_composition=0,
        image_generation_triggered=False,
    )
    _validate_semantic_candidate(candidate)
    return candidate


def _validate_semantic_candidate(candidate: _SemanticPresentationCandidate) -> None:
    try:
        html_document = candidate.report_html.decode("utf-8")
        if len(candidate.report_html) > _MAX_REPORT_HTML_BYTES:
            raise ValueError("semantic candidate exceeds the 3 MiB presentation limit")
        if candidate.production_deploy_eligible is not False:
            raise ValueError("semantic candidate cannot be production deploy eligible")
        if candidate.provider_calls_during_composition != 0 or candidate.image_generation_triggered is not False:
            raise ValueError("semantic candidate composition must remain zero-call")
        if tuple(candidate.mermaid_artifacts) != tuple(_SEMANTIC_MERMAID_DOWNLOADS.values()):
            raise ValueError("semantic candidate Mermaid inventory is incomplete")
        if any(
            PurePosixPath(path).is_absolute()
            or ".." in PurePosixPath(path).parts
            or not payload
            for path, payload in candidate.companion_artifacts.items()
        ):
            raise ValueError("semantic companion artifact inventory is unsafe")
        if set(candidate.companion_artifacts) & set(candidate.mermaid_artifacts):
            raise ValueError("semantic artifact inventories overlap")
        mechanism = _MECHANISM_PRESENTATION.build()
        expected_mechanism = {
            artifact.filename: artifact.payload
            for artifact in mechanism.mermaid_artifacts
        }
        if any(
            candidate.mermaid_artifacts.get(filename) != payload
            for filename, payload in expected_mechanism.items()
        ):
            raise ValueError("semantic candidate mechanism master bytes are crossed")
        if not candidate.mermaid_artifacts[_PROMPT_MODEL_FACTORIAL_MMD].startswith(b"flowchart TB\n"):
            raise ValueError("Prompt-Model factorial Mermaid bytes are malformed")
        _validate_semantic_html(html_document)
    except (KeyError, TypeError, UnicodeDecodeError, ValueError) as exc:
        raise _RobustnessReportClosureError("semantic report candidate failed validation") from exc


def _validate_semantic_html(
    html_document: str,
    *,
    stage_facts: _ProductionPresentationFacts | None = None,
) -> None:
    stage_test_id = "robustness-report-candidate"
    other_test_id = "robustness-report-release"
    eligibility = "false"
    if stage_facts is not None:
        stage_test_id, other_test_id = other_test_id, stage_test_id
        eligibility = "true"
    required_html = (
        'data-editorial-version="v4-semantic"',
        f'data-production-deploy-eligible="{eligibility}"',
        f'data-testid="{stage_test_id}"',
        'data-testid="robustness-source-lineage"',
        'data-testid="real-batch-mechanism-section"',
        'data-testid="prompt-model-factorial-diagram"',
        'data-testid="run-trace-tool"',
    )
    if any(token not in html_document for token in required_html):
        raise ValueError("semantic candidate is missing required presentation evidence")
    forbidden_html = (
        "project-evidence-chain",
        "mechanism-image-generation-audit.json",
        "mechanism-sample-first-v4.png",
        "mechanism-pair-formation-v4.png",
        "mechanism-independent-delivery-v4.png",
        "mechanism-exposure-decisions-v4.png",
        "mechanism-feedback-boundary-v4.png",
        "data:image/webp",
        '<script src=',
    )
    if any(token in html_document for token in forbidden_html):
        raise ValueError("semantic candidate contains a rejected or external presentation input")
    if html_document.count('data-mechanism-diagram-id="') != 6:
        raise ValueError("semantic candidate must render six semantic views")
    mechanism = _MECHANISM_PRESENTATION.build()
    for diagram in mechanism.diagrams:
        if f'data-mechanism-diagram-id="{diagram.diagram_id}"' not in html_document:
            raise ValueError("semantic candidate diagram projection is incomplete")
        for node in diagram.nodes:
            if f'data-semantic-node-id="{node.semantic_id}"' not in html_document:
                raise ValueError("semantic candidate node projection is incomplete")
        for edge in diagram.edges:
            if f'data-semantic-edge-id="{edge.semantic_id}"' not in html_document:
                raise ValueError("semantic candidate edge projection is incomplete")


def _prompt_model_factorial_diagram(
    presentation: _PromptModelPresentation,
    catalog: Mapping[str, Mapping[str, str]],
) -> str:
    nodes = _prompt_model_nodes()
    node_markup = "".join(_diagram_svg_node(catalog, node) for node in nodes)
    edges = _prompt_model_edges()
    edge_markup = "".join(
        _diagram_svg_edge(catalog, edge, marker_id="factorial-arrow")
        for edge in edges
    )
    source_blocks = "".join(
        f'<pre data-robustness-language-variant="{language}"{"" if language == "zh-CN" else " hidden"}>'
        f'<code class="language-mermaid">{_escape(_prompt_model_mermaid_source(catalog, language))}</code></pre>'
        for language in ("zh-CN", "en-US")
    )
    fallback_rows = "".join(
        f'<li>{_robustness_i18n(catalog, f"diagram.fallback.{key}")}</li>'
        for key in ("contract", "cells", "runtime", "reporting")
    )
    diagram_heading = _robustness_i18n(
        catalog,
        "diagram.heading",
        tag="h3",
        attrs=' id="prompt-model-factorial-heading"',
    )
    diagram_title = _robustness_i18n(
        catalog,
        "diagram.title",
        tag="title",
        attrs=' id="prompt-model-factorial-svg-title"',
    )
    diagram_description = _robustness_i18n(
        catalog,
        "diagram.description",
        tag="desc",
        attrs=' id="prompt-model-factorial-svg-description"',
    )
    return (
        '<section class="robustness-factorial" data-testid="prompt-model-factorial-diagram-section" '
        'aria-labelledby="prompt-model-factorial-heading">'
        '<div class="robustness-subsection-heading">'
        f'{diagram_heading}{_robustness_i18n(catalog, "diagram.lead", tag="p")}</div>'
        '<figure class="robustness-factorial-figure">'
        '<div class="robustness-factorial-scroll" tabindex="0" '
        f'{_robustness_i18n_attribute(catalog, "diagram.title", "aria-label")}>'
        '<svg data-testid="prompt-model-factorial-diagram" viewBox="0 0 1200 750" role="img" '
        'aria-labelledby="prompt-model-factorial-svg-title" '
        'aria-describedby="prompt-model-factorial-svg-description prompt-model-factorial-fallback" focusable="false">'
        '<defs><marker id="factorial-arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"/></marker></defs>'
        f"{diagram_title}{diagram_description}"
        f'<g class="robustness-factorial-edges">{edge_markup}</g>'
        f'<g class="robustness-factorial-nodes">{node_markup}</g></svg></div>'
        '<figcaption id="prompt-model-factorial-fallback" class="robustness-factorial-fallback" '
        'data-testid="prompt-model-factorial-fallback">'
        f'{_robustness_i18n(catalog, "diagram.fallback.title", tag="h4")}<ol>{fallback_rows}</ol></figcaption>'
        "</figure>"
        '<details class="robustness-mermaid-source" data-testid="prompt-model-factorial-mermaid-source">'
        f'<summary>{_robustness_i18n(catalog, "diagram.source.summary")}</summary>'
        f'{_robustness_i18n(catalog, "diagram.source.note", tag="p")}{source_blocks}</details>'
        "</section>"
    )


def _build_report_payload(
    *,
    formal: ConcurrentMessageArtifactClosure,
    study: _ClosedStudy,
    manifest: ConcurrentRobustnessManifest,
    manifest_sha256: str,
    rows: _ReportRows,
) -> dict[str, Any]:
    downloads = {
        "candidate_manifest": CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON,
        "report_payload": _REPORT_PAYLOAD,
        "ranking_weight_source": _WEIGHT_JSON,
        "prompt_model_source": _PROMPT_MODEL_JSON,
        "claim_audit": _CLAIM_AUDIT_JSON,
        "study_validation": _STUDY_VALIDATION_JSON,
        "ranking_weight_message_summary": _WEIGHT_MESSAGE_CSV,
        "ranking_weight_batch_diagnostics": _WEIGHT_BATCH_CSV,
        "prompt_model_shared_seed_summary": _SHARED_SEED_CSV,
        "prompt_model_message_summary": _PROMPT_MESSAGE_CSV,
        "prompt_model_trajectory_summary": _PROMPT_TRAJECTORY_CSV,
        "prompt_model_campaign_growth": _PROMPT_GROWTH_CSV,
        "prompt_model_practical_thresholds": _THRESHOLD_CSV,
        "release_evidence": _RELEASE_EVIDENCE_JSON,
        **_READER_MERMAID_DOWNLOADS,
    }
    return {
        "schema_version": _REPORT_PAYLOAD_SCHEMA,
        "title": "Concurrent Message · Incremental Robustness Evidence",
        "source_lineage": {
            "formal": {
                "source_id": manifest.source.source_id,
                "manifest_schema": manifest.source.manifest_schema,
                "manifest_sha256": manifest.source.manifest_sha256,
                "report_payload_schema": formal.report_payload.schema_version,
                "evidence_scope": [
                    "mechanism",
                    "run_evidence",
                    "field_lineage",
                    "demographic_shadow",
                    "primary_shadow_barrier",
                ],
            },
            "study": {
                "output_identity": manifest.output_identity,
                "manifest_sha256": manifest_sha256,
                "root_manifest_schema": study.root_manifest["schema_version"],
                "root_identity_sha256": study.root_manifest["root_identity_sha256"],
                "evidence_scope": ["ranking_weight_sensitivity", "prompt_model_primary_only"],
                "demographic_shadow_rerun": False,
            },
        },
        "ranking_weight": {
            "schema_version": study.ranking["schema_version"],
            "message_summary_rows": rows.weight_messages,
            "batch_diagnostic_rows": rows.weight_batches,
        },
        "prompt_model": {
            "schema_version": study.prompt_model["schema_version"],
            "shared_seed_rows": rows.shared_seed,
            "message_summary_rows": rows.prompt_messages,
            "trajectory_rows": rows.prompt_trajectories,
            "campaign_growth_rows": rows.prompt_growth,
            "practical_threshold_rows": rows.thresholds,
        },
        "row_counts": rows.counts(),
        "trace_row_count": len(formal.decision_trace_document.rows),
        "downloads": downloads,
        "claim_boundary": {
            "scope": "fixed_sample_fixed_graph_one_realized_path_per_cell",
            "ground_truth_used": False,
            "causal_claim": False,
            "calibration_claim": False,
            "statistical_equivalence_claim": False,
            "below_threshold_label": "small_observed_difference",
        },
        "production_deploy_eligible": False,
    }


def _build_semantic_report_payload(
    payload_v1: Mapping[str, Any],
) -> dict[str, Any]:
    if set(payload_v1) != _REPORT_PAYLOAD_V1_FIELDS:
        raise _RobustnessReportClosureError("payload v1 fields are missing or unexpected")
    mechanism = _MECHANISM_PRESENTATION.build()
    masters = {
        artifact.filename: artifact.sha256
        for artifact in mechanism.mermaid_artifacts
    }
    if tuple(masters) != tuple(_SEMANTIC_MERMAID_DOWNLOADS.values())[:-1]:
        raise _RobustnessReportClosureError("approved mechanism master order is crossed")
    downloads = _string_mapping(payload_v1.get("downloads"), "candidate downloads")
    downloads.pop("project_evidence_chain_mermaid", None)
    downloads.pop("batch_mechanism_mermaid", None)
    downloads.update(_SEMANTIC_MERMAID_DOWNLOADS)
    payload = dict(payload_v1)
    payload.update(
        {
            "schema_version": _REPORT_PAYLOAD_V2_SCHEMA,
            "downloads": downloads,
            "mechanism_presentation": {
                "schema_version": mechanism.schema_version,
                "semantic_set_identity_sha256": mechanism.semantic_set_identity_sha256,
                "masters": masters,
            },
        }
    )
    _validate_report_payload_contract(payload, production=False)
    return payload


def _candidate_payloads(
    *,
    formal: ConcurrentMessageArtifactClosure,
    study: _ClosedStudy,
    manifest: ConcurrentRobustnessManifest,
    manifest_sha256: str,
    rows: _ReportRows,
    prompt_model_presentation: _PromptModelPresentation,
    report_payload: Mapping[str, Any],
) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    for name, relative_path in formal.manifest.artifacts.items():
        if name == "report_html":
            continue
        payloads[relative_path] = formal.artifact_paths[name].read_bytes()
    payloads[_REPORT_PAYLOAD] = _json_bytes(report_payload)
    payloads.update(
        _reader_mermaid_artifacts(_presentation_catalog(prompt_model_presentation))
    )
    payloads[_WEIGHT_JSON] = (study.root / "ranking_weight_sensitivity.json").read_bytes()
    payloads[_PROMPT_MODEL_JSON] = (study.root / "prompt_model_analysis.json").read_bytes()
    payloads[_CLAIM_AUDIT_JSON] = (study.root / "claim_audit.json").read_bytes()
    payloads[_STUDY_VALIDATION_JSON] = (study.root / "validation_report.json").read_bytes()
    payloads[_WEIGHT_MESSAGE_CSV] = _csv_bytes(_WEIGHT_MESSAGE_FIELDS, rows.weight_messages)
    payloads[_WEIGHT_BATCH_CSV] = _csv_bytes(_WEIGHT_BATCH_FIELDS, rows.weight_batches)
    payloads[_SHARED_SEED_CSV] = _csv_bytes(_SHARED_SEED_FIELDS, rows.shared_seed)
    payloads[_PROMPT_MESSAGE_CSV] = _csv_bytes(_PROMPT_MESSAGE_FIELDS, rows.prompt_messages)
    payloads[_PROMPT_TRAJECTORY_CSV] = _csv_bytes(_PROMPT_TRAJECTORY_FIELDS, rows.prompt_trajectories)
    payloads[_PROMPT_GROWTH_CSV] = _csv_bytes(_PROMPT_GROWTH_FIELDS, rows.prompt_growth)
    payloads[_THRESHOLD_CSV] = _csv_bytes(_THRESHOLD_FIELDS, rows.thresholds)

    formal_html = render_report(formal.report_payload)
    payloads[CONCURRENT_MESSAGE_REPORT_HTML] = _render_additive_report(
        formal_html,
        payload=report_payload,
        prompt_model_presentation=prompt_model_presentation,
    ).encode("utf-8")
    return _close_candidate_payloads(
        formal=formal,
        study=study,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        rows=rows,
        report_payload=report_payload,
        payloads=payloads,
    )


def _semantic_candidate_payloads(
    *,
    projection: _CandidateProjection,
    semantic_candidate: _SemanticPresentationCandidate,
    report_payload: Mapping[str, Any],
) -> dict[str, bytes]:
    replaced = {
        CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON,
        CONCURRENT_MESSAGE_REPORT_HTML,
        _REPORT_PAYLOAD,
        _RELEASE_EVIDENCE_JSON,
        *_READER_MERMAID_DOWNLOADS.values(),
    }
    payloads = {
        path: payload
        for path, payload in projection.payloads.items()
        if path not in replaced
    }
    payloads[_REPORT_PAYLOAD] = _json_bytes(report_payload)
    payloads[CONCURRENT_MESSAGE_REPORT_HTML] = semantic_candidate.report_html
    payloads.update(semantic_candidate.mermaid_artifacts)
    return _close_candidate_payloads(
        formal=projection.formal,
        study=projection.study,
        manifest=projection.manifest,
        manifest_sha256=projection.manifest_sha256,
        rows=projection.rows,
        report_payload=report_payload,
        payloads=payloads,
    )


def _close_candidate_payloads(
    *,
    formal: ConcurrentMessageArtifactClosure,
    study: _ClosedStudy,
    manifest: ConcurrentRobustnessManifest,
    manifest_sha256: str,
    rows: _ReportRows,
    report_payload: Mapping[str, Any],
    payloads: dict[str, bytes],
) -> dict[str, bytes]:
    report_schema = _validate_report_payload_contract(report_payload, production=False)
    content_hashes = {path: _sha256_bytes(payload) for path, payload in payloads.items()}
    content_identity = _sha256_bytes(_json_bytes(dict(sorted(content_hashes.items()))))
    release_evidence = {
        "schema_version": _RELEASE_EVIDENCE_SCHEMA,
        "candidate_type": "complete_fixture_report_candidate",
        "candidate_content_identity_sha256": content_identity,
        "formal_source_manifest_sha256": manifest.source.manifest_sha256,
        "study_manifest_sha256": manifest_sha256,
        "study_root_identity_sha256": study.root_manifest["root_identity_sha256"],
        "provider_calls_during_composition": 0,
        "image_generation_triggered": False,
        "canonical_deployment_triggered": False,
        "production_deploy_eligible": False,
    }
    payloads[_RELEASE_EVIDENCE_JSON] = _json_bytes(release_evidence)
    artifact_hashes = {path: _sha256_bytes(payload) for path, payload in payloads.items()}
    artifact_mapping = _artifact_mapping(formal, payloads)
    manifest_document = {
        "schema_version": _REPORT_MANIFEST_SCHEMA,
        "candidate_type": "immutable_combined_robustness_report",
        "formal_source": {
            "source_id": manifest.source.source_id,
            "manifest_schema": manifest.source.manifest_schema,
            "manifest_sha256": manifest.source.manifest_sha256,
            "copied_artifact_count": len(formal.manifest.artifacts) - 1,
        },
        "study_source": {
            "output_identity": manifest.output_identity,
            "manifest_sha256": manifest_sha256,
            "artifact_manifest_sha256": study.file_hashes["artifact_manifest.json"],
            "root_identity_sha256": study.root_manifest["root_identity_sha256"],
        },
        "report_schema": report_schema,
        "artifacts": artifact_mapping,
        "sha256": {name: artifact_hashes[path] for name, path in artifact_mapping.items()},
        "candidate_identity_sha256": _sha256_bytes(
            _json_bytes(dict(sorted((path, artifact_hashes[path]) for path in artifact_mapping.values())))
        ),
        "row_counts": rows.counts(),
        "approved_downloads": list(_mapping(report_payload["downloads"], "report downloads").values()),
        "production_deploy_eligible": False,
    }
    payloads[CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON] = _json_bytes(manifest_document)
    return payloads


def _artifact_mapping(
    formal: ConcurrentMessageArtifactClosure,
    payloads: Mapping[str, bytes],
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    formal_paths = {
        relative_path: name
        for name, relative_path in formal.manifest.artifacts.items()
        if name != "report_html"
    }
    for relative_path in sorted(payloads):
        if relative_path == CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON:
            continue
        if relative_path in formal_paths:
            logical_name = f"formal_{formal_paths[relative_path]}"
        else:
            logical_name = Path(relative_path).stem.replace("-", "_")
        if logical_name in mapping:
            raise _RobustnessReportClosureError("candidate artifact logical names are not unique")
        mapping[logical_name] = relative_path
    return dict(sorted(mapping.items()))


def _validate_report_payload_contract(
    payload: Mapping[str, Any],
    *,
    production: bool,
    candidate: Path | None = None,
) -> str:
    schema = payload.get("schema_version")
    base_fields: frozenset[str]
    if schema == _REPORT_PAYLOAD_SCHEMA:
        base_fields = _REPORT_PAYLOAD_V1_FIELDS
    elif schema == _REPORT_PAYLOAD_V2_SCHEMA:
        base_fields = _REPORT_PAYLOAD_V2_FIELDS
    else:
        raise ValueError("report payload schema is unsupported")
    expected_fields = base_fields | ({"production_release"} if production else set())
    if set(payload) != expected_fields:
        raise ValueError("report payload fields are missing or unexpected")
    if schema == _REPORT_PAYLOAD_V2_SCHEMA:
        _validate_mechanism_presentation_contract(
            payload.get("mechanism_presentation"),
            candidate=candidate,
        )
        downloads = _string_mapping(payload.get("downloads"), "semantic report downloads")
        _validate_semantic_downloads(downloads)
    return str(schema)


def _validate_semantic_downloads(downloads: Mapping[str, str]) -> None:
    if any(downloads.get(key) != path for key, path in _SEMANTIC_MERMAID_DOWNLOADS.items()):
        raise ValueError("semantic report Mermaid downloads are incomplete or crossed")
    if "project_evidence_chain_mermaid" in downloads or "batch_mechanism_mermaid" in downloads:
        raise ValueError("semantic report retained a compatibility Mermaid mapping")
    if any(
        path == "mechanism-image-generation-audit.json"
        or path.endswith("-v4.png")
        or path.endswith("-v4.webp")
        for path in downloads.values()
    ):
        raise ValueError("semantic report contains a rejected presentation download")


def _validate_mechanism_presentation_contract(
    value: object,
    *,
    candidate: Path | None,
) -> None:
    facts = _mapping(value, "mechanism presentation facts")
    if set(facts) != _MECHANISM_PRESENTATION_FIELDS:
        raise ValueError("mechanism presentation fields are missing or unexpected")
    mechanism = _MECHANISM_PRESENTATION.build()
    expected_masters = {
        artifact.filename: artifact.sha256
        for artifact in mechanism.mermaid_artifacts
    }
    masters = _string_mapping(facts.get("masters"), "mechanism presentation masters")
    if (
        facts.get("schema_version") != mechanism.schema_version
        or facts.get("semantic_set_identity_sha256") != mechanism.semantic_set_identity_sha256
        or masters != expected_masters
    ):
        raise ValueError("mechanism presentation identity is crossed")
    if candidate is None:
        return
    for filename, expected_sha256 in expected_masters.items():
        relative = PurePosixPath(filename)
        target = candidate / filename
        if (
            relative.is_absolute()
            or relative.as_posix() != filename
            or ".." in relative.parts
            or target.is_symlink()
            or not target.is_file()
            or _sha256_file(target) != expected_sha256
        ):
            raise ValueError("mechanism presentation master bytes are crossed")


def _validate_production_facts(facts: _ProductionPresentationFacts) -> dict[str, str]:
    strings = (
        facts.release_id,
        facts.release_contract_schema,
        facts.canonical_endpoint,
        facts.production_evidence_schema,
        facts.provider_transport,
    )
    if any(not isinstance(value, str) or not value for value in strings):
        raise _RobustnessReportClosureError("production presentation facts contain an empty string")
    if (
        type(facts.formal_logical_judgments) is not int
        or facts.formal_logical_judgments < 0
        or type(facts.formal_physical_attempts) is not int
        or facts.formal_physical_attempts < 0
    ):
        raise _RobustnessReportClosureError("production presentation judgment counts are invalid")
    billed_cost = facts.subscription_billed_cost_usd
    if isinstance(billed_cost, bool) or not isinstance(billed_cost, (int, float)) or not math.isfinite(billed_cost):
        raise _RobustnessReportClosureError("production presentation billed cost is invalid")
    downloads = _string_mapping(facts.approved_downloads, "production approved downloads")
    for key, relative_path in downloads.items():
        path = PurePosixPath(relative_path)
        if (
            _safe_id(key) != key
            or "\\" in relative_path
            or path.is_absolute()
            or path.as_posix() != relative_path
            or ".." in path.parts
        ):
            raise _RobustnessReportClosureError("production presentation download mapping is unsafe")
    return downloads


def _production_release_payload(facts: _ProductionPresentationFacts) -> dict[str, Any]:
    return {
        "schema_version": facts.production_evidence_schema,
        "release_id": facts.release_id,
        "canonical_endpoint": facts.canonical_endpoint,
        "formal_logical_judgments": facts.formal_logical_judgments,
        "formal_physical_attempts": facts.formal_physical_attempts,
        "provider_transport": facts.provider_transport,
        "subscription_billed_cost_usd": facts.subscription_billed_cost_usd,
    }


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"non-standard JSON constant is not allowed: {value}")


def _validate_trace_row_shape(row: object, index: int) -> None:
    if type(row) is not dict:
        raise ValueError(f"trace row {index} must be an object")
    required_strings = (
        "trace_id",
        "pair_id",
        "message_id",
        "message_title",
        "user_id",
        "latent_class",
        "primary_action",
        "shadow_action",
        "provider_status",
    )
    if any(not isinstance(row.get(field), str) or not row[field] for field in required_strings):
        raise ValueError(f"trace row {index} has missing or invalid identity/status fields")
    if type(row.get("time_step")) is not int or type(row.get("ranking_position")) is not int:
        raise ValueError(f"trace row {index} has invalid batch or ranking position")
    if type(row.get("disagreement")) is not bool:
        raise ValueError(f"trace row {index} has invalid disagreement flag")


def _trace_envelope_for_json(trace_json: str, *, expected_row_count: int = _TRACE_ROW_COUNT) -> str:
    if type(expected_row_count) is not int or expected_row_count <= 0:
        raise _RobustnessReportClosureError("trace row count must be a positive strict integer")
    raw = trace_json.encode("utf-8")
    if len(raw) > _MAX_TRACE_UNCOMPRESSED_BYTES:
        raise _RobustnessReportClosureError("trace rows exceed the uncompressed size bound")
    try:
        rows = json.loads(trace_json, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise _RobustnessReportClosureError("trace rows are not valid JSON") from exc
    if type(rows) is not list or len(rows) != expected_row_count:
        raise _RobustnessReportClosureError(
            f"trace rows must be a list of exactly {expected_row_count:,} objects"
        )
    try:
        for index, row in enumerate(rows):
            _validate_trace_row_shape(row, index)
    except ValueError as exc:
        raise _RobustnessReportClosureError("trace rows do not satisfy the persisted view contract") from exc

    compressed_buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed_buffer, mode="wb", filename="", mtime=0) as stream:
        stream.write(raw)
    compressed = compressed_buffer.getvalue()
    if len(compressed) > _MAX_TRACE_COMPRESSED_BYTES:
        raise _RobustnessReportClosureError("trace rows exceed the compressed size bound")
    envelope = {
        "schema": _TRACE_ENVELOPE_SCHEMA,
        "encoding": _TRACE_ENCODING,
        "uncompressed_byte_length": len(raw),
        "sha256": _sha256_bytes(raw),
        "row_count": expected_row_count,
        "payload": base64.b64encode(compressed).decode("ascii"),
    }
    return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), sort_keys=True).replace("</", "<\\/")


def _replace_trace_script(formal_html: str, *, expected_row_count: int = _TRACE_ROW_COUNT) -> str:
    matches = list(_TRACE_SCRIPT_PATTERN.finditer(formal_html))
    if len(matches) != 1 or formal_html.count(_TRACE_SCRIPT_OPEN) != 1:
        raise _RobustnessReportClosureError("historical report must contain exactly one trace rows script")
    match = matches[0]
    envelope = _trace_envelope_for_json(match.group(1), expected_row_count=expected_row_count)
    replacement = f"{_TRACE_SCRIPT_OPEN}{envelope}</script>"
    return formal_html[: match.start()] + replacement + formal_html[match.end() :]


def _stream_trace_gzip(compressed: bytes) -> bytes:
    if len(compressed) > _MAX_TRACE_COMPRESSED_BYTES:
        raise ValueError("trace envelope compressed payload is oversized")
    if len(compressed) < 18:
        raise ValueError("trace envelope gzip payload is too short")
    if compressed[:3] != b"\x1f\x8b\x08" or compressed[3] != 0 or compressed[4:8] != b"\x00\x00\x00\x00":
        raise ValueError("trace envelope gzip header is invalid")
    if compressed[8] not in {0, 2} or compressed[9] not in {3, 255}:
        raise ValueError("trace envelope gzip header is invalid")

    decompressor = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
    chunks: list[bytes] = []
    total = 0
    for offset in range(0, len(compressed), 64 * 1024):
        pending = compressed[offset : offset + 64 * 1024]
        while pending:
            allowance = _MAX_TRACE_UNCOMPRESSED_BYTES - total + 1
            try:
                output = decompressor.decompress(pending, allowance)
            except zlib.error as exc:
                raise ValueError("trace envelope gzip payload is corrupt") from exc
            total += len(output)
            if total > _MAX_TRACE_UNCOMPRESSED_BYTES:
                raise ValueError("trace envelope decompressed payload is oversized")
            if output:
                chunks.append(output)
            pending = decompressor.unconsumed_tail
            if not pending:
                break
    if not decompressor.eof:
        raise ValueError("trace envelope gzip payload is truncated")
    if decompressor.unused_data or decompressor.unconsumed_tail:
        raise ValueError("trace envelope gzip payload has trailing data")
    return b"".join(chunks)


def _decode_trace_envelope(
    envelope: Mapping[str, Any],
    *,
    expected_row_count: int = _TRACE_ROW_COUNT,
) -> list[dict[str, Any]]:
    if type(envelope) is not dict or set(envelope) != _TRACE_ENVELOPE_FIELDS:
        raise ValueError("trace envelope fields are not exact")
    if envelope.get("schema") != _TRACE_ENVELOPE_SCHEMA or envelope.get("encoding") != _TRACE_ENCODING:
        raise ValueError("trace envelope schema or encoding is unsupported")
    length = envelope.get("uncompressed_byte_length")
    if type(length) is not int or length < 0 or length > _MAX_TRACE_UNCOMPRESSED_BYTES:
        raise ValueError("trace envelope uncompressed length is out of bounds")
    if type(expected_row_count) is not int or expected_row_count <= 0:
        raise ValueError("expected trace row count must be a positive strict integer")
    row_count = envelope.get("row_count")
    if type(row_count) is not int or row_count != expected_row_count:
        raise ValueError("trace envelope row count is invalid")
    digest = envelope.get("sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("trace envelope digest is invalid")
    encoded = envelope.get("payload")
    if (
        not isinstance(encoded, str)
        or not encoded
        or len(encoded) > ((_MAX_TRACE_COMPRESSED_BYTES + 2) // 3) * 4
        or len(encoded) % 4
        or not re.fullmatch(r"(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?", encoded)
    ):
        raise ValueError("trace envelope payload is not valid base64")
    try:
        compressed = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("trace envelope payload is not valid base64") from exc
    if base64.b64encode(compressed).decode("ascii") != encoded:
        raise ValueError("trace envelope payload is not canonical base64")
    raw = _stream_trace_gzip(compressed)
    if len(raw) != length:
        raise ValueError("trace envelope decompressed length is invalid")
    if _sha256_bytes(raw) != digest:
        raise ValueError("trace envelope digest does not match")
    try:
        rows_value = json.loads(raw.decode("utf-8"), parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("trace envelope payload is not valid UTF-8 JSON") from exc
    if type(rows_value) is not list or len(rows_value) != expected_row_count:
        raise ValueError(f"trace envelope rows are not exactly {expected_row_count:,} objects")
    for index, row in enumerate(rows_value):
        _validate_trace_row_shape(row, index)
    return rows_value


def _validate_trace_envelope_html(
    html_document: str,
    *,
    expected_row_count: int = _TRACE_ROW_COUNT,
) -> None:
    matches = list(_TRACE_SCRIPT_PATTERN.finditer(html_document))
    if len(matches) != 1 or html_document.count(_TRACE_SCRIPT_OPEN) != 1:
        raise ValueError("report must contain exactly one trace rows script")
    try:
        value = json.loads(matches[0].group(1), parse_constant=_reject_json_constant)
        if type(value) is not dict:
            raise ValueError("trace envelope must be an object")
        _decode_trace_envelope(value, expected_row_count=expected_row_count)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError("report trace envelope failed validation") from exc


_TRACE_RUNTIME_BRIDGE = r"""
(() => {
  const root = document.querySelector('[data-testid="editorial-report"]');
  const traceSection = root?.querySelector('[data-testid="run-llm-decision-section"]');
  const traceTool = root?.querySelector('[data-testid="run-trace-tool"]');
  const traceRowsData = root?.querySelector('[data-testid="run-trace-rows-data"]');
  const deferredRuntime = document.querySelector('[data-concurrent-editorial-runtime="deferred"]');
  const traceTable = root?.querySelector('[data-testid="run-trace-table"]');
  const status = traceTool?.querySelector('[data-testid="run-trace-state"]') || document.createElement('p');
  const maxCompressedBytes = 4 * 1024 * 1024;
  const maxUncompressedBytes = 20 * 1024 * 1024;
  const expectedRowCount = __TRACE_ROW_COUNT__;
  const exactFields = [
    'encoding',
    'payload',
    'row_count',
    'schema',
    'sha256',
    'uncompressed_byte_length',
  ];
  let runtimeStarted = false;

  function setStatus(state, message) {
    if (root) root.dataset.traceState = state;
    if (traceSection) traceSection.dataset.traceState = state;
    if (traceTool) traceTool.dataset.traceState = state;
    status.dataset.traceState = state;
    status.textContent = message;
  }

  function gateControls(disabled) {
    const controls = new Set([
      ...(traceTool?.querySelectorAll('input, select, button') || []),
      ...(root?.querySelectorAll('[data-mechanism-key]') || []),
      ...(document.querySelector('[data-testid="evidence-drawer"]')?.querySelectorAll('button') || []),
    ]);
    controls.forEach((control) => {
      control.disabled = disabled;
      control.setAttribute('aria-disabled', String(disabled));
    });
    if (traceTable) {
      traceTable.setAttribute('aria-disabled', String(disabled));
      traceTable.style.pointerEvents = disabled ? 'none' : '';
    }
  }

  function startEditorialRuntime(rows) {
    if (runtimeStarted || !deferredRuntime || !traceRowsData) return;
    runtimeStarted = true;
    traceRowsData.textContent = JSON.stringify(rows);
    const executable = document.createElement('script');
    executable.textContent = deferredRuntime.textContent || '';
    deferredRuntime.remove();
    document.body.append(executable);
  }

  function failure() {
    try {
      startEditorialRuntime([]);
    } finally {
      gateControls(true);
      setStatus('error', 'Trace data unavailable. Filters and drawer remain disabled.');
      status.setAttribute('role', 'alert');
    }
  }

  async function decodeBase64Envelope() {
    if (!root || !traceSection || !traceTool || !traceRowsData || !deferredRuntime) {
      throw new Error('trace bridge markers are missing');
    }
    if (typeof DecompressionStream !== 'function') {
      throw new Error('gzip decompression is unsupported');
    }
    if (!globalThis.crypto?.subtle || typeof TextDecoder !== 'function') {
      throw new Error('required platform decoding APIs are unsupported');
    }
    const envelope = JSON.parse(traceRowsData.textContent || '');
    if (!envelope || typeof envelope !== 'object' || Array.isArray(envelope)) {
      throw new Error('trace envelope is not an object');
    }
    const observedFields = Object.keys(envelope).sort();
    if (observedFields.join('|') !== exactFields.join('|')) {
      throw new Error('trace envelope fields are not exact');
    }
    if (envelope.schema !== 'concurrent-robustness-trace-envelope-v1'
      || envelope.encoding !== 'gzip+base64') {
      throw new Error('trace envelope schema is unsupported');
    }
    if (!Number.isInteger(envelope.uncompressed_byte_length)
      || envelope.uncompressed_byte_length < 0
      || envelope.uncompressed_byte_length > maxUncompressedBytes) {
      throw new Error('trace envelope is oversized');
    }
    if (!Number.isInteger(envelope.row_count) || envelope.row_count !== expectedRowCount) {
      throw new Error('trace envelope row count is invalid');
    }
    if (typeof envelope.sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(envelope.sha256)) {
      throw new Error('trace envelope digest is invalid');
    }
    if (typeof envelope.payload !== 'string'
      || !envelope.payload
      || envelope.payload.length % 4 !== 0
      || envelope.payload.length > Math.ceil(maxCompressedBytes / 3) * 4
      || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(envelope.payload)) {
      throw new Error('trace envelope payload is invalid');
    }
    const binary = atob(envelope.payload);
    if (binary.length > maxCompressedBytes) throw new Error('trace envelope is oversized');
    if (btoa(binary) !== envelope.payload) throw new Error('trace envelope payload is not canonical base64');
    const compressed = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) compressed[index] = binary.charCodeAt(index);
    if (compressed.length < 18
      || compressed[0] !== 0x1f
      || compressed[1] !== 0x8b
      || compressed[2] !== 0x08
      || compressed[3] !== 0
      || compressed[4] !== 0
      || compressed[5] !== 0
      || compressed[6] !== 0
      || compressed[7] !== 0
      || ![0, 2].includes(compressed[8])
      || ![3, 255].includes(compressed[9])) {
      throw new Error('trace envelope gzip header is invalid');
    }

    const response = new Response(compressed);
    if (!response.body) throw new Error('gzip stream body is unavailable');
    // WHATWG Compression Streams defines gzip as exactly one member and rejects
    // additional input. Reading through done is therefore the browser-side member
    // boundary check; length, digest, and row-shape checks below remain independent.
    const reader = response.body.pipeThrough(new DecompressionStream('gzip')).getReader();
    const chunks = [];
    let total = 0;
    for (;;) {
      const result = await reader.read();
      if (result.done) break;
      const chunk = result.value;
      total += chunk.byteLength;
      if (total > maxUncompressedBytes) throw new Error('trace envelope is oversized');
      chunks.push(chunk);
    }
    if (total !== envelope.uncompressed_byte_length) throw new Error('trace envelope length does not match');
    const raw = new Uint8Array(total);
    let offset = 0;
    chunks.forEach((chunk) => {
      raw.set(chunk, offset);
      offset += chunk.byteLength;
    });
    const digestBuffer = await globalThis.crypto.subtle.digest('SHA-256', raw);
    const digest = [...new Uint8Array(digestBuffer)]
      .map((value) => value.toString(16).padStart(2, '0'))
      .join('');
    if (digest !== envelope.sha256) throw new Error('trace envelope digest does not match');
    const text = new TextDecoder('utf-8', { fatal: true }).decode(raw);
    const rows = JSON.parse(text);
    const requiredStringFields = [
      'trace_id', 'pair_id', 'message_id', 'message_title', 'user_id',
      'latent_class', 'primary_action', 'shadow_action', 'provider_status',
    ];
    if (!Array.isArray(rows) || rows.length !== expectedRowCount
      || rows.some((row) => !row
        || typeof row !== 'object'
        || Array.isArray(row)
        || requiredStringFields.some((field) => typeof row[field] !== 'string' || !row[field])
        || !Number.isInteger(row.time_step)
        || !Number.isInteger(row.ranking_position)
        || typeof row.disagreement !== 'boolean')) {
      throw new Error('trace envelope rows are invalid');
    }
    return rows;
  }

  if (!traceTool) return;
  traceTool.setAttribute('aria-busy', 'true');
  status.dataset.testid = 'run-trace-state';
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  status.setAttribute('aria-atomic', 'true');
  setStatus('loading', 'Loading persisted trace data.');
  if (!status.parentElement) traceTool.prepend(status);
  gateControls(true);
  const traceReady = decodeBase64Envelope()
    .then((rows) => {
      startEditorialRuntime(rows);
      traceTool.setAttribute('aria-busy', 'false');
      gateControls(false);
      setStatus('ready', `Trace ready: ${rows.length.toLocaleString()} persisted rows.`);
      return { state: 'ready', rowCount: rows.length };
    })
    .catch(() => {
      failure();
      traceTool.setAttribute('aria-busy', 'false');
      return { state: 'error', rowCount: 0 };
    });
  globalThis.__concurrentRobustnessTraceReady = traceReady;
})();
"""


def _defer_editorial_runtime(formal_html: str) -> str:
    scripts = list(re.finditer(r"<script(?:\s[^>]*)?>(.*?)</script>", formal_html, re.DOTALL))
    runtime_scripts = [
        match
        for match in scripts
        if "const traceRowsData = root.querySelector" in match.group(1)
        and "const root = document.querySelector('[data-testid=\"editorial-report\"]')" in match.group(1)
    ]
    if len(runtime_scripts) != 1:
        raise _RobustnessReportClosureError("historical Editorial runtime marker is missing or duplicated")
    match = runtime_scripts[0]
    opening_end = formal_html.find(">", match.start(), match.end())
    if opening_end < 0:
        raise _RobustnessReportClosureError("historical Editorial runtime script is malformed")
    opening = formal_html[match.start() : opening_end + 1]
    if opening != "<script>":
        raise _RobustnessReportClosureError("historical Editorial runtime script marker is malformed")
    inert_opening = '<script type="application/x-concurrent-editorial-runtime" data-concurrent-editorial-runtime="deferred">'
    deferred = formal_html[: match.start()] + inert_opening + match.group(1) + "</script>" + formal_html[match.end() :]
    bridge = '<script type="text/javascript">' + _TRACE_RUNTIME_BRIDGE + "</script>"
    runtime_end = match.start() + len(inert_opening) + len(match.group(1)) + len("</script>")
    return deferred[:runtime_end] + bridge + deferred[runtime_end:]


def _validate_semantic_presentation_bundle(
    payload: Mapping[str, Any],
    html_document: str,
    *,
    stage_facts: _ProductionPresentationFacts | None,
) -> None:
    _validate_semantic_html(
        html_document,
        stage_facts=stage_facts,
    )
    downloads = _string_mapping(payload.get("downloads"), "semantic report downloads")
    if stage_facts is None:
        if payload.get("production_deploy_eligible") is not False or "production_release" in payload:
            raise ValueError("semantic candidate presentation stage is crossed")
    else:
        approved_downloads = _validate_production_facts(stage_facts)
        if downloads != approved_downloads:
            raise ValueError("semantic production downloads differ from approved presentation facts")
        if _mapping(payload.get("production_release"), "production release metadata") != (
            _production_release_payload(stage_facts)
        ) or payload.get("production_deploy_eligible") is not True:
            raise ValueError("semantic production release metadata is crossed")
    _validate_semantic_downloads(downloads)
    if _presentation_downloads_from_html(html_document) != downloads:
        raise ValueError("semantic report hrefs differ from its payload downloads")
    if re.search(
        r"<(?:script|link|img)\b[^>]*(?:src|href)=[\"']https?://",
        html_document,
        re.IGNORECASE,
    ):
        raise ValueError("semantic report requests an external resource")


def _validate_presentation_bundle(
    bundle: _PresentationBundle,
    *,
    stage_facts: _ProductionPresentationFacts | None,
) -> None:
    payload_value = json.loads(bundle.report_payload)
    payload = _mapping(payload_value, "report presentation payload")
    html_document = bundle.report_html.decode("utf-8")
    if len(bundle.report_html) >= _MAX_REPORT_HTML_BYTES:
        raise ValueError("report.html exceeds the 3 MiB presentation limit")
    expected_trace_rows = _strict_positive_int(
        payload.get("trace_row_count"),
        "report trace row count",
    )
    if (
        stage_facts is not None
        and stage_facts.release_contract_schema
        in {"abm-report-release-contract-v6", "abm-report-release-contract-v7"}
        and expected_trace_rows != _TRACE_ROW_COUNT
    ):
        raise ValueError("v6/v7 production presentation requires exactly 1,800 trace rows")
    _validate_trace_envelope_html(
        html_document,
        expected_row_count=expected_trace_rows,
    )
    report_schema = _validate_report_payload_contract(
        payload,
        production=stage_facts is not None,
    )
    if stage_facts is not None and (
        (
            stage_facts.release_contract_schema == "abm-report-release-contract-v7"
            and report_schema != _REPORT_PAYLOAD_V2_SCHEMA
        )
        or (
            stage_facts.release_contract_schema
            in {"abm-report-release-contract-v5", "abm-report-release-contract-v6"}
            and report_schema != _REPORT_PAYLOAD_SCHEMA
        )
    ):
        raise ValueError("production report payload schema is crossed with its release contract")
    downloads = _string_mapping(payload.get("downloads"), "report presentation downloads")
    if report_schema == _REPORT_PAYLOAD_V2_SCHEMA:
        _validate_semantic_presentation_bundle(
            payload,
            html_document,
            stage_facts=stage_facts,
        )
        return

    if stage_facts is None:
        stage_test_id = "robustness-report-candidate"
        other_test_id = "robustness-report-release"
        eligibility = False
        release_attribute = ' aria-labelledby="robustness-title"'
        expected_copy = "values in this candidate"
        if "production_release" in payload:
            raise ValueError("candidate presentation contains production release metadata")
    else:
        approved_downloads = _validate_production_facts(stage_facts)
        if downloads != approved_downloads:
            raise ValueError("production payload downloads differ from approved presentation facts")
        if _mapping(payload.get("production_release"), "production release metadata") != (
            _production_release_payload(stage_facts)
        ):
            raise ValueError("production release metadata is crossed")
        stage_test_id = "robustness-report-release"
        other_test_id = "robustness-report-candidate"
        eligibility = True
        release_attribute = f' data-release-id="{_escape(stage_facts.release_id, quote=True)}"'
        expected_copy = "values in this production release"

    if payload.get("production_deploy_eligible") is not eligibility:
        raise ValueError("report payload eligibility is crossed with its presentation stage")
    root_signature = f'data-testid="{stage_test_id}"{release_attribute}'
    selector = f"document.querySelector('[data-testid=\"{stage_test_id}\"]')"
    stage_marker = f'data-testid="{stage_test_id}"'
    other_marker = f'data-testid="{other_test_id}"'
    eligibility_text = str(eligibility).lower()
    eligibility_marker = (
        'data-testid="robustness-production-eligibility">'
        f"production_deploy_eligible={eligibility_text}"
    )
    if (
        html_document.count(root_signature) != 1
        or html_document.count(stage_marker) != 2
        or html_document.count(selector) != 1
        or other_marker in html_document
        or html_document.count(eligibility_marker) != 1
        or f"production_deploy_eligible={str(not eligibility).lower()}" in html_document
        or expected_copy not in html_document
    ):
        raise ValueError("report DOM stage, selector, eligibility, or copy is crossed")

    if stage_facts is None:
        if (
            "data-release-id=" in html_document
            or 'name="abm-release-id"' in html_document
            or 'name="abm-release-contract"' in html_document
        ):
            raise ValueError("candidate presentation contains production stage metadata")
    else:
        release_id = _escape(stage_facts.release_id, quote=True)
        release_schema = _escape(stage_facts.release_contract_schema, quote=True)
        release_meta = f'<meta name="abm-release-id" content="{release_id}">'
        contract_meta = f'<meta name="abm-release-contract" content="{release_schema}">'
        if (
            html_document.count(release_meta) != 1
            or html_document.count(contract_meta) != 1
            or len(re.findall(r'\bdata-release-id="[^"]*"', html_document)) != 1
            or len(re.findall(r'<meta\s+name="abm-release-id"\s+content="[^"]*">', html_document)) != 1
        ):
            raise ValueError("production presentation release metadata is crossed")

    required = (
        'data-testid="mechanism-overview-section"',
        'data-testid="run-evidence-mode-panel"',
        'data-testid="run-trace-lineage-data"',
        'data-testid="run-trace-state"',
        'data-trace-state="loading"',
        'data-concurrent-editorial-runtime="deferred"',
        'data-testid="robustness-source-lineage"',
        'data-testid="ranking-weight-sensitivity-section"',
        'data-testid="prompt-model-robustness-section"',
        'data-testid="prompt-model-contract-disclosure"',
        'data-testid="project-evidence-chain-diagram"',
        'data-testid="project-evidence-chain-fallback"',
        'data-testid="project-evidence-chain-mermaid-source"',
        'data-testid="batch-mechanism-diagram"',
        'data-testid="batch-mechanism-fallback"',
        'data-testid="batch-mechanism-mermaid-source"',
        'data-testid="prompt-model-factorial-diagram"',
        'data-testid="prompt-model-factorial-fallback"',
        'data-testid="prompt-model-factorial-mermaid-source"',
        "4 Prompt × 4 model = 16 execution cells",
        "16 cells × 3 messages = 48 message-level reporting slices",
        "Demographic Shadow evidence remains bound to the historical Formal source",
    )
    if any(marker not in html_document for marker in required):
        raise ValueError("report presentation is missing required historical or robustness evidence")
    if (
        html_document.count('<details class="robustness-prompt-details">') != 4
        or html_document.count(
            '<details class="robustness-shared-contract" '
            'data-testid="prompt-model-shared-contract" open>'
        )
        != 1
    ):
        raise ValueError("Prompt disclosure hierarchy is incomplete or crossed")
    diagram_ids = (
        "project-evidence-chain-diagram",
        "batch-mechanism-diagram",
        "prompt-model-factorial-diagram",
    )
    for diagram_id in diagram_ids:
        svg_match = re.search(
            rf'<svg\b(?=[^>]*data-testid="{re.escape(diagram_id)}")[^>]*>(.*?)</svg>',
            html_document,
            re.DOTALL,
        )
        if svg_match is None:
            raise ValueError("semantic reader diagram is missing")
        svg = svg_match.group(1)
        node_tags = re.findall(r'<g\b(?=[^>]*data-diagram-node-id="[^"]+")[^>]*>', svg)
        edge_tags = re.findall(r'<path\b(?=[^>]*data-diagram-edge-id="[^"]+")[^>]*>', svg)
        if not node_tags or not edge_tags:
            raise ValueError("semantic reader diagram has no queryable nodes or edges")
        node_ids = [
            match
            for tag in node_tags
            for match in re.findall(r'data-diagram-node-id="([^"]+)"', tag)
        ]
        edge_ids = [
            match
            for tag in edge_tags
            for match in re.findall(r'data-diagram-edge-id="([^"]+)"', tag)
        ]
        if len(node_ids) != len(set(node_ids)) or len(edge_ids) != len(set(edge_ids)):
            raise ValueError("semantic reader diagram IDs are not unique")
        if any(
            'data-node-kind="' not in tag or 'data-provenance="' not in tag
            for tag in node_tags
        ):
            raise ValueError("semantic reader diagram node metadata is incomplete")
        edge_attributes = (
            "data-from",
            "data-to",
            "data-direction",
            "data-condition",
            "data-timing",
            "data-effect",
            "data-provenance",
        )
        if any(
            any(f'{attribute}="' not in tag for attribute in edge_attributes)
            for tag in edge_tags
        ):
            raise ValueError("semantic reader diagram edge metadata is incomplete")
        edge_endpoints = [
            (source, target)
            for tag in edge_tags
            for source in re.findall(r'data-from="([^"]+)"', tag)
            for target in re.findall(r'data-to="([^"]+)"', tag)
        ]
        if len(edge_endpoints) != len(edge_tags) or any(
            source not in node_ids or target not in node_ids
            for source, target in edge_endpoints
        ):
            raise ValueError("semantic reader diagram edge references an unknown node")
    batch_edge_tags = re.findall(
        r'<path\b(?=[^>]*data-diagram-edge-id="batch-edge-[^"]+")[^>]*>',
        html_document,
    )
    forbidden_feedback_edges = (
        ('data-from="Shadow"', 'data-to="Commit"'),
        ('data-from="Shadow"', 'data-to="Pending"'),
        ('data-from="NoFeedback"', 'data-to="Commit"'),
    )
    if any(
        all(fragment in tag for fragment in pair)
        for tag in batch_edge_tags
        for pair in forbidden_feedback_edges
    ):
        raise ValueError("non-propagating batch outcome has a campaign feedback edge")
    required_next_edges = {
        ("Commit", "Next1"),
        ("Commit", "Next2"),
        ("Commit", "Next3"),
    }
    observed_next_edges = {
        (source, target)
        for tag in batch_edge_tags
        for source in re.findall(r'data-from="([^"]+)"', tag)
        for target in re.findall(r'data-to="([^"]+)"', tag)
        if source == "Commit" and target.startswith("Next")
    }
    next_edge_contract = (
        'data-condition="next_batch_exists"',
        'data-timing="next_batch_before_ranking"',
        'data-effect="ranking_context_only_no_queue_injection_no_same_batch_writeback"',
        'data-provenance="CampaignEngagementRankingSignal"',
    )
    if observed_next_edges != required_next_edges or any(
        any(fragment not in tag for fragment in next_edge_contract)
        for tag in batch_edge_tags
        if 'data-from="Commit"' in tag and 'data-to="Next' in tag
    ):
        raise ValueError("campaign set must feed exactly three next-batch ranking contexts")
    legend_mark_ids = set(re.findall(r'data-legend-mark-id="([^"]+)"', html_document))
    diagram_mark_ids = set(re.findall(r'data-diagram-mark-id="([^"]+)"', html_document))
    if (
        not legend_mark_ids
        or legend_mark_ids != diagram_mark_ids
        or any(html_document.count(f'data-legend-mark-id="{mark_id}"') != 1 for mark_id in legend_mark_ids)
        or any(html_document.count(f'data-diagram-mark-id="{mark_id}"') != 1 for mark_id in diagram_mark_ids)
    ):
        raise ValueError("semantic diagram legend does not bind one-to-one to real marks")
    for contract in CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.all():
        controlled_change = CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.controlled_change(contract.variant_id)
        required_identity = (
            f'data-testid="prompt-contract-row-{contract.variant_id.lower()}"',
            f'data-controlled-change="{controlled_change}"',
            f'data-prompt-version="{contract.prompt_version}"',
            f'data-prompt-canonical-hash="{contract.canonical_hash}"',
        )
        if any(marker not in html_document for marker in required_identity):
            raise ValueError("Prompt disclosure is crossed with the registry identity")
    expected_disclosure_ids = {
        f"prompt-contract-row-{contract.variant_id.lower()}"
        for contract in CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY.all()
    }
    observed_disclosure_ids = set(
        re.findall(r'data-prompt-disclosure-id="([^"]+)"', html_document)
    )
    if observed_disclosure_ids != expected_disclosure_ids:
        raise ValueError("Prompt chart series do not map one-to-one to disclosure rows")
    if re.search(
        r"<(?:script|link|img)\b[^>]*(?:src|href)=[\"']https?://",
        html_document,
        re.IGNORECASE,
    ):
        raise ValueError("report presentation requests an external resource")
    if any(downloads.get(key) != path for key, path in _READER_MERMAID_DOWNLOADS.items()):
        raise ValueError("reader Mermaid downloads are incomplete or crossed")
    if _presentation_downloads_from_html(html_document) != downloads:
        raise ValueError("report presentation hrefs differ from its payload downloads")


def _presentation_downloads_from_html(html_document: str) -> dict[str, str]:
    section_starts = list(
        re.finditer(
            r'<section\b(?=[^>]*\bdata-testid="robustness-downloads-section")[^>]*>',
            html_document,
            re.IGNORECASE,
        )
    )
    if len(section_starts) != 1:
        raise ValueError("report download section is missing or ambiguous")
    section_end = html_document.find("</section>", section_starts[0].end())
    if section_end < 0:
        raise ValueError("report download section is not closed")
    section = html_document[section_starts[0].end():section_end]
    downloads: dict[str, str] = {}
    for anchor in re.findall(r"<a\b[^>]*>", section, re.IGNORECASE):
        pairs = re.findall(r'([A-Za-z_:][A-Za-z0-9_.:-]*)="([^"]*)"', anchor)
        attributes = {key: html.unescape(value) for key, value in pairs}
        if len(attributes) != len(pairs):
            raise ValueError("report download link attributes are ambiguous")
        test_id = attributes.get("data-testid", "")
        prefix = "robustness-download-"
        key = test_id.removeprefix(prefix)
        href = attributes.get("href")
        if (
            not test_id.startswith(prefix)
            or not re.fullmatch(r"[A-Za-z0-9_-]+", key)
            or href is None
            or key in downloads
        ):
            raise ValueError("report download link mapping is invalid")
        downloads[key] = href
    return downloads


def _validate_candidate(
    candidate: Path,
    *,
    expected_payloads: Mapping[str, bytes],
    expected_row_counts: Mapping[str, int],
) -> None:
    try:
        if candidate.is_symlink() or not candidate.is_dir():
            raise ValueError("candidate is not a real directory")
        entries = list(candidate.iterdir())
        if any(path.is_symlink() or not path.is_file() for path in entries):
            raise ValueError("candidate contains a non-regular artifact")
        if {path.name for path in entries} != set(expected_payloads):
            raise ValueError("candidate has missing or extra artifacts")
        for relative_path, expected in expected_payloads.items():
            if (candidate / relative_path).read_bytes() != expected:
                raise ValueError(f"candidate artifact is not reproducible: {relative_path}")
        manifest = _read_json(candidate / CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON)
        if manifest.get("schema_version") != _REPORT_MANIFEST_SCHEMA:
            raise ValueError("candidate manifest schema is unsupported")
        if manifest.get("candidate_type") != "immutable_combined_robustness_report":
            raise ValueError("candidate type is unsupported")
        if manifest.get("production_deploy_eligible") is not False:
            raise ValueError("candidate cannot be production deploy eligible")
        artifacts = _string_mapping(manifest.get("artifacts"), "candidate artifacts")
        hashes = _string_mapping(manifest.get("sha256"), "candidate hashes")
        if set(artifacts) != set(hashes) or len(set(artifacts.values())) != len(artifacts):
            raise ValueError("candidate artifact and hash inventories are crossed")
        if set(artifacts.values()) != set(expected_payloads) - {CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON}:
            raise ValueError("candidate artifact inventory is incomplete")
        for name, relative_path in artifacts.items():
            if hashes[name] != _sha256_file(candidate / relative_path):
                raise ValueError("candidate artifact hash mismatch")
        identity_rows = dict(sorted((path, hashes[name]) for name, path in artifacts.items()))
        if manifest.get("candidate_identity_sha256") != _sha256_bytes(_json_bytes(identity_rows)):
            raise ValueError("candidate identity hash is crossed")
        if _mapping(manifest.get("row_counts"), "candidate row counts") != dict(expected_row_counts):
            raise ValueError("candidate row counts do not close")
        payload = _read_json(candidate / _REPORT_PAYLOAD)
        report_schema = _validate_report_payload_contract(
            payload,
            production=False,
            candidate=candidate,
        )
        if manifest.get("report_schema") != report_schema:
            raise ValueError("candidate manifest report schema is crossed")
        if _mapping(payload.get("row_counts"), "report payload row counts") != dict(expected_row_counts):
            raise ValueError("report payload row counts do not close")
        payload_downloads = _string_mapping(payload.get("downloads"), "report payload downloads")
        approved_downloads = _string_sequence(manifest.get("approved_downloads"), "approved downloads")
        if set(approved_downloads) != set(payload_downloads.values()):
            raise ValueError("candidate approved downloads are crossed with the report payload")
        if any(
            Path(relative_path).is_absolute()
            or ".." in Path(relative_path).parts
            or not (candidate / relative_path).is_file()
            for relative_path in approved_downloads
        ):
            raise ValueError("candidate approved downloads escape or are missing")
        payload_lineage = _mapping(payload.get("source_lineage"), "report payload source lineage")
        payload_formal = _mapping(payload_lineage.get("formal"), "report payload Formal lineage")
        payload_study = _mapping(payload_lineage.get("study"), "report payload study lineage")
        manifest_formal = _mapping(manifest.get("formal_source"), "candidate Formal lineage")
        manifest_study = _mapping(manifest.get("study_source"), "candidate study lineage")
        if payload_formal.get("manifest_sha256") != manifest_formal.get("manifest_sha256"):
            raise ValueError("candidate Formal lineage is crossed")
        if payload_study.get("manifest_sha256") != manifest_study.get("manifest_sha256"):
            raise ValueError("candidate study lineage is crossed")
        if payload_study.get("root_identity_sha256") != manifest_study.get("root_identity_sha256"):
            raise ValueError("candidate study root identity is crossed")
        release = _read_json(candidate / _RELEASE_EVIDENCE_JSON)
        if release.get("schema_version") != _RELEASE_EVIDENCE_SCHEMA:
            raise ValueError("release evidence schema is unsupported")
        if release.get("production_deploy_eligible") is not False:
            raise ValueError("release evidence cannot authorize production deployment")
        if release.get("provider_calls_during_composition") != 0:
            raise ValueError("report composition cannot call a Provider")
        if release.get("image_generation_triggered") is not False:
            raise ValueError("report composition cannot generate images")
        content_hashes = {
            path: _sha256_file(candidate / path)
            for path in expected_payloads
            if path not in {CONCURRENT_MESSAGE_ARTIFACT_MANIFEST_JSON, _RELEASE_EVIDENCE_JSON}
        }
        if release.get("candidate_content_identity_sha256") != _sha256_bytes(
            _json_bytes(dict(sorted(content_hashes.items())))
        ):
            raise ValueError("release evidence content identity is crossed")
        if release.get("formal_source_manifest_sha256") != manifest_formal.get("manifest_sha256"):
            raise ValueError("release evidence Formal source is crossed")
        if release.get("study_manifest_sha256") != manifest_study.get("manifest_sha256"):
            raise ValueError("release evidence study source is crossed")
        _validate_presentation_bundle(
            _PresentationBundle(
                report_payload=(candidate / _REPORT_PAYLOAD).read_bytes(),
                report_html=(candidate / CONCURRENT_MESSAGE_REPORT_HTML).read_bytes(),
            ),
            stage_facts=None,
        )
        _validate_csv(candidate / _WEIGHT_MESSAGE_CSV, _WEIGHT_MESSAGE_FIELDS, expected_row_counts["ranking_weight_message_summary"])
        _validate_csv(candidate / _WEIGHT_BATCH_CSV, _WEIGHT_BATCH_FIELDS, expected_row_counts["ranking_weight_batch_diagnostics"])
        _validate_csv(candidate / _SHARED_SEED_CSV, _SHARED_SEED_FIELDS, expected_row_counts["prompt_model_shared_seed_summary"])
        _validate_csv(candidate / _PROMPT_MESSAGE_CSV, _PROMPT_MESSAGE_FIELDS, expected_row_counts["prompt_model_message_summary"])
        _validate_csv(candidate / _PROMPT_TRAJECTORY_CSV, _PROMPT_TRAJECTORY_FIELDS, expected_row_counts["prompt_model_trajectory_summary"])
        _validate_csv(candidate / _PROMPT_GROWTH_CSV, _PROMPT_GROWTH_FIELDS, expected_row_counts["prompt_model_campaign_growth"])
        _validate_csv(candidate / _THRESHOLD_CSV, _THRESHOLD_FIELDS, expected_row_counts["prompt_model_practical_thresholds"])
    except _RobustnessReportClosureError:
        raise
    except (OSError, TypeError, ValueError, json.JSONDecodeError, csv.Error) as exc:
        raise _RobustnessReportClosureError("staged robustness report candidate failed closure validation") from exc


def _validate_csv(path: Path, fields: Sequence[str], expected_rows: int) -> None:
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != tuple(fields):
            raise ValueError(f"{path.name} schema is crossed")
        rows = list(reader)
    if len(rows) != expected_rows:
        raise ValueError(f"{path.name} row count does not close")


def _compatibility_raster_tag(match: re.Match[str]) -> str:
    tag = match.group(0)
    if " aria-hidden=" in tag or " alt=" not in tag or " data-i18n-alt=" not in tag:
        raise _RobustnessReportClosureError("compatibility raster image contract is malformed")
    tag = re.sub(r' data-i18n-alt="[^"]*"', "", tag, count=1)
    return re.sub(r' alt="[^"]*"', ' aria-hidden="true" alt=""', tag, count=1)


def _localize_semantic_trace_runtime(rendered: str) -> str:
    replacements = (
        (
            "setStatus('loading', 'Loading persisted trace data.');",
            "setStatus('loading', document.documentElement.lang === 'en-US' ? 'Loading persisted trace data.' : '正在加载持久化决策轨迹数据。');",
        ),
        (
            "setStatus('error', 'Trace data unavailable. Filters and drawer remain disabled.');",
            "setStatus('error', document.documentElement.lang === 'en-US' ? 'Trace data is unavailable. Filters and the drawer remain disabled.' : '决策轨迹数据不可用，筛选器与详情抽屉保持禁用。');",
        ),
        (
            "setStatus('ready', `Trace ready: ${rows.length.toLocaleString()} persisted rows.`);",
            "status.dataset.traceRowCount = String(rows.length);\n      setStatus('ready', document.documentElement.lang === 'en-US' ? `Trace ready: ${rows.length.toLocaleString('en-US')} persisted rows.` : `决策轨迹已就绪：${rows.length.toLocaleString('zh-CN')} 条持久化记录。`);",
        ),
    )
    for old, new in replacements:
        if rendered.count(old) != 1:
            raise _RobustnessReportClosureError("semantic trace status copy marker is missing or duplicated")
        rendered = rendered.replace(old, new, 1)
    return rendered


def _render_semantic_additive_report(
    formal_html: str,
    *,
    payload: Mapping[str, Any],
    prompt_model_presentation: _PromptModelPresentation,
    stage_facts: _ProductionPresentationFacts | None = None,
) -> str:
    if formal_html.count("</head>") != 1 or formal_html.count("</body>") != 1:
        raise _RobustnessReportClosureError("semantic Editorial renderer did not return one closed HTML document")
    insertion_marker = '<aside id="trace-drawer"'
    run_panel_marker = '<section id="editorial-run-panel"'
    if formal_html.count(insertion_marker) != 1 or formal_html.count(run_panel_marker) != 1:
        raise _RobustnessReportClosureError("semantic Editorial shell does not expose the composition markers")
    presentation_catalog = _semantic_presentation_catalog(prompt_model_presentation)
    section_html = _robustness_sections(
        payload,
        prompt_model_presentation=prompt_model_presentation,
        stage_facts=stage_facts,
        semantic_catalog=presentation_catalog,
    )
    prompt_catalog_json = json.dumps(
        presentation_catalog,
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    stage_test_id = (
        "robustness-report-release" if stage_facts is not None else "robustness-report-candidate"
    )
    script = (
        _ROBUSTNESS_SCRIPT.replace("__REPORT_STAGE_TEST_ID__", stage_test_id)
        .replace("__PROMPT_PRESENTATION_CATALOG__", prompt_catalog_json)
    )
    expected_trace_rows = _strict_positive_int(
        payload.get("trace_row_count"),
        "report trace row count",
    )
    rendered = _replace_trace_script(
        formal_html,
        expected_row_count=expected_trace_rows,
    )
    rendered = _defer_editorial_runtime(rendered).replace(
        "__TRACE_ROW_COUNT__",
        str(expected_trace_rows),
    )
    rendered = _localize_semantic_trace_runtime(rendered)
    trace_section_marker = 'data-section-anchor="llm-decision" data-testid="run-llm-decision-section" tabindex="-1"'
    if rendered.count(trace_section_marker) != 1:
        raise _RobustnessReportClosureError("semantic report must contain one trace section")
    rendered = rendered.replace(
        trace_section_marker,
        f'{trace_section_marker} data-trace-state="loading"',
        1,
    )
    trace_tool_marker = '<div class="editorial-trace-tool" data-testid="run-trace-tool">'
    if rendered.count(trace_tool_marker) != 1:
        raise _RobustnessReportClosureError("semantic report must contain one trace tool")
    rendered = rendered.replace(
        trace_tool_marker,
        trace_tool_marker
        + '<p data-testid="run-trace-state" data-trace-state="loading" role="status" aria-live="polite" aria-atomic="true" data-robustness-i18n="semantic.trace.loading">正在加载持久化决策轨迹数据。</p>',
        1,
    )
    if rendered.count(_TRACE_SCRIPT_OPEN) != 1:
        raise _RobustnessReportClosureError("semantic report must contain exactly one trace envelope")
    rendered = rendered.replace(
        "</head>",
        f"<style>{_ROBUSTNESS_CSS}{_SEMANTIC_ROBUSTNESS_CSS}</style>\n</head>",
        1,
    )
    run_panel_start = rendered.find(run_panel_marker)
    drawer_start = rendered.find(insertion_marker, run_panel_start)
    run_panel_close = rendered.rfind("</section>", run_panel_start, drawer_start)
    if run_panel_start < 0 or drawer_start < 0 or run_panel_close < 0:
        raise _RobustnessReportClosureError(
            "semantic robustness evidence could not enter Run Evidence"
        )
    rendered = (
        rendered[:run_panel_close]
        + f"{section_html}\n        "
        + rendered[run_panel_close:]
    )
    rendered = rendered.replace("</body>", f"<script>{script}</script>\n</body>", 1)
    if stage_facts is not None:
        release_id = _escape(stage_facts.release_id, quote=True)
        release_schema = _escape(stage_facts.release_contract_schema, quote=True)
        root_marker = (
            'data-editorial-version="v4-semantic" '
            'data-production-deploy-eligible="false"'
        )
        if rendered.count(root_marker) != 1:
            raise _RobustnessReportClosureError("semantic production root marker is crossed")
        rendered = rendered.replace(
            root_marker,
            'data-editorial-version="v4-semantic" '
            'data-production-deploy-eligible="true"',
            1,
        )
        rendered = rendered.replace(
            "</head>",
            f'<meta name="abm-release-id" content="{release_id}">'
            f'<meta name="abm-release-contract" content="{release_schema}">\n</head>',
            1,
        )
    return rendered


def _render_additive_report(
    formal_html: str,
    *,
    payload: Mapping[str, Any],
    prompt_model_presentation: _PromptModelPresentation,
    stage_facts: _ProductionPresentationFacts | None = None,
) -> str:
    if formal_html.count("</head>") != 1 or formal_html.count("</body>") != 1:
        raise _RobustnessReportClosureError("historical report renderer did not return one closed HTML document")
    insertion_marker = '<aside id="trace-drawer"'
    if formal_html.count(insertion_marker) != 1:
        raise _RobustnessReportClosureError("historical Editorial shell does not expose the private composition marker")
    presentation_catalog = _presentation_catalog(prompt_model_presentation)
    project_diagram_html = _project_evidence_chain_diagram(presentation_catalog)
    batch_diagram_html = _batch_mechanism_diagram(presentation_catalog)
    overview_figure_marker = '<figure class="editorial-figure editorial-figure-overview"'
    ranking_figure_marker = '<figure class="editorial-figure editorial-figure-exposure-ranking"'
    if formal_html.count(overview_figure_marker) != 1 or formal_html.count(ranking_figure_marker) != 1:
        raise _RobustnessReportClosureError(
            "historical Editorial shell does not expose one overview and ranking presentation marker"
        )
    section_html = _robustness_sections(
        payload,
        prompt_model_presentation=prompt_model_presentation,
        stage_facts=stage_facts,
    )
    head_addition = f"<style>{_ROBUSTNESS_CSS}</style>\n"
    if stage_facts is not None:
        head_addition += (
            f'<meta name="abm-release-contract" content="{_escape(stage_facts.release_contract_schema, quote=True)}">'
            f'<meta name="abm-release-id" content="{_escape(stage_facts.release_id, quote=True)}">'
        )
    stage_test_id = (
        "robustness-report-release" if stage_facts is not None else "robustness-report-candidate"
    )
    prompt_catalog_json = json.dumps(
        presentation_catalog,
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    script = (
        _ROBUSTNESS_SCRIPT.replace("__REPORT_STAGE_TEST_ID__", stage_test_id)
        .replace("__PROMPT_PRESENTATION_CATALOG__", prompt_catalog_json)
    )
    expected_trace_rows = _strict_positive_int(
        payload.get("trace_row_count"),
        "report trace row count",
    )
    if (
        stage_facts is not None
        and stage_facts.release_contract_schema
        in {"abm-report-release-contract-v6", "abm-report-release-contract-v7"}
        and expected_trace_rows != _TRACE_ROW_COUNT
    ):
        raise _RobustnessReportClosureError(
            "v6/v7 production presentation requires exactly 1,800 trace rows"
        )
    rendered = _replace_trace_script(
        formal_html,
        expected_row_count=expected_trace_rows,
    )
    rendered = _defer_editorial_runtime(rendered).replace(
        "__TRACE_ROW_COUNT__",
        str(expected_trace_rows),
    )
    trace_section_marker = 'data-section-anchor="llm-decision" data-testid="run-llm-decision-section" tabindex="-1"'
    if rendered.count(trace_section_marker) != 1:
        raise _RobustnessReportClosureError("composed report must contain one trace section")
    rendered = rendered.replace(
        trace_section_marker,
        f'{trace_section_marker} data-trace-state="loading"',
        1,
    )
    trace_tool_marker = '<div class="editorial-trace-tool" data-testid="run-trace-tool">'
    if rendered.count(trace_tool_marker) != 1:
        raise _RobustnessReportClosureError("composed report must contain one trace tool")
    rendered = rendered.replace(
        trace_tool_marker,
        trace_tool_marker
        + '<p data-testid="run-trace-state" data-trace-state="loading" role="status" aria-live="polite" aria-atomic="true">Loading persisted trace data.</p>',
        1,
    )
    if rendered.count(_TRACE_SCRIPT_OPEN) != 1:
        raise _RobustnessReportClosureError("composed report must contain exactly one trace envelope")
    rendered = rendered.replace(
        overview_figure_marker,
        f"{project_diagram_html}{overview_figure_marker}",
        1,
    )
    rendered = rendered.replace(
        ranking_figure_marker,
        f"{batch_diagram_html}{ranking_figure_marker}",
        1,
    )
    rendered, raster_count = re.subn(
        r'<img\b(?=[^>]*data-testid="mechanism-[^"]+-visual-media")[^>]*>',
        _compatibility_raster_tag,
        rendered,
    )
    if raster_count != 5:
        raise _RobustnessReportClosureError(
            "historical Editorial shell does not expose five compatibility raster images"
        )
    rendered = rendered.replace(
        '<div class="editorial-legend editorial-legend-v2 editorial-legend-v3"',
        '<div class="editorial-legend editorial-legend-v2 editorial-legend-v3 robustness-compatibility-legend" aria-hidden="true"',
    )
    rendered = rendered.replace("</head>", f"{head_addition}</head>", 1)
    rendered = rendered.replace(insertion_marker, f"{section_html}\n        {insertion_marker}", 1)
    rendered = rendered.replace("</body>", f"<script>{script}</script>\n</body>", 1)
    return rendered


def _robustness_sections(
    payload: Mapping[str, Any],
    *,
    prompt_model_presentation: _PromptModelPresentation,
    stage_facts: _ProductionPresentationFacts | None = None,
    semantic_catalog: Mapping[str, Mapping[str, str]] | None = None,
) -> str:
    if stage_facts is None:
        stage_test_id = "robustness-report-candidate"
        stage_attribute = ""
        eligibility = "false"
        download_scope = "candidate"
    else:
        stage_test_id = "robustness-report-release"
        stage_attribute = f' data-release-id="{_escape(stage_facts.release_id, quote=True)}"'
        eligibility = "true"
        download_scope = "production release"
    lineage = _mapping(payload["source_lineage"], "source lineage")
    formal = _mapping(lineage["formal"], "Formal source")
    study = _mapping(lineage["study"], "study source")
    ranking = _mapping(payload["ranking_weight"], "ranking report")
    prompt_model = _mapping(payload["prompt_model"], "Prompt–Model report")
    downloads = _string_mapping(payload["downloads"], "report downloads")
    weight_messages = _object_sequence(ranking["message_summary_rows"], "weight message rows")
    weight_batches = _object_sequence(ranking["batch_diagnostic_rows"], "weight batch rows")
    shared_seed = _object_sequence(prompt_model["shared_seed_rows"], "shared-seed rows")
    prompt_messages = _object_sequence(prompt_model["message_summary_rows"], "Prompt message rows")
    trajectories = _object_sequence(prompt_model["trajectory_rows"], "Prompt trajectory rows")
    growth = _object_sequence(prompt_model["campaign_growth_rows"], "Prompt growth rows")
    thresholds = _object_sequence(prompt_model["practical_threshold_rows"], "threshold rows")
    message_ids = list(dict.fromkeys(str(row["message_id"]) for row in weight_messages))
    models = list(dict.fromkeys(str(row["requested_model"]) for row in prompt_messages))
    semantic = semantic_catalog is not None
    prompt_catalog = semantic_catalog or _presentation_catalog(prompt_model_presentation)

    def localized(key: str, fallback: str) -> str:
        return _robustness_i18n(prompt_catalog, key) if semantic else fallback

    def stable(value: object, *, tag: str = "span") -> str:
        escaped = _escape(value)
        return f'<{tag} data-stable-token="true">{escaped}</{tag}>' if semantic else escaped

    def stable_element(value: object, tag: str, token: str) -> str:
        marker = f' data-stable-token="{_escape(token, quote=True)}"' if semantic else ""
        return f"<{tag}{marker}>{_escape(value)}</{tag}>"

    def row_summary(key: str, fallback: str, count: int) -> str:
        if not semantic:
            return f"{fallback} · {count} rows"
        return (
            f'{_robustness_i18n(prompt_catalog, key)}: '
            f'<span data-stable-token="row-count">{count}</span> '
            f'{_robustness_i18n(prompt_catalog, "semantic.common.rows")}'
        )

    prompt_contract_html = _prompt_contract_disclosure(
        prompt_model_presentation,
        prompt_catalog,
        stable_tokens=semantic,
    )
    prompt_factorial_html = _prompt_model_factorial_diagram(prompt_model_presentation, prompt_catalog)
    prompt_title_html = _robustness_i18n(
        prompt_catalog,
        "prompt.title",
        tag="h2",
        attrs=' id="prompt-model-title"',
    )

    family_pairs = [
        ("network-feedback", "base_network_relevance", "campaign_engaged_neighbor_signal"),
        ("network-fit", "base_network_relevance", "normalized_message_user_fit"),
        ("feedback-fit", "campaign_engaged_neighbor_signal", "normalized_message_user_fit"),
    ]
    if semantic:
        semantic_family_options: list[str] = []
        for family_id, _left, _right in family_pairs:
            family_key = f'semantic.weight.family.{family_id.replace("-", "_")}'
            semantic_family_options.append(
                f'<option value="{_escape(family_id, quote=True)}" '
                f'data-robustness-i18n="{family_key}">'
                f'{_escape(prompt_catalog["zh-CN"][family_key])}</option>'
            )
        family_options = "".join(semantic_family_options)
    else:
        family_options = "".join(
            f'<option value="{_escape(family_id, quote=True)}">{_escape(_COMPONENT_LABELS[left])} ↔ {_escape(_COMPONENT_LABELS[right])}</option>'
            for family_id, left, right in family_pairs
        )
    weight_cards: list[str] = []
    for message_id in message_ids:
        family_views: list[str] = []
        for family_index, (family_id, left, right) in enumerate(family_pairs):
            family_scenarios = [
                row
                for row in weight_messages
                if row["message_id"] == message_id
                and {row.get("transfer_from"), row.get("transfer_to")} == {left, right}
            ]
            series: list[dict[str, Any]] = []
            for scenario_index, summary in enumerate(family_scenarios):
                scenario_id = str(summary["scenario_id"])
                batches = sorted(
                    (
                        row
                        for row in weight_batches
                        if row["scenario_id"] == scenario_id and row["message_id"] == message_id
                    ),
                    key=lambda row: int(row["time_step"]),
                )
                if semantic:
                    direction = f"{summary['transfer_from']} -> {summary['transfer_to']}"
                    series_label = f"{direction}: {_display(summary['transfer_mass'])}"
                else:
                    direction = f"{_COMPONENT_LABELS[str(summary['transfer_from'])]} → {_COMPONENT_LABELS[str(summary['transfer_to'])]}"
                    series_label = f"{direction} · {_display(summary['transfer_mass'])}"
                series.append(
                    {
                        "series_id": scenario_id,
                        "label": series_label,
                        "values": [float(row["jaccard_distance"]) for row in batches],
                        "style": _SERIES_STYLES[scenario_index],
                    }
                )
            chart_id = f"weight-{message_id}-{family_id}"
            family_views.append(
                f'<div class="robustness-weight-family" data-weight-family="{family_id}"{"" if family_index == 0 else " hidden"}>'
                f'{_line_chart(chart_id=chart_id, title=f"{message_id} · Top K Jaccard distance", series=series, y_max=1.0, semantic_catalog=prompt_catalog if semantic else None, title_key="semantic.weight.chart.title" if semantic else None, stable_labels=semantic)}'
                "</div>"
            )
        weight_cards.append(
            f'<article class="robustness-message-panel" data-testid="ranking-weight-panel-{_escape(message_id, quote=True)}">'
            f'<header><h3>{stable(message_id)}</h3><p>{localized("semantic.weight.panel.note", "Top K Jaccard distance by frozen batch. Rank movement remains available in the exact-value table.")}</p></header>'
            f'{"".join(family_views)}</article>'
        )

    message_options = "".join(
        f'<option value="{_escape(message, quote=True)}" data-stable-token="true">{_escape(message)}</option>'
        if semantic
        else f'<option value="{_escape(message, quote=True)}">{_escape(message)}</option>'
        for message in message_ids
    )
    prompt_views: list[str] = []
    metric_specs = (
        ("engagement", "cumulative_exposure_engagement_rate", "Cumulative exposure engagement rate", 1.0),
        ("audience", "cumulative_audience_jaccard_distance_from_baseline_cell", "Cumulative audience Jaccard distance", 1.0),
    )
    for message_index, message_id in enumerate(message_ids):
        for metric_index, (metric_id, field, label, y_max) in enumerate(metric_specs):
            model_cards: list[str] = []
            for model in models:
                model_series: list[dict[str, Any]] = []
                for prompt in ("P0", "P1", "P2", "P3"):
                    rows = sorted(
                        (
                            row
                            for row in trajectories
                            if row["message_id"] == message_id
                            and row["requested_model"] == model
                            and row["prompt_variant"] == prompt
                        ),
                        key=lambda row: int(row["time_step"]),
                    )
                    model_series.append(
                        {
                            "series_id": f"{message_id}-{metric_id}-{model}-{prompt}",
                            "label": prompt,
                            "values": [float(row[field]) for row in rows],
                            "style": _PROMPT_STYLES[prompt],
                            "disclosure_id": f"prompt-contract-row-{prompt.lower()}",
                        }
                    )
                chart_id = f"prompt-{message_id}-{metric_id}-{_safe_id(model)}"
                model_cards.append(
                    f'<article class="robustness-model-panel" data-testid="prompt-model-panel-{_safe_id(message_id)}-{_safe_id(model)}-{metric_id}">'
                    f'<header><h4>{stable(model)}</h4>{_robustness_i18n(prompt_catalog, "prompt.panel_note", tag="p")}</header>'
                    f'{_line_chart(chart_id=chart_id, title=f"{model} · {label}", series=model_series, y_max=y_max, semantic_catalog=prompt_catalog if semantic else None, title_key=f"semantic.prompt.metric.{metric_id}" if semantic else None, stable_labels=semantic)}'
                    "</article>"
                )
            hidden = "" if message_index == 0 and metric_index == 0 else " hidden"
            prompt_views.append(
                f'<div class="robustness-model-grid" data-prompt-view="{_escape(message_id, quote=True)}|{metric_id}"{hidden}>'
                f'{"".join(model_cards)}</div>'
            )

    growth_cards: list[str] = []
    growth_max = max((int(row["cumulative_campaign_deduplicated_positive_user_count"]) for row in growth), default=1)
    for model in models:
        series = []
        for prompt in ("P0", "P1", "P2", "P3"):
            rows = sorted(
                (
                    row
                    for row in growth
                    if row["requested_model"] == model and row["prompt_variant"] == prompt
                ),
                key=lambda row: int(row["time_step"]),
            )
            series.append(
                {
                    "series_id": f"growth-{model}-{prompt}",
                    "label": prompt,
                    "values": [float(row["cumulative_campaign_deduplicated_positive_user_count"]) for row in rows],
                    "style": _PROMPT_STYLES[prompt],
                    "disclosure_id": f"prompt-contract-row-{prompt.lower()}",
                }
            )
        growth_cards.append(
            f'<article class="robustness-model-panel" data-testid="prompt-model-growth-panel-{_safe_id(model)}">'
            f'<header><h4>{stable(model)}</h4><p>{localized("semantic.prompt.growth.panel", "Campaign-deduplicated successful Primary-positive users.")}</p></header>'
            f'{_line_chart(chart_id=f"growth-{_safe_id(model)}", title=f"{model} · campaign growth", series=series, y_max=float(max(1, growth_max)), semantic_catalog=prompt_catalog if semantic else None, title_key="semantic.prompt.growth.title" if semantic else None, stable_labels=semantic)}'
            "</article>"
        )

    threshold_counts: dict[str, int] = defaultdict(int)
    for row in thresholds:
        threshold_counts[str(row["classification"])] += 1
    meaningful = threshold_counts["practically_meaningful"]
    small = threshold_counts["small_observed_difference"]
    if semantic:
        download_links = "".join(
            f'<a class="robustness-download" data-testid="robustness-download-{_safe_id(key)}" href="{_escape(path, quote=True)}">'
            f'<span data-stable-token="download-key">{_escape(key)}</span>'
            f'<code data-stable-token="artifact-filename">{_escape(path)}</code></a>'
            for key, path in downloads.items()
        )
    else:
        download_links = "".join(
            f'<a class="robustness-download" data-testid="robustness-download-{_safe_id(key)}" href="{_escape(path, quote=True)}"><span>{_escape(key.replace("_", " ").title())}</span><code>{_escape(path)}</code></a>'
            for key, path in downloads.items()
        )

    eligibility_marker = ' data-stable-token="schema-value"' if semantic else ""
    metric_options = (
        f'<option value="engagement" data-robustness-i18n="semantic.prompt.metric.engagement">{_escape(prompt_catalog["zh-CN"]["semantic.prompt.metric.engagement"])}</option>'
        f'<option value="audience" data-robustness-i18n="semantic.prompt.metric.audience">{_escape(prompt_catalog["zh-CN"]["semantic.prompt.metric.audience"])}</option>'
        if semantic
        else '<option value="engagement">Engagement rate</option><option value="audience">Audience distance</option>'
    )

    return f"""
        <section id="robustness-evidence" class="robustness-report" data-testid="{stage_test_id}"{stage_attribute} aria-labelledby="robustness-title">
          <div class="robustness-hero">
            <p class="robustness-kicker">{localized("semantic.hero.kicker", "Additive evidence · 增量证据")}</p>
            <h2 id="robustness-title">{localized("semantic.hero.title", "Ranking policy and Prompt–Model robustness, without relabelling the historical run")}</h2>
            <p>{localized("semantic.hero.lead", "One fixed sample, one fixed graph, and one realized path per cell. These descriptive comparisons use no ground truth and make no causal, Calibration, or statistical-equivalence claim.")}</p>
            <code data-testid="robustness-production-eligibility"{eligibility_marker}>production_deploy_eligible={eligibility}</code>
          </div>
          <div class="robustness-lineage" data-testid="robustness-source-lineage">
            <article data-source-kind="formal">
              <span>{localized("semantic.lineage.formal.label", "Historical Concurrent Formal source")}</span>
              {stable_element(formal['source_id'], "strong", "source-id")}
              {stable_element(formal['manifest_sha256'], "code", "sha256")}
              <p>{localized("semantic.lineage.formal.body", "Mechanism, Run Evidence, field lineage, Demographic Shadow comparison, and the Primary + Shadow barrier remain sourced here.")}</p>
            </article>
            <div class="robustness-lineage-arrow" aria-hidden="true">＋</div>
            <article data-source-kind="study">
              <span>{localized("semantic.lineage.study.label", "Immutable complete study root")}</span>
              {stable_element(study['output_identity'], "strong", "source-id")}
              {stable_element(study['root_identity_sha256'], "code", "sha256")}
              <p>{localized("semantic.lineage.study.body", "Ranking Weight and Primary-only 4 Prompt × 4 model evidence. No Shadow condition was rerun.")}</p>
            </article>
          </div>
          <p class="robustness-source-warning" data-testid="robustness-shadow-source-label">{localized("semantic.lineage.shadow_warning", "Demographic Shadow evidence remains bound to the historical Formal source; it is not a factorial Prompt–Model result.")}</p>

          <section class="robustness-section" data-testid="ranking-weight-sensitivity-section" aria-labelledby="ranking-weight-title">
            <div class="robustness-section-heading">
              <div><h2 id="ranking-weight-title">{localized("semantic.weight.title", "Ranking Weight Sensitivity")}</h2><p>{localized("semantic.weight.lead", "19 predeclared simplex points, shown as six-series transfer families rather than one 19-line panel. Candidate sets and feedback stay frozen.")}</p></div>
              <label>{localized("semantic.weight.family.label", "Visible transfer family")}<select data-testid="ranking-weight-family-select" data-weight-family-select>{family_options}</select></label>
            </div>
            <div class="robustness-message-grid">{"".join(weight_cards)}</div>
            <details class="robustness-table-disclosure" data-testid="ranking-weight-exact-table">
              <summary>{row_summary("semantic.weight.message_rows", "Exact message-level Jaccard summaries", len(weight_messages))}</summary>
              {_table(_WEIGHT_MESSAGE_FIELDS, weight_messages, test_id="ranking-weight-message-table", stable_tokens=semantic)}
            </details>
            <details class="robustness-table-disclosure" data-testid="ranking-weight-rank-exact-table">
              <summary>{row_summary("semantic.weight.batch_rows", "Exact per-batch entered/exited and rank movement diagnostics", len(weight_batches))}</summary>
              {_table(_WEIGHT_BATCH_FIELDS, weight_batches, test_id="ranking-weight-batch-table", stable_tokens=semantic)}
            </details>
          </section>

          <section class="robustness-section" data-testid="prompt-model-robustness-section" aria-labelledby="prompt-model-title">
            <div class="robustness-section-heading">
              <div>{prompt_title_html}{_robustness_i18n(prompt_catalog, "prompt.lead", tag="p")}</div>
              <div class="robustness-controls">
                <label>{localized("semantic.prompt.message.label", "Message")}<select data-testid="prompt-model-message-select" data-prompt-message-select>{message_options}</select></label>
                <label>{localized("semantic.prompt.metric.label", "Dynamic metric")}<select data-testid="prompt-model-metric-select" data-prompt-metric-select>{metric_options}</select></label>
              </div>
            </div>
            {prompt_contract_html}
            {prompt_factorial_html}
            <div data-testid="prompt-model-dynamic-panels">{"".join(prompt_views)}</div>
            <div class="robustness-subsection-heading"><h3>{localized("semantic.prompt.shared.title", "Shared-seed direct Decisions")}</h3><p>{localized("semantic.prompt.shared.lead", "Binary engage is primary; probability and confidence are secondary. Rows follow the selected message.")}</p></div>
            <div data-testid="prompt-model-shared-seed-table">{_table(_SHARED_SEED_FIELDS, shared_seed, test_id="shared-seed-exact-table", row_attribute="message_id", stable_tokens=semantic)}</div>
            <div class="robustness-subsection-heading"><h3>{localized("semantic.prompt.growth.title", "Campaign-level positive-user growth")}</h3><p>{localized("semantic.prompt.growth.lead", "Growth is campaign-deduplicated across messages, so it is kept outside message panels rather than mislabelled as a message-specific outcome.")}</p></div>
            <div class="robustness-model-grid" data-testid="prompt-model-growth-panels">{"".join(growth_cards)}</div>
            <div class="robustness-threshold-summary" data-testid="practical-threshold-summary">
              <article>{stable_element(meaningful, "strong", "count")}<span>{localized("semantic.threshold.meaningful", "practically meaningful")}</span></article>
              <article>{stable_element(small, "strong", "count")}<span>{localized("semantic.threshold.small", "small_observed_difference")}</span></article>
              <p>{localized("semantic.threshold.note", "Below-threshold values are small observed differences only; they do not establish equivalence.")}</p>
            </div>
            <details class="robustness-table-disclosure" data-testid="prompt-model-message-exact-table">
              <summary>{row_summary("semantic.prompt.message_rows", "Exact per-message dynamic summaries", len(prompt_messages))}</summary>
              {_table(_PROMPT_MESSAGE_FIELDS, prompt_messages, test_id="prompt-model-message-table", stable_tokens=semantic)}
            </details>
            <details class="robustness-table-disclosure" data-testid="practical-threshold-exact-table">
              <summary>{row_summary("semantic.prompt.threshold_rows", "Exact practical-threshold classifications", len(thresholds))}</summary>
              {_table(_THRESHOLD_FIELDS, thresholds, test_id="threshold-table", stable_tokens=semantic)}
            </details>
          </section>

          <section class="robustness-section robustness-downloads" data-testid="robustness-downloads-section" aria-labelledby="robustness-downloads-title">
            <div class="robustness-section-heading"><div><h2 id="robustness-downloads-title">{localized("semantic.downloads.title", "Approved robustness downloads")}</h2><p>{localized("semantic.downloads.lead", f"Companion JSON and CSV files close to the schemas, row counts, hashes, and exact values in this {download_scope}. No raw Prompt, Provider payload, response, or credential is included.")}</p></div></div>
            <div class="robustness-download-grid">{download_links}</div>
          </section>
        </section>
    """


def _line_chart(
    *,
    chart_id: str,
    title: str,
    series: Sequence[Mapping[str, Any]],
    y_max: float,
    semantic_catalog: Mapping[str, Mapping[str, str]] | None = None,
    title_key: str | None = None,
    stable_labels: bool = False,
) -> str:
    width, height = 760.0, 238.0
    left, right, top, bottom = 54.0, 18.0, 22.0, 38.0
    plot_width = width - left - right
    plot_height = height - top - bottom
    max_points = max((len(_sequence(row["values"], "chart values")) for row in series), default=1)
    denominator = max(1, max_points - 1)
    safe_y_max = max(float(y_max), 1e-12)
    grid: list[str] = []
    for index in range(5):
        fraction = index / 4
        y = top + plot_height * (1.0 - fraction)
        label = _display(safe_y_max * fraction)
        stable_marker = ' data-stable-token="axis-value"' if stable_labels else ""
        grid.append(
            f'<line x1="{left:.2f}" y1="{y:.2f}" x2="{width - right:.2f}" y2="{y:.2f}" />'
            f'<text{stable_marker} x="{left - 9:.2f}" y="{y + 4:.2f}" text-anchor="end">{_escape(label)}</text>'
        )
    marks: list[str] = []
    legends: list[str] = []
    for row in series:
        values = [float(value) for value in _sequence(row["values"], "chart values")]
        style = _mapping(row["style"], "chart series style")
        disclosure_id = row.get("disclosure_id")
        if disclosure_id is not None and not isinstance(disclosure_id, str):
            raise _RobustnessReportClosureError("chart disclosure identity must be a string")
        points = [
            (
                left + plot_width * index / denominator,
                top + plot_height * (1.0 - min(max(value / safe_y_max, 0.0), 1.0)),
            )
            for index, value in enumerate(values)
        ]
        point_text = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        series_id = str(row["series_id"])
        dash = str(style.get("dash", ""))
        dash_attr = f' stroke-dasharray="{_escape(dash, quote=True)}"' if dash else ""
        marker_markup = "".join(
            _marker(str(style["marker"]), x, y, str(style["color"])) for x, y in points
        )
        disclosure_attribute = (
            f' data-prompt-disclosure-id="{_escape(disclosure_id, quote=True)}"'
            f' aria-describedby="{_escape(disclosure_id, quote=True)}"'
            if disclosure_id is not None
            else ""
        )
        marks.append(
            f'<g data-series-id="{_escape(series_id, quote=True)}"{disclosure_attribute}><polyline points="{point_text}" fill="none" stroke="{_escape(style["color"], quote=True)}" stroke-width="2.6" vector-effect="non-scaling-stroke"{dash_attr}/>{marker_markup}</g>'
        )
        label_marker = ' data-stable-token="series-label"' if stable_labels else ""
        legends.append(
            f'<li class="robustness-legend-item" data-legend-series-id="{_escape(series_id, quote=True)}"{disclosure_attribute}>'
            f'{_legend_sample(style)}<span{label_marker}>{_escape(row["label"])}</span></li>'
        )
    if semantic_catalog is not None:
        if title_key is None:
            raise _RobustnessReportClosureError("semantic chart requires a localized title key")
        title_markup = _robustness_i18n(
            semantic_catalog,
            title_key,
            tag="title",
            attrs=f' id="{_escape(chart_id, quote=True)}-title"',
        )
        axis_markup = _robustness_i18n(
            semantic_catalog,
            "semantic.chart.batch_axis",
            tag="text",
            class_name="robustness-axis-label",
            attrs=f' x="{width / 2:.2f}" y="{height - 7:.2f}" text-anchor="middle"',
        )
        legend_aria = (
            f'aria-label="{_escape(semantic_catalog["zh-CN"]["semantic.chart.series_aria"], quote=True)}" '
            'data-robustness-i18n-aria-label="semantic.chart.series_aria"'
        )
    else:
        title_markup = f'<title id="{_escape(chart_id, quote=True)}-title">{_escape(title)}</title>'
        axis_markup = (
            f'<text class="robustness-axis-label" x="{width / 2:.2f}" '
            f'y="{height - 7:.2f}" text-anchor="middle">Batch index</text>'
        )
        legend_aria = f'aria-label="Visible series for {_escape(title, quote=True)}"'
    return (
        f'<div class="robustness-chart-shell" data-chart-id="{_escape(chart_id, quote=True)}">'
        f'<div class="robustness-chart"><svg viewBox="0 0 {int(width)} {int(height)}" role="img" aria-labelledby="{_escape(chart_id, quote=True)}-title">'
        f'{title_markup}'
        f'<g class="robustness-grid">{"".join(grid)}</g><g class="robustness-series">{"".join(marks)}</g>'
        f'{axis_markup}'
        "</svg></div>"
        f'<ul class="robustness-legend" {legend_aria}>{"".join(legends)}</ul>'
        "</div>"
    )


def _marker(marker: str, x: float, y: float, color: str) -> str:
    escaped_color = _escape(color, quote=True)
    if marker == "circle":
        return f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3.6" fill="{escaped_color}"/>'
    if marker == "square":
        return f'<rect x="{x - 3.5:.2f}" y="{y - 3.5:.2f}" width="7" height="7" fill="{escaped_color}"/>'
    if marker == "triangle":
        return f'<polygon points="{x:.2f},{y - 4.4:.2f} {x - 4.2:.2f},{y + 3.5:.2f} {x + 4.2:.2f},{y + 3.5:.2f}" fill="{escaped_color}"/>'
    if marker == "diamond":
        return f'<polygon points="{x:.2f},{y - 4.4:.2f} {x - 4.4:.2f},{y:.2f} {x:.2f},{y + 4.4:.2f} {x + 4.4:.2f},{y:.2f}" fill="{escaped_color}"/>'
    if marker == "cross":
        return f'<path d="M{x - 3.5:.2f},{y - 3.5:.2f} L{x + 3.5:.2f},{y + 3.5:.2f} M{x + 3.5:.2f},{y - 3.5:.2f} L{x - 3.5:.2f},{y + 3.5:.2f}" stroke="{escaped_color}" stroke-width="2"/>'
    return f'<path d="M{x - 4:.2f},{y:.2f} H{x + 4:.2f} M{x:.2f},{y - 4:.2f} V{y + 4:.2f}" stroke="{escaped_color}" stroke-width="2"/>'


def _legend_sample(style: Mapping[str, Any]) -> str:
    dash = str(style.get("dash", ""))
    dash_attr = f' stroke-dasharray="{_escape(dash, quote=True)}"' if dash else ""
    color = str(style["color"])
    return (
        '<svg class="robustness-legend-sample" viewBox="0 0 52 16" aria-hidden="true">'
        f'<line x1="2" y1="8" x2="50" y2="8" stroke="{_escape(color, quote=True)}" stroke-width="2.4"{dash_attr}/>'
        f'{_marker(str(style["marker"]), 26, 8, color)}</svg>'
    )


def _table(
    fields: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    *,
    test_id: str,
    row_attribute: str | None = None,
    stable_tokens: bool = False,
) -> str:
    heading_marker = ' data-stable-token="field-name"' if stable_tokens else ""
    headings = "".join(
        f'<th scope="col"{heading_marker}>{_escape(field.replace("_", " "))}</th>'
        for field in fields
    )
    body: list[str] = []
    for row in rows:
        attribute = ""
        if row_attribute is not None:
            attribute = f' data-row-{row_attribute.replace("_", "-")}="{_escape(row.get(row_attribute), quote=True)}"'
        cell_marker = ' data-stable-token="persisted-value"' if stable_tokens else ""
        cells = "".join(
            f"<td{cell_marker}>{_escape(_display(row.get(field)))}</td>" for field in fields
        )
        body.append(f"<tr{attribute}>{cells}</tr>")
    return (
        '<div class="robustness-table-wrap">'
        f'<table data-testid="{_escape(test_id, quote=True)}"><thead><tr>{headings}</tr></thead><tbody>{"".join(body)}</tbody></table>'
        "</div>"
    )


def _assert_formal_unchanged(
    closure: ConcurrentMessageArtifactClosure,
    expected_hashes: Mapping[str, str],
) -> None:
    actual_files: set[str] = set()
    for path in closure.run_dir.rglob("*"):
        relative = path.relative_to(closure.run_dir).as_posix()
        if path.is_symlink():
            raise _RobustnessReportClosureError("historical Formal source changed during report composition")
        if path.is_file():
            actual_files.add(relative)
        elif not path.is_dir():
            raise _RobustnessReportClosureError("historical Formal source changed during report composition")
    if actual_files != set(expected_hashes):
        raise _RobustnessReportClosureError("historical Formal source artifact set changed")
    if {path: _sha256_file(closure.run_dir / path) for path in expected_hashes} != dict(expected_hashes):
        raise _RobustnessReportClosureError("historical Formal source artifact hashes changed")


def _assert_study_unchanged(study: _ClosedStudy, expected_hashes: Mapping[str, str]) -> None:
    entries = list(study.root.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise _RobustnessReportClosureError("immutable study root changed during report composition")
    if {path.name for path in entries} != set(expected_hashes):
        raise _RobustnessReportClosureError("immutable study root artifact set changed")
    if {path.name: _sha256_file(path) for path in entries} != dict(expected_hashes):
        raise _RobustnessReportClosureError("immutable study root artifact hashes changed")


def _csv_bytes(fields: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(fields), lineterminator="\n", extrasaction="raise")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: _csv_value(row.get(field)) for field in fields})
    return stream.getvalue().encode("utf-8")


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return _display(value)
    return value


def _display(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _RobustnessReportClosureError("report values must be finite")
        return format(value, ".12g")
    return str(value)


def _round(value: float) -> float:
    rounded = round(value, 12)
    return 0.0 if rounded == 0.0 else rounded


def _safe_id(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", str(value)).strip("-")


def _escape(value: object, *, quote: bool = False) -> str:
    return html.escape(str(value), quote=quote)


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return {str(key): item for key, item in value.items()}


def _strict_positive_int(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive strict integer")
    return value


def _sequence(value: object, label: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{label} must be a list")
    return list(value)


def _object_sequence(value: object, label: str) -> list[dict[str, Any]]:
    rows = _sequence(value, label)
    if any(not isinstance(row, Mapping) for row in rows):
        raise ValueError(f"{label} must contain objects")
    return [{str(key): item for key, item in row.items()} for row in rows]


def _string_sequence(value: object, label: str) -> list[str]:
    rows = [str(item) for item in _sequence(value, label)]
    if any(not item for item in rows) or len(rows) != len(set(rows)):
        raise ValueError(f"{label} must contain unique strings")
    return rows


def _string_mapping(value: object, label: str) -> dict[str, str]:
    mapping = _mapping(value, label)
    result = {key: str(item) for key, item in mapping.items()}
    if any(not key or not item for key, item in result.items()):
        raise ValueError(f"{label} must contain non-empty strings")
    return result


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain one JSON object")
    return payload


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


_SEMANTIC_ROBUSTNESS_CSS = r"""
.robustness-report .robustness-message-panel,
.robustness-report .robustness-model-panel,
.robustness-report .robustness-chart-shell,
.robustness-report .robustness-legend-item { overflow: hidden; }
.robustness-report [data-stable-token="series-label"] { min-width: 0; overflow-wrap: anywhere; word-break: break-word; }
@media (max-width: 767px) {
  .robustness-report .robustness-factorial-scroll { overflow: hidden; }
  .robustness-report .robustness-factorial-scroll > svg { min-width: 0; }
}
"""


_ROBUSTNESS_CSS = r"""
.robustness-report{--rob-ink:#172033;--rob-muted:#5b6473;--rob-line:#d9dee7;--rob-surface:#f6f8fb;--rob-accent:#155e75;color:var(--rob-ink);background:#fbfcfe;border-top:1px solid var(--rob-line);padding:clamp(4rem,8vw,8rem) max(1rem,calc((100vw - 1320px)/2));font-family:inherit}
.robustness-report *{box-sizing:border-box}.robustness-report [hidden]{display:none!important}.robustness-hero{max-width:980px}.robustness-kicker{font-size:.78rem;font-weight:700;letter-spacing:.13em;text-transform:uppercase;color:var(--rob-accent);margin:0 0 1rem}.robustness-hero h2{font-size:clamp(2rem,4.4vw,4.6rem);line-height:1.02;letter-spacing:-.045em;max-width:16ch;margin:0}.robustness-hero>p:not(.robustness-kicker){max-width:72ch;color:var(--rob-muted);font-size:1.05rem;line-height:1.65;margin:1.5rem 0}.robustness-hero>code{display:inline-block;border:1px solid var(--rob-line);background:white;padding:.55rem .75rem;border-radius:.35rem;color:#8a341f}
.robustness-lineage{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);gap:1rem;align-items:stretch;margin:3rem 0 1rem}.robustness-lineage article{border-top:3px solid var(--rob-accent);background:white;padding:1.35rem;min-width:0}.robustness-lineage article span{display:block;color:var(--rob-muted);font-size:.8rem;text-transform:uppercase;letter-spacing:.08em}.robustness-lineage article strong{display:block;font-size:1.15rem;margin:.55rem 0}.robustness-lineage article code{display:block;overflow-wrap:anywhere;font-size:.74rem;color:var(--rob-muted)}.robustness-lineage article p{line-height:1.55;margin:1rem 0 0}.robustness-lineage-arrow{align-self:center;font-size:2rem;color:var(--rob-muted)}.robustness-source-warning{border-left:4px solid #b45309;background:#fff8eb;padding:1rem 1.2rem;line-height:1.55;margin:0 0 6rem}
.robustness-section{padding:5rem 0;border-top:1px solid var(--rob-line)}.robustness-section-heading{display:flex;align-items:end;justify-content:space-between;gap:2rem;margin-bottom:2rem}.robustness-section-heading>div:first-child{max-width:820px}.robustness-section h2{font-size:clamp(1.8rem,3vw,3.2rem);letter-spacing:-.035em;margin:0 0 .8rem}.robustness-section-heading p,.robustness-subsection-heading p{color:var(--rob-muted);line-height:1.6;margin:0;max-width:72ch}.robustness-section label{display:grid;gap:.45rem;color:var(--rob-muted);font-size:.78rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase}.robustness-section select{min-width:14rem;background:white;border:1px solid #aeb7c5;border-radius:.35rem;padding:.72rem 2.2rem .72rem .75rem;color:var(--rob-ink);font:inherit;text-transform:none;letter-spacing:0}.robustness-section select:focus-visible,.robustness-download:focus-visible,.robustness-table-disclosure summary:focus-visible{outline:3px solid rgba(21,94,117,.32);outline-offset:3px}
.robustness-message-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem}.robustness-message-panel,.robustness-model-panel{min-width:0;background:white;border-top:2px solid #aeb7c5;padding:1.1rem}.robustness-message-panel header,.robustness-model-panel header{min-height:4.7rem}.robustness-message-panel h3,.robustness-model-panel h4{margin:0 0 .35rem;font-size:1rem}.robustness-message-panel p,.robustness-model-panel p{margin:0;color:var(--rob-muted);font-size:.82rem;line-height:1.45}.robustness-chart-shell{display:grid;grid-template-columns:minmax(0,1fr) minmax(8.5rem,.38fr);gap:.8rem;align-items:start;margin-top:1rem}.robustness-chart{min-width:0}.robustness-chart svg{display:block;width:100%;height:auto;aspect-ratio:3.2/1;background:var(--rob-surface);overflow:visible}.robustness-grid line{stroke:#dce2ea;stroke-width:1}.robustness-grid text,.robustness-axis-label{fill:#697386;font-size:11px}.robustness-legend{list-style:none;margin:0;padding:0;display:grid;gap:.35rem}.robustness-legend-item{width:100%;display:grid;grid-template-columns:52px minmax(0,1fr);align-items:center;gap:.45rem;padding:.28rem;color:var(--rob-ink);font-size:.7rem;line-height:1.25}.robustness-legend-sample{display:block;width:52px;height:16px}.robustness-model-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}.robustness-controls{display:flex;gap:1rem;flex-wrap:wrap}.robustness-subsection-heading{margin:4rem 0 1.2rem}.robustness-subsection-heading h3{font-size:1.45rem;margin:0 0 .45rem}
.robustness-prompt-contract{margin:1rem 0 5rem;padding:2rem;border:1px solid var(--rob-line);background:#f7fafc}.robustness-contract-heading{display:grid;gap:.6rem;max-width:820px}.robustness-contract-heading h3{font-size:1.65rem;letter-spacing:-.02em;margin:0}.robustness-contract-heading p,.robustness-dimension-note{color:var(--rob-muted);line-height:1.6;margin:0}.robustness-denominator-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px;margin:2rem 0 1rem;background:var(--rob-line);border:1px solid var(--rob-line)}.robustness-denominator-grid article{display:grid;gap:.55rem;padding:1.25rem;background:white}.robustness-denominator-grid strong{font-size:1.12rem;line-height:1.35}.robustness-denominator-grid span{color:var(--rob-muted);font-size:.78rem}.robustness-prompt-contract-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1rem;margin:2.25rem 0}.robustness-prompt-contract-row{min-width:0;padding:1rem;border-top:4px solid var(--rob-accent);background:white}.robustness-prompt-contract-row:nth-child(2){border-top-color:#b45309}.robustness-prompt-contract-row:nth-child(3){border-top-color:#4d7c0f}.robustness-prompt-contract-row:nth-child(4){border-top-color:#7c3aed}.robustness-prompt-contract-row header{display:grid;gap:.75rem}.robustness-prompt-contract-row header>p,.robustness-prompt-model-note{color:var(--rob-muted);font-size:.78rem;line-height:1.55;margin:0}.robustness-prompt-identity{display:grid;grid-template-columns:52px auto minmax(0,1fr);gap:.5rem;align-items:center}.robustness-prompt-identity strong{font-size:1.25rem}.robustness-prompt-change{font-size:.72rem;font-weight:700;overflow-wrap:anywhere}.robustness-prompt-details{margin-top:1rem;border-top:1px solid var(--rob-line)}.robustness-prompt-details>summary{cursor:pointer;padding:.8rem 0;color:var(--rob-accent);font-size:.76rem;font-weight:700}.robustness-prompt-details>summary:focus-visible{outline:3px solid rgba(21,94,117,.32);outline-offset:3px}.robustness-prompt-token{margin:.4rem 0 .8rem}.robustness-prompt-token dt{color:var(--rob-muted);font-size:.68rem}.robustness-prompt-token dd{margin:.35rem 0 0}.robustness-prompt-token code,.robustness-prompt-hash code{display:block;color:var(--rob-ink);font-size:.68rem;overflow-wrap:anywhere}.robustness-prompt-hash{display:grid;gap:.4rem;margin:.8rem 0}.robustness-prompt-hash strong{color:var(--rob-muted);font-size:.7rem}.robustness-shared-contract{border-top:1px solid var(--rob-line);background:white}.robustness-shared-contract>summary{cursor:pointer;padding:1rem;font-weight:700}.robustness-shared-contract>p{color:var(--rob-muted);line-height:1.6;margin:0;padding:0 1rem 1rem}.robustness-shared-contract-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;background:var(--rob-line);border-top:1px solid var(--rob-line)}.robustness-shared-contract-grid section{min-width:0;padding:1rem;background:white}.robustness-shared-contract-grid h4{font-size:.9rem;margin:0 0 .75rem}.robustness-shared-contract-grid ul{display:grid;gap:.45rem;margin:0;padding:0;list-style:none}.robustness-shared-contract-grid li{min-width:0}.robustness-shared-contract-grid code,.robustness-output-contract code{font-size:.68rem;overflow-wrap:anywhere}.robustness-output-contract{display:grid;gap:.8rem;margin:1rem 0 0}.robustness-output-contract dt{color:var(--rob-muted);font-size:.7rem}.robustness-output-contract dd{margin:.25rem 0 0}.robustness-factorial-scope{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem;margin-top:1.5rem}.robustness-factorial-scope article{padding-top:1rem;border-top:2px solid var(--rob-line)}.robustness-factorial-scope h4{margin:0 0 .45rem;font-size:.9rem}.robustness-factorial-scope p{color:var(--rob-muted);font-size:.78rem;line-height:1.55;margin:0}
.robustness-reader-diagram{margin:3rem 0 4rem;padding-top:1px;color:#172033}.robustness-reader-heading{display:grid;gap:.65rem;max-width:840px;margin-bottom:1.4rem}.robustness-reader-heading h2{font-size:clamp(1.7rem,3vw,2.7rem);letter-spacing:-.035em;line-height:1.05;margin:0}.robustness-reader-heading p{max-width:72ch;color:#5b6473;line-height:1.65;margin:0}.robustness-reader-figure{margin:0}.robustness-reader-scroll{max-width:100%;overflow:auto;border:1px solid #d9dee7;background:#f7fafc}.robustness-reader-scroll:focus-visible{outline:3px solid rgba(21,94,117,.32);outline-offset:3px}.robustness-reader-scroll>svg{display:block;width:100%;min-width:1080px;height:auto}.robustness-semantic-edge{fill:none;stroke:#536174;stroke-width:2.2}.robustness-semantic-edge-dotted{stroke-dasharray:8 7}.robustness-semantic-edges marker path{fill:#536174;stroke:none}.robustness-semantic-node rect{fill:#fff;stroke:#aeb7c5;stroke-width:1.6}.robustness-semantic-node-runtime rect,.robustness-semantic-node-adapter rect{fill:#eef4ff;stroke:#175cd3}.robustness-semantic-node-evidence rect,.robustness-semantic-node-study rect{fill:#edf7f2;stroke:#00875a}.robustness-semantic-node-analysis rect{fill:#fff8eb;stroke:#c76a00}.robustness-semantic-node-ranking rect,.robustness-semantic-node-seed rect,.robustness-semantic-node-next rect{fill:#eef4ff;stroke:#175cd3}.robustness-semantic-node-exposure rect,.robustness-semantic-node-decision rect,.robustness-semantic-node-feedback rect{fill:#edf7f2;stroke:#00875a}.robustness-semantic-node-shadow rect,.robustness-semantic-node-mode rect{fill:#f3f1f8;stroke:#635b8a}.robustness-semantic-node-gate rect,.robustness-semantic-node-terminal rect,.robustness-semantic-node-barrier rect,.robustness-semantic-node-commit rect{fill:#fff8eb;stroke:#c76a00}.robustness-semantic-node-stop rect{fill:#f1f4f8;stroke:#687386}.robustness-semantic-node-report rect,.robustness-semantic-node-release rect,.robustness-semantic-node-canonical rect{fill:#f1f4f8;stroke:#163456}.robustness-semantic-node-label{display:flex;align-items:center;justify-content:center;width:100%;height:100%;padding:0 2px;color:#172033;font:650 15px/1.28 system-ui,-apple-system,sans-serif;text-align:center;overflow-wrap:anywhere;white-space:pre-line}.robustness-semantic-edge-label-box{overflow:visible}.robustness-semantic-edge-label{display:flex;align-items:center;justify-content:center;width:100%;height:100%;padding:2px 5px;border:1px solid #d9dee7;background:#fbfcfe;color:#465164;font:600 11px/1.2 system-ui,-apple-system,sans-serif;text-align:center}.robustness-semantic-legend{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;margin:0;padding:1px;background:#d9dee7;list-style:none}.robustness-semantic-legend-four{grid-template-columns:repeat(4,minmax(0,1fr))}.robustness-semantic-legend-item{display:grid;grid-template-columns:48px minmax(0,1fr);align-items:center;gap:.7rem;min-width:0;padding:.8rem 1rem;background:#fff;font-size:.8rem;font-weight:650}.robustness-semantic-legend-swatch{display:block;width:44px;height:12px;border-top:3px solid #175cd3}.robustness-semantic-legend-swatch-evidence{height:18px;border:2px solid #00875a;background:#edf7f2}.robustness-semantic-legend-swatch-release{height:18px;border:2px solid #163456;background:#f1f4f8}.robustness-semantic-legend-swatch-ranking{height:18px;border:2px solid #175cd3;background:#eef4ff}.robustness-semantic-legend-swatch-required{border-top-color:#536174}.robustness-semantic-legend-swatch-shadow{border-top:3px dashed #635b8a}.robustness-semantic-legend-swatch-next{border-top:3px solid #c76a00}.robustness-reader-fallback{display:grid;gap:.7rem;padding:1rem;border:1px solid #d9dee7;border-top:0;background:#fff}.robustness-reader-fallback h3{margin:0;font-size:1rem}.robustness-reader-fallback ol{display:grid;gap:.45rem;margin:0;padding-left:1.3rem;color:#5b6473;font-size:.84rem;line-height:1.5}.robustness-factorial{margin:0 0 5rem}.robustness-factorial-figure{margin:0}.robustness-factorial-scroll{max-width:100%;overflow:auto;border:1px solid var(--rob-line);background:#f7fafc}.robustness-factorial-scroll:focus-visible{outline:3px solid rgba(21,94,117,.32);outline-offset:3px}.robustness-factorial-scroll>svg{display:block;width:100%;min-width:760px;height:auto}.robustness-factorial-edges path{fill:none;stroke:#687386;stroke-width:2}.robustness-factorial-edges marker path{fill:#687386;stroke:none}.robustness-factorial .robustness-semantic-node-contract rect{fill:#edf5f7;stroke:#155e75}.robustness-factorial .robustness-semantic-node-model rect,.robustness-factorial .robustness-semantic-node-path rect{fill:#f3f1f8;stroke:#635b8a}.robustness-factorial .robustness-semantic-node-result rect{fill:#eff7f1;stroke:#4d7c0f}.robustness-factorial .robustness-semantic-node-metric rect{fill:#fff8eb;stroke:#b45309}.robustness-factorial-fallback{display:grid;gap:.75rem;padding:1rem;border:1px solid var(--rob-line);border-top:0;background:white}.robustness-factorial-fallback h4{margin:0}.robustness-factorial-fallback ol{display:grid;gap:.5rem;margin:0;padding-left:1.3rem;color:var(--rob-muted);font-size:.82rem;line-height:1.5}.robustness-mermaid-source{margin-top:1rem;border-top:1px solid var(--rob-line);background:white}.robustness-mermaid-source>summary{cursor:pointer;padding:1rem;font-weight:700}.robustness-mermaid-source>p{color:var(--rob-muted);margin:0;padding:0 1rem 1rem}.robustness-mermaid-source pre{max-width:100%;margin:0;padding:1rem;overflow:auto;background:#172033;color:#eef5f7;font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:pre}.robustness-mermaid-source pre[hidden]{display:none}
.robustness-table-disclosure{margin-top:2rem;border-top:1px solid var(--rob-line);background:white}.robustness-table-disclosure summary{cursor:pointer;padding:1rem;font-weight:700}.robustness-table-wrap{max-width:100%;overflow:auto;border-top:1px solid var(--rob-line)}.robustness-table-wrap table{width:max-content;min-width:100%;border-collapse:collapse;font-size:.75rem}.robustness-table-wrap th,.robustness-table-wrap td{padding:.62rem .7rem;border-bottom:1px solid #e6eaf0;text-align:left;white-space:nowrap}.robustness-table-wrap th{position:sticky;top:0;background:#eef2f7;color:#465164}.robustness-threshold-summary{display:grid;grid-template-columns:auto auto minmax(0,1fr);gap:1rem;align-items:center;margin:3rem 0;background:#eef3f6;padding:1.25rem}.robustness-threshold-summary article{display:grid;gap:.2rem}.robustness-threshold-summary strong{font-size:1.65rem}.robustness-threshold-summary span,.robustness-threshold-summary p{font-size:.78rem;color:var(--rob-muted);margin:0}.robustness-download-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.65rem}.robustness-download{display:grid;gap:.35rem;padding:1rem;border:1px solid var(--rob-line);background:white;color:var(--rob-ink);text-decoration:none}.robustness-download:hover{border-color:var(--rob-accent)}.robustness-download span{font-weight:700}.robustness-download code{font-size:.72rem;color:var(--rob-muted);overflow-wrap:anywhere}
@media(max-width:1100px){.robustness-prompt-contract-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:980px){.robustness-message-grid,.robustness-model-grid{grid-template-columns:1fr}.robustness-chart-shell{grid-template-columns:1fr}.robustness-legend{grid-template-columns:repeat(2,minmax(0,1fr))}.robustness-message-panel header,.robustness-model-panel header{min-height:0}.robustness-section-heading{align-items:start;flex-direction:column}.robustness-lineage{grid-template-columns:1fr}.robustness-lineage-arrow{justify-self:center}.robustness-download-grid{grid-template-columns:1fr}.robustness-shared-contract-grid,.robustness-factorial-scope{grid-template-columns:1fr}}
@media(max-width:640px){.robustness-semantic-legend,.robustness-semantic-legend-four{grid-template-columns:1fr}.robustness-report{padding-inline:1rem}.robustness-section{padding:3.5rem 0}.robustness-source-warning{margin-bottom:4rem}.robustness-legend{grid-template-columns:1fr}.robustness-controls{display:grid;width:100%}.robustness-section label,.robustness-section select{width:100%;min-width:0}.robustness-threshold-summary,.robustness-denominator-grid,.robustness-prompt-contract-grid{grid-template-columns:1fr}.robustness-prompt-contract{padding:1rem}.robustness-hero h2{font-size:2.35rem}.robustness-chart svg{min-width:0}.robustness-factorial-scroll>svg{min-width:720px}}
"""


_ROBUSTNESS_SCRIPT = r"""
(() => {
  const report = document.querySelector('[data-testid="__REPORT_STAGE_TEST_ID__"]');
  if (!report) return;
  const familySelect = report.querySelector('[data-weight-family-select]');
  const messageSelect = report.querySelector('[data-prompt-message-select]');
  const metricSelect = report.querySelector('[data-prompt-metric-select]');
  const promptCatalog = __PROMPT_PRESENTATION_CATALOG__;

  const applyPromptLanguage = () => {
    const editorialRoot = document.querySelector('[data-testid="editorial-report"]');
    const language = editorialRoot?.dataset.reportLanguage || document.documentElement.lang || 'zh-CN';
    const copy = promptCatalog[language] || promptCatalog['zh-CN'];
    document.querySelectorAll('[data-robustness-i18n]').forEach((element) => {
      const key = element.dataset.robustnessI18n;
      if (key && copy[key]) element.textContent = copy[key];
    });
    document.querySelectorAll('[data-robustness-i18n-aria-label]').forEach((element) => {
      const key = element.dataset.robustnessI18nAriaLabel;
      if (key && copy[key]) element.setAttribute('aria-label', copy[key]);
    });
    document.querySelectorAll('[data-robustness-language-variant]').forEach((element) => {
      element.hidden = element.dataset.robustnessLanguageVariant !== language;
    });
    const traceStatus = document.querySelector('[data-testid="run-trace-state"]');
    if (copy['semantic.trace.loading']) {
      if (traceStatus?.dataset.traceState === 'ready') {
        const rowCount = Number(traceStatus.dataset.traceRowCount || 0).toLocaleString(language);
        traceStatus.textContent = `${copy['semantic.trace.ready']}: ${rowCount} ${copy['semantic.trace.rows']}.`;
      } else if (traceStatus?.dataset.traceState === 'error') {
        traceStatus.textContent = copy['semantic.trace.error'];
      } else if (traceStatus) {
        traceStatus.textContent = copy['semantic.trace.loading'];
      }
    }
  };

  const applyWeightFamily = () => {
    const value = familySelect?.value || 'network-feedback';
    report.querySelectorAll('[data-weight-family]').forEach((panel) => {
      panel.hidden = panel.dataset.weightFamily !== value;
    });
  };
  const applyPromptView = () => {
    const message = messageSelect?.value || 'message_1';
    const metric = metricSelect?.value || 'engagement';
    report.querySelectorAll('[data-prompt-view]').forEach((panel) => {
      panel.hidden = panel.dataset.promptView !== `${message}|${metric}`;
    });
    report.querySelectorAll('[data-row-message-id]').forEach((row) => {
      row.hidden = row.dataset.rowMessageId !== message;
    });
  };

  familySelect?.addEventListener('change', applyWeightFamily);
  messageSelect?.addEventListener('change', applyPromptView);
  metricSelect?.addEventListener('change', applyPromptView);
  document.querySelectorAll('[data-report-language]').forEach((button) => {
    button.addEventListener('click', () => queueMicrotask(applyPromptLanguage));
  });
  applyWeightFamily();
  applyPromptView();
  applyPromptLanguage();
})();
"""
