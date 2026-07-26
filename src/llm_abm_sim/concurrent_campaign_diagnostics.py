from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .prompt_field_summary import AGE_LABELS, EDUCATION_LABELS, GENDER_LABELS, MONTHLY_INCOME_LABELS

CONCURRENT_CAMPAIGN_DIAGNOSTICS_SCHEMA = "concurrent-campaign-diagnostics-v1"
CONCURRENT_CAMPAIGN_DIAGNOSTICS_SUMMARY_SCHEMA = "concurrent-campaign-diagnostics-summary-v1"
CONCURRENT_DEMOGRAPHIC_REASON_SCREENING_METHOD_VERSION = "shadow-demographic-lexical-screen-v1"

_BASE_NETWORK_WEIGHT = 0.50
_CAMPAIGN_FEEDBACK_WEIGHT = 0.30
_MESSAGE_FIT_WEIGHT = 0.20
_POSITIVE_ACTIONS = frozenset({"like", "comment", "share"})
_CAUSAL_TOKENS = ("因为", "由于", "因此", "所以", "作为", "身为")
_PUNCTUATION_CHARS = "\\s，。；、,.!?！？:：()（）\"'“”‘’"
_CJK_CHARS = "\u4e00-\u9fff"


@dataclass(frozen=True)
class ConcurrentCampaignDiagnosticArtifacts:
    payload: dict[str, Any]
    summary: dict[str, Any]


@dataclass(frozen=True)
class _CandidateRow:
    time_step: int
    message_id: str
    user_id: str
    selected: bool
    selection_reason: str
    ranking_position: int
    base_network_relevance: float
    base_network_relevance_text: str
    campaign_engaged_neighbor_signal: float
    campaign_engaged_neighbor_signal_text: str
    raw_message_user_fit: float
    raw_message_user_fit_text: str
    normalized_message_user_fit: float
    normalized_message_user_fit_text: str
    personalized_delivery_score: float
    personalized_delivery_score_text: str


@dataclass(frozen=True)
class _PairRow:
    pair_id: str
    time_step: int
    message_id: str
    message_title: str
    user_id: str
    latent_class: str
    selection_reason: str
    ranking_position: int
    base_network_relevance: float
    base_network_relevance_text: str
    campaign_engaged_neighbor_signal: float
    campaign_engaged_neighbor_signal_text: str
    raw_message_user_fit: float
    raw_message_user_fit_text: str
    normalized_message_user_fit: float
    normalized_message_user_fit_text: str
    personalized_delivery_score: float
    personalized_delivery_score_text: str
    primary_status: str
    primary_action: str
    primary_probability: float | None
    primary_reason: str
    shadow_status: str
    shadow_action: str
    shadow_probability: float | None
    shadow_reason: str
    pair_terminal_coverage: bool
    paired_decision_coverage: bool
    shadow_gender: str | None
    shadow_age: str | None
    shadow_education: str | None
    shadow_monthly_income: str | None


@dataclass(frozen=True)
class _ReasonMatch:
    field_name: str
    match_type: str
    matched_span: str


@dataclass(frozen=True)
class _DemographicFieldDefinition:
    prompt_label: str
    value_labels: Mapping[str, str]
    label_tokens: tuple[str, ...]


_DEMOGRAPHIC_FIELD_DEFINITIONS: dict[str, _DemographicFieldDefinition] = {
    "shadow_gender": _DemographicFieldDefinition(
        prompt_label="性别标签",
        value_labels=GENDER_LABELS,
        label_tokens=("性别标签", "性别"),
    ),
    "shadow_age": _DemographicFieldDefinition(
        prompt_label="年龄段标签",
        value_labels=AGE_LABELS,
        label_tokens=("年龄段标签", "年龄段", "年龄"),
    ),
    "shadow_education": _DemographicFieldDefinition(
        prompt_label="教育程度标签",
        value_labels=EDUCATION_LABELS,
        label_tokens=("教育程度标签", "教育程度", "教育"),
    ),
    "shadow_monthly_income": _DemographicFieldDefinition(
        prompt_label="月收入区间标签",
        value_labels=MONTHLY_INCOME_LABELS,
        label_tokens=("月收入区间标签", "月收入区间", "月收入", "收入"),
    ),
}


