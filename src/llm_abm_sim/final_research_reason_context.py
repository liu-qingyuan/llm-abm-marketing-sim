from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .schemas import PeerContext

PEER_CONTEXT_COUNTERS = (
    "engaged_neighbors",
    "exposed_neighbors",
    "influential_engaged_neighbors",
    "visible_likes",
    "visible_comments",
    "visible_shares",
)


class ExactReasonFacts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    decision_row_count: int = Field(ge=0)
    non_empty_reason_count: int = Field(ge=0)
    empty_reason_count: int = Field(ge=0)
    exact_unique_reason_count: int = Field(ge=0)
    exact_duplicate_row_count: int = Field(ge=0)
    maximum_exact_reason_frequency: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_reason_counts(self) -> ExactReasonFacts:
        if self.decision_row_count != self.non_empty_reason_count + self.empty_reason_count:
            raise ValueError("reason counts must cover every Decision row")
        if self.exact_duplicate_row_count != self.non_empty_reason_count - self.exact_unique_reason_count:
            raise ValueError("exact duplicate rows must equal non-empty rows minus exact unique reasons")
        if self.non_empty_reason_count == 0 and self.maximum_exact_reason_frequency != 0:
            raise ValueError("maximum exact reason frequency must be zero when no non-empty reason exists")
        if (
            self.non_empty_reason_count > 0
            and not 1 <= self.maximum_exact_reason_frequency <= self.non_empty_reason_count
        ):
            raise ValueError("maximum exact reason frequency is outside the non-empty reason denominator")
        return self


class DecisionVisiblePeerContextAggregate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    context_count: int = Field(ge=0)
    neutral_context_count: int = Field(ge=0)
    non_neutral_context_count: int = Field(ge=0)
    counter_totals: dict[str, int]

    @model_validator(mode="after")
    def _validate_context_counts(self) -> DecisionVisiblePeerContextAggregate:
        if set(self.counter_totals) != set(PEER_CONTEXT_COUNTERS):
            raise ValueError("PeerContext aggregate must contain the six Decision-visible counters exactly once")
        if any(type(value) is not int or value < 0 for value in self.counter_totals.values()):
            raise ValueError("PeerContext counter totals must be non-negative strict integers")
        if self.context_count != self.neutral_context_count + self.non_neutral_context_count:
            raise ValueError("neutral and non-neutral PeerContext counts must cover every context")
        if not any(self.counter_totals.values()) and self.neutral_context_count != self.context_count:
            raise ValueError("zero PeerContext totals require every context to be neutral")
        return self


class SelectedRankingContextAggregate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    selected_candidate_count: int = Field(ge=0)
    zero_engaged_neighbor_count: int = Field(ge=0)
    positive_engaged_neighbor_count: int = Field(ge=0)
    engaged_neighbor_count_total: int = Field(ge=0)
    maximum_engaged_neighbor_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_ranking_counts(self) -> SelectedRankingContextAggregate:
        if self.selected_candidate_count != self.zero_engaged_neighbor_count + self.positive_engaged_neighbor_count:
            raise ValueError("zero and positive Ranking context counts must cover every selected candidate")
        if self.selected_candidate_count == 0 and (
            self.engaged_neighbor_count_total != 0 or self.maximum_engaged_neighbor_count != 0
        ):
            raise ValueError("empty selected Ranking context must have zero totals")
        if self.maximum_engaged_neighbor_count > self.engaged_neighbor_count_total:
            raise ValueError("maximum engaged-neighbor count cannot exceed the aggregate total")
        return self


class ReasonContextDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["final-research-reason-context-diagnostics-v1"] = (
        "final-research-reason-context-diagnostics-v1"
    )
    exact_reason_facts: ExactReasonFacts
    decision_visible_peer_context: DecisionVisiblePeerContextAggregate
    selected_ranking_context: SelectedRankingContextAggregate

    @model_validator(mode="after")
    def _validate_context_denominators(self) -> ReasonContextDiagnostics:
        if self.decision_visible_peer_context.context_count != self.selected_ranking_context.selected_candidate_count:
            raise ValueError("PeerContext count must equal selected Ranking count")
        return self


def build_reason_context_diagnostics(
    *,
    decision_rows: Sequence[Mapping[str, object]],
    peer_contexts: Sequence[PeerContext],
    candidate_rows: Sequence[Mapping[str, object]],
) -> ReasonContextDiagnostics:
    return ReasonContextDiagnostics(
        exact_reason_facts=derive_exact_reason_facts(decision_rows),
        decision_visible_peer_context=derive_peer_context_aggregate(peer_contexts),
        selected_ranking_context=derive_selected_ranking_context(candidate_rows),
    )


def derive_exact_reason_facts(decision_rows: Sequence[Mapping[str, object]]) -> ExactReasonFacts:
    reasons: list[str] = []
    for row in decision_rows:
        reason = row.get("reason", "")
        if not isinstance(reason, str):
            raise ValueError("persisted Decision reason must be a string")
        reasons.append(reason)
    non_empty_reasons = [reason for reason in reasons if reason != ""]
    frequencies = Counter(non_empty_reasons)
    return ExactReasonFacts(
        decision_row_count=len(reasons),
        non_empty_reason_count=len(non_empty_reasons),
        empty_reason_count=len(reasons) - len(non_empty_reasons),
        exact_unique_reason_count=len(frequencies),
        exact_duplicate_row_count=len(non_empty_reasons) - len(frequencies),
        maximum_exact_reason_frequency=max(frequencies.values(), default=0),
    )


def derive_peer_context_aggregate(peer_contexts: Sequence[PeerContext]) -> DecisionVisiblePeerContextAggregate:
    totals = {field_name: 0 for field_name in PEER_CONTEXT_COUNTERS}
    neutral_count = 0
    for context in peer_contexts:
        values = [getattr(context, field_name) for field_name in PEER_CONTEXT_COUNTERS]
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("Decision-visible PeerContext counters must be non-negative strict integers")
        for field_name, value in zip(PEER_CONTEXT_COUNTERS, values, strict=True):
            totals[field_name] += value
        if not any(values):
            neutral_count += 1
    return DecisionVisiblePeerContextAggregate(
        context_count=len(peer_contexts),
        neutral_context_count=neutral_count,
        non_neutral_context_count=len(peer_contexts) - neutral_count,
        counter_totals=totals,
    )


def derive_selected_ranking_context(
    candidate_rows: Sequence[Mapping[str, object]],
) -> SelectedRankingContextAggregate:
    counts: list[int] = []
    for row in candidate_rows:
        if not _strict_selected(row.get("selected")):
            continue
        counts.append(_strict_non_negative_int(row.get("engaged_neighbor_count"), "engaged_neighbor_count"))
    zero_count = sum(value == 0 for value in counts)
    return SelectedRankingContextAggregate(
        selected_candidate_count=len(counts),
        zero_engaged_neighbor_count=zero_count,
        positive_engaged_neighbor_count=len(counts) - zero_count,
        engaged_neighbor_count_total=sum(counts),
        maximum_engaged_neighbor_count=max(counts, default=0),
    )


def _strict_selected(value: object) -> bool:
    if type(value) is bool:
        return value
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError("Ranking selected must be true or false")


def _strict_non_negative_int(value: object, label: str) -> int:
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise ValueError(f"{label} must be a non-negative strict integer")
