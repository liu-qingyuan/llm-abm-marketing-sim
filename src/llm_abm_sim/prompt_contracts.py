from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Literal

from .schemas import LATENT_VALUE_DIMENSIONS

PromptVariantId = Literal["P0", "P1", "P2", "P3"]
PromptControlledChange = Literal[
    "baseline",
    "wording_only",
    "information_order_only",
    "structured_rubric_only",
]

CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION = "jinjiang-concurrent-message-primary-prompt-v1"
CONCURRENT_ROBUSTNESS_P1_PROMPT_VERSION = "jinjiang-concurrent-message-primary-robustness-p1-v1"
CONCURRENT_ROBUSTNESS_P2_PROMPT_VERSION = "jinjiang-concurrent-message-primary-robustness-p2-v1"
CONCURRENT_ROBUSTNESS_P3_PROMPT_VERSION = "jinjiang-concurrent-message-primary-robustness-p3-v1"
CONCURRENT_ROBUSTNESS_PROMPT_TOKENS: tuple[str, ...] = (
    CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
    CONCURRENT_ROBUSTNESS_P1_PROMPT_VERSION,
    CONCURRENT_ROBUSTNESS_P2_PROMPT_VERSION,
    CONCURRENT_ROBUSTNESS_P3_PROMPT_VERSION,
)

_APPROVED_TEMPLATE_FIELDS: tuple[str, ...] = (
    "marketing_content_summary",
    "post_value_summary",
    "observed_profile_summary",
    "consumption_preference_summary",
    "peer_influence_summary",
)

APPROVED_VISIBLE_FIELD_ALLOWLIST: tuple[str, ...] = (
    "post.text",
    *(f"post.value_dimensions.{dimension}" for dimension in LATENT_VALUE_DIMENSIONS),
    "profile.activity_score",
    "profile.global_influence_score",
    "profile.local_influence_score",
    "profile.concurrent_environmental_consciousness_coef",
    *(f"profile.concurrent_{dimension}_value_weight" for dimension in LATENT_VALUE_DIMENSIONS),
    "profile.concurrent_hotel_class",
    "profile.concurrent_travel_purpose",
    "peer_context.exposed_neighbors",
    "peer_context.engaged_neighbors",
    "peer_context.engagement_ratio",
    "peer_context.influential_engaged_neighbors",
    "peer_context.visible_likes",
    "peer_context.visible_comments",
    "peer_context.visible_shares",
)

APPROVED_EXCLUDED_FIELDS: tuple[str, ...] = (
    "post.post_id",
    "post.topic_tags",
    "post.media_summary",
    "profile.user_id",
    "profile.interest_tags",
    "profile.nickname",
    "profile.bio",
    "profile.signature",
    "profile.raw_follower_fields",
    "profile.historical_tags",
    "profile.latent_class",
    "profile.concurrent_gender",
    "profile.concurrent_age",
    "profile.concurrent_education",
    "profile.concurrent_monthly_income",
    "platform_context.*",
    "ranking.*",
    "campaign_feedback.*",
    "other_messages.*",
    "time_step",
)

TASK_SEMANTICS: tuple[str, ...] = (
    "judge_engagement_after_exposure_to_current_message",
    "use_only_approved_primary_visible_fields",
    "do_not_infer_or_add_unprovided_context",
    "return_one_final_structured_decision_without_chain_of_thought",
)

ACTION_SEMANTICS: tuple[str, ...] = (
    "engage_false_requires_ignore",
    "engage_true_requires_exactly_one_of_like_comment_share",
    "actions_are_ignore_like_comment_share",
)

EQUIVALENCE_CHECKLIST: tuple[str, ...] = (
    "same_current_message_text",
    "same_post_value_dimensions",
    "same_observed_proxy_fields",
    "same_synthetic_preference_labels",
    "same_neutral_peer_context_fields",
    "same_task_semantics",
    "same_action_semantics",
    "same_output_schema",
    "no_demographic_ranking_feedback_other_message_or_new_profile_fields",
    "no_chain_of_thought_requested_or_persisted",
)


@dataclass(frozen=True)
class PromptDecisionOutputSchema:
    schema_version: Literal["engage-decision-output-v1"] = "engage-decision-output-v1"
    required_fields: tuple[str, ...] = ("engage", "probability", "reason", "confidence", "action")
    additional_properties: bool = False
    probability_range: tuple[float, float] = (0.0, 1.0)
    confidence_range: tuple[float, float] = (0.0, 1.0)
    reason_semantics: str = "brief_non_sensitive_final_reason_not_chain_of_thought"
    action_values: tuple[str, ...] = ("ignore", "like", "comment", "share")
    engage_action_rules: tuple[str, ...] = (
        "engage=false => action=ignore",
        "engage=true => action in {like,comment,share}",
    )


