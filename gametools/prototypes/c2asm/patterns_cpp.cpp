/* c2asm C++ patterns: same format as patterns.c (`// @p NAME: description` above `p_NAME`).
 * Compiled with -lang=c++ and the game's flags (exceptions and RTTI off on most DS games). */
typedef int s32;
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned long size_t;

extern void sink(s32);
void *operator new(size_t n);
void operator delete(void *p);

struct Base {
    s32 x;
    virtual ~Base();
    virtual void f(s32 a);
    virtual s32 g();
    void plain(s32 a);
};
struct Other { s32 y; virtual void h(); };
struct Derived : Base, Other { s32 z; };
struct Holder { s32 pad; Base member; };
struct Small { s32 a, b; Small() : a(0), b(-1) {} };
struct WithVt { s32 a; WithVt(); virtual void k(); };

// @p vcall: virtual call without a return value
void p_vcall(Base *b) { b->f(3); }

// @p vcallret: virtual call whose result is used
s32 p_vcallret(Base *b) { return b->g() + 1; }

// @p vcallnull: virtual call guarded by a null check
void p_vcallnull(Base *b) { if (b) b->f(0); }

// @p vdelete: delete through a virtual destructor
void p_vdelete(Base *b) { delete b; }

// @p membercall: call a method of an embedded member object
void p_membercall(Holder *h) { h->member.plain(5); }

// @p membervcall: virtual call on an embedded member object
void p_membervcall(Holder *h) { h->member.f(1); }

// @p upcast: cast to the second base (this adjustment with null check)
Other *p_upcast(Derived *d) { return d; }

// @p downcast: static_cast from the second base back to the derived class
Derived *p_downcast(Other *o) { return static_cast<Derived *>(o); }

// @p newsmall: new of a small class with an inline constructor
Small *p_newsmall() { return new Small; }

// @p newvt: new of a class with an out-of-line constructor
WithVt *p_newvt() { return new WithVt; }

// @p newarr: new of an int array
s32 *p_newarr(s32 n) { return new s32[n]; }

// @p refparam: increment through a reference
void p_refparam(s32 &r) { r += 2; }

// @p secondbasecall: virtual call through the second base
void p_secondbasecall(Derived *d) { d->h(); }
