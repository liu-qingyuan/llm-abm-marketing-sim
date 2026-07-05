from pathlib import Path

from llm_abm_sim.decision import (
    CachedDecisionAdapter,
    InMemoryDecisionCache,
    RuleBasedDecisionAdapter,
    RuleBasedDecisionConfig,
)
from llm_abm_sim.runner import ExperimentRunner, load_simulation_input
from llm_abm_sim.schemas import (
    LatentAttributes,
    LatentProfileLabels,
    LatentValueWeights,
    PeerContext,
    PostContent,
    UserProfile,
    ValueDimensions,
)


def test_rule_based_decision_returns_binary_schema():
    adapter = RuleBasedDecisionAdapter()
    decision = adapter.decide(
        PostContent(post_id="p1", text="new skincare post", topic_tags=["skincare"]),
        UserProfile(user_id="u1", interest_tags=["skincare"], brand_attitude=0.5, activity_score=0.8),
        PeerContext(engaged_neighbors=3, exposed_neighbors=4),
    )
    assert isinstance(decision.engage, bool)
    assert 0.0 <= decision.probability <= 1.0


def test_rule_based_decision_default_config_preserves_baseline_probability_and_action():
    post = _post_with_values()
    profile = _profile_with_latent()
    peer_context = PeerContext(engaged_neighbors=1, exposed_neighbors=4)

    baseline = RuleBasedDecisionAdapter(RuleBasedDecisionConfig(latent_value_weight=0.0)).decide(
        post, profile, peer_context
    )
    default = RuleBasedDecisionAdapter().decide(post, profile, peer_context)

    assert default.probability == baseline.probability
    assert default.action == baseline.action
    assert default.provider_metadata == {
        "latent_value_score_applied": False,
        "latent_value_score": 0.5,
        "latent_value_weight": 0.0,
    }


def test_rule_based_decision_disabled_latent_weight_ignores_latent_inputs():
    post = _post_with_values()
    profile = _profile_with_latent()
    peer_context = PeerContext(engaged_neighbors=1, exposed_neighbors=4)

    without_latent = RuleBasedDecisionAdapter().decide(
        post.model_copy(update={"value_dimensions": ValueDimensions()}),
        UserProfile(
            user_id=profile.user_id,
            interest_tags=profile.interest_tags,
            brand_attitude=profile.brand_attitude,
            activity_score=profile.activity_score,
        ),
        peer_context,
    )
    disabled = RuleBasedDecisionAdapter(RuleBasedDecisionConfig(latent_value_weight=0.0)).decide(
        post, profile, peer_context
    )

    assert disabled.probability == without_latent.probability
    assert disabled.action == without_latent.action
    assert "latent value score not applied" in disabled.reason


def test_rule_based_decision_adds_configured_latent_value_score_and_clips_probability():
    adapter = RuleBasedDecisionAdapter(RuleBasedDecisionConfig(latent_value_weight=0.5))
    peer_context = PeerContext()

    decision = adapter.decide(
        PostContent(
            post_id="p1",
            text="wellness hotel launch",
            value_dimensions=ValueDimensions(health=0.5, emotional=0.5),
        ),
        _profile_with_latent(
            brand_attitude=1.0,
            activity_score=1.0,
            value_weights=LatentValueWeights(
                epistemic=0.0,
                environmental=0.0,
                functional=0.0,
                health=0.6,
                emotional=0.4,
                social=0.0,
            ),
        ),
        peer_context,
    )

    assert decision.probability == 0.6
    assert decision.provider_metadata == {
        "latent_value_score_applied": True,
        "latent_value_score": 0.5,
        "latent_value_weight": 0.5,
    }
    assert "latent value score applied" in decision.reason

    clipped = RuleBasedDecisionAdapter(RuleBasedDecisionConfig(latent_value_weight=1.0)).decide(
        PostContent(
            post_id="p2",
            text="high match",
            value_dimensions=ValueDimensions(health=1.0, emotional=1.0),
        ),
        _profile_with_latent(
            brand_attitude=1.0,
            activity_score=1.0,
            value_weights=LatentValueWeights(
                epistemic=0.0,
                environmental=0.0,
                functional=0.0,
                health=2.0,
                emotional=2.0,
                social=0.0,
            ),
        ),
        peer_context,
    )
    assert clipped.probability == 1.0


def test_rule_based_decision_missing_latent_or_value_dimensions_returns_baseline():
    adapter = RuleBasedDecisionAdapter(RuleBasedDecisionConfig(latent_value_weight=0.5))
    peer_context = PeerContext(engaged_neighbors=1, exposed_neighbors=4)
    post = _post_with_values()
    profile = _profile_with_latent()

    baseline = RuleBasedDecisionAdapter().decide(post, profile, peer_context)
    missing_latent = adapter.decide(post, profile.model_copy(update={"latent_attributes": None}), peer_context)
    zero_dimensions = adapter.decide(post.model_copy(update={"value_dimensions": ValueDimensions()}), profile, peer_context)

    assert missing_latent.probability == baseline.probability
    assert missing_latent.action == baseline.action
    assert zero_dimensions.probability == baseline.probability
    assert zero_dimensions.action == baseline.action


