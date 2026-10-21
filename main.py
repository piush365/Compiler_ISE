"""
main.py - Command-line driver for all six phases of the compiler.

    python3 main.py                         full pipeline on examples/03_optimizations.src
    python3 main.py prog.src                full pipeline on a file
    python3 main.py prog.src --upto icg     stop after a phase: lex | parse | semantic | icg | opt | codegen
    python3 main.py prog.src --parser slr   use the SLR(1) parser (prints the shift/reduce trace)
    python3 main.py prog.src --regs 2       number of machine registers (default 4, minimum 2)
    python3 main.py prog.src --no-opt       skip Module 5 (generate code from unoptimized TAC)
    python3 main.py prog.src --tables       also print FIRST/FOLLOW, the LL(1) table and the SLR(1) table
    python3 main.py --frontend-demo         the original Module 1-2 demo (both parsers + AI error explainer)
"""
import argparse
import os
import sys
import textwrap

from compiler import compile_source, verify, CompileError
from lexer import Lexer, LexError
from parser_recursive_descent import ParserRecursiveDescent, SyntaxErrorExt
from parser_bottom_up import ParserBottomUp
from ai_error_explainer import explain_syntax_error
from ast_nodes import format_tree
from icg import format_tac, format_quadruples, format_triples, format_indirect_triples
from cfg import leaders_report
from dag import format_dags
from target import format_code
from runtime import storage_report
import grammar

PHASES = ['lex', 'parse', 'semantic', 'icg', 'opt', 'codegen']
DEFAULT_PROGRAM = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'examples', '03_optimizations.src')


def banner(title):
    print(f"\n{'=' * 78}\n {title}\n{'=' * 78}")


def run_pipeline(source, parser='ll', regs=4, opt=True, upto='codegen', tables=False):
    print("Source program:")
    for n, line in enumerate(source.rstrip('\n').splitlines(), 1):
        print(f"  {n:>3} | {line}")

    # ---------------- Module 1: lexical analysis ----------------
    banner("MODULE 1  Lexical analysis")
    try:
        tokens = Lexer(source).tokenize()
    except LexError as e:
        print(f"Lexical error at line {e.line}, column {e.column}: {e.message}")
        return 1
    print(textwrap.fill(' '.join(f"{t.type}" + (f"({t.value})" if t.type in ('IDENTIFIER', 'INT', 'FLOAT', 'FUNC') else '')
                                 for t in tokens), 100, break_long_words=False))
    if upto == 'lex':
        return 0

    # ---------------- Module 2: syntax analysis ----------------
    banner(f"MODULE 2  Syntax analysis ({'SLR(1) bottom-up' if parser == 'slr' else 'LL(1) recursive descent'})")
    if tables:
        grammar.print_sets_table()
        print()
        grammar.print_ll1_table()
        print()
        lx = Lexer(source)
        lx.tokenize()
        ParserBottomUp(lx).print_parsing_table()
        print()
    try:
        c = compile_source(source, parser=parser, upto='parse', slr_trace=(parser == 'slr'))
    except CompileError as e:
        print("[Raw Parser Error]")
        print(e.message)
        if isinstance(e.detail, SyntaxErrorExt):
            print(e.detail.error_info.source_snippet)
            print("\n[AI Explanation]")
            print(explain_syntax_error(e.detail.error_info, source))
        return 1
    print("Abstract syntax tree:")
    print(format_tree(c.ast, 1))
    if upto == 'parse':
        return 0

    # ---------------- Module 3: SDT, types, symbol table, run-time ----------------
    banner("MODULE 3  Syntax-directed translation, type checking, symbol table")
    try:
        c = compile_source(source, parser=parser, nregs=regs, opt=opt)
    except CompileError as e:
        print(e.message)
        return 1
    print("Annotated syntax tree (synthesized attribute .ty):")
    print(format_tree(c.ast, 1, show_types=True))
    print("\nAttribute evaluation order (post-order = S-attributed evaluation):")
    for line in c.analyzer.trace:
        print(f"  {line}")
    print("\nSymbol table (hash table, hashpjw, 211 buckets, separate chaining):")
    print(c.symtab.format())
    if upto == 'semantic':
        return 0

    # ---------------- Module 4: intermediate code ----------------
    banner("MODULE 4  Intermediate code generation (backpatching)")
    print("Three-address code:")
    print(format_tac(c.icg.quads))
    print("\nQuadruples:")
    print(format_quadruples(c.icg.quads))
    print("\nTriples (a temporary is referenced by the number of the triple computing it):")
    print(format_triples(c.icg.quads, c.icg.temps))
    print("\nIndirect triples (execution order is a list of pointers):")
    print(format_indirect_triples(c.icg.quads))
    print("\nLeaders: " + leaders_report(c.icg.quads))
    print("\nFlow graph:")
    print(c.cfg.format())
    print("\nSSA form:")
    print(c.ssa.format())
    if upto == 'icg':
        return finish(c)

    # ---------------- Module 5: optimization ----------------
    if opt:
        banner("MODULE 5  Code optimization")
        o = c.optimizer
        for line in o.log:
            print(f"  {line}")
        print("\nLoops found:")
        for line in o.loops_report or ['  (none)']:
            print(f"  {line}")
        print("\nOptimized flow graph:")
        print(c.opt_cfg.format())
        print(f"\nSummary: {c.cfg.instr_count()} -> {c.opt_cfg.instr_count()} instructions, "
              f"{len(c.cfg.blocks)} -> {len(c.opt_cfg.blocks)} basic blocks")
        for kind, n in sorted(o.stats.items(), key=lambda x: -x[1]):
            print(f"  {n:>3} x {kind}")
    else:
        banner("MODULE 5  Code optimization (skipped: --no-opt)")
    if upto == 'opt':
        return finish(c)

    # ---------------- Module 6: code generation ----------------
    banner(f"MODULE 6  Code generation ({regs} registers)")
    print("DAG of each basic block:")
    print(format_dags(c.opt_cfg))
    print("\nTarget code (getReg with register and address descriptors):")
    print(format_code(c.code))
    print(f"\nPeephole optimization: {len(c.code)} -> {len(c.final_code)} lines")
    for kind, n in sorted(c.peephole_stats.items(), key=lambda x: -x[1]):
        print(f"  {n:>3} x {kind}")
    print("\nFinal target code:")
    print(format_code(c.final_code))
    print()
    print(storage_report(c.symtab, len([i for i in c.final_code if i.op != 'LABEL']), c.codegen.spilled))
    return finish(c)


