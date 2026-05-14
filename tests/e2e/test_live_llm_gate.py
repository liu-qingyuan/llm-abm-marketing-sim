import pytest

from llm_abm_sim.provider_config import load_codex_provider_config, should_run_live_llm


@pytest.mark.live_llm
def test_manual_live_llm_gate_requires_explicit_ready_runtime():
    if not should_run_live_llm():
        pytest.skip("live LLM gate requires LLM_ABM_RUN_LIVE_LLM=1 plus ready Codex auth/provider config")

    config = load_codex_provider_config()
    assert config is not None
    assert config.requires_openai_auth is True
    assert config.auth_available is True
    pytest.xfail("provider-backed live adapter is intentionally not part of the offline scaffold yet")
