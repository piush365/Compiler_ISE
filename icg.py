"""
icg.py - Module 4: Intermediate Code Generation.

Translates the type-checked AST into THREE-ADDRESS CODE (TAC) stored as
QUADRUPLES (op, arg1, arg2, result), and can show the same code as TRIPLES and
INDIRECT TRIPLES.

Boolean expressions and flow-of-control statements are translated with
BACKPATCHING (Dragon book, section 6.7): a jump whose target is not yet known
is emitted with an empty target and put on a list; when the target becomes
known the whole list is "backpatched".

    B -> B1 || M B2   backpatch(B1.falselist, M.quad)
                      B.truelist = merge(B1.truelist, B2.truelist); B.falselist = B2.falselist
    B -> B1 && M B2   backpatch(B1.truelist, M.quad)
                      B.truelist = B2.truelist; B.falselist = merge(B1.falselist, B2.falselist)
    B -> ! B1         B.truelist = B1.falselist; B.falselist = B1.truelist
    B -> E1 relop E2  B.truelist = [nextquad]; B.falselist = [nextquad + 1]
                      emit('if E1 relop E2 goto _'); emit('goto _')
    S -> if (B) M S1 N else M S2
                      backpatch(B.truelist, M1.quad); backpatch(B.falselist, M2.quad)
                      S.nextlist = merge(S1.nextlist, N.nextlist, S2.nextlist)
    S -> while M1 (B) M2 S1
                      backpatch(S1.nextlist, M1.quad); backpatch(B.truelist, M2.quad)
                      S.nextlist = B.falselist; emit('goto M1.quad')
    L -> L1 M S       backpatch(L1.nextlist, M.quad); L.nextlist = S.nextlist

Calls to the built-in functions use the procedure-call form
    param x
    t = call sin, 1
"""
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from ast_nodes import Num, Bool, Var, BinOp, UnaryOp, FuncCall, Assign, Print, Block, If, While
from ops import TOKEN_OP, RELOPS, fmt_value

# 'iffalse x goto L' is never produced by the ICG; the optimizer creates it when
# it inverts a conditional jump (jumps over jumps).
JUMP_OPS = tuple('if' + r for r in RELOPS) + ('if', 'iffalse', 'goto')
UNARY_OPS = ('uminus', 'not', 'inttofloat')
BINARY_OPS = ('+', '-', '*', '/', '%', '^')


def fmt(a):
    return a if isinstance(a, str) else fmt_value(a)


@dataclass
class Quad:
    op: str
    arg1: Any = None
    arg2: Any = None
    result: Any = None      # destination name, or jump target (quad index / block label)

    def is_jump(self):
        return self.op in JUMP_OPS

    def is_cond_jump(self):
        return self.op in JUMP_OPS and self.op != 'goto'

    def defines(self) -> Optional[str]:
        """Name assigned by this instruction, if any."""
        if self.op in ('=', 'call') + BINARY_OPS + UNARY_OPS:
            return self.result
        return None

    def uses(self) -> List[str]:
        if self.op == 'call':
            return []
        if self.op in ('goto', 'halt'):
            return []
        return [a for a in (self.arg1, self.arg2) if isinstance(a, str)]

    def __str__(self):
        op, a, b, r = self.op, fmt(self.arg1), fmt(self.arg2), self.result
        if op == '=':
            return f"{r} = {a}"
        if op in BINARY_OPS:
            return f"{r} = {a} {op} {b}"
        if op in UNARY_OPS:
            return f"{r} = {op} {a}"
        if op == 'goto':
            return f"goto {r if r is not None else '_'}"
        if op == 'if':
            return f"if {a} goto {r if r is not None else '_'}"
        if op == 'iffalse':
            return f"ifFalse {a} goto {r if r is not None else '_'}"
        if op.startswith('if'):
            return f"if {a} {op[2:]} {b} goto {r if r is not None else '_'}"
        if op == 'param':
            return f"param {a}"
        if op == 'call':
            return f"{r} = call {self.arg1}, {self.arg2}"
        if op == 'print':
            return f"print {a}"
        if op == 'halt':
            return "halt"
        return f"({op}, {a}, {b}, {r})"


