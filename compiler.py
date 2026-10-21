"""
compiler.py - Runs all six phases and keeps every intermediate result.

    source --lexer--> tokens --parser--> AST --semantic--> annotated AST + symbol table
           --ICG--> quadruples --> flow graph --optimizer--> optimized flow graph
           --code generator--> target code --peephole--> final target code

`verify()` executes the program at every level (AST, TAC, SSA, optimized TAC,
target code before and after peephole) and checks they all agree.
"""
from dataclasses import dataclass, field
from typing import Any, List, Optional
from lexer import Lexer, LexError
from parser_recursive_descent import ParserRecursiveDescent, SyntaxErrorExt
from parser_bottom_up import ParserBottomUp
from semantic import analyze
from icg import generate as generate_icg
from cfg import build_flow_graph
from ssa import SSAForm, run_ssa
from optimizer import optimize
from codegen import generate_code
from peephole import peephole
from target import run_machine
from interpreter import run_ast, run_quads, run_cfg, initial_env
from ops import EvalError


class CompileError(Exception):
    def __init__(self, phase, message, detail=None):
        super().__init__(message)
        self.phase = phase
        self.message = message
        self.detail = detail          # SyntaxErrorExt / list of SemanticError


@dataclass
class Compilation:
    source: str
    tokens: list = None
    ast: list = None
    symtab: Any = None
    analyzer: Any = None
    icg: Any = None
    cfg: Any = None
    ssa: Any = None
    optimizer: Any = None
    opt_cfg: Any = None
    codegen: Any = None
    code: list = None
    final_code: list = None
    peephole_stats: Any = None

    @property
    def user_vars(self):
        return [v.name for v in self.symtab.variables()]


def compile_source(source, parser='ll', nregs=4, opt=True, upto='codegen', slr_trace=False):
    c = Compilation(source)
    lexer = Lexer(source)
    try:
        c.tokens = lexer.tokenize()
    except LexError as e:
        raise CompileError('lexical', f"Lexical error at line {e.line}, column {e.column}: {e.message}", e)
    try:
        if parser == 'slr':
            c.ast = ParserBottomUp(lexer).parse(trace=slr_trace)
        else:
            c.ast = ParserRecursiveDescent(lexer).parse()
    except SyntaxErrorExt as e:
        raise CompileError('syntax', e.error_info.message, e)
    if upto == 'parse':
        return c
    c.symtab, errors, c.analyzer = analyze(c.ast)
    if errors:
        raise CompileError('semantic', '\n'.join(str(e) for e in errors), errors)
    if upto == 'semantic':
        return c
    c.icg = generate_icg(c.ast, c.symtab)
    c.cfg = build_flow_graph(c.icg.quads)
    c.ssa = SSAForm(c.cfg, c.user_vars)
    if upto == 'icg':
        return c
    if opt:
        c.optimizer = optimize(c.cfg, c.icg, c.symtab)
        c.opt_cfg = c.optimizer.cfg
    else:
        c.opt_cfg = c.cfg.copy()
    if upto == 'opt':
        return c
    c.codegen = generate_code(c.opt_cfg.copy(), c.user_vars, c.icg.temps, nregs)
    c.code = c.codegen.code
    c.final_code, c.peephole_stats = peephole(c.code)
    return c


@dataclass
class Verification:
    ok: bool
    results: List[tuple] = field(default_factory=list)   # (stage, output, finals or error)
    machine_stats: Optional[dict] = None


def verify(c: Compilation):
    """Run every representation that exists and compare outputs + final variable values."""
    stages = [('source (AST interpreter)', lambda: run_ast(c.ast, c.symtab))]
    if c.icg:
        stages.append(('three-address code', lambda: run_quads(c.icg.quads, c.symtab)))
        stages.append(('SSA form', lambda: run_ssa(c.ssa, c.symtab)))
    if c.opt_cfg:
        stages.append(('optimized TAC', lambda: run_cfg(c.opt_cfg, c.symtab)))
    stats = {}
    if c.code:
        def m(code):
            out, fin, st = run_machine(code, initial_env(c.symtab))
            stats.update(st)
            return out, fin
        stages.append(('target code', lambda: m(c.code)))
        stages.append(('target code after peephole', lambda: m(c.final_code)))
    results = []
    for name, fn in stages:
        try:
            out, fin = fn()
            results.append((name, out, fin))
        except EvalError as e:
            results.append((name, None, f"run-time error: {e}"))
    ref = results[0]

    def same(r):
        if r[1] is None or ref[1] is None:
            return r[1] is None and ref[1] is None
        return r[1] == ref[1] and all(type(r[2][k]) is type(v) and r[2][k] == v for k, v in ref[2].items())
    return Verification(all(same(r) for r in results), results, stats or None)