class ConcurrentCampaignDiagnostics:
    """Rebuild concurrent-message campaign diagnostics from persisted candidate and pair rows."""

    def __init__(self, *, delivery_capacity: int | None = None) -> None:
        if delivery_capacity is not None and delivery_capacity < 1:
            raise ValueError("delivery_capacity must be at least 1 when provided")
        self.delivery_capacity = delivery_capacity

    def build(
        self,
        *,
        candidate_rows: Sequence[Mapping[str, Any]],
        pair_rows: Sequence[Mapping[str, Any]],
    ) -> ConcurrentCampaignDiagnosticArtifacts:
        candidates = [_candidate_row(row) for row in candidate_rows]
        pairs = [_pair_row(row) for row in pair_rows]
        if not candidates:
            raise ValueError("campaign diagnostics require at least one candidate row")

        message_order = _stable_unique(candidate.message_id for candidate in candidates)
        if not message_order:
            raise ValueError("campaign diagnostics require at least one message")
        time_steps = sorted({candidate.time_step for candidate in candidates})
        sample_user_ids = _stable_unique(candidate.user_id for candidate in candidates)
        delivery_capacity = self.delivery_capacity or _infer_delivery_capacity(candidates, pairs)
        if delivery_capacity < 1:
            raise ValueError("campaign diagnostics could not infer a positive delivery capacity")

        candidates_by_key: dict[tuple[int, str, str], _CandidateRow] = {}
        candidates_by_batch: dict[tuple[str, int], list[_CandidateRow]] = defaultdict(list)
        selected_candidate_keys: set[tuple[int, str, str]] = set()
        for candidate in candidates:
            key = (candidate.time_step, candidate.message_id, candidate.user_id)
            if key in candidates_by_key:
                raise ValueError(f"duplicate candidate row for {key}")
            candidates_by_key[key] = candidate
            candidates_by_batch[(candidate.message_id, candidate.time_step)].append(candidate)
            if candidate.selected:
                selected_candidate_keys.add(key)

        pairs_by_key: dict[tuple[int, str, str], _PairRow] = {}
        pairs_by_batch: dict[tuple[str, int], list[_PairRow]] = defaultdict(list)
        pairs_by_message: dict[str, list[_PairRow]] = defaultdict(list)
        message_title_by_id: dict[str, str] = {}
        for pair in pairs:
            key = (pair.time_step, pair.message_id, pair.user_id)
            if key in pairs_by_key:
                raise ValueError(f"duplicate pair row for {key}")
            pairs_by_key[key] = pair
            pairs_by_batch[(pair.message_id, pair.time_step)].append(pair)
            pairs_by_message[pair.message_id].append(pair)
            message_title_by_id.setdefault(pair.message_id, pair.message_title)

        self._validate_candidate_rankings(candidates_by_batch, delivery_capacity)
        self._validate_pair_closure(
            candidates_by_key=candidates_by_key,
            selected_candidate_keys=selected_candidate_keys,
            pairs_by_key=pairs_by_key,
        )

        funnel_per_message: dict[str, dict[str, Any]] = {}
        allocation_batches: list[dict[str, Any]] = []
        selected_pair_details: list[dict[str, Any]] = []
        fit_distribution_by_message: dict[str, dict[str, Any]] = {}
        overlap_source: dict[str, set[str]] = {}
        class_labels = _stable_unique(pair.latent_class for pair in pairs)
        class_message_matrix = {latent_class: {message_id: 0 for message_id in message_order} for latent_class in class_labels}

        for message_id in message_order:
            message_pairs = sorted(
                pairs_by_message.get(message_id, []),
                key=lambda row: (row.time_step, row.ranking_position, row.user_id),
            )
            message_title = message_title_by_id.get(message_id, message_id)
            overlap_source[message_id] = {pair.user_id for pair in message_pairs}
            for pair in message_pairs:
                if pair.latent_class not in class_message_matrix:
                    class_message_matrix[pair.latent_class] = {known_message_id: 0 for known_message_id in message_order}
                class_message_matrix[pair.latent_class][message_id] += 1
                selected_pair_details.append(
                    {
                        "pair_id": pair.pair_id,
                        "time_step": pair.time_step,
                        "message_id": pair.message_id,
                        "message_title": pair.message_title,
                        "user_id": pair.user_id,
                        "latent_class": pair.latent_class,
                        "selection_reason": pair.selection_reason,
                        "ranking_position": pair.ranking_position,
                        "base_network_relevance_full_precision": pair.base_network_relevance_text,
                        "campaign_engaged_neighbor_signal_full_precision": pair.campaign_engaged_neighbor_signal_text,
                        "raw_message_user_fit_full_precision": pair.raw_message_user_fit_text,
                        "normalized_message_user_fit_full_precision": pair.normalized_message_user_fit_text,
                        "base_network_component_full_precision": _format_full_precision(
                            _BASE_NETWORK_WEIGHT * pair.base_network_relevance
                        ),
                        "campaign_feedback_component_full_precision": _format_full_precision(
                            _CAMPAIGN_FEEDBACK_WEIGHT * pair.campaign_engaged_neighbor_signal
                        ),
                        "message_user_fit_component_full_precision": _format_full_precision(
                            _MESSAGE_FIT_WEIGHT * pair.normalized_message_user_fit
                        ),
                        "personalized_delivery_score_full_precision": pair.personalized_delivery_score_text,
                    }
                )
            fit_distribution_by_message[message_id] = {
                "message_title": message_title,
                "selected_pairs": len(message_pairs),
                "raw_message_user_fit": _distribution_summary(
                    [pair.raw_message_user_fit for pair in message_pairs]
                ),
                "normalized_message_user_fit": _distribution_summary(
                    [pair.normalized_message_user_fit for pair in message_pairs]
                ),
            }

            message_exposed_user_ids = {pair.user_id for pair in message_pairs}
            funnel_per_message[message_id] = {
                "message_title": message_title,
                "exposures": len(message_pairs),
                "primary_successes": sum(pair.primary_status == "succeeded" for pair in message_pairs),
                "primary_failures": sum(pair.primary_status == "provider_failed" for pair in message_pairs),
                "shadow_successes": sum(pair.shadow_status == "succeeded" for pair in message_pairs),
                "shadow_failures": sum(pair.shadow_status == "provider_failed" for pair in message_pairs),
                "below_delivery_capacity": len(sample_user_ids) - len(message_exposed_user_ids),
            }

            cumulative_pairs = 0
            for time_step in time_steps:
                batch_candidates = sorted(
                    candidates_by_batch[(message_id, time_step)], key=lambda row: row.ranking_position
                )
                batch_pairs = sorted(
                    pairs_by_batch.get((message_id, time_step), []),
                    key=lambda row: (row.ranking_position, row.user_id),
                )
                cumulative_pairs += len(batch_pairs)
                top_count = min(delivery_capacity, len(batch_candidates))
                allocation_batches.append(
                    {
                        "message_id": message_id,
                        "message_title": message_title,
                        "time_step": time_step,
                        "configured_capacity": delivery_capacity,
                        "eligible_users": len(batch_candidates),
                        "selected_pairs": len(batch_pairs),
                        "cumulative_pairs": cumulative_pairs,
                        "below_delivery_capacity": len(batch_candidates) - len(batch_pairs),
                        "actual_selected_user_ids": [pair.user_id for pair in batch_pairs],
                        "full_ranking_top_user_ids": [candidate.user_id for candidate in batch_candidates[:top_count]],
                    }
                )

        coverage_counts = Counter(
            sum(pair.user_id == user_id for pair in pairs)
            for user_id in sample_user_ids
        )
        actual_exposures = len(pairs)
        primary_successes = sum(pair.primary_status == "succeeded" for pair in pairs)
        primary_failures = sum(pair.primary_status == "provider_failed" for pair in pairs)
        shadow_successes = sum(pair.shadow_status == "succeeded" for pair in pairs)
        shadow_failures = sum(pair.shadow_status == "provider_failed" for pair in pairs)
        campaign_funnel = {
            "sample_users": len(sample_user_ids),
            "message_count": len(message_order),
            "eligible_user_message_pairs": len(sample_user_ids) * len(message_order),
            "actual_exposures": actual_exposures,
            "per_message_capacity": {
                "per_batch": delivery_capacity,
                "batches": len(time_steps),
                "per_message_total": delivery_capacity * len(time_steps),
            },
            "distinct_exposed_users": len({pair.user_id for pair in pairs}),
            "campaign_exposure_coverage": {
                str(message_count): coverage_counts.get(message_count, 0)
                for message_count in range(len(message_order) + 1)
            },
            "primary": {
                "attempted": actual_exposures,
                "succeeded": primary_successes,
                "provider_failed": primary_failures,
            },
            "shadow": {
                "attempted": actual_exposures,
                "succeeded": shadow_successes,
                "provider_failed": shadow_failures,
            },
            "below_delivery_capacity_pairs": (len(sample_user_ids) * len(message_order)) - actual_exposures,
            "per_message": funnel_per_message,
        }

        message_overlap = _message_overlap_summary(message_order, overlap_source)
        message_allocation = {
            "descriptive_only": True,
            "non_causal": True,
            "batch_capacity": allocation_batches,
            "overlap": message_overlap,
            "class_message_matrix": class_message_matrix,
            "fit_distribution_by_message": fit_distribution_by_message,
            "selected_pair_details": selected_pair_details,
        }

        primary_audience_response = {
            "descriptive_only": True,
            "non_causal": True,
            "per_message": {
                message_id: _primary_response_summary(message_id, message_title_by_id.get(message_id, message_id), pairs_by_message.get(message_id, []))
                for message_id in message_order
            },
        }

        feedback_effect = self._feedback_effect(
            candidates_by_batch=candidates_by_batch,
            delivery_capacity=delivery_capacity,
            message_order=message_order,
            message_title_by_id=message_title_by_id,
            time_steps=time_steps,
        )

        demographic_sensitivity = _demographic_sensitivity(pairs)

        summary = {
            "schema_version": CONCURRENT_CAMPAIGN_DIAGNOSTICS_SUMMARY_SCHEMA,
            "sample_users": campaign_funnel["sample_users"],
            "message_count": campaign_funnel["message_count"],
            "eligible_user_message_pairs": campaign_funnel["eligible_user_message_pairs"],
            "actual_exposures": campaign_funnel["actual_exposures"],
            "distinct_exposed_users": campaign_funnel["distinct_exposed_users"],
            "below_delivery_capacity_pairs": campaign_funnel["below_delivery_capacity_pairs"],
            "pair_terminal_coverage": demographic_sensitivity["pair_terminal_coverage"]["value"],
            "paired_decision_coverage": demographic_sensitivity["paired_decision_coverage"]["value"],
            "feedback_changed_message_batches": feedback_effect["overall"]["changed_message_batch_count"],
            "reason_screening_method_version": CONCURRENT_DEMOGRAPHIC_REASON_SCREENING_METHOD_VERSION,
        }

        return ConcurrentCampaignDiagnosticArtifacts(
            payload={
                "schema_version": CONCURRENT_CAMPAIGN_DIAGNOSTICS_SCHEMA,
                "descriptive_only": True,
                "non_causal": True,
                "campaign_funnel": campaign_funnel,
                "message_allocation": message_allocation,
                "primary_audience_response": primary_audience_response,
                "campaign_feedback_effect": feedback_effect,
                "demographic_decision_sensitivity": demographic_sensitivity,
                "summary": summary,
            },
            summary=summary,
        )

    def _validate_candidate_rankings(
        self,
        candidates_by_batch: Mapping[tuple[str, int], Sequence[_CandidateRow]],
        delivery_capacity: int,
    ) -> None:
        for (message_id, time_step), batch_rows in candidates_by_batch.items():
            ordered = sorted(batch_rows, key=lambda row: row.ranking_position)
            positions = [row.ranking_position for row in ordered]
            expected_positions = list(range(1, len(ordered) + 1))
            if positions != expected_positions:
                raise ValueError(
                    f"{message_id} batch {time_step} ranking positions must be contiguous from 1"
                )
            for row in ordered:
                recomputed_score = (
                    _BASE_NETWORK_WEIGHT * row.base_network_relevance
                    + _CAMPAIGN_FEEDBACK_WEIGHT * row.campaign_engaged_neighbor_signal
                    + _MESSAGE_FIT_WEIGHT * row.normalized_message_user_fit
                )
                if not _close_enough(row.personalized_delivery_score, recomputed_score):
                    raise ValueError(
                        f"{message_id} batch {time_step} score mismatch for {row.user_id}"
                    )
            reranked = sorted(
                batch_rows,
                key=lambda row: (-row.personalized_delivery_score, row.user_id),
            )
            if [row.user_id for row in ordered] != [row.user_id for row in reranked]:
                raise ValueError(
                    f"{message_id} batch {time_step} persisted ranking does not match score/tie-break"
                )
            selected_count = sum(row.selected for row in batch_rows)
            if selected_count > min(delivery_capacity, len(batch_rows)):
                raise ValueError(
                    f"{message_id} batch {time_step} selected {selected_count} rows above delivery capacity {delivery_capacity}"
                )

    def _validate_pair_closure(
        self,
        *,
        candidates_by_key: Mapping[tuple[int, str, str], _CandidateRow],
        selected_candidate_keys: set[tuple[int, str, str]],
        pairs_by_key: Mapping[tuple[int, str, str], _PairRow],
    ) -> None:
        if selected_candidate_keys != set(pairs_by_key):
            missing_pairs = sorted(selected_candidate_keys - set(pairs_by_key))
            missing_candidates = sorted(set(pairs_by_key) - selected_candidate_keys)
            if missing_pairs:
                raise ValueError(f"selected candidate rows are missing pair rows: {missing_pairs[:3]}")
            raise ValueError(f"pair rows do not map to selected candidate rows: {missing_candidates[:3]}")
        for key, pair in pairs_by_key.items():
            candidate = candidates_by_key.get(key)
            if candidate is None:
                raise ValueError(f"pair row {pair.pair_id} is missing matching candidate evidence")
            if not candidate.selected:
                raise ValueError(f"pair row {pair.pair_id} does not match a selected candidate")
            if pair.selection_reason != candidate.selection_reason:
                raise ValueError(f"pair row {pair.pair_id} selection reason does not match candidate evidence")
            if pair.ranking_position != candidate.ranking_position:
                raise ValueError(f"pair row {pair.pair_id} ranking position does not match candidate evidence")
            for field_name, pair_value, candidate_value in (
                (
                    "base_network_relevance",
                    pair.base_network_relevance,
                    candidate.base_network_relevance,
                ),
                (
                    "campaign_engaged_neighbor_signal",
                    pair.campaign_engaged_neighbor_signal,
                    candidate.campaign_engaged_neighbor_signal,
                ),
                ("raw_message_user_fit", pair.raw_message_user_fit, candidate.raw_message_user_fit),
                (
                    "normalized_message_user_fit",
                    pair.normalized_message_user_fit,
                    candidate.normalized_message_user_fit,
                ),
                (
                    "personalized_delivery_score",
                    pair.personalized_delivery_score,
                    candidate.personalized_delivery_score,
                ),
            ):
                if not _close_enough(pair_value, candidate_value):
                    raise ValueError(
                        f"pair row {pair.pair_id} {field_name} does not match candidate evidence"
                    )

    def _feedback_effect(
        self,
        *,
        candidates_by_batch: Mapping[tuple[str, int], Sequence[_CandidateRow]],
        delivery_capacity: int,
        message_order: Sequence[str],
        message_title_by_id: Mapping[str, str],
        time_steps: Sequence[int],
    ) -> dict[str, Any]:
        per_message: dict[str, Any] = {}
        distinct_added_user_ids: set[str] = set()
        distinct_removed_user_ids: set[str] = set()
        distinct_changed_user_ids: set[str] = set()
        changed_message_batch_count = 0
        for message_id in message_order:
            message_title = message_title_by_id.get(message_id, message_id)
            message_batches: list[dict[str, Any]] = []
            message_added_user_ids: set[str] = set()
            message_removed_user_ids: set[str] = set()
            message_changed_user_ids: set[str] = set()
            changed_batches = 0
            for time_step in time_steps:
                batch_rows = sorted(
                    candidates_by_batch[(message_id, time_step)],
                    key=lambda row: row.ranking_position,
                )
                top_count = min(delivery_capacity, len(batch_rows))
                full_top_user_ids = [row.user_id for row in batch_rows[:top_count]]
                no_feedback_ranked = sorted(
                    batch_rows,
                    key=lambda row: (
                        -(
                            _BASE_NETWORK_WEIGHT * row.base_network_relevance
                            + _MESSAGE_FIT_WEIGHT * row.normalized_message_user_fit
                        ),
                        row.user_id,
                    ),
                )
                no_feedback_top_user_ids = [row.user_id for row in no_feedback_ranked[:top_count]]
                full_top_set = set(full_top_user_ids)
                no_feedback_top_set = set(no_feedback_top_user_ids)
                overlap_user_ids = [user_id for user_id in full_top_user_ids if user_id in no_feedback_top_set]
                feedback_added_user_ids = [user_id for user_id in full_top_user_ids if user_id not in no_feedback_top_set]
                feedback_removed_user_ids = [user_id for user_id in no_feedback_top_user_ids if user_id not in full_top_set]
                top_selection_changed = full_top_set != no_feedback_top_set
                if top_selection_changed:
                    changed_message_batch_count += 1
                    changed_batches += 1
                message_added_user_ids.update(feedback_added_user_ids)
                message_removed_user_ids.update(feedback_removed_user_ids)
                message_changed_user_ids.update(feedback_added_user_ids)
                message_changed_user_ids.update(feedback_removed_user_ids)
                distinct_added_user_ids.update(feedback_added_user_ids)
                distinct_removed_user_ids.update(feedback_removed_user_ids)
                distinct_changed_user_ids.update(feedback_added_user_ids)
                distinct_changed_user_ids.update(feedback_removed_user_ids)
                message_batches.append(
                    {
                        "time_step": time_step,
                        "eligible_users": len(batch_rows),
                        "top_count": top_count,
                        "full_ranking_top_user_ids": full_top_user_ids,
                        "no_feedback_top_user_ids": no_feedback_top_user_ids,
                        "top_overlap_count": len(overlap_user_ids),
                        "top_overlap_user_ids": overlap_user_ids,
                        "feedback_added_user_ids": feedback_added_user_ids,
                        "feedback_removed_user_ids": feedback_removed_user_ids,
                        "top_selection_changed": top_selection_changed,
                    }
                )
            per_message[message_id] = {
                "message_title": message_title,
                "changed_batch_count": changed_batches,
                "distinct_feedback_added_user_ids": sorted(message_added_user_ids),
                "distinct_feedback_removed_user_ids": sorted(message_removed_user_ids),
                "distinct_changed_user_ids": sorted(message_changed_user_ids),
                "batches": message_batches,
            }
        return {
            "descriptive_only": True,
            "non_causal": True,
            "same_candidate_set_and_frozen_state": True,
            "calls_decision_adapter": False,
            "advances_runtime_state": False,
            "full_precision_ranking": True,
            "feedback_component_zeroed_only": True,
            "per_message": per_message,
            "overall": {
                "message_batch_count": sum(len(time_steps) for _message_id in message_order),
                "changed_message_batch_count": changed_message_batch_count,
                "distinct_feedback_added_user_ids": sorted(distinct_added_user_ids),
                "distinct_feedback_removed_user_ids": sorted(distinct_removed_user_ids),
                "distinct_changed_user_ids": sorted(distinct_changed_user_ids),
            },
        }


