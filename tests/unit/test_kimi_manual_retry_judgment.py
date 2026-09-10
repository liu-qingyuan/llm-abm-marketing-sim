import pytest

from llm_abm_sim._concurrent_recovery_judgment import RecoveryJudgmentV1
from tests.unit.test_concurrent_recovery_judgment import _rehash
from tests.unit.test_kimi_migration_judgment import official_payload


def manual_payload():
    p = official_payload()
    p['schema_version'] = 'concurrent-recovery-provider-judgment-v5'
    p['manual_retry_approval'] = {'path': '/fixture/manual.json', 'sha256': 'd' * 64}
    p['unknown_attempts'] = [{'attempt_number': 1, 'intent_sha256': 'e' * 64}]
    p['new_attempts'][0]['attempt_number'] = 2
    _rehash(p)
    return p


def test_manual_retry_keeps_unknown_without_inventing_failure_or_usage():
    p = manual_payload()
    j = RecoveryJudgmentV1.model_validate(p)
    assert j.model_dump(mode='json') == p
    assert j.unknown_attempts[0].attempt_number == 1
    assert j.new_attempts[0].attempt_number == 2
    assert j.observed_model == 'kimi-k3'
    terminal = j.realized_projection(realization_source_identity='f' * 64)
    assert terminal.request_invocations == 2
    assert j.unknown_usage_present is True




@pytest.mark.parametrize('fault', ['no_approval', 'no_intent', 'bad_hash', 'extra_unknown', 'old_version',
                                  'ordinal_one', 'ordinal_three', 'bool_ordinal', 'fake_status', 'fake_usage',
                                  'missing_migration', 'old_route', 'old_model'])
def test_manual_retry_rejects_invented_or_unapproved_history(fault):
    p = manual_payload()
    if fault == 'no_approval':
        p.pop('manual_retry_approval')
    elif fault == 'no_intent':
        p['unknown_attempts'] = []
    elif fault == 'bad_hash':
        p['unknown_attempts'][0]['intent_sha256'] = 'bad'
    elif fault == 'extra_unknown':
        p['unknown_attempts'] *= 2
    elif fault == 'old_version':
        p['schema_version'] = 'concurrent-recovery-provider-judgment-v4'
    elif fault in ('ordinal_one', 'ordinal_three'):
        p['new_attempts'][0]['attempt_number'] = 1 if fault == 'ordinal_one' else 3
    elif fault == 'bool_ordinal':
        p['unknown_attempts'][0]['attempt_number'] = True
    elif fault == 'fake_status':
        p['unknown_attempts'][0]['status_code'] = 429
    elif fault == 'fake_usage':
        p['unknown_attempts'][0]['total_usage'] = 0
    elif fault == 'missing_migration':
        p.pop('official_migration_approval')
    elif fault == 'old_route':
        p['new_attempts'][0]['provider_route'] = 'pi_kimi_oauth_subscription'
    else:
        p['new_attempts'][0]['observed_model_counts'] = {'k3-256k': 1}
    _rehash(p)
    with pytest.raises(ValueError):
        RecoveryJudgmentV1.model_validate(p)
