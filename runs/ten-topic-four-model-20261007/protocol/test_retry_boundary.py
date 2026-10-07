"""Pure retry eligibility tests; no model requests or judgment fixtures."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from bounded_dispatch import known_retry_allowed,missing_response_is_unknown

def test_unknown_never_auto_reissued():
 assert not known_retry_allowed(retryable=True,observed=False,status=None,category='transport',attempt=1)

def test_known_malformed_response_with_original_attempt_bound():
 assert known_retry_allowed(retryable=True,observed=True,status=None,category='malformed_structured_response',attempt=1)
 assert known_retry_allowed(retryable=True,observed=True,status=None,category='malformed_structured_response',attempt=2)
 assert not known_retry_allowed(retryable=True,observed=True,status=None,category='malformed_structured_response',attempt=3)

def test_explicit_rate_limit_is_known_but_auth_or_quota_stops():
 assert known_retry_allowed(retryable=True,observed=False,status=429,category='temporary_rate_limit',attempt=1)
 assert not known_retry_allowed(retryable=False,observed=False,status=402,category='quota_exhausted',attempt=1)
 assert not known_retry_allowed(retryable=True,observed=False,status=401,category='authentication',attempt=1)

def test_typed_provenance_unknown_is_not_nonretryable_known_failure():
 assert missing_response_is_unknown(error_type='ProviderResponseProvenanceUnknown',category=None,status=None,observed=False)
 assert missing_response_is_unknown(error_type='ProviderDecisionError',category='transport',status=None,observed=False)
 assert not missing_response_is_unknown(error_type='ProviderDecisionError',category='authentication',status=401,observed=False)
 assert not missing_response_is_unknown(error_type='ProviderDecisionError',category='quota_exhausted',status=402,observed=False)
 assert not missing_response_is_unknown(error_type='ProviderDecisionError',category='malformed_structured_response',status=None,observed=True)

def test_missing_timeout_response_is_unknown():
 assert missing_response_is_unknown(error_type='ProviderDecisionError',category='timeout',status=None,observed=False)

def test_typed_http_503_known_failure_retains_original_retry_bound():
 assert known_retry_allowed(retryable=True,observed=False,status=503,category='http_status',attempt=2)
 assert not known_retry_allowed(retryable=True,observed=False,status=503,category='http_status',attempt=3)
