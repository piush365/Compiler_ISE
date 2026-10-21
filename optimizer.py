"""
optimizer.py - Module 5: Machine-independent code optimization.

Works on the flow graph of basic blocks and repeats until nothing changes:

  Local (inside one basic block)
    * constant folding           t = 2 * 3            ->  t = 6
    * constant propagation       x = 6; y = x + 1     ->  y = 7
    * copy propagation           x = y; z = x + 1     ->  z = y + 1
    * algebraic simplification   x + 0, x * 1, x / 1, x ^ 1  ->  x
    * strength reduction         x * 2 -> x + x,  x ^ 2 -> x * x (ints)
    * common sub-expression elimination (local value numbering, i.e. the DAG
      of the block): a second a + b reuses the first result
    * copy coalescing            t = a + b; x = t     ->  x = a + b

  Global (whole flow graph, iterative data-flow analysis)
    * global constant propagation (reaching constants, meet over predecessors)
    * dead-code elimination using live-variable analysis
      (a variable's final value is observable, so user variables are live at exit)
    * unreachable-code elimination, jump-to-next removal, jump threading,
      jumps over jumps, and merging of straight-line blocks

  Loops
    * dominators -> back edges -> natural loops
    * loop-invariant code motion into a new pre-header block
    * basic induction variables (i = i +/- c) are detected and reported

Every transformation keeps the program's meaning; main.py and the tests check
that by running the code before and after optimization.
"""
from collections import Counter
from cfg import BasicBlock, FlowGraph, dominators, natural_loops, liveness
from icg import Quad, BINARY_OPS, UNARY_OPS
from ops import binop, unop, EvalError, NEGATED_RELOP, COMMUTATIVE, is_int

PURE_OPS = ('=',) + BINARY_OPS + UNARY_OPS
MAY_FAULT = ('/', '%', '^')          # may raise at run time -> not moved speculatively (unless the divisor is a non-zero constant)


def is_const(a):
    return not isinstance(a, str) and a is not None


def ckey(a):
    """Typed key, so that 1, 1.0 and True are never confused."""
    return ('c', type(a).__name__, a) if is_const(a) else a


def same_const(a, b):
    return type(a) is type(b) and a == b


def fold(op, a, b=None):
    """Evaluate op on constants. Returns (True, value) or (False, None) if it would fault."""
    try:
        if op in BINARY_OPS:
            return True, binop(op, a, b)
        if op in UNARY_OPS:
            return True, unop(op, a)
        if op.startswith('if') and op not in ('if', 'iffalse'):
            return True, binop(op[2:], a, b)
        if op == 'if':
            return True, bool(a)
        if op == 'iffalse':
            return True, not a
    except EvalError:
        pass
    return False, None