def validate_concurrent_validation_summary(
    validation_summary: Mapping[str, Any],
    diagnostics: ConcurrentCampaignDiagnosticArtifacts | Mapping[str, Any],
) -> None:
    payload = diagnostics.payload if isinstance(diagnostics, ConcurrentCampaignDiagnosticArtifacts) else dict(diagnostics)
    counts = _mapping_field(validation_summary, "counts", "concurrent validation")
    coverage = _mapping_field(validation_summary, "campaign_exposure_coverage", "concurrent validation")
    per_message = _mapping_field(validation_summary, "per_message", "concurrent validation")
    funnel = _mapping_field(payload, "campaign_funnel", "campaign diagnostics")
    sensitivity = _mapping_field(payload, "demographic_decision_sensitivity", "campaign diagnostics")
    funnel_primary = _mapping_field(funnel, "primary", "campaign funnel")
    funnel_shadow = _mapping_field(funnel, "shadow", "campaign funnel")
    funnel_per_message = _mapping_field(funnel, "per_message", "campaign funnel")

    _expect_equal(counts.get("sample_users"), funnel.get("sample_users"), "counts.sample_users")
    _expect_equal(
        counts.get("eligible_user_message_pairs"),
        funnel.get("eligible_user_message_pairs"),
        "counts.eligible_user_message_pairs",
    )
    _expect_equal(counts.get("actual_exposures"), funnel.get("actual_exposures"), "counts.actual_exposures")
    _expect_equal(
        counts.get("distinct_exposed_users"),
        funnel.get("distinct_exposed_users"),
        "counts.distinct_exposed_users",
    )
    _expect_equal(
        counts.get("primary_attempted"),
        funnel_primary.get("attempted"),
        "counts.primary_attempted",
    )
    _expect_equal(
        counts.get("primary_successes"),
        funnel_primary.get("succeeded"),
        "counts.primary_successes",
    )
    _expect_equal(
        counts.get("primary_failures"),
        funnel_primary.get("provider_failed"),
        "counts.primary_failures",
    )
    _expect_equal(
        counts.get("shadow_attempted"),
        funnel_shadow.get("attempted"),
        "counts.shadow_attempted",
    )
    _expect_equal(
        counts.get("shadow_successes"),
        funnel_shadow.get("succeeded"),
        "counts.shadow_successes",
    )
    _expect_equal(
        counts.get("shadow_failures"),
        funnel_shadow.get("provider_failed"),
        "counts.shadow_failures",
    )
    if dict(coverage) != dict(funnel.get("campaign_exposure_coverage", {})):
        raise ValueError("campaign exposure coverage does not close with source-row diagnostics")

    pair_terminal_coverage = _mapping_field(
        sensitivity,
        "pair_terminal_coverage",
        "demographic decision sensitivity",
    )
    paired_decision_coverage = _mapping_field(
        sensitivity,
        "paired_decision_coverage",
        "demographic decision sensitivity",
    )
    if not _close_enough(
        _as_float(counts.get("pair_terminal_coverage")),
        _as_float(pair_terminal_coverage.get("value")),
    ):
        raise ValueError("counts.pair_terminal_coverage does not close with source-row diagnostics")
    if not _close_enough(
        _as_float(counts.get("paired_decision_coverage")),
        _as_float(paired_decision_coverage.get("value")),
    ):
        raise ValueError("counts.paired_decision_coverage does not close with source-row diagnostics")

    for message_id in per_message:
        expected = _mapping_field(funnel_per_message, str(message_id), "campaign funnel per_message")
        actual = _mapping_field(per_message, str(message_id), "validation per_message")
        for field_name, diagnostic_field in (
            ("exposures", "exposures"),
            ("primary_successes", "primary_successes"),
            ("primary_failures", "primary_failures"),
            ("shadow_successes", "shadow_successes"),
            ("shadow_failures", "shadow_failures"),
            ("below_delivery_capacity", "below_delivery_capacity"),
        ):
            _expect_equal(actual.get(field_name), expected.get(diagnostic_field), f"per_message.{message_id}.{field_name}")


