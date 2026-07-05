from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .events import SimulationRunResult
from .graph_loader import DatasetValidationReport, load_network_dataset
from .provider_evidence import decision_source_summary, provider_evidence
from .safe_serialization import safe_data
from .schemas import (
    LATENT_PROFILE_LABEL_FIELDS,
    SimulationInput,
    SupportedLanguage,
    UserProfile,
    default_available_languages,
)

METRIC_KEYS = [
    "total_agents",
    "final_exposed",
    "final_engaged",
    "reach_rate",
    "engagement_rate",
    "diffusion_depth",
    "spread_speed",
    "like_count",
    "comment_count",
    "share_count",
]
LatentGroupDimension = Literal[
    "latent_class",
    "latent_hotel_class",
    "latent_travel_purpose",
    "latent_gender",
    "latent_age",
    "latent_education",
    "latent_monthly_income",
]
LATENT_GROUP_DIMENSIONS: tuple[LatentGroupDimension, ...] = (
    "latent_class",
    "latent_hotel_class",
    "latent_travel_purpose",
    "latent_gender",
    "latent_age",
    "latent_education",
    "latent_monthly_income",
)
LATENT_GROUP_PRIVACY_NOTICE = (
    "Latent labels are Virtual Experiment Labels for controlled ABM grouping. "
    "They are not real user identity, not real demographic attributes, and not psychological profiles."
)


class MetricView(BaseModel):
    key: str
    value: float | int | str | list[str] | dict[str, int]
    label_key: str
    description_key: str


class LatentGroupKey(BaseModel):
    dimension: LatentGroupDimension
    value: str


class LatentGroupMetrics(BaseModel):
    group: LatentGroupKey
    user_count: int
    exposed_count: int
    engaged_count: int
    engagement_rate: float


class LatentGroupReport(BaseModel):
    available: bool
    privacy_notice: str = LATENT_GROUP_PRIVACY_NOTICE
    groups: list[LatentGroupMetrics] = Field(default_factory=list)


class ReportPayload(BaseModel):
    """Sanitized view-model boundary consumed by HTML/JS report rendering."""

    schema_version: str = "report-payload-v1"
    title: str
    default_language: SupportedLanguage = "en-US"
    available_languages: list[SupportedLanguage] = Field(default_factory=default_available_languages)
    run: dict[str, Any]
    inputs: dict[str, Any]
    metrics: list[MetricView]
    trend: list[dict[str, Any]]
    graph_trace: dict[str, Any]
    dataset_validation: dict[str, Any] | None
    decision_source_summary: dict[str, int]
    provider_evidence: dict[str, Any] | None
    latent_group_report: LatentGroupReport
    narrative: dict[str, str]


def build_report_payload(
    result: SimulationRunResult,
    config: SimulationInput,
    *,
    dataset_validation_report: DatasetValidationReport | None = None,
    provider_readiness: dict[str, Any] | None = None,
) -> ReportPayload:
    trace = build_graph_trace(result, config)
    source_summary = decision_source_summary(result)
    dataset_payload = dataset_validation_report.to_dict() if dataset_validation_report is not None else None
    metrics = [
        MetricView(
            key=key,
            value=result.metrics_summary[key],
            label_key=f"metric.{key}.label",
            description_key=f"metric.{key}.desc",
        )
        for key in METRIC_KEYS
        if key in result.metrics_summary
    ]
    decision_mode = "provider-backed" if source_summary.get("provider", 0) else "offline rule-based"
    inputs = {
        "post": config.post.model_dump(mode="json"),
        "seed_user_ids": config.simulation.seed_user_ids,
        "platform_context": config.platform_context.model_dump(mode="json"),
        "dataset": config.dataset.model_dump(mode="json"),
        "profile_count": len(config.profiles) if config.profiles else (dataset_payload or {}).get("profile_count", 0),
        "edge_count": len(config.graph_edges)
        if config.graph_edges
        else (dataset_payload or {}).get("graph_edge_count", 0),
        "decision_mode": decision_mode,
        "provider_configured": config.provider_llm.enabled,
    }
    run = {
        "run_id": result.run_id,
        "random_seed": result.random_seed,
        "horizon": result.horizon,
        "time_step_label": config.simulation.time_step_label,
        "observation_window": config.simulation.observation_window,
    }
    trend = [_report_payload_data(record.model_dump(mode="json")) for record in result.step_records]
    narrative = {
        "summary_en": _narrative_summary(result, source_summary, "en-US"),
        "summary_zh": _narrative_summary(result, source_summary, "zh-CN"),
    }
    latent_group_report = build_latent_group_report(result, config)
    return ReportPayload.model_validate(
        safe_data(
            {
                "title": config.report.title,
                "default_language": config.report.default_language,
                "available_languages": config.report.available_languages,
                "run": run,
                "inputs": inputs,
                "metrics": [metric.model_dump(mode="json") for metric in metrics],
                "trend": trend,
                "graph_trace": trace,
                "dataset_validation": dataset_payload,
                "decision_source_summary": source_summary,
                "provider_evidence": provider_evidence(result, provider_readiness),
                "latent_group_report": latent_group_report.model_dump(mode="json"),
                "narrative": narrative,
            }
        )
    )


