"""a5 r13: converts m2c draft stack locals spXX into one volatile frame array frm[N] (offset XX). Usage: a5_frame_volatile.py DRAFT FUNC FRAME_HEX OUT."""
import re,sys
# converts m2c draft stack locals spXX into one volatile frame array frm[N] (offset XX)
src=open(sys.argv[1]).read()
nwords=int(sys.argv[3],0)//4
out=[]
decl_re=re.compile(r'^\s*(s8|s16|s32|u8|u16|u32|void \*|M2C_UNK|void\*)\s+sp[0-9A-Fa-f]+;\s*$')
in_fn=False
for line in src.split('\n'):
    if (" "+sys.argv[2]+"(") in line and line.rstrip().endswith("{") and not in_fn:
        out.append(line)
        out.append('    volatile s32 frm[%d];' % nwords)
        in_fn=True
        continue
    if in_fn and decl_re.match(line):
        continue
    if in_fn:
        line=re.sub(r'\bsp([0-9A-Fa-f]{1,2})\b', lambda m: 'frm[%d]' % (int(m.group(1),16)//4), line)
    out.append(line)
open(sys.argv[4],'w').write('#include "m2c.h"\n'+'\n'.join(out))
