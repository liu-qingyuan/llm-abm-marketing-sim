"""Incremental index for the authoritative append-only ledger; never a result source."""
import json,os,sqlite3,fcntl,datetime,time,subprocess
from pathlib import Path
from contextlib import contextmanager
ROOT=Path(__file__).resolve().parents[1]
LEDGER=ROOT/'request-ledger.jsonl'
INDEX=ROOT/'.ledger-index.sqlite'
LOCK=ROOT/'.ledger-index.lock'
CAP=29143
@contextmanager
def indexed():
 with LOCK.open('a+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  db=sqlite3.connect(INDEX)
  try:
   db.execute('CREATE TABLE IF NOT EXISTS offsets(singleton INTEGER PRIMARY KEY, position INTEGER NOT NULL)')
   db.execute('INSERT OR IGNORE INTO offsets VALUES(1,0)')
   db.execute('CREATE TABLE IF NOT EXISTS intents(id TEXT PRIMARY KEY)')
   position=db.execute('SELECT position FROM offsets WHERE singleton=1').fetchone()[0]
   if LEDGER.exists():
    size=LEDGER.stat().st_size
    if size<position:raise ValueError('authoritative ledger truncated')
    with LEDGER.open('rb') as source:
     source.seek(position)
     while True:
      line=source.readline()
      if not line or not line.endswith(b'\n'):break
      row=json.loads(line)
      if row['type']=='intent':
       db.execute('INSERT INTO intents VALUES(?)',(row['request_id'],))
      position=source.tell()
   db.execute('UPDATE offsets SET position=? WHERE singleton=1',(position,));db.commit()
   yield db
   db.commit()
  finally:db.close();fcntl.flock(lock,fcntl.LOCK_UN)
def physical_count():
 with indexed() as db:return db.execute('SELECT COUNT(*) FROM intents').fetchone()[0]
def intent_exists(identity):
 with indexed() as db:return db.execute('SELECT 1 FROM intents WHERE id=?',(identity,)).fetchone() is not None
def legacy_remaining_reservation():
 bindings=ROOT/'protocol/active-process-bindings.json'
 if not bindings.exists():return 0
 entries=json.loads(bindings.read_text());remaining=0
 for label,slug in [('Gemini','gemini-3.1-pro'),('Kimi','Kimi')]:
  binding=entries.get(label)
  if binding is None:continue
  identity=subprocess.run(['ps','-p',str(binding['pid']),'-o','lstart=,args='],capture_output=True,text=True).stdout.strip()
  if identity!=binding['identity']:continue
  journal=ROOT/f'formal-paths/P0--{slug}-events.jsonl'
  terminal_count=0
  if journal.exists():
   for line in journal.read_text().splitlines():
    if not line.endswith('}'):continue
    row=json.loads(line)
    terminal_count+=row['kind']=='terminal'
  # Existing serial producers cannot produce more than one intent per remaining exposure.
  remaining+=max(0,1800-terminal_count)
 return remaining

def append_event(event):
 event=dict(event)
 while True:
  should_wait=False
  with indexed() as db:
   if event['type']=='intent':
    if db.execute('SELECT 1 FROM intents WHERE id=?',(event['request_id'],)).fetchone():raise ValueError('duplicate physical request identity; no silent resend')
    count=db.execute('SELECT COUNT(*) FROM intents').fetchone()[0]
    if count>=CAP:raise ValueError('physical budget reached before dispatch')
    # Two already-running initial producers predate this shared index. Reserve their entire
    # remaining serial exposure scopes near the cap; never overshoot on a stale legacy read.
    reservation=legacy_remaining_reservation() if count>=CAP-3600 else 0
    if count+reservation>=CAP:should_wait=True
    else:event['physical_ordinal']=count+1
   if not should_wait:
    event['at_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    with LEDGER.open('a') as output:
     output.write(json.dumps(event,ensure_ascii=False,sort_keys=True)+'\n');output.flush();os.fsync(output.fileno())
    return
  # No dispatched request exists while waiting for reserved legacy headroom.
  time.sleep(2)