class IntermediateCodeGenerator:
    def __init__(self, symtab):
        self.symtab = symtab
        self.quads: List[Quad] = []
        self.types: Dict[str, str] = {s.name: s.type for s in symtab.variables()}
        names = set(self.types)
        self.temp_prefix = '_t' if any(re.fullmatch(r't\d+', n) for n in names) else 't'
        self.ntemps = 0
        self.temps: set = set()

    # ---------- helpers ----------
    @property
    def nextquad(self):
        return len(self.quads)

    def emit(self, op, a1=None, a2=None, res=None) -> int:
        self.quads.append(Quad(op, a1, a2, res))
        return len(self.quads) - 1

    def newtemp(self, ty) -> str:
        self.ntemps += 1
        t = f"{self.temp_prefix}{self.ntemps}"
        self.types[t] = ty
        self.temps.add(t)
        return t

    def backpatch(self, lst, target):
        for i in lst:
            self.quads[i].result = target

    # ---------- statements ----------
    def generate(self, program) -> List[Quad]:
        nxt = self.stmt_list(program)
        self.backpatch(nxt, self.nextquad)
        self.emit('halt')
        return self.quads

    def stmt_list(self, stmts):
        nextlist = []
        for s in stmts:                     # L -> L1 M S
            self.backpatch(nextlist, self.nextquad)
            nextlist = self.stmt(s)
        return nextlist

    def stmt(self, s):
        if isinstance(s, Assign):
            addr = self.rvalue(s.expr)
            if self.types[s.var_name] == 'float' and s.expr.ty == 'int':
                addr = self.coerce(addr)
            self.emit('=', addr, None, s.var_name)
            return []
        if isinstance(s, Print):
            self.emit('print', self.rvalue(s.expr))
            return []
        if isinstance(s, Block):
            return self.stmt_list(s.stmts)
        if isinstance(s, If):
            truelist, falselist = self.cond(s.cond)
            self.backpatch(truelist, self.nextquad)
            n1 = self.stmt_list(s.then_body)
            if s.else_body is None:
                return n1 + falselist
            n = [self.emit('goto')]                      # N: jump over the else part
            self.backpatch(falselist, self.nextquad)
            n2 = self.stmt_list(s.else_body)
            return n1 + n + n2
        if isinstance(s, While):
            begin = self.nextquad
            truelist, falselist = self.cond(s.cond)
            self.backpatch(truelist, self.nextquad)
            n1 = self.stmt_list(s.body)
            self.backpatch(n1, begin)
            self.emit('goto', res=begin)
            return falselist
        self.rvalue(s)                                    # expression statement
        return []

    # ---------- expressions producing a value ----------
    def coerce(self, addr):
        if not isinstance(addr, str):
            return float(addr)
        t = self.newtemp('float')
        self.emit('inttofloat', addr, None, t)
        return t

    def operand(self, child, want):
        addr = self.rvalue(child)
        if want == 'float' and child.ty == 'int':
            addr = self.coerce(addr)
        return addr

    def rvalue(self, n):
        if isinstance(n, (Num, Bool)):
            return n.value
        if isinstance(n, Var):
            return n.name
        if n.ty == 'bool':
            # boolean value needed: evaluate with jumping code, then materialise it
            truelist, falselist = self.cond(n)
            t = self.newtemp('bool')
            self.backpatch(truelist, self.nextquad)
            self.emit('=', True, None, t)
            self.emit('goto', res=self.nextquad + 2)
            self.backpatch(falselist, self.nextquad)
            self.emit('=', False, None, t)
            return t
        if isinstance(n, BinOp):
            op = TOKEN_OP[n.op.type]
            want = 'float' if n.ty == 'float' else 'int'
            a = self.operand(n.left, want)
            b = self.operand(n.right, want)
            t = self.newtemp(n.ty)
            self.emit(op, a, b, t)
            return t
        if isinstance(n, UnaryOp):                        # unary minus (! is boolean)
            a = self.rvalue(n.expr)
            t = self.newtemp(n.ty)
            self.emit('uminus', a, None, t)
            return t
        if isinstance(n, FuncCall):
            a = self.operand(n.arg, 'float')
            self.emit('param', a)
            t = self.newtemp('float')
            self.emit('call', n.func_name, 1, t)
            return t
        raise TypeError(n)

    # ---------- boolean expressions: jumping code with backpatching ----------
    def cond(self, n):
        if isinstance(n, BinOp) and n.op.type == 'OR':
            t1, f1 = self.cond(n.left)
            self.backpatch(f1, self.nextquad)
            t2, f2 = self.cond(n.right)
            return t1 + t2, f2
        if isinstance(n, BinOp) and n.op.type == 'AND':
            t1, f1 = self.cond(n.left)
            self.backpatch(t1, self.nextquad)
            t2, f2 = self.cond(n.right)
            return t2, f1 + f2
        if isinstance(n, UnaryOp) and n.op.type == 'NOT':
            t, f = self.cond(n.expr)
            return f, t
        if isinstance(n, BinOp) and TOKEN_OP[n.op.type] in RELOPS:
            want = 'float' if 'float' in (n.left.ty, n.right.ty) else n.left.ty
            a = self.operand(n.left, want)
            b = self.operand(n.right, want)
            i = self.emit('if' + TOKEN_OP[n.op.type], a, b)
            j = self.emit('goto')
            return [i], [j]
        if isinstance(n, Bool):
            j = self.emit('goto')
            return ([j], []) if n.value else ([], [j])
        a = self.rvalue(n)                              # a bool variable
        i = self.emit('if', a)
        j = self.emit('goto')
        return [i], [j]


