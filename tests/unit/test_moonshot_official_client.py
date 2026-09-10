import json

import httpx


def test_official_client_uses_fixed_request_and_retains_wire_usage():
    from llm_abm_sim.providers.moonshot import MoonshotOfficialClient

    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={
            'model': 'kimi-k3',
            'usage': {'prompt_tokens': 660, 'completion_tokens': 302, 'total_tokens': 962},
            'choices': [{'finish_reason': 'tool_calls', 'message': {'tool_calls': [
                {'type': 'function', 'function': {'name': 'engage_decision', 'arguments': json.dumps({
                    'engage': False, 'probability': .32, 'reason': 'test', 'confidence': .78, 'action': 'ignore'
                })}}
            ]}}],
        })

    with MoonshotOfficialClient(api_key='fixture-not-a-secret', live_enabled=True,
                                transport=httpx.MockTransport(handler)) as client:
        result = client.create_response([{'role': 'user', 'content': 'test'}], 'kimi-k3',
                                        reasoning_effort='low', output_token_ceiling=1024)
    assert len(requests) == 1
    assert str(requests[0].url) == 'https://api.moonshot.cn/v1/chat/completions'
    body = json.loads(requests[0].content)
    assert body['tool_choice'] == 'required'
    assert body['tools'][0]['function']['parameters']['type'] == 'object'
    assert body['max_tokens'] == 1024
    assert body['reasoning_effort'] == 'low'
    assert result.observed_model == 'kimi-k3'
    assert result.output_tokens == 302
    assert result.total_tokens == 962
    assert result.cached_input_tokens is None


def test_malformed_tool_preserves_known_response_model_and_usage():
    from llm_abm_sim.providers.moonshot import MoonshotOfficialClient

    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={
        'model': 'kimi-k3', 'usage': {'prompt_tokens': 5, 'completion_tokens': 9, 'total_tokens': 14},
        'choices': [{'finish_reason': 'length', 'message': {'content': 'unusable'}}],
    }))
    with MoonshotOfficialClient(api_key='fixture', live_enabled=True, transport=transport) as client:
        result = client.create_response([], 'kimi-k3', reasoning_effort='low', output_token_ceiling=1024)
    assert result.decision_text == ''
    assert result.observed_model == 'kimi-k3'
    assert result.total_tokens == 14


def test_http_error_is_single_attempt_and_does_not_leak_body():
    import pytest

    from llm_abm_sim.decision import ProviderAttemptFailure
    from llm_abm_sim.providers.moonshot import MoonshotOfficialClient

    for status in (400, 401, 402, 403, 429, 503, 307):
        calls = []

        def handler(request, calls=calls, status=status):
            calls.append(request)
            return httpx.Response(status, text='PRIVATE_PAYLOAD', headers={'location': 'https://example.com'})

        with MoonshotOfficialClient(api_key='fixture', live_enabled=True,
                                    transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ProviderAttemptFailure) as exc:
                client.create_response([], 'kimi-k3', reasoning_effort='low', output_token_ceiling=1024)
            assert exc.value.status_code == status
            assert exc.value.retryable is False
            assert 'PRIVATE_PAYLOAD' not in str(exc.value)
        assert len(calls) == 1


def test_transport_failure_remains_unknown_without_retry():
    import pytest

    from llm_abm_sim.decision import ProviderResponseProvenanceUnknown
    from llm_abm_sim.providers.moonshot import MoonshotOfficialClient

    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout('PRIVATE_PAYLOAD')

    with MoonshotOfficialClient(api_key='fixture', live_enabled=True,
                                transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderResponseProvenanceUnknown) as exc:
            client.create_response([], 'kimi-k3', reasoning_effort='low', output_token_ceiling=1024)
    assert len(calls) == 1
    assert 'PRIVATE_PAYLOAD' not in str(exc.value)


def test_live_gate_and_request_mismatch_dispatch_nothing():
    import pytest

    from llm_abm_sim.providers.moonshot import MoonshotOfficialClient

    with pytest.raises(ValueError):
        MoonshotOfficialClient(api_key='fixture')
    calls = []
    with MoonshotOfficialClient(api_key='fixture', live_enabled=True,
                                transport=httpx.MockTransport(lambda r: (calls.append(r), httpx.Response(500))[1])) as client:
        with pytest.raises(ValueError):
            client.create_response([], 'k3-256k', reasoning_effort='low', output_token_ceiling=1024)
        assert 'fixture' not in json.dumps(client.safe_metadata)
    assert not calls


def test_missing_usage_and_wrong_identity_remain_observed_not_relabelled():
    from llm_abm_sim.providers.moonshot import MoonshotOfficialClient

    with MoonshotOfficialClient(api_key='fixture', live_enabled=True,
                                transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
                                    'model': 'different-model', 'choices': []
                                }))) as client:
        result = client.create_response([], 'kimi-k3', reasoning_effort='low', output_token_ceiling=1024)
    assert result.observed_model == 'different-model'
    assert result.usage_status == 'missing'
    assert result.total_tokens is None
