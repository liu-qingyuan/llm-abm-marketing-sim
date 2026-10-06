"""Study-owned prevalidated immutable input cache; original Kernel remains scheduler."""

import hashlib

import offline_path_engine as engine

from llm_abm_sim import _parameter_judgment_bank as bank
from llm_abm_sim._parameter_study import RULE
from llm_abm_sim.concurrent_message_experiment import _ConcurrentRuntimeKernel, _message_user_fit_components
from llm_abm_sim.decision import EngageDecision


class Campaign:
    def __init__(self, config, prepared, condition, records):
        self.config = config
        self.prepared = prepared
        self.entries = engine.checked_entries(config, prepared, condition, records)
        self.decisions = {k: EngageDecision.model_validate(r["decision"]) for k, r in self.entries.items()}
        # Every time step is checked once for this immutable arm, not once per seed/parameter.
        for k, entry in self.entries.items():
            data = engine.decision_input(config, prepared, condition, *k)
            if any(
                bank.client_identity(data.model_copy(update={"time_step": step}), condition)
                != (entry["client_messages_sha256"], entry["client_condition_sha256"])
                for step in range(config.horizon)
            ):
                raise ValueError("non-invariant client input")
        self.fits = {
            m.message_id: {
                u: _message_user_fit_components(m, prepared.cohort.users_by_id[u])
                for u in prepared.cohort.sample_user_ids
            }
            for m in config.messages
        }

    def execute(self, anchor, seed, weights, saturation):
        def resolve(user, msg, step):
            entry = self.entries[user.user_id, msg.message_id]
            d = self.decisions[user.user_id, msg.message_id]
            value = engine.anchored_draw(anchor, seed, user.user_id, msg.message_id) if d.engage else None
            positive = value is not None and value < d.probability
            return {
                "client_condition_sha256": entry["client_condition_sha256"],
                "bank_source": entry["source"],
                "uniform_draw": value,
                "realized_engage": positive,
                "realized_action": d.action if positive else "ignore",
            }

        return _ConcurrentRuntimeKernel.fixed_judgment_path(
            config=self.config,
            prepared=self.prepared,
            weights=weights,
            neighbor_saturation=saturation,
            message_fits=self.fits,
            resolve=resolve,
        )

    def verify(self, path, anchor, seed, weights, saturation):
        cfg = self.config
        p = self.prepared
        users = p.cohort.sample_user_ids
        seeds = set(p.cohort.seed_user_ids)
        exposed = {m.message_id: set() for m in cfg.messages}
        campaign = set()
        cursor = 0
        if len(path["barriers"]) != cfg.horizon:
            raise ValueError("barrier count differs")
        for step in range(cfg.horizon):
            frozen = set(campaign)
            positive = set()
            for msg in cfg.messages:
                ranked = []
                m = msg.message_id
                for u in users:
                    if u in exposed[m]:
                        continue
                    n = len(p.neighbors_by_user.get(u, set()) & frozen)
                    score = (
                        weights[0] * p.base_network_by_user.get(u, 0.0)
                        + weights[1] * min(1.0, n / saturation)
                        + weights[2] * self.fits[m][u][1]
                    )
                    ranked.append((u, score, n))
                ranked.sort(key=lambda r: (-r[1], r[0]))
                selected = (
                    (
                        [r for r in ranked if r[0] in seeds]
                        + [r for r in ranked if r[0] not in seeds][: cfg.delivery_capacity - len(seeds)]
                    )
                    if step == 0
                    else ranked[: cfg.delivery_capacity]
                )
                if len(selected) != cfg.delivery_capacity:
                    raise ValueError("capacity differs")
                for u, score, n in selected:
                    entry = self.entries[u, m]
                    d = self.decisions[u, m]
                    digest = hashlib.sha256(bank.canonical([RULE, anchor, seed, u, m])).digest()
                    value = (int.from_bytes(digest[:7], "big") >> 3) / 9007199254740992 if d.engage else None
                    engage = value is not None and value < d.probability
                    expected = {
                        "time_step": step,
                        "user_id": u,
                        "message_id": m,
                        "uniform_draw": value,
                        "realized_engage": engage,
                        "realized_action": d.action if engage else "ignore",
                        "ranking_score": score,
                        "engaged_neighbor_count": n,
                        "bank_source": entry["source"],
                        "client_condition_sha256": entry["client_condition_sha256"],
                        "selection_reason": ("seed_union" if u in seeds else "personalized_topup")
                        if step == 0
                        else "personalized_top20",
                    }
                    if cursor >= len(path["terminals"]) or path["terminals"][cursor] != expected:
                        raise ValueError("rank/draw/action/source differs")
                    cursor += 1
                    exposed[m].add(u)
                    if engage:
                        positive.add(u)
            campaign.update(positive)
            expected = {
                "time_step": step,
                "exposure_count": len(cfg.messages) * cfg.delivery_capacity,
                "frozen_positive_user_ids": sorted(frozen),
                "committed_positive_user_ids": sorted(positive),
                "campaign_positive_user_count": len(campaign),
            }
            if path["barriers"][step] != expected:
                raise ValueError("feedback barrier differs")
        if cursor != len(path["terminals"]) or any(
            len(s) != cfg.horizon * cfg.delivery_capacity for s in exposed.values()
        ):
            raise ValueError("exposure closure differs")
        return True