def _candidate_row(row: Mapping[str, Any]) -> _CandidateRow:
    return _CandidateRow(
        time_step=_as_int(row.get("time_step")),
        message_id=_required_str(row.get("message_id"), "message_id"),
        user_id=_required_str(row.get("user_id"), "user_id"),
        selected=_as_bool(row.get("selected")),
        selection_reason=str(row.get("selection_reason", "") or ""),
        ranking_position=_as_int(row.get("ranking_position")),
        base_network_relevance=_preferred_float(
            row,
            "base_network_relevance_full_precision",
            "base_network_relevance",
        ),
        base_network_relevance_text=_preferred_float_text(
            row,
            "base_network_relevance_full_precision",
            "base_network_relevance",
        ),
        campaign_engaged_neighbor_signal=_preferred_float(
            row,
            "campaign_engaged_neighbor_signal_full_precision",
            "campaign_engaged_neighbor_signal",
        ),
        campaign_engaged_neighbor_signal_text=_preferred_float_text(
            row,
            "campaign_engaged_neighbor_signal_full_precision",
            "campaign_engaged_neighbor_signal",
        ),
        raw_message_user_fit=_preferred_float(
            row,
            "raw_message_user_fit_full_precision",
            "raw_message_user_fit",
        ),
        raw_message_user_fit_text=_preferred_float_text(
            row,
            "raw_message_user_fit_full_precision",
            "raw_message_user_fit",
        ),
        normalized_message_user_fit=_preferred_float(
            row,
            "normalized_message_user_fit_full_precision",
            "normalized_message_user_fit",
        ),
        normalized_message_user_fit_text=_preferred_float_text(
            row,
            "normalized_message_user_fit_full_precision",
            "normalized_message_user_fit",
        ),
        personalized_delivery_score=_preferred_float(
            row,
            "personalized_delivery_score_full_precision",
            "personalized_delivery_score",
        ),
        personalized_delivery_score_text=_preferred_float_text(
            row,
            "personalized_delivery_score_full_precision",
            "personalized_delivery_score",
        ),
    )


