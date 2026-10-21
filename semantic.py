"""
semantic.py - Module 3: Syntax-Directed Translation, type checking and the symbol table.

What happens here
-----------------
* A SYMBOL TABLE organised as a hash table with separate chaining. The hash
  function is `hashpjw` from the Dragon book (P. J. Weinberger's hash), the
  table has 211 buckets (a prime, as the book recommends).
* Every expression node gets a SYNTHESIZED attribute `ty` (int / float / bool),
  computed bottom-up by a post-order walk - the evaluation order of an
  S-attributed SDD. The rules are written next to each case below.
* An INHERITED attribute is used for assignments: the declared type of the
  target variable flows down to the right-hand side to decide whether an
  int -> float coercion must be inserted.
* Variables are declared implicitly by their first assignment, which fixes
  their type. Using a variable before any assignment is an error.
* Static storage allocation: each variable gets an offset in the static data
  area (int 4 bytes, float 8, bool 1, aligned to its own width).

Semantic rules (SDD) used:
  E -> E1 + E2 | E1 - E2 | E1 * E2 | E1 / E2
        E.ty = float if either operand is float else int   (operands must be numeric)
  E -> E1 % E2        E.ty = int                            (operands must be int)
  E -> E1 ^ E2        E.ty = int if both int else float
  E -> E1 relop E2    E.ty = bool  (both numeric, or both bool for == / !=)
  E -> E1 && E2 | E1 || E2   E.ty = bool   (operands must be bool)
  E -> ! E1           E.ty = bool  (E1 must be bool)
  E -> - E1           E.ty = E1.ty (must be numeric)
  E -> f(E1)          E.ty = float (E1 numeric; f in sin, cos, log, sqrt)
  S -> id = E         id.ty = E.ty on first assignment; afterwards E.ty must
                      equal id.ty, or be int when id.ty is float (coerced)
  S -> if (E) ... | while (E) ...    E.ty must be bool
"""
from dataclasses import dataclass, field
from typing import List, Optional
from ast_nodes import (Num, Bool, Var, BinOp, UnaryOp, FuncCall, Assign, Print, Block, If, While, node_pos)
from ops import TOKEN_OP

TYPE_WIDTH = {'int': 4, 'float': 8, 'bool': 1}
NUMERIC = ('int', 'float')
BUILTIN_FUNCS = ('sin', 'cos', 'log', 'sqrt')


def hashpjw(s: str, size: int) -> int:
    """P. J. Weinberger's hash function (Aho, Sethi, Ullman - Compilers, Fig. 7.35)."""
    h = 0
    for ch in s:
        h = ((h << 4) + ord(ch)) & 0xFFFFFFFF
        g = h & 0xF0000000
        if g:
            h ^= g >> 24
            h ^= g
    return h % size


@dataclass
class Symbol:
    name: str
    kind: str                    # 'variable' or 'function'
    type: str                    # 'int' | 'float' | 'bool' | 'float -> float'
    line: int = 0                # where it was declared (first assigned)
    offset: Optional[int] = None # static-area offset (variables only)
    width: int = 0
    refs: List[int] = field(default_factory=list)   # lines where it is used


class SymbolTable:
    """Hash table with separate chaining (each bucket is a linked list of Symbols)."""
    SIZE = 211

    def __init__(self):
        self.buckets: List[List[Symbol]] = [[] for _ in range(self.SIZE)]
        self.order: List[Symbol] = []     # insertion order, for printing
        self.static_size = 0              # bytes used in the static data area
        for f in BUILTIN_FUNCS:
            self.insert(Symbol(f, 'function', 'float -> float'))

    def lookup(self, name: str) -> Optional[Symbol]:
        for sym in self.buckets[hashpjw(name, self.SIZE)]:
            if sym.name == name:
                return sym
        return None

    def insert(self, sym: Symbol) -> Symbol:
        if sym.kind == 'variable':
            sym.width = TYPE_WIDTH[sym.type]
            # align the offset to the width of the type
            sym.offset = (self.static_size + sym.width - 1) // sym.width * sym.width
            self.static_size = sym.offset + sym.width
        self.buckets[hashpjw(sym.name, self.SIZE)].insert(0, sym)   # insert at chain head
        self.order.append(sym)
        return sym

    def variables(self) -> List[Symbol]:
        return [s for s in self.order if s.kind == 'variable']

    def type_of(self, name: str) -> Optional[str]:
        s = self.lookup(name)
        return s.type if s else None

    def format(self) -> str:
        out = [f"{'Name':<10} {'Kind':<9} {'Type':<15} {'Bucket':>6} {'Offset':>6} {'Width':>5}  {'Declared':>8}  Used at lines"]
        out.append('-' * 85)
        for s in self.order:
            off = '' if s.offset is None else str(s.offset)
            wid = '' if s.kind != 'variable' else str(s.width)
            decl = '' if s.kind != 'variable' else str(s.line)
            refs = ', '.join(str(r) for r in sorted(set(s.refs)))
            out.append(f"{s.name:<10} {s.kind:<9} {s.type:<15} {hashpjw(s.name, self.SIZE):>6} {off:>6} {wid:>5}  {decl:>8}  {refs}")
        chains = [(i, b) for i, b in enumerate(self.buckets) if len(b) > 1]
        if chains:
            out.append("Collision chains: " + "; ".join(
                f"bucket {i}: " + " -> ".join(s.name for s in b) for i, b in chains))
        out.append(f"Static data area size: {self.static_size} bytes")
        return '\n'.join(out)


