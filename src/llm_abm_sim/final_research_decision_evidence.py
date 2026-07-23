from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .decision import CachedDecisionAdapter, LLMDecisionAdapter, RuleBasedDecisionAdapter
from .provider_accounting import (
    ProviderAccounting,
    empty_provider_accounting,
    provider_accounting_delta,
)
from .provider_evidence import allowlisted_provider_evidence
from .providers.openai_compatible import OpenAICompatibleDecisionAdapter

DecisionExecutionMode = Literal["rule_based", "mock_provider", "live_provider"]
DecisionSamplingStatus = Literal["validation_run", "persisted_seed_first_formal_run"]
EngagementAction = Literal["like", "comment", "share", "ignore"]
_ACTIONS: tuple[EngagementAction, ...] = ("like", "comment", "share", "ignore")
_ACTION_SET = frozenset(_ACTIONS)


class DecisionAdapterClassification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    decision_execution_mode: DecisionExecutionMode
    adapter_chain: list[str]
    live_api_triggered: bool
    provider_metadata: dict[str, object]


class DecisionTerminalCounts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    sample_users: int = Field(ge=0)
    exposed_users: int = Field(ge=0)
    decided_users: int = Field(ge=0)
    provider_failed: int = Field(ge=0)
    below_delivery_capacity: int = Field(ge=0)


