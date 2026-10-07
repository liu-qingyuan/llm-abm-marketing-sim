"""Aggregation metadata fixtures only; no fake model judgments or Provider calls."""
import pytest
from summarize_call_ledger import amount,input_signature

def test_unknown_amount_not_zero():assert amount([{'nominal_usd':None}],'nominal_usd')==(None,0)
def test_explicit_zero_is_known():assert amount([{'nominal_usd':'0'}],'nominal_usd')==('0',1)
def test_decimal_sum_separate_known_count():assert amount([{'nominal_usd':'0.1'},{'nominal_usd':'0.2'},{'nominal_usd':None}],'nominal_usd')==('0.3',2)
@pytest.mark.parametrize('value',['-0.1','NaN','Infinity'])
def test_invalid_monetary_field_stops(value):
 with pytest.raises(AssertionError):amount([{'fee':value}],'fee')

def test_identity_requires_user_message_and_conditions_not_run_seed():
 a={'model':'model','template':'P0','user_id':'u','message_id':'m','full_client_messages':[],'request_condition':{'frozen':True}}
 assert input_signature(a)==input_signature(dict(a,output_directory='new',behavior_seed=20260824,time_step=29))
 for key,value in [('user_id','u2'),('message_id','m2'),('model','other'),('template','P1'),('request_condition',{'frozen':False})]:assert input_signature(a)!=input_signature(dict(a,**{key:value}))
