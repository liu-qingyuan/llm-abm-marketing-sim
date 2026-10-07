import ast,sys
from pathlib import Path
module=ast.parse(Path(sys.argv[1]).read_text())
names={node.name for node in ast.walk(module) if isinstance(node,ast.FunctionDef)}
ok='render_ten_topic_research' in names
print('ten_topic_report_interface='+str(ok).lower());sys.exit(0 if ok else 1)
