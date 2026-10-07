"""Inspect explicit known-invalid collection guard; do not call any Provider."""
import ast,sys
from pathlib import Path
s=Path(sys.argv[1]).read_text();ast.parse(s)
ok=all(x in s for x in ['known_invalid_recollection_allowed','KNOWN_INVALID_RECOLLECTION_AUTHORIZATION.json','explicit_known_invalid_new_collection','known_invalid_parent_request_id'])
print('known_invalid_separate_collection='+str(ok).lower());sys.exit(0 if ok else 1)
