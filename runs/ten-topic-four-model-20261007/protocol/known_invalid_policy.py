"""Known invalid response stays invalid; explicit recollection is not a retryability rewrite."""
def known_invalid_recollection_allowed(failure,response,model):
 if model!='kimi-k3' or failure.get('failure_category')!='malformed_structured_response' or failure.get('retryable') is not False:return False
 if not response or response.get('observed_model')!='kimi-k3' or response.get('usage_status')!='complete':return False
 tokens=[response.get(k) for k in ['input_tokens','output_tokens','total_tokens']]
 if any(isinstance(x,bool) or not isinstance(x,int) or x<0 for x in tokens):return False
 return tokens[0]+tokens[1]==tokens[2] and tokens[1]<=1024
