"""
Run with:   python3 -m unittest discover tests      (from the project folder)
"""
import glob
import os
import random
import sys
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lexer import Lexer  # noqa: E402
from parser_recursive_descent import ParserRecursiveDescent, SyntaxErrorExt  # noqa: E402
from parser_bottom_up import ParserBottomUp, SLR_CONFLICTS  # noqa: E402
from grammar import LL1_CONFLICTS  # noqa: E402
from compiler import compile_source, verify, CompileError  # noqa: E402
from icg import format_tac  # noqa: E402
from target import format_code  # noqa: E402
import fuzz  # noqa: E402

EXAMPLES = sorted(glob.glob(os.path.join(ROOT, 'examples', '*.src')))
VALID = [p for p in EXAMPLES if 'error' not in os.path.basename(p)]


def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def parse_both(src):
    l1 = Lexer(src); l1.tokenize()
    l2 = Lexer(src); l2.tokenize()
    return ParserRecursiveDescent(l1).parse(), ParserBottomUp(l2).parse(trace=False)


class TestFrontEnd(unittest.TestCase):
    def test_lexer_keywords_and_operators(self):
        types = [t.type for t in Lexer("if iffy while print true <= == != && || ! { }").tokenize()]
        self.assertEqual(types, ['IF', 'IDENTIFIER', 'WHILE', 'PRINT', 'TRUE', 'LE', 'EQ', 'NE',
                                 'AND', 'OR', 'NOT', 'LBRACE', 'RBRACE', 'EOF'])

    def test_grammars_have_no_conflicts(self):
        self.assertEqual(LL1_CONFLICTS, [])
        self.assertEqual(SLR_CONFLICTS, [])

    def test_trailing_semicolon_accepted_by_both_parsers(self):
        # regression: the old SLR(1) parser rejected "x = 1;" with "Unexpected token EOF"
        a, b = parse_both("x = 5.5 + -3 * 2; y = x;")
        self.assertEqual(a, b)
        self.assertEqual(len(a), 2)

    def test_parsers_build_identical_trees(self):
        for path in EXAMPLES:
            if 'syntax' in path:
                continue
            a, b = parse_both(read(path))
            self.assertEqual(a, b, path)

    def test_syntax_errors_detected_by_both(self):
        for bad in ["x = 5.5 + * 3;", "y = (4 + 5 * 2;", "z = 10 ^ ;", "x = 1", "a < b < c;", "if (x) { y = 1;"]:
            for P in (ParserRecursiveDescent, ParserBottomUp):
                lx = Lexer(bad); lx.tokenize()
                with self.assertRaises(SyntaxErrorExt, msg=f"{P.__name__}: {bad}"):
                    P(lx).parse() if P is ParserRecursiveDescent else P(lx).parse(trace=False)

    def test_precedence_and_associativity(self):
        c = compile_source("x = 2 ^ 3 ^ 2; y = 1 - 2 - 3; z = -2 ^ 2; b = 1 < 2 || false && false;")
        v = verify(c)
        self.assertTrue(v.ok)
        self.assertEqual(v.results[0][2], {'x': 512, 'y': -4, 'z': -4, 'b': True})


class TestSemantic(unittest.TestCase):
    def test_semantic_errors_example(self):
        with self.assertRaises(CompileError) as cm:
            compile_source(read(os.path.join(ROOT, 'examples', '05_semantic_errors.src')))
        self.assertEqual(cm.exception.phase, 'semantic')
        self.assertEqual(len(cm.exception.detail), 5)

    def test_types_and_coercion(self):
        c = compile_source("x = 1.5; x = 2; i = 7 / 2; f = 7 / 2.0; m = -7 % 3;", upto='semantic')
        self.assertEqual(c.symtab.type_of('x'), 'float')
        self.assertEqual(c.symtab.type_of('i'), 'int')
        v = verify(compile_source("x = 1.5; x = 2; i = 7 / 2; f = 7 / 2.0; m = -7 % 3;"))
        self.assertEqual(v.results[0][2], {'x': 2.0, 'i': 3, 'f': 3.5, 'm': -1})

    def test_symbol_table_offsets_are_aligned(self):
        c = compile_source("a = true; b = 1.5; c = 2;", upto='semantic')
        offs = {s.name: s.offset for s in c.symtab.variables()}
        self.assertEqual(offs, {'a': 0, 'b': 8, 'c': 16})


class TestIntermediateCode(unittest.TestCase):
    def test_backpatching_of_or(self):
        c = compile_source("a = 1; b = 2; c = true; if (a < b || c) { x = 1; }", upto='icg')
        self.assertEqual(format_tac(c.icg.quads).splitlines(), [
            "   0: a = 1", "   1: b = 2", "   2: c = true",
            "   3: if a < b goto 7", "   4: goto 5",
            "   5: if c goto 7", "   6: goto 8",
            "   7: x = 1", "   8: halt"])

    def test_while_loop_jumps_back(self):
        c = compile_source("i = 0; while (i < 3) { i = i + 1; }", upto='icg')
        tac = format_tac(c.icg.quads)
        self.assertIn("1: if i < 3 goto 3", tac)
        self.assertIn("goto 1", tac)


class TestOptimizerAndCodegen(unittest.TestCase):
    def test_examples_agree_at_every_level(self):
        for path in VALID:
            for opt in (True, False):
                for regs in (2, 3, 4, 6):
                    v = verify(compile_source(read(path), nregs=regs, opt=opt))
                    self.assertTrue(v.ok, f"{path} opt={opt} regs={regs}: {v.results}")

    def test_optimizations_fire(self):
        c = compile_source(read(os.path.join(ROOT, 'examples', '03_optimizations.src')))
        s = c.optimizer.stats
        for kind in ('constant folding', 'common subexpression', 'dead code elimination',
                     'loop-invariant code motion', 'unreachable code elimination'):
            self.assertGreater(s[kind], 0, kind)
        self.assertLess(c.opt_cfg.instr_count(), c.cfg.instr_count())

    def test_peephole_uses_inc(self):
        c = compile_source("i = 0; while (i < 5) { i = i + 1; } print(i);")
        self.assertIn("INC", format_code(c.final_code))
        self.assertTrue(verify(c).ok)

    def test_random_programs(self):
        rng = random.Random(2026)
        for _ in range(120):
            src = fuzz.Gen(rng).program()
            self.assertIsNone(fuzz.check(src, regs=(2, 4)), src)


if __name__ == '__main__':
    unittest.main()