class DecisionDegeneracyFlags(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    all_decisions_ignore: bool
    single_action_only: bool
    no_engagement_feedback: bool


class _DecisionRowFacts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    decision_source_counts: dict[str, int]
    action_counts: dict[str, int]
    terminal_counts: DecisionTerminalCounts
    degeneracy_flags: DecisionDegeneracyFlags


class DecisionExecutionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["final-research-decision-execution-evidence-v1"]
    status: Literal["persisted"]
    formal_research_evidence: bool
    decision_execution_mode: DecisionExecutionMode
    adapter_chain: list[str]
    decision_source_counts: dict[str, int]
    action_counts: dict[str, int]
    terminal_counts: DecisionTerminalCounts
    provider_metadata: dict[str, object]
    live_api_triggered: bool
    sampling_status: DecisionSamplingStatus
    degeneracy_flags: DecisionDegeneracyFlags

    @model_validator(mode="after")
    def _validate_closed_evidence(self) -> DecisionExecutionEvidence:
        allowlisted_metadata = allowlisted_provider_evidence(self.provider_metadata)
        if not isinstance(allowlisted_metadata, dict) or allowlisted_metadata != self.provider_metadata:
            raise ValueError("provider metadata must contain only allowlisted, redacted fields")
        if set(self.action_counts) != _ACTION_SET:
            raise ValueError("decision action counts must contain like/comment/share/ignore exactly once")
        if any(value < 0 for value in (*self.action_counts.values(), *self.decision_source_counts.values())):
            raise ValueError("decision evidence counts must be non-negative")
        counts = self.terminal_counts
        if counts.sample_users != counts.exposed_users + counts.below_delivery_capacity:
            raise ValueError(
                "decision terminal invariant failed: sample_users != exposed_users + below_delivery_capacity"
            )
        if counts.exposed_users != counts.decided_users + counts.provider_failed:
            raise ValueError("decision terminal invariant failed: exposed_users != decided_users + provider_failed")
        if counts.decided_users != sum(self.action_counts.values()):
            raise ValueError("decision terminal invariant failed: decided_users != sum(action_counts)")
        if counts.decided_users != sum(self.decision_source_counts.values()):
            raise ValueError("decision source counts do not sum to decided_users")
        is_live = self.decision_execution_mode == "live_provider" and self.live_api_triggered
        if self.formal_research_evidence != is_live:
            raise ValueError("formal research evidence must match actual live provider execution")
        expected_status = "persisted_seed_first_formal_run" if is_live else "validation_run"
        if self.sampling_status != expected_status:
            raise ValueError("sampling status must match actual live provider execution")
        if self.decision_execution_mode == "live_provider" and not self.live_api_triggered:
            raise ValueError("live_provider mode requires an actual provider request invocation")
        if self.decision_execution_mode != "live_provider" and self.live_api_triggered:
            raise ValueError("non-live decision execution mode cannot report a live API invocation")
        return self


class DecisionExecutionEvidenceV2(DecisionExecutionEvidence):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["final-research-decision-execution-evidence-v2"]  # type: ignore[assignment]
    provider_accounting: ProviderAccounting

    @model_validator(mode="after")
    def _validate_provider_accounting(self) -> DecisionExecutionEvidenceV2:
        accounting = self.provider_accounting
        if accounting.successful_decision_count > self.terminal_counts.decided_users:
            raise ValueError("Provider leaf successful Decisions cannot exceed persisted runtime Decisions")
        if self.decision_execution_mode == "rule_based" and accounting != empty_provider_accounting():
            raise ValueError("rule-based Decision evidence cannot contain Provider accounting")
        if (
            self.adapter_chain == ["openai_compatible"]
            and accounting.successful_decision_count != self.terminal_counts.decided_users
        ):
            raise ValueError("bare Provider accounting must cover every persisted runtime Decision")
        if self.decision_execution_mode == "live_provider":
            if not (
                accounting.external_request_invocations
                >= accounting.provider_response_count
                >= accounting.successful_decision_count
            ):
                raise ValueError("live Provider accounting requires invocations >= responses >= successful Decisions")
        elif accounting.external_request_invocations != 0:
            raise ValueError("non-live Decision evidence cannot contain external request invocations")
        return self


class _FinalResearchDecisionEvidenceBuilder:
    """Build one closed Decision evidence object from registered adapters and runtime rows."""

    def __init__(self, adapter: LLMDecisionAdapter) -> None:
        self._adapter_chain, self._leaf = _registered_adapter_chain(adapter)
        self._external_request_baseline = (
            self._leaf.external_request_invocations if type(self._leaf) is OpenAICompatibleDecisionAdapter else 0
        )
        self._provider_accounting_baseline = (
            self._leaf.provider_accounting
            if type(self._leaf) is OpenAICompatibleDecisionAdapter
            else empty_provider_accounting()
        )

    def external_provider_calls_configured(self) -> bool:
        return type(self._leaf) is OpenAICompatibleDecisionAdapter and self._leaf.client is None

    def classification(self) -> DecisionAdapterClassification:
        current = self._leaf
        chain = list(self._adapter_chain)
        if type(current) is RuleBasedDecisionAdapter:
            return DecisionAdapterClassification(
                decision_execution_mode="rule_based",
                adapter_chain=chain,
                live_api_triggered=False,
                provider_metadata={
                    "adapter": "rule_based",
                    "prompt_version": current.prompt_version,
                },
            )
        if type(current) is OpenAICompatibleDecisionAdapter:
            invocation_delta = current.external_request_invocations - self._external_request_baseline
            if invocation_delta < 0:
                raise ValueError("provider external request invocation counter moved backwards")
            live_api_triggered = invocation_delta > 0
            metadata = allowlisted_provider_evidence(current.safe_metadata)
            if not isinstance(metadata, dict):  # pragma: no cover - safe metadata is an object by contract.
                raise TypeError("provider safe metadata must remain an object")
            return DecisionAdapterClassification(
                decision_execution_mode="live_provider" if live_api_triggered else "mock_provider",
                adapter_chain=chain,
                live_api_triggered=live_api_triggered,
                provider_metadata=metadata,
            )
        raise AssertionError("registered adapter leaf changed unexpectedly")  # pragma: no cover

    def _run_evidence_inputs(
        self,
        *,
        sample_users: int,
        decision_rows: Sequence[Mapping[str, object]],
        action_rows: Sequence[Mapping[str, object]],
        outcome_rows: Sequence[Mapping[str, object]],
        provider_failure_rows: Sequence[Mapping[str, object]],
    ) -> tuple[_DecisionRowFacts, DecisionAdapterClassification, bool]:
        facts = _derive_decision_row_facts(
            sample_users=sample_users,
            decision_rows=decision_rows,
            action_rows=action_rows,
            outcome_rows=outcome_rows,
            provider_failure_rows=provider_failure_rows,
        )
        classification = self.classification()
        is_live = classification.decision_execution_mode == "live_provider" and classification.live_api_triggered
        return facts, classification, is_live

    def build(
        self,
        *,
        sample_users: int,
        decision_rows: Sequence[Mapping[str, object]],
        action_rows: Sequence[Mapping[str, object]],
        outcome_rows: Sequence[Mapping[str, object]],
        provider_failure_rows: Sequence[Mapping[str, object]],
    ) -> DecisionExecutionEvidence:
        facts, classification, is_live = self._run_evidence_inputs(
            sample_users=sample_users,
            decision_rows=decision_rows,
            action_rows=action_rows,
            outcome_rows=outcome_rows,
            provider_failure_rows=provider_failure_rows,
        )
        return DecisionExecutionEvidence(
            schema_version="final-research-decision-execution-evidence-v1",
            status="persisted",
            formal_research_evidence=is_live,
            decision_execution_mode=classification.decision_execution_mode,
            adapter_chain=classification.adapter_chain,
            decision_source_counts=facts.decision_source_counts,
            action_counts=facts.action_counts,
            terminal_counts=facts.terminal_counts,
            provider_metadata=classification.provider_metadata,
            live_api_triggered=classification.live_api_triggered,
            sampling_status="persisted_seed_first_formal_run" if is_live else "validation_run",
            degeneracy_flags=facts.degeneracy_flags,
        )

    def build_v2(
        self,
        *,
        sample_users: int,
        decision_rows: Sequence[Mapping[str, object]],
        action_rows: Sequence[Mapping[str, object]],
        outcome_rows: Sequence[Mapping[str, object]],
        provider_failure_rows: Sequence[Mapping[str, object]],
    ) -> DecisionExecutionEvidenceV2:
        facts, classification, is_live = self._run_evidence_inputs(
            sample_users=sample_users,
            decision_rows=decision_rows,
            action_rows=action_rows,
            outcome_rows=outcome_rows,
            provider_failure_rows=provider_failure_rows,
        )
        current_accounting = (
            self._leaf.provider_accounting
            if type(self._leaf) is OpenAICompatibleDecisionAdapter
            else empty_provider_accounting()
        )
        accounting = provider_accounting_delta(current_accounting, self._provider_accounting_baseline)
        return DecisionExecutionEvidenceV2(
            schema_version="final-research-decision-execution-evidence-v2",
            status="persisted",
            formal_research_evidence=is_live,
            decision_execution_mode=classification.decision_execution_mode,
            adapter_chain=classification.adapter_chain,
            decision_source_counts=facts.decision_source_counts,
            action_counts=facts.action_counts,
            terminal_counts=facts.terminal_counts,
            provider_metadata=classification.provider_metadata,
            provider_accounting=accounting,
            live_api_triggered=classification.live_api_triggered,
            sampling_status="persisted_seed_first_formal_run" if is_live else "validation_run",
            degeneracy_flags=facts.degeneracy_flags,
        )

    @staticmethod
    def validate_persisted(
        evidence: DecisionExecutionEvidence,
        *,
        sample_users: int,
        decision_rows: Sequence[Mapping[str, object]],
        action_rows: Sequence[Mapping[str, object]],
        outcome_rows: Sequence[Mapping[str, object]],
        provider_failure_rows: Sequence[Mapping[str, object]],
    ) -> None:
        facts = _derive_decision_row_facts(
            sample_users=sample_users,
            decision_rows=decision_rows,
            action_rows=action_rows,
            outcome_rows=outcome_rows,
            provider_failure_rows=provider_failure_rows,
        )
        for field_name in ("decision_source_counts", "action_counts", "terminal_counts", "degeneracy_flags"):
            if getattr(evidence, field_name) != getattr(facts, field_name):
                raise ValueError(f"persisted Decision evidence {field_name} does not match runtime rows")


def _registered_adapter_chain(adapter: LLMDecisionAdapter) -> tuple[list[str], LLMDecisionAdapter]:
    current = adapter
    chain: list[str] = []
    seen: set[int] = set()
    while type(current) is CachedDecisionAdapter:
        if id(current) in seen:
            raise ValueError("decision adapter wrapper chain contains a cycle")
        seen.add(id(current))
        chain.append("cached")
        current = current.wrapped
    if type(current) is RuleBasedDecisionAdapter:
        return [*chain, "rule_based"], current
    if type(current) is OpenAICompatibleDecisionAdapter:
        return [*chain, "openai_compatible"], current
    raise ValueError(f"unsupported Final Research decision adapter: {type(current).__qualname__}")


def _derive_decision_row_facts(
    *,
    sample_users: int,
    decision_rows: Sequence[Mapping[str, object]],
    action_rows: Sequence[Mapping[str, object]],
    outcome_rows: Sequence[Mapping[str, object]],
    provider_failure_rows: Sequence[Mapping[str, object]],
) -> _DecisionRowFacts:
    if sample_users < 0:
        raise ValueError("sample_users must be non-negative")
    decisions = _unique_user_rows(decision_rows, "Decision")
    actions = _unique_user_rows(action_rows, "action")
    outcomes = _unique_user_rows(outcome_rows, "outcome")
    failures = _unique_user_rows(provider_failure_rows, "provider failure")
    if len(outcomes) != sample_users:
        raise ValueError("outcome rows must cover every sample user exactly once")
    if set(decisions) != set(actions):
        raise ValueError("every successful Decision must have exactly one action row")

    action_counts: Counter[str] = Counter()
    decision_source_counts: Counter[str] = Counter()
    for user_id, decision in decisions.items():
        action_row = actions[user_id]
        action = _action(decision.get("action"), f"Decision for {user_id}")
        if _action(action_row.get("action"), f"action row for {user_id}") != action:
            raise ValueError(f"Decision and action row disagree for {user_id}")
        for field_name in ("schedule_position", "user_id", "video_id", "time_step"):
            if str(decision.get(field_name, "")) != str(action_row.get(field_name, "")):
                raise ValueError(f"Decision and action row identity disagree for {user_id}")
        engage = _strict_bool(decision.get("engage"), f"Decision engage for {user_id}")
        if engage != (action != "ignore"):
            raise ValueError(f"Decision engage and action disagree for {user_id}")
        source = str(decision.get("decision_source", "")).strip()
        if not source:
            raise ValueError(f"Decision source is missing for {user_id}")
        outcome = outcomes.get(user_id)
        if outcome is None or outcome.get("result_status") != action or outcome.get("provider_status") != "succeeded":
            raise ValueError(f"Decision does not match the terminal outcome for {user_id}")
        action_counts[action] += 1
        decision_source_counts[source] += 1

    failed_outcome_ids = {
        user_id
        for user_id, row in outcomes.items()
        if row.get("result_status") == "provider_failed" and row.get("provider_status") == "provider_failed"
    }
    below_capacity_ids = {
        user_id
        for user_id, row in outcomes.items()
        if row.get("result_status") == "below_delivery_capacity" and row.get("provider_status") == "not_called"
    }
    classified_outcome_ids = set(decisions) | failed_outcome_ids | below_capacity_ids
    if classified_outcome_ids != set(outcomes):
        raise ValueError("outcome rows contain an unsupported or inconsistent terminal status")
    if set(failures) != failed_outcome_ids:
        raise ValueError("provider failure rows must match provider_failed outcomes exactly")
    if set(decisions) & (failed_outcome_ids | below_capacity_ids):  # pragma: no cover - guarded above.
        raise ValueError("failed or below-capacity users cannot have successful Decisions")

    stable_action_counts: dict[str, int] = {action: action_counts[action] for action in _ACTIONS}
    terminal_counts = DecisionTerminalCounts(
        sample_users=sample_users,
        exposed_users=len(decisions) + len(failures),
        decided_users=len(decisions),
        provider_failed=len(failures),
        below_delivery_capacity=len(below_capacity_ids),
    )
    active_actions = sum(count > 0 for count in stable_action_counts.values())
    return _DecisionRowFacts(
        decision_source_counts=dict(sorted(decision_source_counts.items())),
        action_counts=stable_action_counts,
        terminal_counts=terminal_counts,
        degeneracy_flags=DecisionDegeneracyFlags(
            all_decisions_ignore=bool(decisions) and stable_action_counts["ignore"] == len(decisions),
            single_action_only=bool(decisions) and active_actions == 1,
            no_engagement_feedback=sum(stable_action_counts[action] for action in ("like", "comment", "share")) == 0,
        ),
    )


def _unique_user_rows(
    rows: Sequence[Mapping[str, object]],
    label: str,
) -> dict[str, Mapping[str, object]]:
    indexed: dict[str, Mapping[str, object]] = {}
    for row in rows:
        user_id = str(row.get("user_id", "")).strip()
        if not user_id:
            raise ValueError(f"{label} rows require a non-empty user_id")
        if user_id in indexed:
            raise ValueError(f"{label} rows contain duplicate user_id {user_id}")
        indexed[user_id] = row
    return indexed


def _action(value: object, label: str) -> EngagementAction:
    if value not in _ACTION_SET:
        raise ValueError(f"{label} has unsupported action {value!r}")
    return value


def _strict_bool(value: object, label: str) -> bool:
    if type(value) is bool:
        return value
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError(f"{label} must be true or false")
