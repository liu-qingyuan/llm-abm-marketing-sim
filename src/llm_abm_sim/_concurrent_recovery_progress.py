"""Study-owned recovery accounting replay, separate from physical persistence."""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
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

    @property
    def current_model(self) -> str | None:
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

    def transition(self, kind: str, payload: dict[str, Any]) -> Callable[[], None]:
        """Validate before durable append; apply its returned effect only afterwards."""
        if self.status in {"stopped", "reconciliation_required", "complete"}:
            raise RecoveryCampaignError("Recovery terminal campaign cannot admit more work")
        if kind == "epoch_admitted":
            self._exact(payload, {"ordinal", "requested_model", "epoch_identity_sha256", "plan_path", "plan_sha256"})
            if self.status not in {"ready", "checkpoint", "paused", "running"} or self.inflight is not None:
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
            if self.inflight is not None or payload["epoch_identity_sha256"] != self.epochs[-1]["epoch_identity_sha256"]:
                raise RecoveryCampaignError("Recovery invocation has unknown dispatch or a crossed epoch")
            if type(payload["ordinal"]) is not int or payload["ordinal"] != len(self.invocations) + 1:
                raise RecoveryCampaignError("Recovery invocation ordinal is not monotonic")
            def begin_invocation() -> None:
                self.invocations.append(dict(payload))
                self.status = "running"
            return begin_invocation
        if kind == "pair_reserved":
            self._pair(payload)
            if self.reservation is not None or self.inflight is not None:
                raise RecoveryCampaignError("Recovery permits only one reserved pair")
            key = payload["cell_index"], payload["pair_schedule_position"]
            if self.cells[key[0]].requested_model != self.epochs[-1]["requested_model"]:
                raise RecoveryCampaignError("One recovery invocation cannot enter another model")
            if len(self.attempts(key)) >= 3:
                raise RecoveryCampaignError("Recovery logical pair exhausted its cumulative slots")
            return lambda: setattr(self, "reservation", dict(payload))
        if kind == "attempt_intent":
            self._exact(payload, {"attempt_number"})
            if self.reservation is None or self.inflight is not None or self.pending_judgment is not None:
                raise RecoveryCampaignError("Recovery dispatch requires a unique pending reservation")
            key = self.reservation["cell_index"], self.reservation["pair_schedule_position"]
            ordinal = payload["attempt_number"]
            if key in self.success_decisions:
                raise RecoveryCampaignError("Recovery cannot redispatch a persisted successful response")
            if type(ordinal) is not int or ordinal != len(self.attempts(key)) + 1 or ordinal > 3:
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
            if self.reservation is None or self.inflight is not None or self.pending_judgment is not None:
                raise RecoveryCampaignError("Recovery Judgment has an unresolved or duplicated predecessor")
            key = self.reservation["cell_index"], self.reservation["pair_schedule_position"]
            attempts = self.new_attempts.get(key, [])
            if not attempts or attempts[-1].outcome != "succeeded":
                raise RecoveryCampaignError("Recovery Judgment requires a settled successful response")
            judgment = RecoveryJudgmentV1.model_validate(payload["judgment"])
            historical = self.historical_failure if key == self.failed_key else ()
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
            if self.pending_judgment is None or self.pending_realized is None or self.reservation is None or self.inflight is not None:
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
            return lambda: self.batch_commits.__setitem__(key, dict(payload["commit"]))
        if kind == "epoch_finished":
            self._exact(payload, {"status"})
            status = payload["status"]
            if self.inflight is not None:
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
