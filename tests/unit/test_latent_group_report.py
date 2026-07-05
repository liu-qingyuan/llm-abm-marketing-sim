from __future__ import annotations

import json
from pathlib import Path

from llm_abm_sim.decision import EngageDecision
from llm_abm_sim.events import ActionEvent, DecisionEvent, ExposureEvent, SimulationRunResult, StepRecord
from llm_abm_sim.outputs import write_report_html, write_run_outputs
from llm_abm_sim.report_payload import build_report_payload
from llm_abm_sim.schemas import (
    GenderLabel,
    HotelClassLabel,
    LatentAttributes,
    LatentClass,
    LatentProfileLabels,
    LatentValueWeights,
    MonthlyIncomeLabel,
    PeerContext,
    PlatformContext,
    PostContent,
    SimulationConfig,
    SimulationInput,
    TravelPurposeLabel,
    UserProfile,
)
from llm_abm_sim.trace import build_decision_trace_summary


def test_report_payload_groups_spread_metrics_by_latent_labels() -> None:
    config = _latent_config()
    result = _latent_result()

    payload = build_report_payload(result, config)

    report = payload.latent_group_report
    assert report.available is True
    assert "Virtual Experiment Labels" in report.privacy_notice
    assert "not real user identity" in report.privacy_notice
    assert "not real demographic attributes" in report.privacy_notice

    class_1 = _group(report.model_dump(mode="json"), "latent_class", "class_1")
    assert class_1 == {
        "group": {"dimension": "latent_class", "value": "class_1"},
        "user_count": 2,
        "exposed_count": 2,
        "engaged_count": 1,
        "engagement_rate": 0.5,
    }

    economy = _group(report.model_dump(mode="json"), "latent_hotel_class", "economy")
    assert economy["user_count"] == 2
    assert economy["exposed_count"] == 2
    assert economy["engaged_count"] == 2
    assert economy["engagement_rate"] == 1.0

    assert _group(report.model_dump(mode="json"), "latent_gender", "female")["engaged_count"] == 2
    assert _group(report.model_dump(mode="json"), "latent_monthly_income", "income_8001_15000")[
        "user_count"
    ] == 1


def test_report_payload_marks_latent_grouping_unavailable_without_latent_attributes() -> None:
    config = SimulationInput(
        simulation=SimulationConfig(horizon=1, seed_user_ids=["u1"]),
        graph_edges=[("u1", "u2")],
        profiles=[UserProfile(user_id="u1"), UserProfile(user_id="u2")],
    )
    result = SimulationRunResult(
        run_id="no-latent",
        random_seed=42,
        horizon=1,
        metrics_summary={"total_agents": 2, "final_exposed": 1, "final_engaged": 0},
        step_records=[
            StepRecord(
                time_step=0,
                exposed_count=1,
                engaged_count=0,
                new_exposed_count=1,
                new_engaged_count=0,
                exposure_events=[ExposureEvent(time_step=0, user_id="u1", channel="seed")],
            )
        ],
    )

    payload = build_report_payload(result, config)

    assert payload.latent_group_report.available is False
    assert payload.latent_group_report.groups == []


def test_latent_group_report_outputs_boundary_notice_and_no_user_details(tmp_path: Path) -> None:
    config = _latent_config()
    result = _latent_result()

    output_dir = write_run_outputs(result, config, tmp_path)
    report_html = (output_dir / "report.html").read_text(encoding="utf-8")
    payload_text = (output_dir / "report_payload.json").read_text(encoding="utf-8")
    payload = json.loads(payload_text)

    assert "Virtual Experiment Labels" in report_html
    assert "not real user identity" in report_html
    assert "not real demographic attributes" in report_html
    assert payload["latent_group_report"]["available"] is True

    forbidden_terms = ("nickname", "bio", "signature", "raw_payload", "raw payload", "Alice", "secret profile")
    combined = f"{report_html}\n{payload_text}"
    for term in forbidden_terms:
        assert term not in combined

    assert "latent_attributes" not in payload["trend"][0]["decision_events"][0]["trace_summary"]["input"]["profile"]
    assert "latent_attributes" not in payload["graph_trace"]["steps"][0]["decision_events"][0]["trace_summary"]["input"][
        "profile"
    ]
    assert all("latent_attributes" not in node["profile"] for node in payload["graph_trace"]["nodes"])


