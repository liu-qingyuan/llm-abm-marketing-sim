import hashlib
import json
from dataclasses import asdict
from typing import Any

import httpx

from llm_abm_sim.providers.moonshot import MoonshotOfficialClient


def test_estimate_matches_complete_chat_body_and_never_claims_usage():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'data': {'total_tokens': 659}})

    kwargs: dict[str, Any] = dict(reasoning_effort='low', output_token_ceiling=1024)
    messages = [{'role': 'user', 'content': '实际中文请求'}]
    with MoonshotOfficialClient(api_key='fixture', live_enabled=True,
                               transport=httpx.MockTransport(handler)) as client:
        quote = client.estimate_request(messages, 'kimi-k3', **kwargs)
        assert len(requests) == 1
        client.create_response(messages, 'kimi-k3', **kwargs)
        other = client.estimate_request([{'role': 'user', 'content': 'different'}], 'kimi-k3', **kwargs)
    assert requests[0].url.path == '/v1/tokenizers/estimate-token-count'
    assert requests[1].url.path == '/v1/chat/completions'
    assert requests[0].content == requests[1].content
    body = json.loads(requests[0].content)
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    assert quote.request_sha256 == hashlib.sha256(canonical).hexdigest()
    assert quote.request_sha256 != other.request_sha256
    assert asdict(quote) == dict(request_sha256=quote.request_sha256, estimated_input_tokens=659,
                                output_token_ceiling=1024, is_invoice=False)


def test_estimate_failures_never_retry_leak_payload_or_dispatch_chat():
    import pytest

    from llm_abm_sim.providers.moonshot import MoonshotEstimateError

    responses = [httpx.Response(status, text='PRIVATE_PAYLOAD') for status in (400, 401, 402, 403, 429, 503, 307)]
    responses += [httpx.Response(200, json=payload) for payload in (
        None, [], {}, {'data': None}, {'data': {'total_tokens': True}},
        {'data': {'total_tokens': 0}}, {'data': {'total_tokens': -1}},
        {'data': {'total_tokens': 2.5}}, {'data': {'total_tokens': '659'}},
        {'error': 'PRIVATE_PAYLOAD', 'data': {'total_tokens': 659}},
        {'status': False, 'data': {'total_tokens': 659}},
        {'code': 2, 'data': {'total_tokens': 659}},
    )]
    responses += [httpx.Response(200, text='PRIVATE_PAYLOAD'), httpx.ReadTimeout('PRIVATE_PAYLOAD')]
    for response in responses:
        calls = []

        def handler(request, response=response, calls=calls):
            calls.append(request)
            if isinstance(response, Exception):
                raise response
            return response

        with MoonshotOfficialClient(api_key='fixture', live_enabled=True,
                                   transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(MoonshotEstimateError) as exc:
                client.estimate_request([], 'kimi-k3', reasoning_effort='low', output_token_ceiling=1024)
            assert 'PRIVATE_PAYLOAD' not in str(exc.value)
        assert len(calls) == 1
        assert calls[0].url.path == '/v1/tokenizers/estimate-token-count'


def test_estimate_rejects_contract_mismatch_before_transport():
    import pytest

    calls = []
    with MoonshotOfficialClient(api_key='fixture', live_enabled=True,
                               transport=httpx.MockTransport(lambda r: (calls.append(r), httpx.Response(500))[1])) as client:
        for override in (
            {'model': 'k3-256k'}, {'reasoning_effort': None}, {'reasoning_effort': 'high'},
            {'output_token_ceiling': 256}, {'output_token_ceiling': 1024.0}, {'thinking_mode': 'enabled'},
        ):
            kwargs: dict[str, Any] = dict(model='kimi-k3', reasoning_effort='low', output_token_ceiling=1024)
            kwargs.update(override)
            with pytest.raises(ValueError):
                client.estimate_request([], **kwargs)
    assert not calls
