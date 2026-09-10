import pytest

from llm_abm_sim.concurrent_robustness_recovery_task import _self_check_input
from llm_abm_sim.decision import ProviderDecisionError
from llm_abm_sim.provider_accounting import ProviderResponseEnvelope


class Client:
    external_provider_client = False
    provider_transport = "moonshot_official"

    def __init__(self, **changes):
        self.calls = []
        values = dict(decision_text='{"engage":false,"probability":0.3,"reason":"fit","confidence":0.8,"action":"ignore"}',
                      observed_model='kimi-k3', observed_model_status='reported', usage_status='complete',
                      input_tokens=660, output_tokens=302, total_tokens=962)
        values.update(changes)
        self.response = ProviderResponseEnvelope.model_validate(values)

    def create_response(self, messages, model, **settings):
        self.calls.append((messages, model, settings))
        return self.response


def decide(adapter):
    d = _self_check_input()
    return adapter.decide(post=d.post, profile=d.profile, peer_context=d.peer_context,
                          platform_context=d.platform_context, time_step=d.time_step)


def test_official_identity_and_prompt_without_modifying_original_disclosure():
    from llm_abm_sim.providers.robustness import OfficialKimiDecisionAdapter, robustness_provider_disclosures

    before = robustness_provider_disclosures()
    client = Client()
    adapter = OfficialKimiDecisionAdapter(prompt_version=_self_check_input().prompt_version, client=client)
    result = decide(adapter)
    assert result.decision_source == 'provider'
    assert result.provider_metadata is not None
    assert result.provider_metadata['requested_model'] == 'kimi-k3'
    assert adapter.required_observed_model == 'kimi-k3'
    assert adapter.provider_route == 'moonshot_official'
    assert adapter.request_evidence['output_token_ceiling'] == 1024
    assert adapter.request_evidence['billing_currency'] == 'CNY'
    assert adapter.last_provider_fee_cny is None
    assert len(client.calls) == 1
    assert client.calls[0][1] == 'kimi-k3'
    assert robustness_provider_disclosures() == before


@pytest.mark.parametrize(('changes', 'failure'), [
    ({'observed_model': 'k3-256k'}, 'model_identity'),
    ({'output_tokens': 1025, 'total_tokens': 1685}, 'output_ceiling_exceeded'),
    ({'usage_status': 'missing', 'input_tokens': None, 'output_tokens': None, 'total_tokens': None}, 'usage_evidence'),
    ({'decision_text': ''}, 'malformed_structured_response'),
])
def test_rejects_invalid_response_after_accounting_without_retry(changes, failure):
    from llm_abm_sim.providers.robustness import OfficialKimiDecisionAdapter

    client = Client(**changes)
    adapter = OfficialKimiDecisionAdapter(prompt_version=_self_check_input().prompt_version, client=client)
    with pytest.raises(ProviderDecisionError) as exc:
        decide(adapter)
    assert exc.value.failure_category == failure
    assert exc.value.retryable is False
    assert len(client.calls) == 1
    assert adapter.provider_accounting.provider_response_count == 1
    assert adapter.provider_accounting.successful_decision_count == 0
    assert adapter.provider_accounting.total_tokens == client.response.total_tokens


def test_rejects_subscription_transport_before_dispatch():
    from llm_abm_sim.providers.robustness import OfficialKimiDecisionAdapter

    client = Client()
    client.external_provider_client = True
    client.provider_transport = 'kimi-coding'
    with pytest.raises(ValueError):
        OfficialKimiDecisionAdapter(prompt_version=_self_check_input().prompt_version, client=client)
    assert client.calls == []


def test_unknown_is_not_converted_to_retryable_failure():
    from llm_abm_sim.decision import ProviderResponseProvenanceUnknown
    from llm_abm_sim.providers.robustness import OfficialKimiDecisionAdapter

    class UnknownClient(Client):
        def create_response(self, *args, **kwargs):
            self.calls.append(1)
            raise ProviderResponseProvenanceUnknown('unsettled')

    client = UnknownClient()
    adapter = OfficialKimiDecisionAdapter(prompt_version=_self_check_input().prompt_version, client=client)
    with pytest.raises(ProviderResponseProvenanceUnknown):
        decide(adapter)
    assert len(client.calls) == 1
    assert adapter.provider_accounting.provider_response_count == 0
