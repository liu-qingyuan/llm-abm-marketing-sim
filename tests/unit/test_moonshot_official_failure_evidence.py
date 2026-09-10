"""Offline transport-to-Study regression: a hard HTTP failure must stay recordable."""
import httpx
import pytest

from llm_abm_sim import concurrent_robustness_v2 as v2
from llm_abm_sim.concurrent_robustness_recovery_task import _self_check_input
from llm_abm_sim.decision import ProviderDecisionError
from llm_abm_sim.providers.moonshot import MoonshotOfficialClient
from llm_abm_sim.providers.robustness import OfficialKimiDecisionAdapter


@pytest.mark.parametrize('status', [402, 429, 503])
def test_terminal_http_failure_preserves_typed_cooldown_without_retry(status):
    calls = []
    def transport(request):
        calls.append(request.url.path)
        return httpx.Response(status, json={})
    with MoonshotOfficialClient(api_key='offline-fixture', live_enabled=True,
                                transport=httpx.MockTransport(transport)) as client:
        data = _self_check_input()
        adapter = OfficialKimiDecisionAdapter(prompt_version=data.prompt_version, client=client)
        before = v2._v2_adapter_snapshot(adapter)
        with pytest.raises(ProviderDecisionError) as error:
            adapter.decide(post=data.post, profile=data.profile, peer_context=data.peer_context,
                           platform_context=data.platform_context, time_step=data.time_step)
        row = v2._v2_attempt_evidence(adapter=adapter, before=before, attempt_number=1,
              outcome='nonretryable_failure', error=error.value, wait_seconds=None, wait_source=None)
        assert error.value.retryable is False
        assert row.status_code == status and row.lane_cooldown == (status != 402)
        assert row.wait_seconds is None and row.request_invocations == 1
        assert len(calls) == 1