def _pair_row(row: Mapping[str, Any]) -> _PairRow:
    return _PairRow(
        pair_id=_required_str(row.get("pair_id"), "pair_id"),
        time_step=_as_int(row.get("time_step")),
        message_id=_required_str(row.get("message_id"), "message_id"),
        message_title=_required_str(row.get("message_title"), "message_title"),
        user_id=_required_str(row.get("user_id"), "user_id"),
        latent_class=_required_str(row.get("latent_class"), "latent_class"),
        selection_reason=str(row.get("selection_reason", "") or ""),
        ranking_position=_as_int(row.get("ranking_position")),
        base_network_relevance=_preferred_float(
            row,
            "base_network_relevance_full_precision",
            "base_network_relevance",
        ),
        base_network_relevance_text=_preferred_float_text(
            row,
            "base_network_relevance_full_precision",
            "base_network_relevance",
        ),
        campaign_engaged_neighbor_signal=_preferred_float(
            row,
            "campaign_engaged_neighbor_signal_full_precision",
            "campaign_engaged_neighbor_signal",
        ),
        campaign_engaged_neighbor_signal_text=_preferred_float_text(
            row,
            "campaign_engaged_neighbor_signal_full_precision",
            "campaign_engaged_neighbor_signal",
        ),
        raw_message_user_fit=_preferred_float(
            row,
            "raw_message_user_fit_full_precision",
            "raw_message_user_fit",
        ),
        raw_message_user_fit_text=_preferred_float_text(
            row,
            "raw_message_user_fit_full_precision",
            "raw_message_user_fit",
        ),
        normalized_message_user_fit=_preferred_float(
            row,
            "normalized_message_user_fit_full_precision",
            "normalized_message_user_fit",
        ),
        normalized_message_user_fit_text=_preferred_float_text(
            row,
            "normalized_message_user_fit_full_precision",
            "normalized_message_user_fit",
        ),
        personalized_delivery_score=_preferred_float(
            row,
            "personalized_delivery_score_full_precision",
            "personalized_delivery_score",
        ),
        personalized_delivery_score_text=_preferred_float_text(
            row,
            "personalized_delivery_score_full_precision",
            "personalized_delivery_score",
        ),
        primary_status=_required_str(row.get("primary_status"), "primary_status"),
        primary_action=str(row.get("primary_action", "") or ""),
        primary_probability=_optional_float(row.get("primary_probability")),
        primary_reason=str(row.get("primary_reason", "") or ""),
        shadow_status=_required_str(row.get("shadow_status"), "shadow_status"),
        shadow_action=str(row.get("shadow_action", "") or ""),
        shadow_probability=_optional_float(row.get("shadow_probability")),
        shadow_reason=str(row.get("shadow_reason", "") or ""),
        pair_terminal_coverage=_as_bool(row.get("pair_terminal_coverage")),
        paired_decision_coverage=_as_bool(row.get("paired_decision_coverage")),
        shadow_gender=_optional_str(row.get("shadow_gender")),
        shadow_age=_optional_str(row.get("shadow_age")),
        shadow_education=_optional_str(row.get("shadow_education")),
        shadow_monthly_income=_optional_str(row.get("shadow_monthly_income")),
    )


