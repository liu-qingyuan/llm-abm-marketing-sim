"""Private immutable metadata snapshot guard; zero Provider calls."""
import importlib.util,sys,tempfile,hashlib
from pathlib import Path
spec=importlib.util.spec_from_file_location('summary_snapshot_under_test',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
if not hasattr(m,'save_snapshot'):print('private_content_addressed_snapshot=false');sys.exit(1)
with tempfile.TemporaryDirectory() as d:
 raw=b'{"metadata_only":true}\n';sha=hashlib.sha256(raw).hexdigest();p=m.save_snapshot(Path(d),sha,raw);before=p.stat().st_mtime_ns
 assert m.save_snapshot(Path(d),sha,raw)==p and p.stat().st_mtime_ns==before and p.stat().st_mode & 0o777==0o600
 print('private_content_addressed_snapshot=true;mode=0600;idempotent=true')
