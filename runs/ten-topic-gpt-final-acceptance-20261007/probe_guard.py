"""Pure contract/math probe on source copies; never executes research/Provider."""

import ast
import importlib.util
import sys
from pathlib import Path

p = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("guard_probe", p)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
labels = [
    n.args[1].value
    for n in ast.walk(ast.parse(p.read_text()))
    if isinstance(n, ast.Call)
    and isinstance(n.func, ast.Name)
    and n.func.id == "require"
    and len(n.args) > 1
    and isinstance(n.args[1], ast.Constant)
]
print(
    "matrix_guard="
    + ("exact_weight_threshold_matrix" if "original_exact_matrix" in labels else "names_only_fallback")
    + "; df99_t="
    + format(m.tq(0.975), ".12f")
    + "; provider_calls=0"
)
