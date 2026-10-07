"""Metadata-only adversarial guard check; never constructs model judgments."""
import importlib.util,sys
from types import SimpleNamespace
spec=importlib.util.spec_from_file_location('acceptance_under_test',sys.argv[1]);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
if not hasattr(module,'assert_request_condition'):
 print('frozen_request_condition_guard=false');sys.exit(1)
qualified={'provider_route':'original-channel','output_token_ceiling':256,'prompt_version':'P0','prompt_canonical_hash':'hash-P0'};prompt=SimpleNamespace(prompt_version='P1',canonical_hash='hash-P1');actual=dict(qualified,prompt_version=prompt.prompt_version,prompt_canonical_hash=prompt.canonical_hash)
module.assert_request_condition(actual,qualified,prompt)
for key,value in [('provider_route','wrong-channel'),('output_token_ceiling',1024),('prompt_canonical_hash','wrong-hash')]:
 try:module.assert_request_condition(dict(actual,**{key:value}),qualified,prompt)
 except AssertionError:continue
 print('frozen_request_condition_guard=false');sys.exit(1)
print('frozen_request_condition_guard=true;wrong_route_ceiling_hash_rejected=true')