class Optimizer:
    def __init__(self, cfg: FlowGraph, types, temps, user_vars):
        self.cfg = cfg.copy()
        self.types = dict(types)
        self.temps = set(temps)
        self.user_vars = set(user_vars)
        self.stats = Counter()
        self.log = []
        self.loops_report = []
        self.npre = 0

    def note(self, kind, msg=None):
        self.stats[kind] += 1
        if msg and len(self.log) < 400:
            self.log.append(f"[{kind}] {msg}")

    def type_of(self, a):
        if is_const(a):
            return 'bool' if isinstance(a, bool) else ('int' if is_int(a) else 'float')
        return self.types.get(a)

    # ------------------------------------------------------------------
    def run(self, loops=True):
        self._fixpoint()
        if loops:
            self.loop_optimizations()
            self._fixpoint()
        return self.cfg

    def _fixpoint(self):
        for _ in range(50):
            changed = False
            changed |= self.constant_and_local_pass()
            changed |= self.coalesce_copies()
            changed |= self.dead_code_elimination()
            changed |= self.cleanup_control_flow()
            if not changed:
                break

    # ------------------------------------------------------------------
    # Global constant propagation (forward data flow) + local optimizations
    # ------------------------------------------------------------------
    def _transfer_consts(self, block, state):
        """Apply a block to a {name: const} map. NAC (not a constant) = name missing."""
        state = dict(state)
        for q in block.instrs:
            d = q.defines()
            if not d:
                continue
            val = lambda a: a if is_const(a) else state.get(a)
            if q.op == '=' and val(q.arg1) is not None:
                state[d] = val(q.arg1)
                continue
            if q.op in BINARY_OPS + UNARY_OPS:
                a, b = val(q.arg1), (val(q.arg2) if q.op in BINARY_OPS else 0)
                if a is not None and b is not None:
                    ok, v = fold(q.op, a, b if q.op in BINARY_OPS else None)
                    if ok:
                        state[d] = v
                        continue
            state.pop(d, None)
        return state

    def global_constants(self):
        """
        Reaching-constants analysis (optimistic, iterative):
          in[B]  = meet of out[P] over predecessors P   (x is kept only if every P agrees)
          out[B] = transfer(B, in[B])
        Unvisited predecessors (TOP) are ignored until they have been processed.
        """
        reach = self.cfg.reachable()
        blocks = [b for b in self.cfg.blocks if b.name in reach]
        out = {b.name: None for b in blocks}             # None = TOP
        inn = {}

        def typed(d):
            return {k: (type(v), v) for k, v in d.items()}

        changed = True
        while changed:
            changed = False
            for b in blocks:
                if b is self.cfg.entry:
                    state = {}                           # nothing is known at program start
                else:
                    preds = [out[p] for p in b.pred if p in reach and out[p] is not None]
                    if not preds:
                        continue
                    state = {k: v for k, v in preds[0].items()
                             if all(k in p and same_const(p[k], v) for p in preds[1:])}
                inn[b.name] = state
                new_out = self._transfer_consts(b, state)
                if out[b.name] is None or typed(new_out) != typed(out[b.name]):
                    out[b.name] = new_out
                    changed = True
        return inn

    def constant_and_local_pass(self):
        changed = False
        inn = self.global_constants()
        for b in self.cfg.blocks:
            if b.name in inn:
                changed |= self.local_block(b, inn[b.name])
        if changed:
            self.cfg.compute_edges()
        return changed

    def local_block(self, block, consts_in):
        consts = dict(consts_in)      # name -> constant
        copies = {}                   # name -> name it is a copy of
        avail = {}                    # expression key -> name holding its value
        new_instrs = []
        changed = False

        def subst(a):
            if not isinstance(a, str):
                return a
            if a in consts:
                return consts[a]
            return copies.get(a, a)

        def kill(x):
            consts.pop(x, None)
            copies.pop(x, None)
            for y in [y for y, s in copies.items() if s == x]:
                del copies[y]
            for k in [k for k, h in avail.items() if h == x or x in k[1:]]:
                del avail[k]

        for q in block.instrs:
            q = Quad(q.op, q.arg1, q.arg2, q.result)
            orig = str(q)
            # 1. constant / copy propagation into the operands
            if q.op not in ('call', 'goto', 'halt'):
                a1, a2 = subst(q.arg1), subst(q.arg2)
                if (a1, a2) != (q.arg1, q.arg2):
                    kind = 'constant propagation' if (is_const(a1) and not is_const(q.arg1)) or \
                                                     (is_const(a2) and not is_const(q.arg2)) else 'copy propagation'
                    q.arg1, q.arg2 = a1, a2
                    self.note(kind, f"{block.name}: {orig}  =>  {q}")
                    changed = True

            # 2. constant folding (including conditional jumps)
            if q.is_cond_jump() and is_const(q.arg1) and (q.op in ('if', 'iffalse') or is_const(q.arg2)):
                ok, taken = fold(q.op, q.arg1, q.arg2)
                if ok:
                    changed = True
                    if taken:
                        self.note('constant folding', f"{block.name}: {q}  =>  goto {q.result}")
                        new_instrs.append(Quad('goto', result=q.result))
                    else:
                        self.note('constant folding', f"{block.name}: {q}  =>  (removed, never taken)")
                    continue
            if q.op in BINARY_OPS and is_const(q.arg1) and is_const(q.arg2) or \
                    q.op in UNARY_OPS and is_const(q.arg1):
                ok, v = fold(q.op, q.arg1, q.arg2)
                if ok:
                    before = str(q)
                    q = Quad('=', v, None, q.result)
                    self.note('constant folding', f"{block.name}: {before}  =>  {q}")
                    changed = True

            # 3. algebraic simplification and strength reduction
            if q.op in BINARY_OPS:
                simp = self.simplify(q)
                if simp is not None:
                    self.note(simp[0], f"{block.name}: {q}  =>  {simp[1]}")
                    q = simp[1]
                    changed = True

            # 4. local common sub-expression elimination (value numbering)
            if q.op in BINARY_OPS + UNARY_OPS:
                k1, k2 = ckey(q.arg1), ckey(q.arg2)
                if q.op in COMMUTATIVE and repr(k2) < repr(k1):
                    k1, k2 = k2, k1
                key = (q.op, k1, k2)
                if key in avail and avail[key] != q.result:
                    before = str(q)
                    q = Quad('=', avail[key], None, q.result)
                    self.note('common subexpression', f"{block.name}: {before}  =>  {q}")
                    changed = True
                d = q.result
                kill(d)
                if q.op != '=' and d not in (q.arg1, q.arg2):
                    avail[key] = d
            else:
                d = q.defines()
                if d:
                    kill(d)
            if q.op == '=':
                if is_const(q.arg1):
                    consts[q.result] = q.arg1
                elif q.arg1 != q.result:
                    copies[q.result] = q.arg1
                else:
                    self.note('self-assignment removed', f"{block.name}: {q}")
                    changed = True
                    continue
            new_instrs.append(q)
            if q.op == 'goto':
                break                                  # anything after an unconditional jump is dead
        if new_instrs != block.instrs:
            block.instrs = new_instrs
        return changed

    def simplify(self, q):
        op, a, b, r = q.op, q.arg1, q.arg2, q.result
        ta = self.type_of(a)
        ints = self.type_of(r) == 'int'

        def isc(x, v):
            return is_const(x) and not isinstance(x, bool) and x == v

        copy = lambda x: ('algebraic simplification', Quad('=', x, None, r))
        if op == '+' and ints:
            if isc(b, 0): return copy(a)
            if isc(a, 0): return copy(b)
        if op == '-' and isc(b, 0): return copy(a)
        if op == '-' and ints and a == b and isinstance(a, str): return copy(0)
        if op == '*':
            if isc(b, 1) and self.type_of(b) == ta: return copy(a)
            if isc(a, 1) and self.type_of(a) == self.type_of(b): return copy(b)
            if ints and (isc(a, 0) or isc(b, 0)): return copy(0)
            if isc(b, 2) and isinstance(a, str) and self.type_of(b) == ta:
                return ('strength reduction', Quad('+', a, a, r))
            if isc(a, 2) and isinstance(b, str) and self.type_of(a) == self.type_of(b):
                return ('strength reduction', Quad('+', b, b, r))
        if op == '/' and isc(b, 1) and self.type_of(b) == ta: return copy(a)
        if op == '^' and ints:
            if isc(b, 1): return copy(a)
            if isc(b, 0): return copy(1)
            if isc(b, 2) and isinstance(a, str): return ('strength reduction', Quad('*', a, a, r))
        return None

    # ------------------------------------------------------------------
    def coalesce_copies(self):
        """t = a op b ; x = t   ==>   x = a op b   (t a temporary with exactly one def and one use)."""
        defs, uses = Counter(), Counter()
        for b in self.cfg.blocks:
            for q in b.instrs:
                if q.defines():
                    defs[q.defines()] += 1
                for u in q.uses():
                    uses[u] += 1
        changed = False
        for b in self.cfg.blocks:
            out = []
            for q in b.instrs:
                if out and q.op == '=' and q.arg1 in self.temps and defs[q.arg1] == 1 and uses[q.arg1] == 1 \
                        and out[-1].defines() == q.arg1 \
                        and self.types.get(q.arg1) == self.types.get(q.result):
                    prev = out.pop()
                    merged = Quad(prev.op, prev.arg1, prev.arg2, q.result)
                    self.note('copy coalescing', f"{b.name}: {prev} ; {q}  =>  {merged}")
                    out.append(merged)
                    changed = True
                else:
                    out.append(q)
            b.instrs = out
        return changed

    # ------------------------------------------------------------------
    # Live-variable analysis and dead-code elimination
    # ------------------------------------------------------------------
    def instr_uses(self, q):
        if q.op == 'halt':
            return set(self.user_vars)              # final values are observable
        return set(q.uses())

    def liveness(self):
        return liveness(self.cfg, self.user_vars)

    def dead_code_elimination(self):
        _, live_out = self.liveness()
        changed = False
        for b in self.cfg.blocks:
            live = set(live_out[b.name])
            kept = []
            skip_param = False
            for q in reversed(b.instrs):
                if skip_param and q.op == 'param':
                    skip_param = False
                    continue
                d = q.defines()
                if d and d not in live and (q.op in PURE_OPS or q.op == 'call'):
                    self.note('dead code elimination', f"{b.name}: {q}  ({d} is never used)")
                    changed = True
                    skip_param = q.op == 'call'
                    continue
                if d:
                    live.discard(d)
                live |= self.instr_uses(q)
                kept.append(q)
            b.instrs = kept[::-1]
        return changed

    # ------------------------------------------------------------------
    # Control-flow clean-up
    # ------------------------------------------------------------------
    def cleanup_control_flow(self):
        changed = False
        cfg = self.cfg
        # unreachable blocks
        reach = cfg.reachable()
        dead = [b.name for b in cfg.blocks if b.name not in reach]
        if dead:
            cfg.blocks = [b for b in cfg.blocks if b.name in reach]
            self.note('unreachable code elimination', f"removed block(s) {', '.join(dead)}")
            changed = True
            cfg.compute_edges()

        # jump threading: a jump to a block that only contains 'goto Y' goes straight to Y
        names = cfg.by_name()
        for b in cfg.blocks:
            last = b.last()
            if last is not None and last.is_jump():
                seen = set()
                tgt = last.result
                while (len(names[tgt].instrs) == 1 and names[tgt].instrs[0].op == 'goto'
                       and names[tgt].instrs[0].result not in seen | {tgt}):
                    seen.add(tgt)
                    tgt = names[tgt].instrs[0].result
                if tgt != last.result:
                    self.note('jump threading', f"{b.name}: {last}  =>  jump to {tgt}")
                    last.result = tgt
                    changed = True

        # jump to the very next block in the layout is useless
        for i, b in enumerate(cfg.blocks[:-1]):
            last = b.last()
            nxt = cfg.blocks[i + 1].name
            if last is not None and last.is_jump() and last.result == nxt:
                self.note('jump to next removed', f"{b.name}: {last}")
                b.instrs.pop()
                changed = True

        # jumps over jumps:  if c goto L1 ; goto L2 ; L1:   ==>   if !c goto L2 ; L1:
        cfg.compute_edges()
        names = cfg.by_name()
        for i, b in enumerate(cfg.blocks[:-2]):
            last, n, after = b.last(), cfg.blocks[i + 1], cfg.blocks[i + 2]
            if (last is not None and last.is_cond_jump() and last.result == after.name
                    and len(n.instrs) == 1 and n.instrs[0].op == 'goto' and n.pred == [b.name]):
                inv = self.negate(last)
                if inv is not None:
                    inv.result = n.instrs[0].result
                    self.note('jumps over jumps', f"{b.name}: {last} ; goto {n.instrs[0].result}  =>  {inv}")
                    b.instrs[-1] = inv
                    n.instrs = []
                    changed = True
                    cfg.compute_edges()

        # remove empty blocks (jumps to them go to the following block instead)
        while True:
            empties = [i for i, b in enumerate(cfg.blocks) if not b.instrs and i + 1 < len(cfg.blocks)]
            if not empties:
                break
            i = empties[0]
            e, nxt = cfg.blocks[i], cfg.blocks[i + 1].name
            for b in cfg.blocks:
                if b.last() is not None and b.last().is_jump() and b.last().result == e.name:
                    b.last().result = nxt
            del cfg.blocks[i]
            changed = True
        cfg.compute_edges()

        # merge B with its layout successor S when B -> S is the only edge out of B and into S
        i = 0
        while i < len(cfg.blocks) - 1:
            b, s = cfg.blocks[i], cfg.blocks[i + 1]
            last = b.last()
            if b.succ == [s.name] and s.pred == [b.name] and not (last is not None and last.is_cond_jump()):
                if last is not None and last.op == 'goto':
                    b.instrs.pop()
                b.instrs.extend(s.instrs)
                self.note('block merging', f"{s.name} merged into {b.name}")
                del cfg.blocks[i + 1]
                cfg.compute_edges()
                changed = True
                continue
            i += 1
        return changed

    def negate(self, q):
        if q.op == 'if':
            return Quad('iffalse', q.arg1)
        if q.op == 'iffalse':
            return Quad('if', q.arg1)
        # !(a < b) == (a >= b) only without NaN, i.e. for int / bool operands
        if all(self.type_of(x) in ('int', 'bool') for x in (q.arg1, q.arg2)):
            return Quad('if' + NEGATED_RELOP[q.op[2:]], q.arg1, q.arg2)
        return None

    # ------------------------------------------------------------------
    # Loop optimizations
    # ------------------------------------------------------------------
    def loop_optimizations(self):
        for _ in range(10):                      # re-detect after each successful motion
            cfg = self.cfg
            cfg.compute_edges()
            dom = dominators(cfg)
            moved = False
            for header, body, back_edges in natural_loops(cfg, dom):
                if self.hoist(header, body, dom):
                    moved = True
                    break
            if not moved:
                break
        cfg = self.cfg
        cfg.compute_edges()
        dom = dominators(cfg)
        self.loops_report = []
        for header, body, back_edges in natural_loops(cfg, dom):
            order = [b.name for b in cfg.blocks if b.name in body]
            ivs = self.induction_variables(body)
            self.loops_report.append(
                f"loop with header {header}: blocks {{{', '.join(order)}}}, back edge(s) "
                + ', '.join(f"{t}->{h}" for t, h in back_edges)
                + (f"; basic induction variable(s): {', '.join(ivs)}" if ivs else ''))

    def induction_variables(self, body):
        names = self.cfg.by_name()
        defs = Counter()
        found = []
        for bn in body:
            for q in names[bn].instrs:
                if q.defines():
                    defs[q.defines()] += 1
        for bn in body:
            for q in names[bn].instrs:
                if q.op in ('+', '-') and q.result in self.user_vars and defs[q.result] == 1:
                    if q.arg1 == q.result and is_const(q.arg2):
                        found.append(f"{q.result} ({q.op}{q.arg2} per iteration)")
                    elif q.op == '+' and q.arg2 == q.result and is_const(q.arg1):
                        found.append(f"{q.result} (+{q.arg1} per iteration)")
        return found

    def hoist(self, header, body, dom):
        cfg = self.cfg
        names = cfg.by_name()
        loop_blocks = [b for b in cfg.blocks if b.name in body]
        defined_in_loop = Counter()
        for b in loop_blocks:
            for q in b.instrs:
                if q.defines():
                    defined_in_loop[q.defines()] += 1
        exits = {b.name for b in loop_blocks if any(s not in body for s in b.succ)}

        invariant, moves = set(), []
        progress = True
        while progress:
            progress = False
            for b in loop_blocks:
                for q in b.instrs:
                    if id(q) in {id(m[1]) for m in moves}:
                        continue
                    if q.op not in BINARY_OPS + UNARY_OPS or q.result not in self.temps:
                        continue
                    if defined_in_loop[q.result] != 1:
                        continue
                    ops = [q.arg1] + ([q.arg2] if q.op in BINARY_OPS else [])
                    if not all(is_const(a) or defined_in_loop[a] == 0 or a in invariant for a in ops):
                        continue
                    safe_div = q.op in ('/', '%') and is_const(q.arg2) and q.arg2 != 0
                    if q.op in MAY_FAULT and not safe_div and not all(b.name in dom.get(e, ()) for e in exits):
                        continue
                    invariant.add(q.result)
                    moves.append((b, q))
                    progress = True
        if not moves:
            return False

        # create the pre-header just before the header in the layout
        self.npre += 1
        pre = BasicBlock(f"P{self.npre}", [q for _, q in moves])
        for b, q in moves:
            b.instrs = [x for x in b.instrs if x is not q]
            self.note('loop-invariant code motion', f"{q}  moved from {b.name} to pre-header {pre.name}")
        idx = cfg.blocks.index(names[header])
        if idx > 0:
            prev = cfg.blocks[idx - 1]
            plast = prev.last()
            falls = not (plast is not None and plast.op in ('goto', 'halt'))
            if prev.name in body and falls:
                # a loop block falls into the header: keep that back edge by an explicit jump
                cfg.blocks.insert(idx, BasicBlock(f"{pre.name}j", [Quad('goto', result=header)]))
                idx += 1
        cfg.blocks.insert(idx, pre)
        # every jump into the header from OUTSIDE the loop now enters the pre-header
        for b in cfg.blocks:
            last = b.last()
            if b.name not in body and b is not pre and last is not None and last.is_jump() and last.result == header:
                last.result = pre.name
        cfg.compute_edges()
        return True


def optimize(cfg, gen, symtab, loops=True):
    opt = Optimizer(cfg, gen.types, gen.temps, [v.name for v in symtab.variables()])
    opt.run(loops=loops)
    return opt
