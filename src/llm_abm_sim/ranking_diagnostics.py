from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RankingDiagnosticArtifacts:
    payload: dict[str, Any]
    summary: dict[str, Any]
    ablation_rows: list[dict[str, Any]]
    sensitivity_rows: list[dict[str, Any]]


@dataclass(frozen=True)
class RankingWeights:
    base_network: float
    engaged_neighbor: float
    tag_affinity: float

    def score(self, candidate: _CandidateEvidence) -> float:
        return (
            self.base_network * candidate.base_network_relevance
            + self.engaged_neighbor * candidate.engaged_neighbor_signal
            + self.tag_affinity * candidate.historical_tag_affinity
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "base_network": self.base_network,
            "engaged_neighbor": self.engaged_neighbor,
            "tag_affinity": self.tag_affinity,
        }


@dataclass(frozen=True)
class _CandidateEvidence:
    user_id: str
    persisted_rank: int
    persisted_selected: bool
    base_network_relevance: float
    engaged_neighbor_signal: float
    historical_tag_affinity: float


@dataclass(frozen=True)
class _RankingWeightVariant:
    variant_id: str
    weights: RankingWeights


MAIN_RANKING_WEIGHTS = RankingWeights(base_network=0.50, engaged_neighbor=0.30, tag_affinity=0.20)
WEAKER_NETWORK_RANKING_WEIGHTS = RankingWeights(base_network=0.40, engaged_neighbor=0.20, tag_affinity=0.40)
NO_NETWORK_RANKING_WEIGHTS = RankingWeights(base_network=0.0, engaged_neighbor=0.0, tag_affinity=1.0)
RANKING_WEIGHT_VARIANTS = (
    _RankingWeightVariant("main_50_30_20", MAIN_RANKING_WEIGHTS),
    _RankingWeightVariant("weaker_network_40_20_40", WEAKER_NETWORK_RANKING_WEIGHTS),
    _RankingWeightVariant("no_network_0_0_100", NO_NETWORK_RANKING_WEIGHTS),
)


