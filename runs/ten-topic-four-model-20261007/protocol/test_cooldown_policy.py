"""Pure settlement-metadata tests; no model responses, judgments or calls."""
import datetime
import pytest
from cooldown_policy import observed_retry_not_before

def test_server_503_deadline_exact():
 failure={'status_code':503,'failure_category':'http_status','at_utc':'2026-10-07T04:13:08+00:00','wait_seconds':7192.0}
 assert observed_retry_not_before(failure)==datetime.datetime(2026,10,7,6,13,0,tzinfo=datetime.timezone.utc)
 assert failure['status_code']==503

@pytest.mark.parametrize('wait',[None,0,0.0])
def test_no_observed_cooldown(wait):assert observed_retry_not_before({'wait_seconds':wait}) is None

@pytest.mark.parametrize('wait',[True,-1,float('nan'),float('inf'),'7192'])
def test_invalid_wait_stops_instead_of_redispatch(wait):
 with pytest.raises(ValueError):observed_retry_not_before({'at_utc':'2026-10-07T04:13:08+00:00','wait_seconds':wait})

def test_missing_timezone_stops():
 with pytest.raises(ValueError):observed_retry_not_before({'at_utc':'2026-10-07T04:13:08','wait_seconds':10})