DECISION_OUTPUT_SCHEMA = PromptDecisionOutputSchema()


@dataclass(frozen=True)
class ConcurrentPromptContract:
    schema_version: Literal["concurrent-robustness-prompt-contract-v1"]
    variant_id: PromptVariantId
    prompt_version: str
    canonical_hash: str
    visible_field_allowlist: tuple[str, ...]
    excluded_fields: tuple[str, ...]
    task_semantics: tuple[str, ...]
    action_semantics: tuple[str, ...]
    output_schema: PromptDecisionOutputSchema
    equivalence_checklist: tuple[str, ...]

    def audit_record(self) -> dict[str, object]:
        """Return the versioned static contract without any per-user Prompt text."""

        return asdict(self)


@dataclass(frozen=True)
class _PromptSection:
    field_key: str
    heading: str


@dataclass(frozen=True)
class _PromptTemplate:
    system_content: str
    sections: tuple[_PromptSection, ...]
    output_instruction: str
    rubric: str | None = None


_OUTPUT_INSTRUCTION = (
    "【输出 schema】\n"
    "必须返回字段：engage（boolean）、probability（0.0 到 1.0）、"
    "reason（简短非敏感理由）、confidence（0.0 到 1.0）、"
    "action（ignore/like/comment/share）。"
    "engage=false 时 action 必须为 ignore；"
    "engage=true 时 action 必须为 like、comment 或 share 之一。"
)

_P0_SYSTEM = (
    "你是 concurrent-message validation runtime 中的结构化决策函数。"
    "你只可以使用当前 message 原文、可观测代理指标、受控 Synthetic Experiment Labels 和中性 PeerContext。"
    "不要推断或补写未提供的人口学身份、Class、昵称、简介、签名、粉丝原始字段、历史标签、平台上下文或其他 message 历史。"
    "只返回一个 JSON 对象，不要输出 Markdown、解释性段落、headers、secrets 或额外 commentary。"
)

_P0_SECTIONS = (
    _PromptSection("marketing_content_summary", "【当前 message 原文】"),
    _PromptSection("post_value_summary", "【内容主要强调的价值】"),
    _PromptSection("observed_profile_summary", "【用户可观测代理指标】"),
    _PromptSection("consumption_preference_summary", "【Synthetic Experiment Labels】"),
    _PromptSection("peer_influence_summary", "【中性 PeerContext】"),
)

_TEMPLATES: tuple[tuple[PromptVariantId, str, _PromptTemplate], ...] = (
    (
        "P0",
        CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION,
        _PromptTemplate(system_content=_P0_SYSTEM, sections=_P0_SECTIONS, output_instruction=_OUTPUT_INSTRUCTION),
    ),
    (
        "P1",
        CONCURRENT_ROBUSTNESS_P1_PROMPT_VERSION,
        _PromptTemplate(
            system_content=(
                "你在 concurrent-message validation runtime 中负责生成结构化互动判断。"
                "判断时仅能依据当前 message 文案、可观测代理指标、受控 Synthetic Experiment Labels 与中性 PeerContext。"
                "不得猜测或补充未给出的人口学身份、Class、昵称、简介、签名、粉丝原始字段、历史标签、平台上下文或其他 message 历史。"
                "最终只输出一个 JSON 对象；不要输出 Markdown、说明段落、headers、secrets 或其他 commentary。"
            ),
            sections=(
                _PromptSection("marketing_content_summary", "【当前 message 文案】"),
                _PromptSection("post_value_summary", "【内容强调的主要价值】"),
                _PromptSection("observed_profile_summary", "【用户的可观测代理指标】"),
                _PromptSection("consumption_preference_summary", "【受控 Synthetic Experiment Labels】"),
                _PromptSection("peer_influence_summary", "【保持中性的 PeerContext】"),
            ),
            output_instruction=_OUTPUT_INSTRUCTION,
        ),
    ),
    (
        "P2",
        CONCURRENT_ROBUSTNESS_P2_PROMPT_VERSION,
        _PromptTemplate(
            system_content=_P0_SYSTEM,
            sections=(
                _P0_SECTIONS[2],
                _P0_SECTIONS[3],
                _P0_SECTIONS[4],
                _P0_SECTIONS[0],
                _P0_SECTIONS[1],
            ),
            output_instruction=_OUTPUT_INSTRUCTION,
        ),
    ),
    (
        "P3",
        CONCURRENT_ROBUSTNESS_P3_PROMPT_VERSION,
        _PromptTemplate(
            system_content=_P0_SYSTEM,
            sections=_P0_SECTIONS,
            rubric=(
                "【结构化判断 rubric】\n"
                "仅在内部核对：当前 message 与价值信息、用户代理指标与受控标签、中性 PeerContext，"
                "然后选择符合动作语义的最终判断。不要输出逐步分析或 chain-of-thought。"
            ),
            output_instruction=_OUTPUT_INSTRUCTION,
        ),
    ),
)