def _infer_delivery_capacity(candidates: Sequence[_CandidateRow], pairs: Sequence[_PairRow]) -> int:
    pair_group_sizes = Counter((pair.message_id, pair.time_step) for pair in pairs)
    candidate_selected_sizes = Counter(
        (candidate.message_id, candidate.time_step) for candidate in candidates if candidate.selected
    )
    maxima = [0]
    maxima.extend(pair_group_sizes.values())
    maxima.extend(candidate_selected_sizes.values())
    return max(maxima)


def _message_overlap_summary(
    message_order: Sequence[str],
    overlap_source: Mapping[str, set[str]],
) -> dict[str, Any]:
    pairwise: list[dict[str, Any]] = []
    for index, left_message_id in enumerate(message_order):
        for right_message_id in message_order[index + 1 :]:
            overlap_user_ids = sorted(overlap_source[left_message_id] & overlap_source[right_message_id])
            pairwise.append(
                {
                    "left_message_id": left_message_id,
                    "right_message_id": right_message_id,
                    "overlap_count": len(overlap_user_ids),
                    "overlap_user_ids": overlap_user_ids,
                }
            )
    if not message_order:
        union_user_ids: list[str] = []
        intersection_user_ids: list[str] = []
    else:
        union_user_ids = sorted(set().union(*(overlap_source[message_id] for message_id in message_order)))
        intersection_user_ids = sorted(set.intersection(*(overlap_source[message_id] for message_id in message_order)))
    return {
        "pairwise": pairwise,
        "three_way_intersection_count": len(intersection_user_ids),
        "three_way_intersection_user_ids": intersection_user_ids,
        "distinct_union_count": len(union_user_ids),
        "distinct_union_user_ids": union_user_ids,
    }