def build_latent_group_report(result: SimulationRunResult, config: SimulationInput) -> LatentGroupReport:
    """Aggregate spread outcomes by allowed latent class and Table 11 label dimensions."""

    dataset = load_network_dataset(
        config.dataset,
        inline_edges=[(str(left), str(right)) for left, right in config.graph_edges],
        inline_profiles=config.profiles,
        seed_user_ids=config.simulation.seed_user_ids,
    )
    profiles = dataset.profiles
    exposed_user_ids = {event.user_id for event in result.exposure_events}
    engaged_user_ids = {event.user_id for event in result.action_events}

    groups: dict[tuple[LatentGroupDimension, str], dict[str, set[str]]] = {}
    for user_id, profile in profiles.items():
        for dimension, value in _latent_group_values(profile):
            bucket = groups.setdefault(
                (dimension, value),
                {"users": set(), "exposed": set(), "engaged": set()},
            )
            bucket["users"].add(user_id)
            if user_id in exposed_user_ids:
                bucket["exposed"].add(user_id)
            if user_id in engaged_user_ids:
                bucket["engaged"].add(user_id)

    metrics = []
    for dimension in LATENT_GROUP_DIMENSIONS:
        dimension_groups = sorted(
            ((value, counts) for (group_dimension, value), counts in groups.items() if group_dimension == dimension),
            key=lambda item: item[0],
        )
        for value, counts in dimension_groups:
            exposed_count = len(counts["exposed"])
            engaged_count = len(counts["engaged"])
            metrics.append(
                LatentGroupMetrics(
                    group=LatentGroupKey(dimension=dimension, value=value),
                    user_count=len(counts["users"]),
                    exposed_count=exposed_count,
                    engaged_count=engaged_count,
                    engagement_rate=round(engaged_count / exposed_count, 6) if exposed_count else 0.0,
                )
            )

    return LatentGroupReport(available=bool(metrics), groups=metrics)


def _latent_group_values(profile: UserProfile) -> list[tuple[LatentGroupDimension, str]]:
    attributes = profile.latent_attributes
    if attributes is None:
        return []
    values: list[tuple[LatentGroupDimension, str]] = [("latent_class", attributes.latent_class)]
    profile_labels = attributes.profile_labels.model_dump(mode="json")
    for field_name in LATENT_PROFILE_LABEL_FIELDS:
        dimension = f"latent_{field_name}"
        if dimension in LATENT_GROUP_DIMENSIONS:
            values.append((dimension, str(profile_labels[field_name])))  # type: ignore[arg-type]
    return values


def _report_payload_data(value: Any) -> Any:
    return _drop_report_only_profile_fields(safe_data(value))


def _drop_report_only_profile_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _drop_report_only_profile_fields(item)
            for key, item in value.items()
            if key != "latent_attributes"
        }
    if isinstance(value, list):
        return [_drop_report_only_profile_fields(item) for item in value]
    return value