def test_rule_based_decision_table_11_labels_do_not_change_probability_or_action():
    adapter = RuleBasedDecisionAdapter(RuleBasedDecisionConfig(latent_value_weight=0.25))
    post = _post_with_values()
    peer_context = PeerContext()
    base_profile = _profile_with_latent()
    changed_profile = _profile_with_latent(
        profile_labels=LatentProfileLabels(
            hotel_class="upper_midscale",
            travel_purpose="leisure",
            gender="male",
            age="age_46_55",
            education="master_or_above",
            monthly_income="income_40001_or_more",
        )
    )

    base_decision = adapter.decide(post, base_profile, peer_context)
    changed_decision = adapter.decide(post, changed_profile, peer_context)

    assert changed_decision.probability == base_decision.probability
    assert changed_decision.action == base_decision.action


def test_rule_based_decision_config_can_be_enabled_from_runner_config(tmp_path: Path):
    config_path = tmp_path / "latent-rule-based.yaml"
    config_path.write_text(
        """
run_id: latent-rule-based-smoke
simulation:
  horizon: 1
  seed_user_ids: [u1]
  base_exposure_probability: 1.0
  peer_exposure_boost: 0.0
post:
  post_id: p1
  text: "Wellness hotel launch"
  value_dimensions:
    health: 1.0
rule_based_decision:
  latent_value_weight: 0.4
profiles:
  - user_id: u1
    brand_attitude: 0.0
    activity_score: 0.0
    like_tendency: 1.0
    latent_attributes:
      spec_id: jinjiang_user_latent_attributes_v1
      method: latent_class_exact_quota_v1
      seed: 20260630
      latent_class: class_1
      environmental_consciousness_coef: 0.0
      value_weights:
        epistemic: 0.0
        environmental: 0.0
        functional: 0.0
        health: 1.0
        emotional: 0.0
        social: 0.0
      profile_labels:
        hotel_class: economy
        travel_purpose: business
        gender: female
        age: age_26_35
        education: bachelor
        monthly_income: income_8001_15000
""",
        encoding="utf-8",
    )

    loaded = load_simulation_input(config_path)
    result = ExperimentRunner(loaded).run()

    decision_events = result.decision_events
    assert decision_events
    assert decision_events[0].decision.probability == 0.4
    assert decision_events[0].decision.provider_metadata is not None
    assert decision_events[0].decision.provider_metadata["latent_value_score_applied"] is True


def test_rule_based_decision_cache_key_includes_latent_value_weight():
    cache = InMemoryDecisionCache()
    post = _post_with_values()
    profile = _profile_with_latent()
    peer_context = PeerContext()

    baseline = CachedDecisionAdapter(
        RuleBasedDecisionAdapter(RuleBasedDecisionConfig(latent_value_weight=0.0)),
        cache,
    ).decide(post, profile, peer_context)
    latent_enabled = CachedDecisionAdapter(
        RuleBasedDecisionAdapter(RuleBasedDecisionConfig(latent_value_weight=0.5)),
        cache,
    ).decide(post, profile, peer_context)

    assert baseline.probability == 0.0
    assert latent_enabled.probability == 0.25
    assert len(cache.decisions) == 2


def _post_with_values() -> PostContent:
    return PostContent(
        post_id="p1",
        text="wellness hotel launch",
        value_dimensions=ValueDimensions(health=0.5, emotional=0.5),
    )


def _profile_with_latent(
    *,
    brand_attitude: float = 0.0,
    activity_score: float = 0.0,
    value_weights: LatentValueWeights | None = None,
    profile_labels: LatentProfileLabels | None = None,
) -> UserProfile:
    return UserProfile(
        user_id="u1",
        brand_attitude=brand_attitude,
        activity_score=activity_score,
        latent_attributes=LatentAttributes(
            spec_id="jinjiang_user_latent_attributes_v1",
            method="latent_class_exact_quota_v1",
            seed=20260630,
            latent_class="class_1",
            environmental_consciousness_coef=0.0,
            value_weights=value_weights
            or LatentValueWeights(
                epistemic=0.0,
                environmental=0.0,
                functional=0.0,
                health=0.6,
                emotional=0.4,
                social=0.0,
            ),
            profile_labels=profile_labels
            or LatentProfileLabels(
                hotel_class="economy",
                travel_purpose="business",
                gender="female",
                age="age_26_35",
                education="bachelor",
                monthly_income="income_8001_15000",
            ),
        ),
    )
