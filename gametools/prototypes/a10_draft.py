"""a10_draft.py OUT_DIR NAME... : write the m2c draft of each function (from workbench info) to OUT_DIR/NAME.c, judged by the caller."""
import json, subprocess, sys, os
out_dir = sys.argv[1]
here = os.path.dirname(os.path.abspath(__file__))
for name in sys.argv[2:]:
    out = subprocess.run([sys.executable, os.path.join(here, '..', 'workbench.py'), 'info', name], capture_output=True, text=True).stdout
    try:
        d = json.loads(out[out.find('{'):])
    except Exception:
        print('no info', name); continue
    draft = d.get('draft') or ''
    path = os.path.join(out_dir, name + '.c')
    if not os.path.exists(path):
        open(path, 'w').write(draft if draft else '#include "m2c.h"\n')
    print(name, len(draft))
