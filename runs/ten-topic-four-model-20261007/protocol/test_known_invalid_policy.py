"""Eligibility metadata only; original invalid status is never changed into a judgment."""
import pytest
from known_invalid_policy import known_invalid_recollection_allowed

def test_observed_known_invalid_separate_recollection():
 f={'failure_category':'malformed_structured_response','retryable':False};r={'observed_model':'kimi-k3','usage_status':'complete','input_tokens':971,'output_tokens':1024,'total_tokens':1995}
 assert known_invalid_recollection_allowed(f,r,'kimi-k3')
 assert f['retryable'] is False and f['failure_category']=='malformed_structured_response'

@pytest.mark.parametrize('category',['quota_exhausted','model_identity','usage_evidence','authentication','response_evidence'])
def test_other_nonretryable_failures_are_not_admitted(category):
 assert not known_invalid_recollection_allowed({'failure_category':category,'retryable':False},{'observed_model':'kimi-k3'},'kimi-k3')

@pytest.mark.parametrize('change',[{'observed_model':'other-model'},{'usage_status':'unknown'},{'output_tokens':1025,'total_tokens':1996},{'input_tokens':True},{'total_tokens':0}])
def test_response_identity_usage_and_original_ceiling_required(change):
 f={'failure_category':'malformed_structured_response','retryable':False};r={'observed_model':'kimi-k3','usage_status':'complete','input_tokens':971,'output_tokens':1024,'total_tokens':1995};r.update(change)
 assert not known_invalid_recollection_allowed(f,r,'kimi-k3')
