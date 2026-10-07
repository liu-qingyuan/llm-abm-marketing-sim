"""Respect observed Retry-After without changing frozen generation or request caps."""
import datetime,math

def observed_retry_not_before(failure):
 wait=failure.get('wait_seconds')
 if wait is None:return None
 if isinstance(wait,bool) or not isinstance(wait,(int,float)) or not math.isfinite(wait) or wait<0:raise ValueError('invalid observed cooldown')
 if wait==0:return None
 at=datetime.datetime.fromisoformat(failure['at_utc'])
 if at.tzinfo is None:raise ValueError('cooldown requires timezone-aware observed settlement')
 return at+datetime.timedelta(seconds=wait)
