"""split_asm.py NAME JSON NINSNS JOIN_TARGET SECOND_NAME OUT.c : workbench-info asm -> mwcc asm functions.
The first NINSNS instructions become `asm void NAME`, whose branch `#0x...` goes to JOIN_TARGET; the rest falls
through into `asm void SECOND_NAME`."""
import json, os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import auto_match as am  # noqa: E402
from asmconv import pre_ual  # noqa: E402

name, js, n, join, second, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5], sys.argv[6]
asm = json.load(open(js))['asm']
asm = re.sub(r'(\s+b\w*\s+)#0x[0-9a-f]+', r'\1' + join, asm)
am.ASM_ONLY = re.compile(r'.', re.M)
src = am.asm_function_general(name, asm)
src = '\n'.join(pre_ual(l) for l in src.split('\n'))
C = 'eq|ne|cs|hs|cc|lo|mi|pl|vs|vc|hi|ls|ge|lt|gt|le'
src = re.sub(r'^(\s*)(and|eor|sub|rsb|add|adc|sbc|rsc|orr|mov|bic|mvn|mul|mla)s(' + C + r')\b', r'\1\2\3s', src, flags=re.M)
src = re.sub(r'^(\s*)rrx(s?)(\w*)\s+(\w+),\s*(\w+)$', r'\1mov\3\2 \4, \5, rrx', src, flags=re.M)
head, body = src.split(f'asm void {name}(void) {{\n', 1)
body, tail = body.rsplit('\n}\n', 1)
lines = body.split('\n')
first, rest = lines[:n], lines[n:]
head = head.replace('/* Uses instructions the compiler never generates: written in assembly. */\n', '')
head = re.sub(r'extern void (\w+)\(\);\n', lambda m: '' if m.group(1) == second else f'void {m.group(1)}(void);\n', head)
code = (head + f'asm void {name}(void) {{\n' + '\n'.join(first) + '\n}\n\n'
        + f'asm void {second}(void) {{\n' + '\n'.join(rest) + '\n}\n' + tail)
open(out, 'w', newline='\n').write(code)
print(code[:800])
