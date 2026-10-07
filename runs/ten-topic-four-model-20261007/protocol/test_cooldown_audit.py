"""Independent ledger timing fixtures contain only failures, never research judgments."""
import json
import pytest
import audit_ledger as audit
from test_collection_audit import fixture

def with_timing(tmp_path,monkeypatch,policy=False,late=False):
 fixture(tmp_path,monkeypatch)
 path=tmp_path/'request-ledger.jsonl';events=[json.loads(x) for x in path.read_text().splitlines()]
 intents=[e for e in events if e['type']=='intent']
 for i,e in enumerate(intents):e['at_utc']=f'2026-10-07T04:13:0{i}+00:00'
 failure=next(e for e in events if e['type']=='failed_or_unknown');failure.update(at_utc='2026-10-07T04:13:01+00:00',wait_seconds=7199.0)
 if policy:intents[-1].update(cooldown_policy='observed-Retry-After-before-dispatch-v1',dispatch_not_before_utc='2026-10-07T06:13:00+00:00')
 if late:intents[-1]['at_utc']='2026-10-07T06:13:00+00:00'
 path.write_text(''.join(json.dumps(e)+'\n' for e in events))

def test_old_violations_remain_visible(tmp_path,monkeypatch):
 with_timing(tmp_path,monkeypatch);audit.main()
 report=json.loads((tmp_path/'ledger-audit/LEDGER_AUDIT.json').read_text())
 assert len(report['pre_fix_retry_after_violations_retained'])==3 and report['physical_requests']==4

def test_postfix_early_dispatch_fails_acceptance(tmp_path,monkeypatch):
 with_timing(tmp_path,monkeypatch,policy=True)
 with pytest.raises(AssertionError):audit.main()

def test_postfix_dispatch_at_deadline_passes(tmp_path,monkeypatch):
 with_timing(tmp_path,monkeypatch,policy=True,late=True);audit.main()
 report=json.loads((tmp_path/'ledger-audit/LEDGER_AUDIT.json').read_text())
 assert report['post_fix_cooldown_intents_checked']==1 and len(report['pre_fix_retry_after_violations_retained'])==2
