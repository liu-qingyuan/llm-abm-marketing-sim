"""Known quota refusal stays known; positive fresh balance permits a separate retry."""
import datetime,math

def quota_recovery_allowed(failure,account,now=None):
 if failure.get('failure_category')!='quota_exhausted' or failure.get('status_code') not in [402,429]:return False
 if account.get('endpoint')!='https://api.moonshot.cn/v1/users/me/balance' or account.get('method')!='GET' or account.get('status_code')!=200:return False
 if account.get('model_requests')!=0:return False
 balance=account.get('balance_cny',{}).get('available_balance')
 if isinstance(balance,bool) or not isinstance(balance,(float,int)) or not math.isfinite(balance) or balance<=0:return False
 when=datetime.datetime.fromisoformat(account['at_utc']);now=now or datetime.datetime.now(datetime.timezone.utc)
 return when.tzinfo is not None and 0<=(now-when).total_seconds()<=3600