CONCURRENT_ROBUSTNESS_PROMPT_CANONICAL_HASHES: Mapping[str, str] = MappingProxyType(
    {
        CONCURRENT_MESSAGE_PRIMARY_PROMPT_VERSION: (
            "sha256:cc50affc4e658a9a1804f5e1824710cb073003aff3cc6af8f8c5cd8edf5cdc7c"
        ),
        CONCURRENT_ROBUSTNESS_P1_PROMPT_VERSION: (
            "sha256:67b38d5edfc562bf43a115d9a7aaebc856d51049614dc4cc633c431dd57bf0e1"
        ),
        CONCURRENT_ROBUSTNESS_P2_PROMPT_VERSION: (
            "sha256:6784ecc2163e6b2426631d81672994376c3781791fa265c3e0f67d1428b71cb4"
        ),
        CONCURRENT_ROBUSTNESS_P3_PROMPT_VERSION: (
            "sha256:a3ac934d194437f6ee86011b92666cf1ea19fb086a383fb7b7407cf5f44bd7ea"
        ),
    }
)


class PromptContractRegistry:
    """Immutable registry that owns Prompt equivalence, rendering, and canonical hashes."""

    def __init__(self, templates: tuple[tuple[PromptVariantId, str, _PromptTemplate], ...]) -> None:
        if tuple(variant for variant, _, _ in templates) != ("P0", "P1", "P2", "P3"):
            raise ValueError("Prompt registry must define P0, P1, P2, and P3 exactly once")
        tokens = tuple(token for _, token, _ in templates)
        if len(set(tokens)) != len(tokens):
            raise ValueError("Prompt registry tokens must be unique")

        contracts: list[ConcurrentPromptContract] = []
        templates_by_token: dict[str, _PromptTemplate] = {}
        contracts_by_key: dict[str, ConcurrentPromptContract] = {}
        controlled_changes_by_key: dict[str, PromptControlledChange] = {}
        baseline_template = templates[0][2]
        controlled_changes: list[PromptControlledChange] = []
        for variant_id, prompt_version, template in templates:
            self._validate_template(variant_id, template)
            controlled_change = self._classify_controlled_change(template, baseline_template)
            controlled_changes.append(controlled_change)
            canonical_hash = self._canonical_hash(variant_id, prompt_version, template)
            if canonical_hash != CONCURRENT_ROBUSTNESS_PROMPT_CANONICAL_HASHES.get(prompt_version):
                raise ValueError(f"{variant_id} canonical Prompt hash changed without a new stable token")
            contract = ConcurrentPromptContract(
                schema_version="concurrent-robustness-prompt-contract-v1",
                variant_id=variant_id,
                prompt_version=prompt_version,
                canonical_hash=canonical_hash,
                visible_field_allowlist=APPROVED_VISIBLE_FIELD_ALLOWLIST,
                excluded_fields=APPROVED_EXCLUDED_FIELDS,
                task_semantics=TASK_SEMANTICS,
                action_semantics=ACTION_SEMANTICS,
                output_schema=DECISION_OUTPUT_SCHEMA,
                equivalence_checklist=EQUIVALENCE_CHECKLIST,
            )
            contracts.append(contract)
            templates_by_token[prompt_version] = template
            contracts_by_key[prompt_version] = contract
            contracts_by_key[variant_id] = contract
            controlled_changes_by_key[prompt_version] = controlled_change
            controlled_changes_by_key[variant_id] = controlled_change
        if tuple(controlled_changes) != (
            "baseline",
            "wording_only",
            "information_order_only",
            "structured_rubric_only",
        ):
            raise ValueError("Prompt registry templates do not form the declared controlled variants")
        self._contracts = tuple(contracts)
        self._templates_by_token = MappingProxyType(templates_by_token)
        self._contracts_by_key = MappingProxyType(contracts_by_key)
        self._controlled_changes_by_key = MappingProxyType(controlled_changes_by_key)

    def all(self) -> tuple[ConcurrentPromptContract, ...]:
        return self._contracts

    def controlled_change(self, token_or_variant: str) -> PromptControlledChange:
        """Classify a variant from registry-owned template structure without exposing template text."""

        try:
            return self._controlled_changes_by_key[token_or_variant]
        except KeyError as exc:
            raise ValueError(f"unsupported concurrent robustness prompt: {token_or_variant}") from exc

    def catalog_records(self) -> tuple[dict[str, object], ...]:
        """Return complete static client-message templates without per-user rendered values."""

        records: list[dict[str, object]] = []
        placeholders = {field: f"{{{{{field}}}}}" for field in _APPROVED_TEMPLATE_FIELDS}
        for contract in self._contracts:
            template = self._templates_by_token[contract.prompt_version]
            records.append(
                {
                    "schema_version": "concurrent-robustness-prompt-catalog-record-v1",
                    "variant_id": contract.variant_id,
                    "controlled_change": self.controlled_change(contract.variant_id),
                    "prompt_version": contract.prompt_version,
                    "canonical_hash": contract.canonical_hash,
                    "placeholder_fields": _APPROVED_TEMPLATE_FIELDS,
                    "client_submitted_message_templates": (
                        {"role": "system", "content": template.system_content},
                        {"role": "user", "content": self._user_content(template, placeholders)},
                    ),
                    "decision_output_schema": asdict(contract.output_schema),
                }
            )
        return tuple(records)

    def resolve(self, token_or_variant: str) -> ConcurrentPromptContract:
        try:
            return self._contracts_by_key[token_or_variant]
        except KeyError as exc:
            raise ValueError(f"unsupported concurrent robustness prompt: {token_or_variant}") from exc

    def render(self, token_or_variant: str, summaries: Mapping[str, str]) -> list[dict[str, str]]:
        contract = self.resolve(token_or_variant)
        template = self._templates_by_token[contract.prompt_version]
        missing = [key for key in _APPROVED_TEMPLATE_FIELDS if not isinstance(summaries.get(key), str)]
        if missing:
            raise ValueError(f"Prompt summaries missing approved fields: {', '.join(missing)}")
        return [
            {"role": "system", "content": template.system_content},
            {"role": "user", "content": self._user_content(template, summaries)},
        ]

    @staticmethod
    def _user_content(template: _PromptTemplate, summaries: Mapping[str, str]) -> str:
        blocks = [f"{section.heading}\n{summaries[section.field_key]}" for section in template.sections]
        if template.rubric is not None:
            blocks.append(template.rubric)
        blocks.append(template.output_instruction)
        return "\n\n".join(blocks)

    @staticmethod
    def _validate_template(variant_id: PromptVariantId, template: _PromptTemplate) -> None:
        counts = Counter(section.field_key for section in template.sections)
        if counts != Counter(_APPROVED_TEMPLATE_FIELDS):
            raise ValueError(f"{variant_id} must include every approved Prompt field exactly once")
        if variant_id != "P3" and template.rubric is not None:
            raise ValueError(f"{variant_id} must not add a reasoning rubric")
        if variant_id == "P3" and (template.rubric is None or "chain-of-thought" not in template.rubric):
            raise ValueError("P3 must explicitly forbid chain-of-thought output")

    @staticmethod
    def _classify_controlled_change(
        template: _PromptTemplate,
        baseline: _PromptTemplate,
    ) -> PromptControlledChange:
        if template == baseline:
            return "baseline"
        if (
            tuple(section.field_key for section in template.sections)
            == tuple(section.field_key for section in baseline.sections)
            and template.output_instruction == baseline.output_instruction
            and template.rubric == baseline.rubric
            and (
                template.system_content != baseline.system_content
                or tuple(section.heading for section in template.sections)
                != tuple(section.heading for section in baseline.sections)
            )
        ):
            return "wording_only"
        if (
            template.system_content == baseline.system_content
            and template.output_instruction == baseline.output_instruction
            and template.rubric == baseline.rubric
            and Counter(template.sections) == Counter(baseline.sections)
            and template.sections != baseline.sections
        ):
            return "information_order_only"
        if (
            template.system_content == baseline.system_content
            and template.sections == baseline.sections
            and template.output_instruction == baseline.output_instruction
            and template.rubric is not None
        ):
            return "structured_rubric_only"
        raise ValueError("Prompt template changes more than one declared controlled dimension")

    @staticmethod
    def _canonical_hash(variant_id: PromptVariantId, prompt_version: str, template: _PromptTemplate) -> str:
        payload = {
            "schema_version": "concurrent-robustness-prompt-contract-v1",
            "variant_id": variant_id,
            "prompt_version": prompt_version,
            "visible_field_allowlist": APPROVED_VISIBLE_FIELD_ALLOWLIST,
            "excluded_fields": APPROVED_EXCLUDED_FIELDS,
            "task_semantics": TASK_SEMANTICS,
            "action_semantics": ACTION_SEMANTICS,
            "output_schema": asdict(DECISION_OUTPUT_SCHEMA),
            "equivalence_checklist": EQUIVALENCE_CHECKLIST,
            "template": asdict(template),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


CONCURRENT_ROBUSTNESS_PROMPT_REGISTRY = PromptContractRegistry(_TEMPLATES)
