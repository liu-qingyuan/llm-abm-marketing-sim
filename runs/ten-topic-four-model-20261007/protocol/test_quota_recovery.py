"""Offline account-metadata fixtures only; no model or account HTTP calls."""
import datetime,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from quota_recovery import quota_recovery_allowed
NOW=datetime.datetime(2026,10,7,tzinfo=datetime.timezone.utc)
def account(value):return {'endpoint':'https://api.moonshot.cn/v1/users/me/balance','method':'GET','status_code':200,'model_requests':0,'at_utc':NOW.isoformat(),'balance_cny':{'available_balance':value}}
def test_zero_balance_remains_blocked():
 assert not quota_recovery_allowed({'failure_category':'quota_exhausted','status_code':429},account(0),NOW)
def test_restored_balance_does_not_change_old_failure():
 f={'failure_category':'quota_exhausted','status_code':429,'retryable':False}
 assert quota_recovery_allowed(f,account(20),NOW)
 assert f=={'failure_category':'quota_exhausted','status_code':429,'retryable':False}
def test_stale_or_wrong_source_cannot_authorize():
 f={'failure_category':'quota_exhausted','status_code':429}
 assert not quota_recovery_allowed(f,account(20),NOW+datetime.timedelta(hours=2))
 a=account(20);a['endpoint']='https://other.example/balance';assert not quota_recovery_allowed(f,a,NOW)
def test_boolean_balance_and_nonquota_are_not_recovery():
 assert not quota_recovery_allowed({'failure_category':'quota_exhausted','status_code':429},account(True),NOW)
 assert not quota_recovery_allowed({'failure_category':'authentication','status_code':401},account(20),NOW)
