from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from llm_abm_sim.data_sources.douyin_collector import DouyinCollector, DouyinCollectRequest
from llm_abm_sim.data_sources.tikhub_client import TikHubClient, TikHubSettings


@pytest.mark.live_tikhub
def test_live_tikhub_gate_requires_explicit_env_and_writes_live_report(tmp_path: Path) -> None:
    if not (os.environ.get("TIKHUB_LIVE_FETCH") == "1" and os.environ.get("TIKHUB_API_KEY")):
        pytest.skip("live TikHub smoke requires TIKHUB_LIVE_FETCH=1 and TIKHUB_API_KEY")
    base_settings = TikHubSettings.from_env(os.environ)
    settings = base_settings.model_copy(
        update={
            "max_videos": 1,
            "max_comments_per_video": min(base_settings.max_comments_per_video or 5, 5),
            "max_replies_per_comment": min(base_settings.max_replies_per_comment or 2, 2),
            "max_users": min(base_settings.max_users or 20, 20),
        }
    )
    assert settings.live_readiness() == (True, "ready")
    assert settings.max_videos == 1
    assert settings.max_comments_per_video is not None
    assert settings.max_replies_per_comment is not None
    assert settings.max_users is not None
    assert settings.max_comments_per_video <= 5
    assert settings.max_replies_per_comment <= 2
    assert settings.max_users <= 20
    paths = DouyinCollector(TikHubClient(settings), settings).collect(
        DouyinCollectRequest(
            hashtag="锦江酒店",
            run_id="live-smoke",
            output_root=tmp_path,
            mode="live",
        )
    )
    report = json.loads(Path(paths["report"]).read_text(encoding="utf-8"))
    assert report["mode"] == "live"
    assert report["limits"]["max_videos"] == 1
    assert report["limits"]["max_comments_per_video"] <= 5
    assert report["limits"]["max_replies_per_comment"] <= 2
    assert report["limits"]["max_users"] <= 20
    assert "api_key" in report["redacted_config"]
    assert os.environ["TIKHUB_API_KEY"] not in json.dumps(report, ensure_ascii=False)
