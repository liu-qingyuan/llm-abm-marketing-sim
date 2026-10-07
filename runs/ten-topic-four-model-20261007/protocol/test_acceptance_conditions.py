"""Metadata-only fixtures; no fabricated research decisions or Provider calls."""
from types import SimpleNamespace
import pytest
from accept_completed_cells import assert_request_condition

@pytest.mark.parametrize('route,ceiling',[('pi_openai_oauth_subscription',256),('antigravity_openai_compatible_gateway',256),('moonshot_official',1024),('deepseek_official',256)])
@pytest.mark.parametrize('template',['P0','P1','P2','P3'])
def test_exact_qualified_settings_and_declared_template(route,ceiling,template):
 qualified={'provider_route':route,'output_token_ceiling':ceiling,'prompt_version':'original-P0','prompt_canonical_hash':'sha256:original-P0'}
 prompt=SimpleNamespace(prompt_version='declared-'+template,canonical_hash='sha256:'+template)
 actual=dict(qualified,prompt_version=prompt.prompt_version,prompt_canonical_hash=prompt.canonical_hash)
 assert_request_condition(actual,qualified,prompt)
 for key,value in [('provider_route','other-channel'),('output_token_ceiling',ceiling+1),('prompt_version','wrong-template'),('prompt_canonical_hash','wrong-canonical-hash')]:
  with pytest.raises(AssertionError):assert_request_condition(dict(actual,**{key:value}),qualified,prompt)
