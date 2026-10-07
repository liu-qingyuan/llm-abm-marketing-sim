import importlib.util,json,sys,tempfile
from pathlib import Path
spec=importlib.util.spec_from_file_location('checked',sys.argv[1]);a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
with tempfile.TemporaryDirectory() as d:
 a.ROOT=Path(d);auth=a.ROOT/'auth.json';auth.write_text(json.dumps({'global_physical_cap':29143,'maximum_physical_attempts_per_collection':3}));events=[]
 for n in range(1,5):
  rid='logical' if n==1 else 'logical:attempt'+str(n) if n<4 else 'logical:collection2'
  intent={'type':'intent','request_id':rid,'purpose':'formal_exposure','model':'gemini-3.1-pro','full_client_messages':[],'request_condition':{'frozen':True}}
  if n==4:intent.update(logical_request_id='logical',collection_id=rid,collection_number=2,collection_user_authorization=str(auth),exhausted_collection_parent_request_id='logical:attempt3')
  events.extend([intent,{'type':'failed_or_unknown','request_id':rid,'failure_category':'http_status','status_code':503}])
 (a.ROOT/'request-ledger.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
 try:a.main()
 except AssertionError:print('authorized_separate_collection_accepted=false');sys.exit(1)
 print('authorized_separate_collection_accepted=true')