def _primary_response_summary(
    message_id: str,
    message_title: str,
    pairs: Sequence[_PairRow],
) -> dict[str, Any]:
    action_counts = {action: 0 for action in ("like", "comment", "share", "ignore", "provider_failed")}
    for pair in pairs:
        if pair.primary_status == "provider_failed":
            action_counts["provider_failed"] += 1
            continue
        if pair.primary_action not in action_counts:
            raise ValueError(f"unexpected primary action in message {message_id}: {pair.primary_action!r}")
        action_counts[pair.primary_action] += 1
    positive_actions = sum(action_counts[action] for action in _POSITIVE_ACTIONS)
    primary_successes = sum(pair.primary_status == "succeeded" for pair in pairs)
    return {
        "message_title": message_title,
        "action_counts": action_counts,
        "positive_actions": positive_actions,
        "exposure_engagement_rate": _rate(positive_actions, len(pairs)),
        "decision_engagement_rate": _rate(positive_actions, primary_successes),
    }


def _demographic_sensitivity(pairs: Sequence[_PairRow]) -> dict[str, Any]:
    exposures = len(pairs)
    pair_terminal_numerator = sum(pair.pair_terminal_coverage for pair in pairs)
    paired_decision_numerator = sum(pair.paired_decision_coverage for pair in pairs)
    dual_success_pairs = [
        pair
        for pair in pairs
        if pair.primary_status == "succeeded" and pair.shadow_status == "succeeded"
    ]
    engage_disagreements = sum(
        (pair.primary_action != "ignore") != (pair.shadow_action != "ignore") for pair in dual_success_pairs
    )
    action_transition_counts = Counter(
        f"{pair.primary_action}->{pair.shadow_action}" for pair in dual_success_pairs
    )
    absolute_probability_delta_sum = sum(
        abs((pair.primary_probability or 0.0) - (pair.shadow_probability or 0.0))
        for pair in dual_success_pairs
    )
    flagged_pairs: list[dict[str, Any]] = []
    shadow_success_pairs = [pair for pair in pairs if pair.shadow_status == "succeeded"]
    for pair in shadow_success_pairs:
        matches = _screen_shadow_reason(pair)
        if not matches:
            continue
        flagged_pairs.append(
            {
                "pair_id": pair.pair_id,
                "time_step": pair.time_step,
                "message_id": pair.message_id,
                "message_title": pair.message_title,
                "user_id": pair.user_id,
                "shadow_reason": pair.shadow_reason,
                "matched_spans": [
                    {
                        "field_name": match.field_name,
                        "match_type": match.match_type,
                        "matched_span": match.matched_span,
                    }
                    for match in matches
                ],
            }
        )
    return {
        "descriptive_only": True,
        "non_causal": True,
        "pair_terminal_coverage": _rate(pair_terminal_numerator, exposures),
        "paired_decision_coverage": _rate(paired_decision_numerator, exposures),
        "dual_success_pair_count": len(dual_success_pairs),
        "engage_disagreement_rate": _rate(engage_disagreements, len(dual_success_pairs)),
        "action_transition_counts": dict(sorted(action_transition_counts.items())),
        "mean_absolute_probability_delta": {
            "absolute_delta_sum": _round_metric(absolute_probability_delta_sum),
            "denominator": len(dual_success_pairs),
            "value": _round_metric(
                0.0 if not dual_success_pairs else absolute_probability_delta_sum / len(dual_success_pairs)
            ),
        },
        "reason_screening": {
            "method_version": CONCURRENT_DEMOGRAPHIC_REASON_SCREENING_METHOD_VERSION,
            "screened_shadow_pairs": len(shadow_success_pairs),
            "screened_non_empty_shadow_reasons": sum(bool(pair.shadow_reason.strip()) for pair in shadow_success_pairs),
            "flagged_pair_count": len(flagged_pairs),
            "flagged_pairs": flagged_pairs,
            "limitations": (
                "Deterministic lexical screening only checks persisted Shadow reasons for shown demographic "
                "labels/values and predeclared direct-causal phrases. It is not a full semantic bias classifier."
            ),
        },
    }


