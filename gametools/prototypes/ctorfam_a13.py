"""Generate C++ sources for the Sims 2 "sub-object constructor" family (size 112-120 B).

Shape: arg0 = self, arg1 = source record. Calls func_02018734(self, arg1, self+0x18),
stores the vtable into self[0], calls func_02018ad0 / func_02018aa0 on the sub-object
self+0x18, writes sub-object fields and a u16 at self+0x10, then the virtual slot 3
(offset 0xC) with arg1->4, returns self.  Used by agent a13 (hunt r3).

usage: python ctorfam_a13.py NAME VT K SUB_STORES POST_STORES OUT.c
  SUB_STORES / POST_STORES: ';'-separated C statements (sub = sub-object pointer, self = arg0)
"""
import sys

TEMPLATE = '''#include "m2c.h"
struct VA {{
    virtual void f0();
    virtual void f1();
    virtual void f2();
    virtual void f3(s32 a);
}};
extern "C" void func_02018734(void *, s32, void *);
extern "C" void func_02018ad0(void *, void *);
extern "C" void func_02018aa0(void *, s32);
extern u8 {vt};
extern "C" void *{name}(void *arg0, void *arg1) {{
    void *self;
    void *a1;
    void *sub;
    self = arg0;
    a1 = arg1;
    func_02018734(self, (s32)a1, (u8 *)self + 0x18);
    sub = (u8 *)self + 0x18;
    *(void **)self = &{vt};
    func_02018ad0(sub, &{vt});
    func_02018aa0(sub, {K});
{sub_stores}
    *(u16 *)((u8 *)self + 0x10) = {K};
    ((VA *)self)->f3(*(s32 *)((u8 *)a1 + 4));
{post_stores}
    return self;
}}
'''


def build(name, vt, k, sub_stores, post_stores):
    def lines(s):
        return "\n".join("    " + x.strip() + ";" for x in s.split(";") if x.strip())
    return TEMPLATE.format(name=name, vt=vt, K=k, sub_stores=lines(sub_stores),
                           post_stores=lines(post_stores))


if __name__ == "__main__":
    name, vt, k, subs, posts, out = sys.argv[1:7]
    with open(out, "w", encoding="ascii") as f:
        f.write(build(name, vt, k, subs, posts))
