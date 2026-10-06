"""Bind unchanged index arm definitions without importing/writing historical modules."""
import importlib.util
from pathlib import Path
from llm_abm_sim import _parameter_judgment_bank as bank

p=Path('/Users/liuqingyuan/work/llm-abm-marketing-sim/runs/gpt-p0-index-sensitivity-20260920-formal-01/study.py')
spec=importlib.util.spec_from_file_location('frozen_index_arms',p)
frozen=importlib.util.module_from_spec(spec)
exec(compile(p.read_bytes(),str(p),'exec'),frozen.__dict__)
ARMS=frozen.ARMS
arm_inputs=frozen.arm_inputs
key=frozen.key