def build_graph_trace(result: SimulationRunResult, config: SimulationInput) -> dict[str, Any]:
    """Build the offline interactive graph trace consumed by report.html."""

    dataset = load_network_dataset(
        config.dataset,
        inline_edges=[(str(left), str(right)) for left, right in config.graph_edges],
        inline_profiles=config.profiles,
        seed_user_ids=config.simulation.seed_user_ids,
    )
    graph = dataset.graph
    profiles = dataset.profiles
    seed_ids = set(config.simulation.seed_user_ids)
    max_step = max([0, *[step.time_step for step in result.step_records]])

    exposures_by_user: dict[str, list[dict[str, Any]]] = {}
    decisions_by_user: dict[str, list[dict[str, Any]]] = {}
    actions_by_user: dict[str, list[dict[str, Any]]] = {}
    exposed_steps: dict[str, int] = {}
    engaged_steps: dict[str, int] = {}

    for exposure_event in result.exposure_events:
        payload = _report_payload_data(exposure_event.model_dump(mode="json"))
        exposures_by_user.setdefault(exposure_event.user_id, []).append(payload)
        exposed_steps[exposure_event.user_id] = min(
            exposed_steps.get(exposure_event.user_id, exposure_event.time_step), exposure_event.time_step
        )
    for decision_event in result.decision_events:
        payload = _report_payload_data(decision_event.model_dump(mode="json"))
        decisions_by_user.setdefault(decision_event.user_id, []).append(payload)
    for action_event in result.action_events:
        payload = _report_payload_data(action_event.model_dump(mode="json"))
        actions_by_user.setdefault(action_event.user_id, []).append(payload)
        engaged_steps[action_event.user_id] = min(
            engaged_steps.get(action_event.user_id, action_event.time_step), action_event.time_step
        )

    nodes = []
    for node_id in sorted(str(node) for node in graph.nodes):
        profile = profiles.get(node_id)
        profile_payload = (
            _report_payload_data(profile.model_dump(mode="json", exclude={"latent_attributes"}))
            if profile is not None
            else {"user_id": node_id}
        )
        nodes.append(
            {
                "id": node_id,
                "label": node_id,
                "profile": profile_payload,
                "is_seed": node_id in seed_ids,
                "timeline": [
                    _node_timeline_entry(
                        node_id,
                        time_step,
                        exposed_steps,
                        engaged_steps,
                        exposures_by_user,
                        decisions_by_user,
                        actions_by_user,
                    )
                    for time_step in range(max_step + 1)
                ],
            }
        )

    edges = [
        {"source": str(source), "target": str(target), "attributes": dict(attributes)}
        for source, target, attributes in sorted(graph.edges(data=True), key=lambda edge: (str(edge[0]), str(edge[1])))
    ]
    steps = [
        {
            "time_step": step.time_step,
            "exposed_count": step.exposed_count,
            "engaged_count": step.engaged_count,
            "new_exposed_count": step.new_exposed_count,
            "new_engaged_count": step.new_engaged_count,
            "exposure_events": [_report_payload_data(event.model_dump(mode="json")) for event in step.exposure_events],
            "decision_events": [_report_payload_data(event.model_dump(mode="json")) for event in step.decision_events],
            "action_events": [_report_payload_data(event.model_dump(mode="json")) for event in step.action_events],
        }
        for step in result.step_records
    ]
    return _report_payload_data(
        {
            "schema_version": "graph-trace-v1",
            "nodes": nodes,
            "edges": edges,
            "steps": steps,
            "post": config.post.model_dump(mode="json"),
            "run": {
                "run_id": result.run_id,
                "random_seed": result.random_seed,
                "horizon": result.horizon,
                "time_step_label": config.simulation.time_step_label,
                "observation_window": config.simulation.observation_window,
                "decision_source_summary": source_summary
                if (source_summary := decision_source_summary(result))
                else {},
            },
            "process": [
                "Environment computes exposure",
                "Agent observes post and neighbor behavior",
                "DecisionAdapter decides",
                "User state/action updates",
                "Metrics/events collected",
            ],
        }
    )


def _node_timeline_entry(
    node_id: str,
    time_step: int,
    exposed_steps: dict[str, int],
    engaged_steps: dict[str, int],
    exposures_by_user: dict[str, list[dict[str, Any]]],
    decisions_by_user: dict[str, list[dict[str, Any]]],
    actions_by_user: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    exposures = [event for event in exposures_by_user.get(node_id, []) if event["time_step"] == time_step]
    decisions = [event for event in decisions_by_user.get(node_id, []) if event["time_step"] == time_step]
    actions = [event for event in actions_by_user.get(node_id, []) if event["time_step"] == time_step]
    if node_id in engaged_steps and engaged_steps[node_id] <= time_step:
        state = "engaged"
    elif node_id in exposed_steps and exposed_steps[node_id] <= time_step:
        state = "exposed"
    else:
        state = "unseen"
    return {
        "time_step": time_step,
        "state": state,
        "exposures": exposures,
        "decisions": decisions,
        "actions": actions,
    }


def _narrative_summary(result: SimulationRunResult, source_summary: dict[str, int], language: SupportedLanguage) -> str:
    final_exposed = result.metrics_summary.get("final_exposed", 0)
    final_engaged = result.metrics_summary.get("final_engaged", 0)
    engagement_rate = result.metrics_summary.get("engagement_rate", 0)
    source_text = ", ".join(f"{key}={value}" for key, value in source_summary.items()) or "none"
    if language == "zh-CN":
        return f"本次模拟最终触达 {final_exposed} 个用户，其中 {final_engaged} 个发生互动，互动率为 {engagement_rate}。决策来源：{source_text}。"
    return f"The run reached {final_exposed} users; {final_engaged} engaged, with engagement rate {engagement_rate}. Decision sources: {source_text}."