class RankingDiagnostics:
    """Compare deterministic rankings derived from frozen batch evidence."""

    def __init__(
        self,
        *,
        delivery_capacity: int,
    ) -> None:
        if delivery_capacity < 1:
            raise ValueError("delivery_capacity must be at least 1")
        self.delivery_capacity = delivery_capacity

    def build(
        self,
        *,
        candidate_rows: Sequence[Mapping[str, Any]],
        holdout_diagnostic: Mapping[str, Any],
        batch_time_steps: Sequence[int] | None = None,
    ) -> RankingDiagnosticArtifacts:
        batches: dict[int, list[_CandidateEvidence]] = defaultdict(list)
        for time_step in batch_time_steps or ():
            batches[int(time_step)]
        for row in candidate_rows:
            batches[int(row["time_step"])].append(
                _CandidateEvidence(
                    user_id=str(row["user_id"]),
                    persisted_rank=int(row["ranking_position"]),
                    persisted_selected=_as_bool(row["selected"]),
                    base_network_relevance=float(row["base_network_relevance"]),
                    engaged_neighbor_signal=float(row["engaged_neighbor_signal"]),
                    historical_tag_affinity=float(row["historical_tag_affinity"]),
                )
            )

        paired_batches = [self._compare_batch(time_step, batches[time_step]) for time_step in sorted(batches)]
        sensitivity_variants = [self._sensitivity_variant(variant, batches) for variant in RANKING_WEIGHT_VARIANTS]
        batches_with_top_selection_change = sum(
            bool(batch["network_added_user_ids"] or batch["network_removed_user_ids"])
            for batch in paired_batches
        )
        top_selection_changed = batches_with_top_selection_change > 0
        ablation_rows = _ablation_rows(paired_batches, batches)
        sensitivity_rows = _sensitivity_rows(sensitivity_variants)
        summary = {
            "schema_version": "ranking-diagnostics-summary-v2",
            "diagnostic_decision_adapter_calls": 0,
            "counts": {
                "batches": len(paired_batches),
                "ablation_rows": len(ablation_rows),
                "sensitivity_rows": len(sensitivity_rows),
            },
            "recommendation_signal_inclusion": {
                "network_signals_in_formula": (
                    MAIN_RANKING_WEIGHTS.base_network > 0.0 or MAIN_RANKING_WEIGHTS.engaged_neighbor > 0.0
                ),
                "main_weights": MAIN_RANKING_WEIGHTS.as_dict(),
                "meaning": (
                    "Network signals are included in the predeclared ranking formula; inclusion alone does not "
                    "establish an observed result effect."
                ),
            },
            "observed_recommendation_signal_effect": {
                "top_selection_changed": top_selection_changed,
                "batches_with_top_selection_change": batches_with_top_selection_change,
                "meaning": (
                    "The paired no-network shadow ranking changed at least one frozen-batch delivery selection."
                    if top_selection_changed
                    else "The network signals were included but changed no frozen-batch delivery selection."
                ),
            },
        }
        return RankingDiagnosticArtifacts(
            payload={
                "schema_version": "ranking-diagnostics-v2",
                "paired_ablation": {
                    "same_candidate_set_and_frozen_state": True,
                    "shadow_ranking_only": True,
                    "advances_user_state": False,
                    "calls_decision_adapter": False,
                    "complete_counterfactual_trajectory": False,
                    "rank_delta_definition": (
                        "network_rank_delta = no_network_rank - full_rank; positive values mean the network "
                        "signals improved the user's full-ranking position"
                    ),
                    "batches": paired_batches,
                },
                "weight_sensitivity": {
                    "variants": sensitivity_variants,
                    "parameter_search_performed": False,
                    "reuses_persisted_candidate_evidence": True,
                    "diagnostic_decision_adapter_calls": 0,
                },
                "historical_top20_diagnostic": _historical_top20_diagnostic(holdout_diagnostic),
                "summary": summary,
            },
            summary=summary,
            ablation_rows=ablation_rows,
            sensitivity_rows=sensitivity_rows,
        )

    def _compare_batch(self, time_step: int, evidence: Sequence[_CandidateEvidence]) -> dict[str, Any]:
        no_network_ranked = _rank(evidence, NO_NETWORK_RANKING_WEIGHTS)
        persisted_ranked = sorted(evidence, key=lambda candidate: candidate.persisted_rank)
        persisted_user_ids = [candidate.user_id for candidate in persisted_ranked]
        if len(set(persisted_user_ids)) != len(persisted_user_ids):
            raise ValueError(f"batch {time_step} contains duplicate candidate user ids")
        if [candidate.persisted_rank for candidate in persisted_ranked] != list(range(1, len(evidence) + 1)):
            raise ValueError(f"batch {time_step} persisted ranks must be contiguous from 1")

        top_count = min(self.delivery_capacity, len(evidence))
        full_top = persisted_user_ids[:top_count]
        persisted_selected = [candidate.user_id for candidate in persisted_ranked if candidate.persisted_selected]
        if persisted_selected != full_top:
            raise ValueError(f"batch {time_step} persisted selection does not match full-ranking delivery capacity")
        no_network_user_ids = [candidate.user_id for candidate in no_network_ranked]
        no_network_top = no_network_user_ids[:top_count]
        full_top_set = set(full_top)
        no_network_top_set = set(no_network_top)
        full_positions = {user_id: rank for rank, user_id in enumerate(persisted_user_ids, start=1)}
        no_network_positions = {user_id: rank for rank, user_id in enumerate(no_network_user_ids, start=1)}

        return {
            "time_step": time_step,
            "eligible_count": len(evidence),
            "candidate_user_ids": persisted_user_ids,
            "full_top_user_ids": full_top,
            "no_network_top_user_ids": no_network_top,
            "top_overlap_user_ids": [user_id for user_id in full_top if user_id in no_network_top_set],
            "top_overlap_count": len(full_top_set & no_network_top_set),
            "network_added_user_ids": [user_id for user_id in full_top if user_id not in no_network_top_set],
            "network_removed_user_ids": [user_id for user_id in no_network_top if user_id not in full_top_set],
            "top_selection_changed": full_top_set != no_network_top_set,
            "rank_deltas": [
                {
                    "user_id": user_id,
                    "full_rank": full_positions[user_id],
                    "no_network_rank": no_network_positions[user_id],
                    "network_rank_delta": no_network_positions[user_id] - full_positions[user_id],
                }
                for user_id in persisted_user_ids
            ],
        }

    def _sensitivity_variant(
        self,
        variant: _RankingWeightVariant,
        batches: Mapping[int, Sequence[_CandidateEvidence]],
    ) -> dict[str, Any]:
        main_top_by_step = {
            time_step: [candidate.user_id for candidate in sorted(evidence, key=lambda item: item.persisted_rank)][
                : min(self.delivery_capacity, len(evidence))
            ]
            for time_step, evidence in batches.items()
        }
        variant_batches: list[dict[str, object]] = []
        for time_step in sorted(batches):
            evidence = batches[time_step]
            top_count = min(self.delivery_capacity, len(evidence))
            ranked = (
                sorted(evidence, key=lambda candidate: candidate.persisted_rank)
                if variant.weights == MAIN_RANKING_WEIGHTS
                else _rank(evidence, variant.weights)
            )
            top_user_ids = [candidate.user_id for candidate in ranked][:top_count]
            main_top = main_top_by_step[time_step]
            main_set = set(main_top)
            top_set = set(top_user_ids)
            variant_batches.append(
                {
                    "time_step": time_step,
                    "eligible_count": len(evidence),
                    "top_user_ids": top_user_ids,
                    "overlap_with_main_user_ids": [user_id for user_id in main_top if user_id in top_set],
                    "added_vs_main_user_ids": [user_id for user_id in top_user_ids if user_id not in main_set],
                    "removed_vs_main_user_ids": [user_id for user_id in main_top if user_id not in top_set],
                }
            )
        return {
            "variant_id": variant.variant_id,
            "weights": variant.weights.as_dict(),
            "batches": variant_batches,
        }