def test_write_report_html_renders_latent_group_table(tmp_path: Path) -> None:
    report_path = tmp_path / "report.html"

    write_report_html(_latent_result(), _latent_config(), report_path)

    html = report_path.read_text(encoding="utf-8")
    assert 'data-testid="latent-group-section"' in html
    assert "latent_class" in html
    assert "class_1" in html
    assert "latent_hotel_class" in html
    assert "economy" in html


def _group(report: dict[str, object], dimension: str, value: str) -> dict[str, object]:
    for group in report["groups"]:  # type: ignore[index]
        if group["group"] == {"dimension": dimension, "value": value}:
            return group
    raise AssertionError(f"missing group {dimension}={value}")


def _latent_config() -> SimulationInput:
    return SimulationInput(
        run_id="latent-report",
        simulation=SimulationConfig(horizon=1, seed_user_ids=["u1"]),
        graph_edges=[("u1", "u2"), ("u2", "u3"), ("u3", "u4")],
        profiles=[
            _profile("u1", "class_1", hotel_class="economy", travel_purpose="business", gender="female"),
            _profile(
                "u2",
                "class_1",
                hotel_class="midscale",
                travel_purpose="leisure",
                gender="male",
                monthly_income="income_15001_25000",
            ),
            _profile(
                "u3",
                "class_2",
                hotel_class="economy",
                travel_purpose="leisure",
                gender="female",
                monthly_income="income_25001_40000",
            ),
            UserProfile.model_validate(
                {
                    "user_id": "u4",
                    "nickname": "Alice",
                    "bio": "secret profile",
                    "signature": "private",
                    "raw_payload": {"x": 1},
                }
            ),
        ],
    )


def _latent_result() -> SimulationRunResult:
    return SimulationRunResult(
        run_id="latent-report",
        random_seed=42,
        horizon=1,
        metrics_summary={
            "total_agents": 4,
            "final_exposed": 3,
            "final_engaged": 2,
            "engagement_rate": 2 / 3,
        },
        step_records=[
            StepRecord(
                time_step=0,
                exposed_count=3,
                engaged_count=2,
                new_exposed_count=3,
                new_engaged_count=2,
                exposure_events=[
                    ExposureEvent(time_step=0, user_id="u1", channel="seed"),
                    ExposureEvent(time_step=0, user_id="u2", source_user_id="u1"),
                    ExposureEvent(time_step=0, user_id="u3", source_user_id="u2"),
                ],
                action_events=[
                    ActionEvent(time_step=0, user_id="u1", action="like"),
                    ActionEvent(time_step=0, user_id="u3", action="share"),
                ],
                decision_events=[_decision_event("u1", _profile("u1", "class_1", hotel_class="economy", travel_purpose="business", gender="female"))],
            )
        ],
    )


def _profile(
    user_id: str,
    latent_class: LatentClass,
    *,
    hotel_class: HotelClassLabel,
    travel_purpose: TravelPurposeLabel,
    gender: GenderLabel,
    monthly_income: MonthlyIncomeLabel = "income_8001_15000",
) -> UserProfile:
    return UserProfile(
        user_id=user_id,
        latent_attributes=LatentAttributes(
            spec_id="jinjiang_user_latent_attributes_v1",
            method="latent_class_exact_quota_v1",
            seed=20260630,
            latent_class=latent_class,
            environmental_consciousness_coef=1.0,
            value_weights=LatentValueWeights(
                epistemic=0.1,
                environmental=0.2,
                functional=0.3,
                health=0.4,
                emotional=0.5,
                social=0.6,
            ),
            profile_labels=LatentProfileLabels(
                hotel_class=hotel_class,
                travel_purpose=travel_purpose,
                gender=gender,
                age="age_26_35",
                education="bachelor",
                monthly_income=monthly_income,
            ),
        ),
    )


def _decision_event(user_id: str, profile: UserProfile) -> DecisionEvent:
    post = PostContent(post_id="p1", text="hotel offer")
    decision = EngageDecision(engage=True, probability=0.8, action="like", reason="test")
    return DecisionEvent(
        time_step=0,
        user_id=user_id,
        decision=decision,
        trace_summary=build_decision_trace_summary(
            user_id=user_id,
            post=post,
            profile=profile,
            peer_context=PeerContext(),
            platform_context=PlatformContext(),
            time_step=0,
            decision=decision,
            prompt_version="test",
        ),
    )
