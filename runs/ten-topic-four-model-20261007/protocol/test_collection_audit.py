"""Offline synthetic failure-only ledger fixtures; not research judgments."""
import json
import pytest
import audit_ledger as audit

def fixture(tmp_path,monkeypatch,new_attempts=1,model='gemini-3.1-pro',parent_count=3,changed_input=False):
 monkeypatch.setattr(audit,'ROOT',tmp_path)
 authorization=tmp_path/'authorization.json';authorization.write_text(json.dumps({'global_physical_cap':29143,'maximum_physical_attempts_per_collection':3}))
 events=[]
 for i in range(1,parent_count+1):
  rid='logical' if i==1 else 'logical:attempt'+str(i)
  events += [{'type':'intent','request_id':rid,'model':model,'purpose':'formal_exposure','full_client_messages':[],'request_condition':{'frozen':True}}, {'type':'failed_or_unknown','request_id':rid,'failure_category':'http_status','status_code':503}]
 for i in range(1,new_attempts+1):
  rid='logical:collection2'+('' if i==1 else ':attempt'+str(i))
  events += [{'type':'intent','request_id':rid,'logical_request_id':'logical','collection_id':'logical:collection2','collection_number':2,'model':model,'purpose':'formal_exposure','full_client_messages':[{}] if changed_input else [],'request_condition':{'frozen':True},'collection_user_authorization':str(authorization),'exhausted_collection_parent_request_id':'logical:attempt3'}, {'type':'failed_or_unknown','request_id':rid,'failure_category':'http_status','status_code':503}]
 (tmp_path/'request-ledger.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in events))

def test_authorized_separate_collection(tmp_path,monkeypatch):
 fixture(tmp_path,monkeypatch);audit.main()
 evidence=json.loads((tmp_path/'ledger-audit/LEDGER_AUDIT.json').read_text())
 assert evidence['physical_requests']==4 and evidence['explicit_additional_collection_count']==1 and evidence['provider_calls_during_audit']==0

@pytest.mark.parametrize('kwargs',[{'new_attempts':4},{'model':'kimi-k3'},{'parent_count':2},{'changed_input':True}])
def test_reject_invalid_collection(tmp_path,monkeypatch,kwargs):
 fixture(tmp_path,monkeypatch,**kwargs)
 with pytest.raises((AssertionError,KeyError)):audit.main()
