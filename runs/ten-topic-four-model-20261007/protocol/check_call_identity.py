"""Zero-Provider signature guard check, with only synthetic request metadata."""
import importlib.util,sys
spec=importlib.util.spec_from_file_location('summary_under_test',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
a={'model':'model','template':'P0','user_id':'u','message_id':'m','full_client_messages':[],'request_condition':{'frozen':True}}
ok=m.input_signature(a)!=m.input_signature(dict(a,user_id='other')) and m.input_signature(a)!=m.input_signature(dict(a,message_id='other'))
print('unique_input_requires_user_and_message='+str(ok).lower());sys.exit(0 if ok else 1)