def _screen_shadow_reason(pair: _PairRow) -> list[_ReasonMatch]:
    reason = pair.shadow_reason.strip()
    if not reason:
        return []
    matches: list[_ReasonMatch] = []
    for field_name, definition in _DEMOGRAPHIC_FIELD_DEFINITIONS.items():
        code = getattr(pair, field_name)
        if code is None:
            continue
        display_value = definition.value_labels.get(code)
        if display_value is None:
            continue
        label_match = _first_substring_match(reason, definition.label_tokens)
        if label_match is not None:
            matches.append(_ReasonMatch(field_name=field_name, match_type="label_reference", matched_span=label_match))
        value_match = _first_display_value_match(reason, display_value)
        if value_match is not None:
            matches.append(_ReasonMatch(field_name=field_name, match_type="value_reference", matched_span=value_match))
        causal_match = _first_direct_causal_match(reason, (*definition.label_tokens, display_value))
        if causal_match is not None:
            matches.append(_ReasonMatch(field_name=field_name, match_type="direct_causal_phrase", matched_span=causal_match))
    deduped: list[_ReasonMatch] = []
    seen: set[tuple[str, str, str]] = set()
    for match in matches:
        key = (match.field_name, match.match_type, match.matched_span)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(match)
    return deduped


def _first_substring_match(text: str, tokens: Sequence[str]) -> str | None:
    for token in sorted(tokens, key=len, reverse=True):
        if token and token in text:
            return token
    return None


def _first_display_value_match(text: str, value: str) -> str | None:
    for pattern in _display_value_patterns(value):
        match = pattern.search(text)
        if match is not None:
            return match.group(0)
    return None


def _display_value_patterns(value: str) -> tuple[re.Pattern[str], ...]:
    escaped = re.escape(value)
    boundary = f"[{_PUNCTUATION_CHARS}]"
    if re.search(rf"[{_CJK_CHARS}]", value):
        return (
            re.compile(rf"{escaped}(?=$|{boundary})"),
            re.compile(rf"(?:是|为|像|作为|身为){escaped}(?=$|{boundary})"),
        )
    return (re.compile(rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])"),)


def _first_direct_causal_match(text: str, tokens: Sequence[str]) -> str | None:
    token_group = "|".join(re.escape(token) for token in sorted(tokens, key=len, reverse=True) if token)
    if not token_group:
        return None
    causal_group = "|".join(re.escape(token) for token in _CAUSAL_TOKENS)
    patterns = (
        re.compile(rf"(?:{causal_group}).{{0,8}}(?:{token_group})"),
        re.compile(rf"(?:{token_group}).{{0,8}}(?:{causal_group})"),
    )
    for pattern in patterns:
        match = pattern.search(text)
        if match is not None:
            return match.group(0)
    return None


def _distribution_summary(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "mean": None, "max": None}
    return {
        "count": len(values),
        "min": _round_metric(min(values)),
        "mean": _round_metric(sum(values) / len(values)),
        "max": _round_metric(max(values)),
    }


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": _round_metric(0.0 if denominator == 0 else numerator / denominator),
    }


def _mapping_field(container: Mapping[str, Any], field_name: str, scope: str) -> Mapping[str, Any]:
    value = container.get(field_name)
    if not isinstance(value, Mapping):
        raise ValueError(f"{scope} is missing {field_name}")
    return value


def _required_mapping(value: Any, field_name: str, scope: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{scope} is missing {field_name}")
    return value


def _expect_equal(actual: Any, expected: Any, field_name: str) -> None:
    if actual != expected:
        raise ValueError(f"{field_name} does not close with source-row diagnostics")


def _preferred_float(row: Mapping[str, Any], full_precision_field: str, fallback_field: str) -> float:
    if row.get(full_precision_field) not in (None, ""):
        return _as_float(row.get(full_precision_field))
    return _as_float(row.get(fallback_field))


def _preferred_float_text(row: Mapping[str, Any], full_precision_field: str, fallback_field: str) -> str:
    value = row.get(full_precision_field)
    if value not in (None, ""):
        return _stringify_number(value)
    return _format_full_precision(_as_float(row.get(fallback_field)))


def _stable_unique(values: Any) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw_value in values:
        value = str(raw_value)
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "false"}:
            return lowered == "true"
    raise ValueError(f"expected boolean field, got {value!r}")


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError(f"expected integer field, got {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        return int(value.strip())
    raise ValueError(f"expected integer field, got {value!r}")


def _as_float(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError(f"expected float field, got {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        return float(value.strip())
    raise ValueError(f"expected float field, got {value!r}")


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return _as_float(value)


def _required_str(value: Any, field_name: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ValueError(f"missing required string field {field_name}")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    raise ValueError(f"expected string or null field, got {value!r}")


def _round_metric(value: float) -> float:
    return round(value, 12)


def _format_full_precision(value: float) -> str:
    return format(value, ".17g")


def _stringify_number(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return _format_full_precision(_as_float(value))


def _close_enough(left: float, right: float) -> bool:
    return abs(left - right) <= 1e-12
