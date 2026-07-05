import pytest
from pydantic import ValidationError

from llm_abm_sim.decision import DecisionInput
from llm_abm_sim.report_payload import build_report_payload
from llm_abm_sim.runner import ExperimentRunner, load_simulation_input
from llm_abm_sim.schemas import PeerContext, PlatformContext, PostContent, UserProfile, ValueDimensions


def test_post_content_defaults_to_zero_value_dimensions():
    post = PostContent(post_id="p1", text="eco skincare")

    assert post.value_dimensions == ValueDimensions()
    assert post.model_dump(mode="json")["value_dimensions"] == {
        "epistemic": 0.0,
        "environmental": 0.0,
        "functional": 0.0,
        "health": 0.0,
        "emotional": 0.0,
        "social": 0.0,
    }


def test_config_loading_preserves_typed_value_dimensions(tmp_path):
    config_path = tmp_path / "value-dimensions.yaml"
    config_path.write_text(
        """
run_id: value-dimensions-test
post:
  post_id: p1
  text: "Refillable skincare launch"
  topic_tags: [skincare, eco]
  value_dimensions:
    epistemic: 0.7
    environmental: 0.9
    functional: 0.6
    health: 0.5
    emotional: 0.4
    social: 0.3
""",
        encoding="utf-8",
    )

    loaded = load_simulation_input(config_path)

    assert loaded.post.value_dimensions == ValueDimensions(
        epistemic=0.7,
        environmental=0.9,
        functional=0.6,
        health=0.5,
        emotional=0.4,
        social=0.3,
    )


@pytest.mark.parametrize(
    "value_dimensions",
    [
        {"epistemic": 1.1},
        {"environmental": -0.1},
        {"functional": "high"},
        {"unknown": 0.5},
    ],
)
def test_invalid_value_dimensions_are_rejected(value_dimensions):
    with pytest.raises(ValidationError):
        PostContent(post_id="p1", text="eco skincare", value_dimensions=value_dimensions)


def test_decision_cache_key_includes_value_dimensions():
    base_input = DecisionInput(
        post=PostContent(post_id="p1", text="eco skincare"),
        profile=UserProfile(user_id="u1"),
        peer_context=PeerContext(),
        platform_context=PlatformContext(),
        time_step=1,
    )
    changed_input = base_input.model_copy(
        update={
            "post": PostContent(
                post_id="p1",
                text="eco skincare",
                value_dimensions=ValueDimensions(environmental=0.8),
            )
        }
    )

    assert base_input.cache_key() == base_input.model_copy(deep=True).cache_key()
    assert base_input.cache_key() != changed_input.cache_key()


def test_report_payload_serializes_value_dimensions():
    config = load_simulation_input("configs/default.yaml")
    config = config.model_copy(
        update={"post": config.post.model_copy(update={"value_dimensions": ValueDimensions(environmental=0.8)})}
    )
    result = ExperimentRunner(config).run()

    payload = build_report_payload(result, config)

    assert payload.inputs["post"]["value_dimensions"]["environmental"] == 0.8


@pytest.mark.parametrize(
    "config_path",
    [
        "configs/default.yaml",
        "configs/fixtures/toy_dataset.yaml",
        "configs/fixtures/realistic_marketing_dataset.yaml",
    ],
)
def test_existing_configs_run_without_declaring_value_dimensions(config_path):
    config = load_simulation_input(config_path)

    assert config.post.value_dimensions == ValueDimensions()
    ExperimentRunner(config).run()
