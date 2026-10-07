"""Local budget/durability fixtures only; no Provider objects or decisions."""
import importlib.util,json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest

def load(tmp_path):
 path=Path(__file__).with_name('ledger_store.py');spec=importlib.util.spec_from_file_location('isolated_ledger_store',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 m.ROOT=tmp_path;m.LEDGER=tmp_path/'ledger.jsonl';m.INDEX=tmp_path/'index.sqlite';m.LOCK=tmp_path/'ledger.lock';return m

def test_atomic_cap_and_unknown_no_redispatch(tmp_path):
 m=load(tmp_path);m.CAP=2
 m.append_event({'type':'intent','request_id':'a'})
 with pytest.raises(ValueError,match='duplicate'):m.append_event({'type':'intent','request_id':'a'})
 m.append_event({'type':'intent','request_id':'b'})
 with pytest.raises(ValueError,match='budget'):m.append_event({'type':'intent','request_id':'c'})
 assert m.physical_count()==2 and m.intent_exists('a')
 assert len(m.LEDGER.read_text().splitlines())==2

def test_concurrent_reservation_and_index_rebuild(tmp_path):
 m=load(tmp_path)
 with ThreadPoolExecutor(max_workers=5) as pool:list(pool.map(lambda n:m.append_event({'type':'intent','request_id':str(n)}),range(20)))
 assert m.physical_count()==20
 rows=[json.loads(x) for x in m.LEDGER.read_text().splitlines()]
 assert sorted(r['physical_ordinal'] for r in rows)==list(range(1,21))
 m.INDEX.unlink() # Disposable fixture cache, authoritative test ledger unchanged.
 assert m.physical_count()==20 and m.intent_exists('19')

def test_preexisting_intent_is_not_a_new_attempt(tmp_path):
 m=load(tmp_path);m.LEDGER.write_text('{"type":"intent","request_id":"lost-response"}\n')
 assert m.physical_count()==1
 with pytest.raises(ValueError,match='duplicate'):m.append_event({'type':'intent','request_id':'lost-response'})