def finish(c):
    banner("VERIFICATION  run the program at every level and compare")
    v = verify(c)
    for stage, out, fin in v.results:
        shown = ', '.join(out) if out is not None else fin
        print(f"  {stage:<28} output: [{shown}]")
    if v.results and v.results[0][1] is not None:
        print("  final variable values: " + ', '.join(f"{k}={val}" for k, val in v.results[0][2].items()))
    if v.machine_stats:
        print("  machine run: " + ', '.join(f"{k} {val}" for k, val in v.machine_stats.items()))
    print("  RESULT: " + ("all stages agree" if v.ok else "MISMATCH between stages"))
    return 0 if v.ok else 2


def frontend_demo():
    """The original Module 1-2 demonstration: both parsers + AI error explainer."""
    test_programs = [
        "x = 5.5 + -3 * sin(y);",
        "z = x ^ 2 ^ 3;",
        "result = (10 % 3) / log(x); y = -x;",
        "x = 5.5 + * 3;",            # Unexpected STAR
        "y = (4 + 5 * 2;",           # Missing RPAREN
        "z = 10 ^ ;",                # Missing expression after CARET
    ]
    print("=== Compiler Front-End Demonstration ===")
    for i, prog in enumerate(test_programs):
        print(f"\n{'=' * 50}\nTest {i + 1}:")
        for use_slr in (False, True):
            print(f"\n--- Compiling: {prog} ---")
            lexer = Lexer(prog)
            try:
                tokens = lexer.tokenize()
                print(f"Tokens: {[t.type for t in tokens]}")
                if use_slr:
                    print("\n[SLR(1) Bottom-Up Parser]")
                    ast = ParserBottomUp(lexer).parse(trace=True)
                else:
                    print("\n[LL(1) Recursive Descent Parser]")
                    ast = ParserRecursiveDescent(lexer).parse()
                print("AST:")
                print(format_tree(ast, 1))
            except LexError as e:
                print(f"Lexical Error: {e.message}")
            except SyntaxErrorExt as e:
                print("\n[Raw Parser Error]")
                print(e.error_info.message)
                print(e.error_info.source_snippet)
                print("\n[AI Explanation]")
                print(explain_syntax_error(e.error_info, prog))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Compiler for a small language: all six phases.")
    ap.add_argument('file', nargs='?', help='source file (default: examples/03_optimizations.src)')
    ap.add_argument('--parser', choices=['ll', 'slr'], default='ll')
    ap.add_argument('--regs', type=int, default=4, help='number of registers (>= 2)')
    ap.add_argument('--no-opt', action='store_true', help='skip the optimization phase')
    ap.add_argument('--upto', choices=PHASES, default='codegen', help='stop after this phase')
    ap.add_argument('--tables', action='store_true', help='print FIRST/FOLLOW, LL(1) and SLR(1) tables')
    ap.add_argument('--frontend-demo', action='store_true', help='run the original Module 1-2 demo')
    args = ap.parse_args(argv)
    if args.frontend_demo:
        frontend_demo()
        return 0
    if args.regs < 2:
        ap.error("--regs must be at least 2")
    path = args.file or DEFAULT_PROGRAM
    with open(path, encoding='utf-8') as f:
        source = f.read()
    return run_pipeline(source, args.parser, args.regs, not args.no_opt, args.upto, args.tables)


if __name__ == "__main__":
    sys.exit(main())
