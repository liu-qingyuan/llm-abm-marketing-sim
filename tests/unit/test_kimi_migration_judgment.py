from copy import deepcopy

import pytest

from llm_abm_sim._concurrent_recovery_judgment import RecoveryJudgmentV1
from tests.unit.test_concurrent_recovery_judgment import _attempt, _payload, _rehash


def official_payload(with_failure=False):
    p = _payload(historical=False)
    p['schema_version'] = 'concurrent-recovery-provider-judgment-v4'
    p['official_migration_approval'] = {'path': '/fixture/migration.json', 'sha256': 'c' * 64}
    p['cell_index'] = 12
    p['cell'].update(cell_id='P0::kimi-coding/k3-256k', requested_model='kimi-coding/k3-256k',
                     required_observed_model='k3-256k')
    success = _attempt(2 if with_failure else 1)
    success.update(provider_route='moonshot_official', observed_model_counts={'kimi-k3': 1},
                   billing_semantics='token_metered_cny', billing_currency='CNY')
    attempts = []
    if with_failure:
        failure = _attempt(1, outcome='nonretryable_failure', no_response=True)
        failure.update(provider_route='pi_kimi_oauth_subscription', failure_category='entitlement', status_code=403,
                       billing_semantics='subscription_quota_with_nominal_usd_reference', billing_currency=None)
        attempts.append(failure)
    p['new_attempts'] = [*attempts, success]
    _rehash(p)
    return p


def test_official_judgment_keeps_original_cell_and_true_response_identity():
    p = official_payload(True)
    original = deepcopy(p)
    result = RecoveryJudgmentV1.model_validate(p)
    assert p == original
    assert result.cell.required_observed_model == 'k3-256k'
    assert result.new_attempts[-1].observed_model_counts == {'kimi-k3': 1}
    assert result.new_attempts[0].status_code == 403
    assert result.new_attempts[0].total_usage is None
    assert result.new_attempts[-1].attempt_number == 2
    assert result.model_dump(mode='json') == original


def test_new_official_pair_and_legacy_serialization_are_separate():
    p = official_payload()
    result = RecoveryJudgmentV1.model_validate(p)
    assert result.new_attempts[0].attempt_number == 1
    assert result.successful_sequence_accounting.observed_model_counts == {'kimi-k3': 1}
    legacy = _payload(historical=False)
    assert RecoveryJudgmentV1.model_validate(legacy).model_dump(mode='json') == legacy
    assert 'official_migration_approval' not in legacy


def test_migration_reference_does_not_make_original_v1_accept_official_route():
    p = official_payload()
    p['schema_version'] = 'concurrent-recovery-provider-judgment-v1'
    p.pop('official_migration_approval')
    _rehash(p)
    with pytest.raises(ValueError):
        RecoveryJudgmentV1.model_validate(p)



@pytest.mark.parametrize('fault', ['missing_ref', 'old_success', 'old_401', 'new_model', 'new_route',
                                  'cap', 'extra_retry', 'quota_ref', 'output_ref', 'usage'])
def test_official_judgment_rejects_crossed_migration(fault):
    p = official_payload(True)
    if fault == 'missing_ref':
        p.pop('official_migration_approval')
    elif fault == 'old_success':
        p['new_attempts'][0] = deepcopy(p['new_attempts'][-1])
        p['new_attempts'][0]['attempt_number'] = 1
    elif fault == 'old_401':
        p['new_attempts'][0]['status_code'] = 401
    elif fault == 'new_model':
        p['new_attempts'][-1]['observed_model_counts'] = {'k3-256k': 1}
    elif fault == 'new_route':
        p['new_attempts'][-1].update(provider_route='pi_kimi_oauth_subscription',
                                    billing_semantics='subscription_quota_with_nominal_usd_reference', billing_currency=None)
    elif fault == 'cap':
        p['new_attempts'][-1].update(output_usage=1025, total_usage=1035)
    elif fault == 'extra_retry':
        p['new_attempts'].insert(1, deepcopy(p['new_attempts'][0]))
        p['new_attempts'][1]['attempt_number'] = 2
        p['new_attempts'][-1]['attempt_number'] = 3
    elif fault == 'quota_ref':
        p['quota_retry_approval'] = p['official_migration_approval']
    elif fault == 'output_ref':
        p['output_amendment_approval'] = p['official_migration_approval']
    else:
        p['new_attempts'][-1]['total_usage'] += 1
    _rehash(p)
    with pytest.raises(ValueError):
        RecoveryJudgmentV1.model_validate(p)
