"""Study-owned recovery accounting replay, separate from physical persistence."""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any

from . import concurrent_robustness_v2 as _v2
from ._concurrent_recovery_campaign import CampaignJournal, RecoveryCampaignError
from ._concurrent_recovery_judgment import RecoveryJudgmentV1
from .decision import EngageDecision


class CampaignProgress:
    """Recompute cumulative attempts and model-major cursors from verified origins.

    The owning execution Module verifies proposal and epoch plan lineages before
    constructing this state. Neither this state nor a journal handle authorizes
    Provider execution. Unknown dispatched work is never made retryable here.
    """

    def __init__(self, proposal: Mapping[str, Any]) -> None:
        self.proposal = proposal
        self.cells = tuple(_v2._PromptModelCell.model_validate(row) for row in proposal["frozen_context"]["prompt_model_cells"])
        self.model_order = tuple(row["requested_model"] for row in proposal["model_budgets"])
        self.per_cell = proposal["logical_judgment_cap"] // len(self.cells)
        self.model_index = next((i for i, row in enumerate(proposal["model_budgets"]) if row["remaining_valid_judgments"]), len(self.model_order))
        self.prefix = [0] * len(self.cells)
        self.old_successes: set[tuple[int, int]] = set()
        for cell in proposal["inherited_cells"]:
            index = cell["cell_index"]
            self.prefix[index] = len(cell["inherited_pairs"])
            self.old_successes.update((index, row["pair_schedule_position"]) for row in cell["inherited_pairs"])
        failure = proposal["failed_pair"]
        self.failed_key = (failure["cell_index"], failure["pair_schedule_position"])
        self.historical_failure = tuple(_v2._V2AttemptEvidence.model_validate(row) for row in failure["attempt_evidence"])
        self.new_attempts: dict[tuple[int, int], list[_v2._V2AttemptEvidence]] = {}
        self.judgments: dict[tuple[int, int], dict[str, Any]] = {}
        self.success_decisions: dict[tuple[int, int], EngageDecision] = {}
        self.attempt_epochs: dict[tuple[tuple[int, int], int], str] = {}
        self.physical_by_model: Counter[str] = Counter()
        self.physical_attempts = 0
        self.reservation: dict[str, Any] | None = None
        self.inflight: tuple[tuple[int, int], int] | None = None
        self.pending_judgment: dict[str, Any] | None = None
        self.pending_realized: dict[str, Any] | None = None
        self.epochs: list[dict[str, Any]] = []
        self.invocations: list[dict[str, Any]] = []
        self.batch_commits: dict[tuple[int, int, int], dict[str, Any]] = {}
        self.status = "ready"
        self.task_plan: dict[str, Any] | None = None
        self.task_revoked = False
        self.self_check_intents: dict[str, dict[str, Any]] = {}
        self.self_checks: dict[str, dict[str, Any]] = {}
        self.self_check_inflight: str | None = None
        self.accepted_rechecks: dict[str, dict[str, Any]] = {}
        self.parallel_approval: dict[str, Any] | None = None
        self.parallel_batches: dict[tuple[int, int], dict[str, Any]] = {}
        self.parallel_active_batch: tuple[int, int] | None = None
        self.parallel_inflight: dict[tuple[int, int], int] = {}
        self.parallel_unknown: set[tuple[int, int]] = set()
        self.quota_retry_approval: dict[str, Any] | None = None
        self.quota_retry_pending: tuple[int, int] | None = None
        self.gemini_restoration_approval: dict[str, Any] | None = None
        self.model_lane_approval: dict[str, Any] | None = None
        self.output_amendment: dict[str, Any] | None = None
        self.amended_self_check_intent: dict[str, Any] | None = None
        self.amended_self_check: dict[str, Any] | None = None
        self.suspended_models: dict[str, dict[str, Any]] = {}
        self.model_stage_complete = False
        self.final_model_continuation: dict[str, Any] | None = None
        self.kimi_migration_approval: dict[str, Any] | None = None
        self.kimi_migration_active = False
        self.kimi_manual_retry_approval: dict[str, Any] | None = None
        self.kimi_retry_policy: dict[str, Any] | None = None
        self.kimi_cash_cap_amendment: dict[str, Any] | None = None
        self.kimi_request_quotes: dict[tuple[int, int], dict[str, Any]] = {}
        self.kimi_estimate_inflight: dict[str, Any] | None = None
        self.kimi_archived_unknown: dict[tuple[int, int], dict[str, Any]] = {}

    @property
    def has_inflight(self) -> bool:
        return self.inflight is not None or bool(self.parallel_inflight) or self.kimi_estimate_inflight is not None


    def effective_self_check(self, model: str) -> dict[str, Any] | None:
        if self.kimi_migration_active and model == "kimi-coding/k3-256k":
            return {"qualification_kind": "accepted_official_migration",
                    "migration": self.kimi_migration_approval, "attempt": {"outcome": "succeeded"}}
        if self.output_amendment is not None and model == self.output_amendment["requested_model"]:
            return self.amended_self_check
        return self.accepted_rechecks.get(model, self.self_checks.get(model))

    @property
    def effective_parallel_approval(self) -> dict[str, Any] | None:
        if self.final_model_continuation is not None:
            return None
        if self.kimi_migration_active:
            assert self.kimi_migration_approval is not None
            return {**self.kimi_migration_approval, "requested_model": "kimi-coding/k3-256k", "stop_after_model": True}
        if self.gemini_restoration_approval is not None:
            return self.gemini_restoration_approval
        return self.model_lane_approval if self.model_lane_approval is not None else self.parallel_approval

    @property
    def current_model(self) -> str | None:
        if self.final_model_continuation is not None:
            return self.final_model_continuation["requested_model"]
        if self.kimi_migration_active:
            return "kimi-coding/k3-256k"
        if self.gemini_restoration_approval is not None:
            return self.gemini_restoration_approval["requested_model"]
        if self.model_lane_approval is not None:
            return self.model_lane_approval["requested_model"]
        return self.model_order[self.model_index] if self.model_index < len(self.model_order) else None

    @property
    def current_key(self) -> tuple[int, int] | None:
        for index, count in enumerate(self.prefix):
            if self.cells[index].requested_model == self.current_model and count < self.per_cell:
                return index, count
        return None

    @property
    def new_valid_judgments(self) -> int:
        return sum(self.prefix) - len(self.old_successes)

    def next_attempt_number(self, key: tuple[int, int]) -> int:
        return len(self.attempts(key)) + int(key in self.kimi_archived_unknown) + 1

    def attempts(self, key: tuple[int, int]) -> tuple[_v2._V2AttemptEvidence, ...]:
        old = self.historical_failure if key == self.failed_key else ()
        return (*old, *self.new_attempts.get(key, ()))

    @staticmethod
    def _exact(payload: Mapping[str, Any], fields: set[str]) -> None:
        if set(payload) != fields:
            raise RecoveryCampaignError("Recovery event payload fields are crossed")

    def _pair(self, payload: Mapping[str, Any]) -> tuple[int, int]:
        self._exact(payload, {"cell_index", "pair_schedule_position", "pair_id", "time_step", "message_id", "user_id"})
        if any(type(payload[k]) is not int or payload[k] < 0 for k in ("cell_index", "pair_schedule_position", "time_step")):
            raise RecoveryCampaignError("Recovery pair coordinates must be strict integers")
        key = payload["cell_index"], payload["pair_schedule_position"]
        if key != self.current_key or key in self.old_successes:
            raise RecoveryCampaignError("Recovery cannot skip a cursor or resend an inherited success")
        if any(not isinstance(payload[k], str) or not payload[k] for k in ("pair_id", "message_id", "user_id")):
            raise RecoveryCampaignError("Recovery pair identity is malformed")
        if key == self.failed_key:
            old = self.proposal["failed_pair"]
            if any(payload[k] != old[k] for k in payload):
                raise RecoveryCampaignError("Recovery failed-pair identity differs from its origin")
        return key

    def _parallel_key(self, payload: Mapping[str, Any]) -> tuple[int, int]:
        index, position = payload["cell_index"], payload["pair_schedule_position"]
        if (type(index) is not int or not 0 <= index < len(self.cells)
            or type(position) is not int or not 0 <= position < self.per_cell):
            raise RecoveryCampaignError("Parallel pair coordinates are invalid")
        return index, position

    def _parallel_transition(self, kind: str, payload: dict[str, Any]) -> Callable[[], None]:
        if kind == "parallel_execution_accepted":
            self._exact(payload, {"approval", "requested_model", "maximum_inflight", "stop_after_model"})
            self._exact(payload["approval"], {"path", "sha256"})
            _v2._require_sha256(payload["approval"]["sha256"], "parallel approval")
            check = self.effective_self_check(self.current_model or "")
            if (self.parallel_approval is not None or self.task_plan is None or self.task_revoked
                or self.status != "paused" or not self.epochs or self.has_inflight
                or self.self_check_inflight is not None or self.reservation is not None
                or self.pending_judgment is not None or self.pending_realized is not None
                or self.current_model != "gemini-3.1-pro" or payload["requested_model"] != self.current_model
                or type(payload["maximum_inflight"]) is not int or payload["maximum_inflight"] != 4
                or payload["stop_after_model"] is not True or check is None or check["attempt"]["outcome"] != "succeeded"
                or not isinstance(payload["approval"]["path"], str) or not payload["approval"]["path"].startswith("/")
                or any(n % (self.per_cell // 30) for n in self.prefix)):
                raise RecoveryCampaignError("Parallel acceptance requires a settled paused Gemini batch boundary")
            return lambda: setattr(self, "parallel_approval", deepcopy(payload))
        if self.effective_parallel_approval is None or not self.epochs:
            raise RecoveryCampaignError("Parallel event lacks its approved task extension")
        if kind == "parallel_attempt_settled":
            # A stop/revocation prevents dispatch, not recording earlier responses.
            self._exact(payload, {"cell_index", "pair_schedule_position", "attempt", "decision"})
            key = self._parallel_key(payload)
            attempt = _v2._V2AttemptEvidence.model_validate(payload["attempt"])
            if key not in self.parallel_inflight or key in self.parallel_unknown or attempt.attempt_number != self.parallel_inflight[key]:
                raise RecoveryCampaignError("Parallel response lacks its unique matching intent")
            if attempt.request_invocations != 1 or attempt.provider_response_count not in {0, 1}:
                raise RecoveryCampaignError("Parallel worker must account for exactly one physical request")
            decision = EngageDecision.model_validate(payload["decision"]) if attempt.outcome == "succeeded" else None
            if decision is None and payload["decision"] is not None:
                raise RecoveryCampaignError("Failed parallel response cannot manufacture a Decision")
            if decision is not None and (attempt.provider_response_count != 1
                or attempt.successful_decision_count != 1 or attempt.usage_complete_response_count != 1
                or attempt.usage_missing_response_count or attempt.usage_malformed_response_count
                or attempt.observed_model_counts != {"kimi-k3" if self.kimi_migration_active else self.cells[key[0]].required_observed_model: 1}):
                raise RecoveryCampaignError("Parallel success lacks strict identity and complete usage")
            if self.kimi_migration_active:
                from ._concurrent_recovery_kimi_migration import validate_attempt
                validate_attempt(self, key, attempt)
            def settle() -> None:
                self.new_attempts.setdefault(key, []).append(attempt)
                if decision is not None:
                    self.success_decisions[key] = decision
                del self.parallel_inflight[key]
                quote = self.kimi_request_quotes.get(key)
                if quote is not None and attempt.input_usage is not None and attempt.output_usage is not None:
                    from ._concurrent_recovery_request_quote import reserve
                    if attempt.input_usage * 20 + attempt.output_usage * 100 > reserve(quote):
                        self.status = "stopped"

                if key == self.quota_retry_pending:
                    if decision is not None:
                        self.quota_retry_pending = None
                    else:
                        self.status = "stopped"
                if attempt.outcome not in {"succeeded", "retryable_failure"} and self.status != "reconciliation_required":
                    self.status = "stopped"
            return settle
        if kind == "parallel_dispatch_unknown":
            self._exact(payload, {"cell_index", "pair_schedule_position", "attempt_number"})
            key = self._parallel_key(payload)
            if (type(payload["attempt_number"]) is not int or key in self.parallel_unknown
                or self.parallel_inflight.get(key) != payload["attempt_number"]):
                raise RecoveryCampaignError("Parallel unknown lacks a unique matching intent")
            def mark_unknown() -> None:
                self.parallel_unknown.add(key)
                self.status = "reconciliation_required"
            return mark_unknown
        if self.status != "running" or self.task_revoked:
            raise RecoveryCampaignError("Parallel dispatch requires a running nonterminal task")
        if self.current_model != self.effective_parallel_approval["requested_model"]:
            raise RecoveryCampaignError("Parallel scope excludes other models")
        if kind == "parallel_batch_reserved":
            self._exact(payload, {"cell_index", "time_step", "pairs"})
            index, step = payload["cell_index"], payload["time_step"]
            size = self.per_cell // 30
            if (type(index) is not int or type(step) is not int or not 0 <= step < 30
                or self.current_key != (index, step * size) or self.parallel_active_batch is not None
                or self.has_inflight or self.reservation is not None
                or not isinstance(payload["pairs"], list) or len(payload["pairs"]) != size
                or (index, step) in self.parallel_batches):
                raise RecoveryCampaignError("Parallel reservation requires exactly the next complete frozen batch")
            ids = set()
            for offset, row in enumerate(payload["pairs"]):
                self._exact(row, {"coordinates", "context_sha256"})
                coords = row["coordinates"]
                self._exact(coords, {"cell_index", "pair_schedule_position", "pair_id", "time_step", "message_id", "user_id"})
                key = self._parallel_key(coords)
                if (key != (index, step * size + offset) or type(coords["time_step"]) is not int
                    or coords["time_step"] != step or key in self.old_successes
                    or any(not isinstance(coords[k], str) or not coords[k] for k in ("pair_id", "message_id", "user_id"))
                    or coords["pair_id"] in ids):
                    raise RecoveryCampaignError("Parallel batch coordinates are crossed or duplicated")
                if key == self.failed_key and any(coords[k] != self.proposal["failed_pair"][k] for k in coords):
                    raise RecoveryCampaignError("Parallel failed pair differs from its immutable history")
                ids.add(coords["pair_id"])
                _v2._require_sha256(row["context_sha256"], "parallel context")
            def reserve() -> None:
                self.parallel_batches[index, step] = deepcopy(payload)
                self.parallel_active_batch = index, step
            return reserve
        if kind == "parallel_attempt_intent":
            self._exact(payload, {"cell_index", "pair_schedule_position", "attempt_number"})
            key = self._parallel_key(payload)
            ordinal = payload["attempt_number"]
            batch_key = key[0], key[1] // (self.per_cell // 30)
            if (self.quota_retry_pending is not None
                and (key != self.quota_retry_pending or self.has_inflight)):
                raise RecoveryCampaignError("Explicit quota retry permits one original failed pair before recovery")
            if (self.parallel_active_batch != batch_key or self.inflight is not None
                or key in self.parallel_inflight or key in self.success_decisions or key in self.old_successes
                or len(self.parallel_inflight) >= (self.kimi_retry_policy["maximum_active_lanes"] if self.kimi_retry_policy else self.effective_parallel_approval["maximum_inflight"])
                or type(ordinal) is not int or ordinal != self.next_attempt_number(key) or ordinal > 3):
                raise RecoveryCampaignError("Parallel attempt is unreserved, duplicated, successful or exhausted")
            if self.kimi_migration_active:
                from ._concurrent_recovery_kimi_migration import validate_dispatch
                validate_dispatch(self, key)
            model = self.cells[key[0]].requested_model
            cap = next(row["maximum_new_physical_attempts"] for row in self.proposal["model_budgets"] if row["requested_model"] == model)
            if self.physical_by_model[model] >= cap or self.physical_attempts >= self.proposal["maximum_new_physical_attempts"]:
                raise RecoveryCampaignError("Parallel cumulative physical cap is exhausted")
            def dispatch() -> None:
                self.parallel_inflight[key] = ordinal
                self.attempt_epochs[key, ordinal] = self.epochs[-1]["epoch_identity_sha256"]
                self.physical_attempts += 1
                self.physical_by_model[model] += 1
            return dispatch
        raise RecoveryCampaignError("Unknown parallel recovery event")

    def transition(self, kind: str, payload: dict[str, Any]) -> Callable[[], None]:
        """Validate before durable append; apply its returned effect only afterwards."""
        if kind == "final_model_continuation_accepted":
            from ._concurrent_recovery_final_model import transition
            return transition(self, payload)
        if kind == "kimi_cash_cap_amendment_accepted":
            from ._concurrent_recovery_kimi_migration import cash_cap_transition
            return cash_cap_transition(self, payload)
        if kind == "kimi_retry_policy_accepted":
            from ._concurrent_recovery_kimi_retry import transition as kimi_retry
            return kimi_retry(self, payload)
        if kind in {"kimi_estimate_intent", "kimi_estimate_settled", "kimi_estimate_failed"}:
            from ._concurrent_recovery_request_quote import transition as request_quote
            return request_quote(self, kind, payload)
        if kind == "kimi_manual_retry_accepted":
            from ._concurrent_recovery_manual_retry import transition as manual_retry
            return manual_retry(self, payload)
        if kind == "kimi_official_cash_budget_stopped":
            from ._concurrent_recovery_kimi_migration import cash_stop
            return cash_stop(self, payload)
        if kind == "kimi_official_execution_activated":
            from ._concurrent_recovery_kimi_migration import activate
            return activate(self, payload)
        if kind == "kimi_official_migration_accepted":
            from ._concurrent_recovery_kimi_migration import transition as migrate
            return migrate(self, payload)
        if kind == "gemini_restoration_accepted":
            from ._concurrent_recovery_gemini_restoration import transition as restore
            return restore(self, payload)
        if kind == "kimi_output_amendment_accepted":
            from ._concurrent_recovery_output_amendment import transition as amend
            return amend(self, payload)
        if kind in {"amended_self_check_intent", "amended_self_check_settled"}:
            from ._concurrent_recovery_output_amendment import check_transition
            return check_transition(self, kind, payload)
        if kind == "model_lane_source_drift":
            self._exact(payload, {"failure_category"})
            if self.model_lane_approval is None or self.status != "running" or payload["failure_category"] != "source_drift":
                raise RecoveryCampaignError("Source drift stop lacks an active model lane")
            return lambda: setattr(self, "status", "stopped")
        if kind == "model_lane_accepted":
            from ._concurrent_recovery_model_lane import transition
            return transition(self, payload)
        if kind == "quota_retry_accepted":
            from ._concurrent_recovery_quota_retry import transition
            return transition(self, payload)
        if kind.startswith("parallel_"):
            return self._parallel_transition(kind, payload)
        if self.effective_parallel_approval is not None:
            if kind == "attempt_intent":
                raise RecoveryCampaignError("Parallel task cannot bypass keyed intent accounting")
            if kind in {"self_check_intent", "epoch_admitted"} and payload.get("requested_model") != self.effective_parallel_approval["requested_model"]:
                raise RecoveryCampaignError("Parallel stage cannot advance to another model")
        if kind == "task_admitted":
            self._exact(payload, {"task_plan"})
            if self.task_plan is not None or self.epochs or self.status != "ready":
                raise RecoveryCampaignError("Recovery task grant was already consumed")
            return lambda: setattr(self, "task_plan", dict(payload["task_plan"]))
        if kind == "task_revoked":
            self._exact(payload, {"revocation"})
            if self.task_plan is None or self.task_revoked:
                raise RecoveryCampaignError("Recovery revocation is unbound or duplicated")
            return lambda: setattr(self, "task_revoked", True)
        if kind == "self_check_recheck_accepted":
            self._exact(payload, {"approval", "requested_model", "attempt", "decision"})
            model = payload["requested_model"]
            old = self.self_checks.get(model)
            if (self.task_plan is None or self.task_revoked or self.status != "stopped"
                or self.accepted_rechecks or self.epochs or self.invocations or self.physical_attempts
                or self.has_inflight or self.self_check_inflight is not None
                or self.reservation is not None or self.pending_judgment is not None
                or self.pending_realized is not None or model != self.current_model
                or len(self.self_check_intents) != 1 or len(self.self_checks) != 1 or old is None):
                raise RecoveryCampaignError("Recheck requires one settled pre-Formal connection stop")
            failed = _v2._V2AttemptEvidence.model_validate(old["attempt"])
            accepted = _v2._V2AttemptEvidence.model_validate(payload["attempt"])
            if (failed.failure_category != "connection" or failed.outcome != "nonretryable_failure"
                or failed.request_invocations != 1 or failed.provider_response_count != 0
                or failed.successful_decision_count != 0 or failed.observed_model_counts
                or failed.status_code is not None or failed.wait_seconds is not None or failed.lane_cooldown
                or accepted.outcome != "succeeded" or accepted.request_invocations != 1
                or accepted.provider_response_count != 1 or accepted.usage_complete_response_count != 1
                or accepted.successful_decision_count != 1 or payload["decision"] is None):
                raise RecoveryCampaignError("Recheck cannot release another hard stop or unknown")
            def accept_check() -> None:
                self.accepted_rechecks[model] = dict(payload)
                self.status = "ready"
            return accept_check
        if self.status in {"stopped", "reconciliation_required", "complete", "model_complete"} or self.task_revoked:
            raise RecoveryCampaignError("Recovery terminal campaign cannot admit more work")
        if kind == "self_check_intent":
            self._exact(payload, {"requested_model", "contract_sha256"})
            model = payload["requested_model"]
            if (self.task_plan is None or model != self.current_model or model in self.self_check_intents
                or self.has_inflight or self.self_check_inflight is not None
                or self.status not in {"ready", "checkpoint"}):
                raise RecoveryCampaignError("Recovery self-check is duplicated, concurrent or out of order")
            _v2._require_sha256(payload["contract_sha256"], "self-check contract")
            def start_check() -> None:
                self.self_check_intents[model] = dict(payload)
                self.self_check_inflight = model
            return start_check
        if kind == "self_check_settled":
            self._exact(payload, {"requested_model", "attempt", "decision"})
            model = payload["requested_model"]
            if model != self.self_check_inflight or model in self.self_checks:
                raise RecoveryCampaignError("Recovery self-check has no unique unsettled intent")
            attempt = _v2._V2AttemptEvidence.model_validate(payload["attempt"])
            if attempt.attempt_number != 1 or attempt.outcome not in {"succeeded", "nonretryable_failure"}:
                raise RecoveryCampaignError("Recovery self-check permits one attempt and no retry")
            if (attempt.outcome == "succeeded") != (payload["decision"] is not None):
                raise RecoveryCampaignError("Recovery self-check Decision and attempt are crossed")
            def finish_check() -> None:
                self.self_checks[model] = dict(payload)
                self.self_check_inflight = None
                if attempt.outcome != "succeeded":
                    self.status = "stopped"
            return finish_check
        if kind == "epoch_admitted":
            if self.self_check_inflight is not None or (self.task_plan is not None and self.current_model not in self.self_checks):
                raise RecoveryCampaignError("Recovery task epoch requires a settled successful self-check")
            self._exact(payload, {"ordinal", "requested_model", "epoch_identity_sha256", "plan_path", "plan_sha256"})
            if self.status not in {"ready", "checkpoint", "paused", "running"} or self.has_inflight:
                raise RecoveryCampaignError("Recovery epoch requires a safe committed checkpoint")
            if type(payload["ordinal"]) is not int or payload["ordinal"] != len(self.epochs) + 1:
                raise RecoveryCampaignError("Recovery epoch ordinal is stale or duplicated")
            if payload["requested_model"] != self.current_model:
                raise RecoveryCampaignError("Recovery epoch cannot skip the incomplete model")
            if any(row["plan_sha256"] == payload["plan_sha256"] for row in self.epochs):
                raise RecoveryCampaignError("Recovery execution grant was already consumed")
            for field in ("epoch_identity_sha256", "plan_sha256"):
                _v2._require_sha256(payload[field], field)
            def admit() -> None:
                self.epochs.append(dict(payload))
                self.status = "running"
            return admit
        if not self.epochs or (self.status != "running" and not (kind == "invocation_started" and self.status == "paused")):
            raise RecoveryCampaignError("Recovery requires an admitted active epoch")
        if kind == "invocation_started":
            self._exact(payload, {"epoch_identity_sha256", "ordinal"})
            if self.has_inflight or payload["epoch_identity_sha256"] != self.epochs[-1]["epoch_identity_sha256"]:
                raise RecoveryCampaignError("Recovery invocation has unknown dispatch or a crossed epoch")
            if type(payload["ordinal"]) is not int or payload["ordinal"] != len(self.invocations) + 1:
                raise RecoveryCampaignError("Recovery invocation ordinal is not monotonic")
            def begin_invocation() -> None:
                self.invocations.append(dict(payload))
                self.status = "running"
            return begin_invocation
        if kind == "pair_reserved":
            self._pair(payload)
            if self.reservation is not None or self.has_inflight:
                raise RecoveryCampaignError("Recovery permits only one reserved pair")
            key = payload["cell_index"], payload["pair_schedule_position"]
            if self.cells[key[0]].requested_model != self.epochs[-1]["requested_model"]:
                raise RecoveryCampaignError("One recovery invocation cannot enter another model")
            if self.next_attempt_number(key) > 3 and key not in self.success_decisions:
                raise RecoveryCampaignError("Recovery logical pair exhausted its cumulative slots")
            if self.effective_parallel_approval is not None:
                batch_key = key[0], key[1] // (self.per_cell // 30)
                if self.parallel_active_batch != batch_key or key not in self.success_decisions:
                    raise RecoveryCampaignError("Parallel projection requires its settled frozen response")
                expected = self.parallel_batches[batch_key]["pairs"][key[1] % (self.per_cell // 30)]["coordinates"]
                if payload != expected:
                    raise RecoveryCampaignError("Parallel projection differs from its frozen reservation")
            return lambda: setattr(self, "reservation", dict(payload))
        if kind == "attempt_intent":
            self._exact(payload, {"attempt_number"})
            if self.reservation is None or self.has_inflight or self.pending_judgment is not None:
                raise RecoveryCampaignError("Recovery dispatch requires a unique pending reservation")
            key = self.reservation["cell_index"], self.reservation["pair_schedule_position"]
            ordinal = payload["attempt_number"]
            if key in self.success_decisions:
                raise RecoveryCampaignError("Recovery cannot redispatch a persisted successful response")
            if type(ordinal) is not int or ordinal != self.next_attempt_number(key) or ordinal > 3:
                raise RecoveryCampaignError("Recovery attempt ordinal is duplicated or exhausted")
            model = self.cells[key[0]].requested_model
            cap = next(row["maximum_new_physical_attempts"] for row in self.proposal["model_budgets"] if row["requested_model"] == model)
            if self.physical_by_model[model] >= cap or self.physical_attempts >= self.proposal["maximum_new_physical_attempts"]:
                raise RecoveryCampaignError("Recovery cumulative physical cap is exhausted")
            def dispatch() -> None:
                self.inflight = key, ordinal
                self.attempt_epochs[key, ordinal] = self.epochs[-1]["epoch_identity_sha256"]
                self.physical_attempts += 1
                self.physical_by_model[model] += 1
            return dispatch
        if kind == "attempt_settled":
            self._exact(payload, {"attempt", "decision"})
            attempt = _v2._V2AttemptEvidence.model_validate(payload["attempt"])
            if self.inflight is None or attempt.attempt_number != self.inflight[1]:
                raise RecoveryCampaignError("Recovery response has no unique matching intent")
            decision = EngageDecision.model_validate(payload["decision"]) if attempt.outcome == "succeeded" else None
            if attempt.outcome != "succeeded" and payload["decision"] is not None:
                raise RecoveryCampaignError("A failed recovery response cannot manufacture a Decision")
            key = self.inflight[0]
            def settle_attempt() -> None:
                self.new_attempts.setdefault(key, []).append(attempt)
                if decision is not None:
                    self.success_decisions[key] = decision
                self.inflight = None
                if attempt.outcome not in {"succeeded", "retryable_failure"}:
                    self.status = "stopped"
            return settle_attempt
        if kind == "judgment_persisted":
            self._exact(payload, {"judgment"})
            if self.reservation is None or self.has_inflight or self.pending_judgment is not None:
                raise RecoveryCampaignError("Recovery Judgment has an unresolved or duplicated predecessor")
            key = self.reservation["cell_index"], self.reservation["pair_schedule_position"]
            attempts = self.new_attempts.get(key, [])
            if not attempts or attempts[-1].outcome != "succeeded":
                raise RecoveryCampaignError("Recovery Judgment requires a settled successful response")
            judgment = RecoveryJudgmentV1.model_validate(payload["judgment"])
            historical = self.historical_failure if key == self.failed_key else ()
            from ._concurrent_recovery_quota_retry import judgment_reference
            expected_quota = judgment_reference(self, key)
            actual_quota = judgment.quota_retry_approval.model_dump(mode="json") if judgment.quota_retry_approval is not None else None
            from ._concurrent_recovery_output_amendment import judgment_reference as output_reference
            actual_output = judgment.output_amendment_approval.model_dump(mode="json") if judgment.output_amendment_approval is not None else None
            from ._concurrent_recovery_kimi_migration import judgment_reference as migration_reference
            expected_migration = migration_reference(self, key)
            actual_migration = (judgment.official_migration_approval.model_dump(mode="json")
                                if judgment.official_migration_approval is not None else None)
            from ._concurrent_recovery_manual_retry import judgment_fields
            fields = judgment_fields(self, key)
            actual_manual = (judgment.manual_retry_approval.model_dump(mode="json")
                             if judgment.manual_retry_approval is not None else None)
            if actual_manual != fields["manual_retry_approval"] or judgment.unknown_attempts != fields["unknown_attempts"]:
                raise RecoveryCampaignError("Manual retry Judgment differs from its original archived intent")
            from ._concurrent_recovery_kimi_retry import judgment_reference as retry_reference
            actual_retry = judgment.official_retry_policy.model_dump(mode="json") if judgment.official_retry_policy else None
            if actual_retry != retry_reference(self, key):
                raise RecoveryCampaignError("Kimi retry Judgment differs from admitted policy")
            if actual_migration != expected_migration:
                raise RecoveryCampaignError("Official Judgment differs from its admitted migration")
            if actual_output != (None if expected_migration else output_reference(self, judgment.cell.requested_model)):
                raise RecoveryCampaignError("Kimi Judgment differs from its accepted output amendment")
            if actual_quota != expected_quota:
                raise RecoveryCampaignError("Quota Judgment differs from its accepted receipt")
            if (
                judgment.cell_index != key[0] or judgment.cell != self.cells[key[0]]
                or judgment.pair.model_dump() != {k: v for k, v in self.reservation.items() if k != "cell_index"}
                or judgment.historical_attempts != historical or judgment.new_attempts != tuple(attempts)
                or judgment.decision != self.success_decisions[key]
                or judgment.epoch_identity_sha256 != self.attempt_epochs[key, attempts[-1].attempt_number]
            ):
                raise RecoveryCampaignError("Recovery Judgment differs from its reserved pair or settled response")
            return lambda: setattr(self, "pending_judgment", judgment.model_dump(mode="json"))
        if kind == "realized_persisted":
            self._exact(payload, {"terminal"})
            if self.pending_judgment is None or self.pending_realized is not None:
                raise RecoveryCampaignError("Recovery Realization requires one unprojected Judgment")
            judgment = RecoveryJudgmentV1.model_validate(self.pending_judgment)
            terminal = judgment.realized_projection(realization_source_identity=self.proposal["frozen_context"]["realization_source_identity"])
            if _v2._canonical_json_bytes(terminal.model_dump(mode="json")) != _v2._canonical_json_bytes(payload["terminal"]):
                raise RecoveryCampaignError("Recovery Realized payload is crossed")
            return lambda: setattr(self, "pending_realized", terminal.model_dump(mode="json"))
        if kind == "pair_settled":
            self._exact(payload, {"judgment_id", "realized_terminal_id"})
            if self.pending_judgment is None or self.pending_realized is None or self.reservation is None or self.has_inflight:
                raise RecoveryCampaignError("Recovery pair requires a persisted successful Judgment")
            if payload["judgment_id"] != self.pending_judgment["judgment_id"]:
                raise RecoveryCampaignError("Recovery settled pair is crossed with its Judgment")
            judgment = RecoveryJudgmentV1.model_validate(self.pending_judgment)
            realization = judgment.realized_projection(realization_source_identity=self.proposal["frozen_context"]["realization_source_identity"])
            if realization.realized_terminal_id != payload["realized_terminal_id"]:
                raise RecoveryCampaignError("Recovery Realization differs from its Judgment")
            key = self.reservation["cell_index"], self.reservation["pair_schedule_position"]
            def settle_pair() -> None:
                assert self.pending_judgment is not None
                self.judgments[key] = self.pending_judgment
                self.prefix[key[0]] += 1
                self.reservation = None
                self.pending_judgment = None
                self.pending_realized = None
            return settle_pair
        if kind == "batch_committed":
            self._exact(payload, {"cell_index", "time_step", "commit"})
            index, step = payload["cell_index"], payload["time_step"]
            if type(index) is not int or type(step) is not int or index < 0 or index >= len(self.cells) or not 0 <= step < 30:
                raise RecoveryCampaignError("Recovery batch coordinates are invalid")
            key = len(self.epochs), index, step
            if key in self.batch_commits or self.prefix[index] < (step + 1) * (self.per_cell // 30):
                raise RecoveryCampaignError("Recovery batch is duplicated or ahead of settled pairs")
            if self.cells[index].requested_model != self.epochs[-1]["requested_model"]:
                raise RecoveryCampaignError("Recovery batch is crossed with the admitted model")
            parallel_key = index, step
            if parallel_key in self.parallel_batches:
                from ._concurrent_recovery_gemini_restoration import replays_prior_barrier
                if self.has_inflight or (self.parallel_active_batch != parallel_key
                    and not replays_prior_barrier(self, index, step, payload["commit"])):
                    raise RecoveryCampaignError("Parallel barrier has unresolved or crossed work")
            def commit_batch() -> None:
                self.batch_commits[key] = dict(payload["commit"])
                if self.parallel_active_batch == parallel_key:
                    self.parallel_active_batch = None
            return commit_batch
        if kind == "epoch_finished":
            self._exact(payload, {"status"})
            status = payload["status"]
            if self.has_inflight:
                if status != "reconciliation_required":
                    raise RecoveryCampaignError("Unknown dispatch cannot be released or paused safely")
            elif status == "checkpoint":
                model = self.epochs[-1]["requested_model"]
                indexes = [i for i, cell in enumerate(self.cells) if cell.requested_model == model]
                if self.reservation is not None or any(self.prefix[i] != self.per_cell for i in indexes):
                    raise RecoveryCampaignError("Recovery model checkpoint is incomplete")
                if any((len(self.epochs), i, step) not in self.batch_commits for i in indexes for step in range(30)):
                    raise RecoveryCampaignError("Recovery checkpoint lacks full batch barriers")
                def finish_model() -> None:
                    if self.model_lane_approval is not None:
                        self.model_stage_complete = True
                        self.status = "model_complete"
                        return
                    self.model_index += 1
                    self.status = "complete" if self.current_model is None else "checkpoint"
                return finish_model
            elif status != "paused":
                raise RecoveryCampaignError("Recovery epoch terminal status is invalid")
            return lambda: setattr(self, "status", status)
        raise RecoveryCampaignError("Unknown recovery campaign event")

    def append(self, journal: CampaignJournal, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        effect = self.transition(kind, payload)
        record = journal.append(kind, payload)
        effect()
        return record

    @classmethod
    def replay(cls, proposal: Mapping[str, Any], journal: CampaignJournal) -> CampaignProgress:
        state = cls(proposal)
        for row in journal.records:
            state.transition(row["kind"], row["payload"])()
        return state