def _rank(
    evidence: Sequence[_CandidateEvidence],
    weights: RankingWeights,
) -> list[_CandidateEvidence]:
    return sorted(
        evidence,
        key=lambda candidate: (
            -weights.score(candidate),
            candidate.user_id,
        ),
    )


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise ValueError(f"expected boolean candidate selection, got {value!r}")


def _historical_top20_diagnostic(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "observed_holdout_participant_count": int(source.get("observed_holdout_participant_count", 0)),
        "observed_holdout_participant_ids": list(source.get("observed_holdout_participant_ids", [])),
        "model_recommended_user_count": int(source.get("model_recommended_user_count", 0)),
        "model_recommended_user_ids": list(source.get("model_recommended_user_ids", [])),
        "intersection_count": int(source.get("intersection_count", 0)),
        "intersection_user_ids": list(source.get("intersection_user_ids", [])),
        "observed_participant_signal_coverage": dict(source.get("observed_participant_signal_coverage", {})),
        "positive_sample_sparsity_limit": True,
        "real_exposure_denominator_available": False,
        "holdout_revealed_after_ranking": True,
        "diagnostic_only": True,
        "production_accuracy_claim": False,
        "limitations": (
            "Observed target participants are sparse positive evidence revealed only after holdout-safe ranking; "
            "the dataset has no real exposure denominator."
        ),
    }


def _ablation_rows(
    paired_batches: Sequence[Mapping[str, Any]],
    batches: Mapping[int, Sequence[_CandidateEvidence]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for batch in paired_batches:
        time_step = int(batch["time_step"])
        evidence_by_user = {candidate.user_id: candidate for candidate in batches[time_step]}
        full_top = set(batch["full_top_user_ids"])
        no_network_top = set(batch["no_network_top_user_ids"])
        for rank_delta in batch["rank_deltas"]:
            user_id = str(rank_delta["user_id"])
            evidence = evidence_by_user[user_id]
            full_selected = user_id in full_top
            no_network_selected = user_id in no_network_top
            rows.append(
                {
                    "time_step": time_step,
                    "user_id": user_id,
                    "full_rank": rank_delta["full_rank"],
                    "no_network_rank": rank_delta["no_network_rank"],
                    "network_rank_delta": rank_delta["network_rank_delta"],
                    "full_selected": _csv_bool(full_selected),
                    "no_network_selected": _csv_bool(no_network_selected),
                    "selection_effect": _selection_effect(full_selected, no_network_selected),
                    "base_network_relevance": round(evidence.base_network_relevance, 12),
                    "engaged_neighbor_signal": round(evidence.engaged_neighbor_signal, 12),
                    "historical_tag_affinity": round(evidence.historical_tag_affinity, 12),
                }
            )
    return rows


def _sensitivity_rows(variants: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for variant in variants:
        weights = variant["weights"]
        assert isinstance(weights, Mapping)
        for batch in variant["batches"]:
            assert isinstance(batch, Mapping)
            top_user_ids = list(batch["top_user_ids"])
            overlap_user_ids = list(batch["overlap_with_main_user_ids"])
            rows.append(
                {
                    "time_step": batch["time_step"],
                    "variant_id": variant["variant_id"],
                    "base_network_weight": weights["base_network"],
                    "engaged_neighbor_weight": weights["engaged_neighbor"],
                    "tag_affinity_weight": weights["tag_affinity"],
                    "eligible_count": batch["eligible_count"],
                    "selected_count": len(top_user_ids),
                    "top_user_ids": _json_cell(top_user_ids),
                    "overlap_with_main_count": len(overlap_user_ids),
                    "overlap_with_main_user_ids": _json_cell(overlap_user_ids),
                    "added_vs_main_user_ids": _json_cell(batch["added_vs_main_user_ids"]),
                    "removed_vs_main_user_ids": _json_cell(batch["removed_vs_main_user_ids"]),
                }
            )
    return rows


def _selection_effect(full_selected: bool, no_network_selected: bool) -> str:
    if full_selected and not no_network_selected:
        return "network_added"
    if no_network_selected and not full_selected:
        return "network_removed"
    if full_selected:
        return "retained"
    return "not_selected"


def _csv_bool(value: bool) -> str:
    return "true" if value else "false"


def _json_cell(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
