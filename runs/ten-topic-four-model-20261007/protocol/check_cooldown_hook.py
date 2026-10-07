"""Inspect dispatch placement, then verify observed server deadline; zero Provider calls."""
import ast,sys
from pathlib import Path
from cooldown_policy import observed_retry_not_before
s=Path(sys.argv[1]).read_text();ast.parse(s)
required=['from cooldown_policy import observed_retry_not_before','observed=observed_retry_not_before(failure)','time.sleep(remaining)',"'cooldown_policy':'observed-Retry-After-before-dispatch-v1'"]
ok=all(x in s for x in required)
if ok:ok=s.index('time.sleep(remaining)')<s.index("append({'type':'intent'")
print('cooldown_before_dispatch='+str(ok).lower())
if not ok:sys.exit(1)
f={'at_utc':'2026-10-07T04:13:08+00:00','wait_seconds':7192.0}
print('observed_deadline='+observed_retry_not_before(f).isoformat())
