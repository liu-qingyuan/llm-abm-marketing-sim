"""Check a captured main HEAD against actual preserved Git commit ancestry."""
import json
import subprocess
import sys
from pathlib import Path

record = json.loads(Path(sys.argv[1]).read_bytes())
repo = Path(__file__).resolve().parents[2]
result = subprocess.run(['git', 'merge-base', '--is-ancestor', record['research_head'], record['main_head']], cwd=repo)
print('research_history_in_main=' + str(result.returncode == 0).lower())
raise SystemExit(result.returncode)