# ---------------- printing the different representations ----------------
def format_tac(quads):
    return '\n'.join(f"{i:>4}: {q}" for i, q in enumerate(quads))


def format_quadruples(quads):
    rows = [f"{'#':>4}  {'op':<10} {'arg1':<10} {'arg2':<10} {'result':<10}", '-' * 50]
    for i, q in enumerate(quads):
        cells = [q.op, '' if q.arg1 is None else fmt(q.arg1), '' if q.arg2 is None else fmt(q.arg2),
                 '' if q.result is None else str(q.result)]
        rows.append(f"{i:>4}  {cells[0]:<10} {cells[1]:<10} {cells[2]:<10} {cells[3]:<10}")
    return '\n'.join(rows)


def to_triples(quads, temps):
    """
    Triples drop the result field: a temporary is referred to by the number of
    the triple that computes it, written (k). A temporary assigned more than once
    (boolean values: t = true ... t = false) keeps its name, like a variable.
    """
    defs = {}
    for i, q in enumerate(quads):
        d = q.defines()
        if d in temps:
            defs.setdefault(d, []).append(i)
    single = {t: idx[0] for t, idx in defs.items() if len(idx) == 1}

    def ref(a):
        if isinstance(a, str) and a in single:
            return f"({single[a]})"
        return '' if a is None else fmt(a)

    triples = []
    for i, q in enumerate(quads):
        if q.op == '=':
            triples.append(('=', q.result, ref(q.arg1), None))
        elif q.op == 'call':
            triples.append(('call', q.arg1, str(q.arg2), None))
        elif q.is_jump():
            triples.append((q.op, ref(q.arg1), ref(q.arg2), f"({q.result})"))
        else:
            triples.append((q.op, ref(q.arg1), ref(q.arg2), None))
    return triples


def format_triples(quads, temps):
    rows = [f"{'#':>5}  {'op':<10} {'arg1':<10} {'arg2':<10} {'jump to'}", '-' * 48]
    for i, (op, a, b, tgt) in enumerate(to_triples(quads, temps)):
        rows.append(f"{'(' + str(i) + ')':>5}  {op:<10} {a or '':<10} {b or '':<10} {tgt or ''}")
    return '\n'.join(rows)


def format_indirect_triples(quads, base=100):
    """Indirect triples: a separate list of pointers to triples gives the execution
    order, so an optimizer can reorder statements without renumbering triples."""
    rows = [f"{'statement':>9}  points to triple", '-' * 28]
    for i in range(len(quads)):
        rows.append(f"{base + i:>9}  ({i})")
    return '\n'.join(rows)


def generate(program, symtab):
    g = IntermediateCodeGenerator(symtab)
    g.generate(program)
    return g
