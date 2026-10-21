"""
tests/fuzz.py - Random program generator for differential testing.

Generates random, well-typed programs (assignments, print, nested if/else,
bounded while loops, int/float/bool expressions, built-in calls) and checks
that every compilation stage computes exactly what the source program computes.

    python3 tests/fuzz.py [count] [seed]
"""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from compiler import compile_source, verify, CompileError  # noqa: E402
from interpreter import run_ast  # noqa: E402
from ops import EvalError  # noqa: E402


class Gen:
    def __init__(self, rng):
        self.r = rng
        self.vars = {}          # name -> type
        self.n = 0
        self.depth = 0
        self.loop_counters = set()

    def fresh(self):
        self.n += 1
        return f"v{self.n}"

    def var_of(self, ty, assignable=False):
        c = [v for v, t in self.vars.items() if t == ty and not (assignable and v in self.loop_counters)]
        return self.r.choice(c) if c else None

    def expr(self, ty, d=0):
        r = self.r
        if d > 3 or r.random() < 0.25:
            return self.leaf(ty)
        if ty == 'int':
            k = r.randrange(7)
            if k == 0:
                return f"-{self.expr('int', d + 1)}"
            if k == 1:
                return f"({self.expr('int', d + 1)} {r.choice(['/', '%'])} {r.randint(1, 5)})"
            if k == 2:
                return f"({self.leaf('int')} ^ {r.randint(0, 3)})"
            return f"({self.expr('int', d + 1)} {r.choice(['+', '-', '*'])} {self.expr('int', d + 1)})"
        if ty == 'float':
            k = r.randrange(6)
            if k == 0:
                return f"{r.choice(['sin', 'cos'])}({self.expr(r.choice(['int', 'float']), d + 1)})"
            if k == 1:
                return f"sqrt({r.randint(0, 50)} + {self.leaf('int')} * 0)"
            other = r.choice(['int', 'float'])
            a, b = self.expr('float', d + 1), self.expr(other, d + 1)
            if r.random() < 0.5:
                a, b = b, a
            return f"({a} {r.choice(['+', '-', '*', '+'])} {b})"
        # bool
        k = r.randrange(6)
        if k == 0:
            return f"!{self.expr('bool', d + 1)}"
        if k in (1, 2):
            return f"({self.expr('bool', d + 1)} {r.choice(['&&', '||'])} {self.expr('bool', d + 1)})"
        if k == 3 and self.var_of('bool'):
            return f"({self.expr('bool', d + 1)} {r.choice(['==', '!='])} {self.expr('bool', d + 1)})"
        t1 = r.choice(['int', 'float', 'int'])
        t2 = r.choice(['int', 'float']) if t1 == 'float' else r.choice(['int', 'int', 'float'])
        return f"({self.expr(t1, d + 1)} {r.choice(['<', '<=', '>', '>=', '==', '!='])} {self.expr(t2, d + 1)})"

    def leaf(self, ty):
        r = self.r
        v = self.var_of(ty)
        if v and r.random() < 0.6:
            return v
        if ty == 'int':
            return str(r.randint(0, 9))
        if ty == 'float':
            return f"{r.randint(0, 9)}.{r.choice(['0', '5', '25'])}"
        return r.choice(['true', 'false'])

    def stmt(self):
        r = self.r
        k = r.random()
        if k < 0.45 or self.depth >= 2:
            ty = r.choice(['int', 'int', 'float', 'bool'])
            existing = self.var_of(ty, assignable=True)
            if existing and r.random() < 0.5:
                name = existing
                if ty == 'float' and r.random() < 0.3:
                    return f"{name} = {self.expr('int')};"         # int -> float coercion
            else:
                name = self.fresh()
                e = self.expr(ty)
                self.vars[name] = ty
                return f"{name} = {e};"
            return f"{name} = {self.expr(ty)};"
        if k < 0.6:
            return f"print({self.expr(r.choice(['int', 'float', 'bool']))});"
        if k < 0.65:
            return f"{self.expr(r.choice(['int', 'float']))};"
        self.depth += 1
        try:
            if k < 0.85:
                s = f"if ({self.expr('bool')}) {{ {self.block()} }}"
                if r.random() < 0.6:
                    s += f" else {{ {self.block()} }}"
                elif r.random() < 0.3:
                    s += f" else if ({self.expr('bool')}) {{ {self.block()} }}"
                return s
            # bounded while loop; also plant a loop-invariant computation
            c = self.fresh()
            self.vars[c] = 'int'
            self.loop_counters.add(c)
            inv = self.var_of('int') or '3'
            cond = f"{c} < {r.randint(0, 6)}"
            if r.random() < 0.4:
                cond = f"({cond} && {self.expr('bool')})"
            extra = self.fresh()
            self.vars[extra] = 'int'
            body = self.block()
            return (f"{c} = 0; {extra} = 0; while ({cond}) {{ {body} {extra} = {inv} * 7 + {c}; "
                    f"{c} = {c} + 1; }}")
        finally:
            self.depth -= 1

    def block(self):
        return ' '.join(self.stmt() for _ in range(self.r.randint(0, 3)))

    def program(self):
        return '\n'.join(self.stmt() for _ in range(self.r.randint(3, 10)))


def check(src, regs=(2, 3, 4)):
    """Returns None if fine / not applicable, else a description of the failure."""
    try:
        c = compile_source(src, parser='ll', upto='semantic')
    except CompileError as e:
        return f"generator produced an invalid program ({e.phase}): {e.message}"
    try:
        run_ast(c.ast, c.symtab)
    except EvalError:
        return None                       # program faults at run time: skip
    slr = compile_source(src, parser='slr', upto='parse')
    if slr.ast != c.ast:
        return "LL(1) and SLR(1) parsers built different trees"
    for opt in (True, False):
        for n in regs:
            full = compile_source(src, nregs=n, opt=opt)
            v = verify(full)
            if not v.ok:
                return f"mismatch (opt={opt}, regs={n}): " + '; '.join(f"{s}: {o} {f}" for s, o, f in v.results)
    return None


if __name__ == '__main__':
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    rng = random.Random(seed)
    bad = 0
    for k in range(count):
        src = Gen(rng).program()
        err = check(src)
        if err:
            bad += 1
            print(f"--- program {k} ---\n{src}\n{err}\n")
            if bad >= 3:
                break
    print(f"{count} random programs checked, {bad} failure(s)")
    sys.exit(1 if bad else 0)
