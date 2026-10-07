"""Read-only independent serialization/public-body checks; no Provider imports."""
from pathlib import Path
import concurrent.futures
import csv
import hashlib
import io
import json
import re
import subprocess
import datetime

P = Path(__file__).resolve().parent
location = json.loads((P / 'RELEASE_LOCATION.json').read_text())
source = Path(location['source_directory'])
contract = json.loads(Path(location['contract']).read_text())
html = (source / 'report.html').read_bytes()
payload = re.search(rb'<script type="application/json" id="ten-topic-public-data">(.*?)</script>', html, re.S)
assert payload
data = json.loads(payload[1])
rows = list(csv.DictReader((source / 'ten-topic/whole/results.csv').open(encoding='utf-8-sig')))
totals = {k: sum(int(r[k]) for r in rows) for k in ('exposures', 'like', 'comment', 'share', 'ignore')}
assert totals == data['whole']['summary']
assert totals['exposures'] == 109200
assert sum(totals[k] for k in ('like', 'comment', 'share', 'ignore')) == 109200
assert len(data['models']['conditions']) == 16
assert sum(r['exposures'] for r in data['models']['conditions']) == 28800
assert data['index']['local_p99_rebuilt_overlap'] == 23
for name in ('parameters', 'index'):
    estimates = data[name]['estimates']
    assert all(r['n'] == 100 for r in estimates)
    assert len({r['configuration'] for r in estimates}) == (21 if name == 'parameters' else 7)
assert len(data['models']['paired_seed']) == 384
assert len({r['configuration'] for r in data['parameters']['estimates'] if r['metric'] == 'engagement_rate' and r['message'] == 'all'}) == 21

def download(item):
    name, expected = item
    destination = P / 'public-body-downloads' / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    url = 'https://abm.q1ngyuan.top/' + name + '?release=' + location['release_id']
    result = subprocess.run(['curl', '-fsSL', '--retry', '3', '--max-time', '180', '-H', 'Cache-Control: no-cache', url, '-o', str(destination)], capture_output=True)
    assert result.returncode == 0, (name, result.returncode)
    actual = hashlib.sha256(destination.read_bytes()).hexdigest()
    assert actual == expected, (name, expected, actual)
    return {'path': name, 'sha256': actual, 'bytes': destination.stat().st_size, 'http_body_match': True}

items = [(k, v) for k, v in contract['artifact_sha256'].items() if k.startswith('ten-topic/') or k in ('report.html', 'artifact_manifest.json', 'single-topic-report.html', 'single-topic-artifact-manifest.json')]
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    bodies = list(pool.map(download, items))
out = {'schema_version': 'ten-topic-independent-publication-acceptance-v1', 'status': 'pass', 'at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'release_id': location['release_id'], 'provider_calls': 0, 'independent_checks': ['HTML embedded JSON parsed without Report code', 'CSV exclusive counts and totals match rendered JSON', '21/7 configurations with n100; 16 conditions with 28800 exposures', '384 paired-panel estimates downloadable', 'all new public downloads and original historical HTML/manifest full body SHA matches'], 'shared_checks': 'Production Release rematerialization/workbook cell comparison share the Report projection; original research acceptance supplies independent experiment validation.', 'whole_totals': totals, 'public_body_count': len(bodies), 'public_bodies': sorted(bodies, key=lambda r:r['path'])}
(P / 'PUBLIC_ACCEPTANCE.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
print(f"PASS independent publication checks; {len(bodies)} public full bodies; provider_calls=0")
