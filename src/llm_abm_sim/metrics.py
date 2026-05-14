from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .events import ActionEvent, ExposureEvent


@dataclass
class StepMetrics:
    time_step: int
    exposed_count: int
    engaged_count: int
    new_exposed_count: int
    new_engaged_count: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass
class MetricsCollector:
    """Collect time-series diffusion metrics from event flow."""

    records: list[StepMetrics] = field(default_factory=list)
    exposure_events: list[ExposureEvent] = field(default_factory=list)
    action_events: list[ActionEvent] = field(default_factory=list)

    def record(
        self,
        time_step: int,
        exposed_count: int,
        engaged_count: int,
        previous_exposed_count: int,
        previous_engaged_count: int,
        exposure_events: list[ExposureEvent] | None = None,
        action_events: list[ActionEvent] | None = None,
    ) -> StepMetrics:
        self.exposure_events.extend(exposure_events or [])
        self.action_events.extend(action_events or [])
        record = StepMetrics(
            time_step=time_step,
            exposed_count=exposed_count,
            engaged_count=engaged_count,
            new_exposed_count=max(exposed_count - previous_exposed_count, 0),
            new_engaged_count=max(engaged_count - previous_engaged_count, 0),
        )
        self.records.append(record)
        return record

    def summary(self, total_agents: int) -> dict[str, float | int | list[str] | dict[str, int]]:
        if not self.records:
            return {
                "total_agents": total_agents,
                "final_exposed": 0,
                "final_engaged": 0,
                "reach_rate": 0.0,
                "engagement_rate": 0.0,
                "diffusion_depth": 0,
                "spread_speed": 0.0,
                "key_influencers": [],
                "conversion_trend": {},
            }
        final = self.records[-1]
        engagement_denominator = final.exposed_count or total_agents
        influencer_counts: dict[str, int] = {}
        for event in self.exposure_events:
            if event.source_user_id:
                influencer_counts[event.source_user_id] = influencer_counts.get(event.source_user_id, 0) + 1
        ranked_influencers = [
            user_id for user_id, _ in sorted(influencer_counts.items(), key=lambda item: (-item[1], item[0]))
        ]
        conversion_trend = {str(record.time_step): record.new_engaged_count for record in self.records}
        return {
            "total_agents": total_agents,
            "final_exposed": final.exposed_count,
            "final_engaged": final.engaged_count,
            "reach_rate": round(final.exposed_count / total_agents, 6) if total_agents else 0.0,
            "engagement_rate": round(final.engaged_count / engagement_denominator, 6)
            if engagement_denominator
            else 0.0,
            "diffusion_depth": max((event.depth for event in self.exposure_events), default=0),
            "spread_speed": round(sum(record.new_exposed_count for record in self.records) / len(self.records), 6),
            "key_influencers": ranked_influencers,
            "conversion_trend": conversion_trend,
            "like_count": sum(1 for event in self.action_events if event.action == "like"),
            "comment_count": sum(1 for event in self.action_events if event.action == "comment"),
            "share_count": sum(1 for event in self.action_events if event.action == "share"),
        }