@dataclass
class SemanticError:
    line: int
    col: int
    message: str

    def __str__(self):
        return f"Semantic error at line {self.line}, col {self.col}: {self.message}"


class SemanticAnalyzer:
    def __init__(self):
        self.symtab = SymbolTable()
        self.errors: List[SemanticError] = []
        self.trace: List[str] = []      # attribute evaluation order (for viva / --verbose)

    def error(self, node, msg):
        line, col = node_pos(node)
        self.errors.append(SemanticError(line, col, msg))

    def analyze(self, program):
        for stmt in program:
            self.stmt(stmt)
        return self.symtab, self.errors

    # ---------------- statements ----------------
    def stmt(self, s):
        if isinstance(s, Assign):
            ety = self.expr(s.expr)
            sym = self.symtab.lookup(s.var_name)
            if sym is None:
                if ety != 'error':
                    self.symtab.insert(Symbol(s.var_name, 'variable', ety, s.line))
                    self.trace.append(f"line {s.line}: declare {s.var_name} : {ety} "
                                      f"(offset {self.symtab.lookup(s.var_name).offset})")
            else:
                if ety == 'error':
                    return
                if sym.type == ety:
                    pass
                elif sym.type == 'float' and ety == 'int':
                    self.trace.append(f"line {s.line}: {s.var_name}.ty = float is inherited by the RHS -> coerce int to float")
                else:
                    self.error(s, f"cannot assign a value of type {ety} to '{s.var_name}' of type {sym.type}"
                                  + (" (possible loss of precision)" if (sym.type, ety) == ('int', 'float') else ""))
        elif isinstance(s, Print):
            self.expr(s.expr)
        elif isinstance(s, Block):
            for x in s.stmts:
                self.stmt(x)
        elif isinstance(s, If):
            self.condition(s.cond, 'if')
            for x in s.then_body:
                self.stmt(x)
            for x in (s.else_body or []):
                self.stmt(x)
        elif isinstance(s, While):
            self.condition(s.cond, 'while')
            for x in s.body:
                self.stmt(x)
        else:                                   # expression statement
            self.expr(s)

    def condition(self, cond, what):
        ty = self.expr(cond)
        if ty not in ('bool', 'error'):
            self.error(cond, f"{what} condition must be bool, got {ty} (did you mean '!= 0'?)")

    # ---------------- expressions: synthesize .ty ----------------
    def expr(self, n) -> str:
        ty = self._expr(n)
        n.ty = ty
        return ty

    def _expr(self, n) -> str:
        if isinstance(n, Num):
            return 'int' if isinstance(n.value, int) else 'float'
        if isinstance(n, Bool):
            return 'bool'
        if isinstance(n, Var):
            sym = self.symtab.lookup(n.name)
            if sym is None:
                self.error(n, f"variable '{n.name}' is used before it is assigned a value")
                return 'error'
            sym.refs.append(n.line)
            return sym.type
        if isinstance(n, FuncCall):
            aty = self.expr(n.arg)
            sym = self.symtab.lookup(n.func_name)
            if sym:
                sym.refs.append(n.line)
            if aty not in NUMERIC + ('error',):
                self.error(n, f"{n.func_name}() needs a numeric argument, got {aty}")
            self.trace.append(f"{n.func_name}(E).ty = float")
            return 'float'
        if isinstance(n, UnaryOp):
            ety = self.expr(n.expr)
            if ety == 'error':
                return 'error'
            if n.op.type == 'MINUS':
                if ety not in NUMERIC:
                    self.error(n, f"unary '-' needs a number, got {ety}")
                    return 'error'
                self.trace.append(f"(-E).ty = E.ty = {ety}")
                return ety
            if ety != 'bool':
                self.error(n, f"'!' needs a bool, got {ety}")
                return 'error'
            self.trace.append("(!E).ty = bool")
            return 'bool'
        if isinstance(n, BinOp):
            lt, rt = self.expr(n.left), self.expr(n.right)
            if 'error' in (lt, rt):
                return 'error'
            op = TOKEN_OP[n.op.type]
            res = self._binop_type(n, op, lt, rt)
            if res != 'error':
                self.trace.append(f"(E1 {op} E2).ty = {res}   [E1.ty = {lt}, E2.ty = {rt}]")
            return res
        raise TypeError(f"unknown node {n!r}")

    def _binop_type(self, n, op, lt, rt):
        if op in ('&&', '||'):
            if lt == rt == 'bool':
                return 'bool'
            self.error(n, f"'{op}' needs bool operands, got {lt} and {rt}")
            return 'error'
        if op in ('==', '!='):
            if (lt in NUMERIC and rt in NUMERIC) or lt == rt == 'bool':
                return 'bool'
            self.error(n, f"cannot compare {lt} with {rt}")
            return 'error'
        if lt not in NUMERIC or rt not in NUMERIC:
            self.error(n, f"'{op}' needs numeric operands, got {lt} and {rt}")
            return 'error'
        if op in ('<', '<=', '>', '>='):
            return 'bool'
        if op == '%':
            if lt == rt == 'int':
                return 'int'
            self.error(n, f"'%' needs int operands, got {lt} and {rt}")
            return 'error'
        return 'float' if 'float' in (lt, rt) else 'int'


def analyze(program):
    """Convenience wrapper: returns (symtab, errors, analyzer)."""
    a = SemanticAnalyzer()
    symtab, errors = a.analyze(program)
    return symtab, errors, a
