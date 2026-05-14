from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StepMetrics:
    time_step: int
    exposed_count: int
    engaged_count: int
    new_engaged_count: int


@dataclass
class MetricsCollector:
    """Collect time-series diffusion metrics."""

    records: list[StepMetrics] = field(default_factory=list)

    def record(self, time_step: int, exposed_count: int, engaged_count: int, previous_engaged_count: int) -> None:
        self.records.append(
            StepMetrics(
                time_step=time_step,
                exposed_count=exposed_count,
                engaged_count=engaged_count,
                new_engaged_count=max(engaged_count - previous_engaged_count, 0),
            )
        )
