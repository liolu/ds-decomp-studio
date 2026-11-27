"""a10_brief.py NAME... : print compact asm lines + best C (if any) of each function from workbench info, for hand matching."""
import json, subprocess, sys, os
for name in sys.argv[1:]:
    out = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), '..', 'workbench.py'), 'info', name], capture_output=True, text=True).stdout
    i = out.find('{')
    try:
        d = json.loads(out[i:])
    except Exception:
        print('==', name, 'no json'); continue
    print('==', name, 'size', d.get('size'), 'callers', d.get('callers'), 'calls', d.get('calls'), 'data', d.get('data'))
    print('\n'.join(d.get('lines', [])))
    if d.get('draft') and not d.get('matched'):
        print('-- draft:'); print(d['draft'][:600])
