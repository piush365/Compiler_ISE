"""
codegen.py - Module 6: Code generation.

The "simple code generator" of the Dragon book (section 8.6), one basic block at
a time, using

  * a REGISTER DESCRIPTOR for every register: the names whose current value it holds;
  * an ADDRESS DESCRIPTOR for every name: where its current value can be found
    (memory and/or registers);
  * getReg(), which picks the register for an operand or a result:
        1. a register that already holds the operand,
        2. else an empty register,
        3. else a register whose contents are "safe" to lose - each value it holds
           is also somewhere else, or is dead (not live after this instruction),
           or is the very name being overwritten;
        4. else the register needing the fewest spill stores (ST) is chosen;
  * NEXT-USE / liveness information, from global live-variable analysis, so
    dead values are never stored and live ones are never lost.

At the end of a basic block every live name whose current value is only in a
register is stored back to memory, so each block starts with all values in memory.

Instruction selection: a constant second operand becomes an immediate (#c), so
"i = i + 1" needs no extra load; built-in calls use PUSH / CALL with the result in RV.
"""
from cfg import liveness
from icg import BINARY_OPS
from target import MInstr, Reg, Imm, Mem, Lbl, RV, ARITH, RELOP_BRANCH

OP_INSTR = {v: k for k, v in ARITH.items()}
UNARY_INSTR = {'uminus': 'NEG', 'not': 'NOT', 'inttofloat': 'ITOF'}


def is_name(a):
    return isinstance(a, str)


class CodeGenerator:
    def __init__(self, cfg, user_vars, temps, nregs=4):
        if nregs < 2:
            raise ValueError("the code generator needs at least 2 registers")
        self.cfg = cfg
        self.user_vars = list(user_vars)
        self.temps = set(temps)
        self.regs = [Reg(f"R{i}") for i in range(nregs)]
        self.code = []
        self.spilled = set()        # temporaries that had to be stored to memory

    def emit(self, op, *args):
        self.code.append(MInstr(op, list(args)))

    def generate(self):
        self.cfg.compute_edges()
        _, live_out = liveness(self.cfg, self.user_vars)
        for b in self.cfg.blocks:
            self.emit('LABEL', b.name)
            self.gen_block(b, live_out[b.name])
        return self.code

    # ---------------- descriptors ----------------
    def loc(self, name):
        return self.addr[name] if name in self.addr else {'mem'}

    def regs_holding(self, name):
        return [r for r in self.regs if name in self.reg_desc[r]]

    def get_reg(self, i, avoid=(), operands=(), result=None, soft=()):
        """Choose a register (steps 2-4 above), storing values that would be lost."""
        live = self.live_after[i]

        def unsafe(r):
            bad = []
            for v in self.reg_desc[r]:
                elsewhere = len(self.loc(v) - {r}) > 0
                if result is not None:
                    ok = elsewhere or v not in live or v == result
                else:
                    ok = elsewhere or (v not in live and v not in operands)
                if not ok:
                    bad.append(v)
            return bad

        cands = [r for r in self.regs if r not in avoid]
        empty = [r for r in cands if not self.reg_desc[r]]
        if empty:
            empty.sort(key=lambda r: r in soft)
            return empty[0]
        # fewest stores first, then a register whose values are dead or not needed soon
        cands.sort(key=lambda r: (len(unsafe(r)), sum(v in live for v in self.reg_desc[r]),
                                  r in soft, self.regs.index(r)))
        r = cands[0]
        for v in sorted(unsafe(r)):
            self.emit('ST', Mem(v), r)                 # spill
            self.addr[v] = self.loc(v) | {'mem'}
            if v in self.temps:
                self.spilled.add(v)
        for v in self.reg_desc[r]:
            self.addr[v] = self.loc(v) - {r}
        self.reg_desc[r] = set()
        return r

    def fetch(self, a, i, operands, avoid=(), allow_imm=False):
        """Get operand a into a register (or as an immediate)."""
        if not is_name(a):
            if allow_imm:
                return Imm(a)
            r = self.get_reg(i, avoid=avoid, operands=operands)
            self.emit('LD', r, Imm(a))
            return r
        held = self.regs_holding(a)
        if held:
            return held[0]
        r = self.get_reg(i, avoid=avoid, operands=operands)
        self.emit('LD', r, Mem(a))
        self.reg_desc[r] = {a}
        self.addr[a] = self.loc(a) | {r}
        return r

    def set_result(self, x, r):
        """After 'r = ...' : r holds only x, and x is only in r."""
        for v in self.reg_desc[r]:
            if v != x:
                self.addr[v] = self.loc(v) - {r}
        for r2 in self.regs:
            self.reg_desc[r2].discard(x)
        self.reg_desc[r] = {x}
        self.addr[x] = {r}

    def store_live(self, live):
        for v in sorted(live):
            if 'mem' not in self.loc(v):
                held = [r for r in self.loc(v) if r != 'mem']
                if held:
                    self.emit('ST', Mem(v), held[0])
                    self.addr[v] = self.loc(v) | {'mem'}
                    if v in self.temps:
                        self.spilled.add(v)

    # ---------------- one basic block ----------------
    def gen_block(self, block, live_out):
        self.reg_desc = {r: set() for r in self.regs}
        self.addr = {}
        instrs = block.instrs
        # liveness after each instruction (next-use information)
        self.live_after = [None] * len(instrs)
        live = set(live_out)
        for i in range(len(instrs) - 1, -1, -1):
            self.live_after[i] = set(live)
            q = instrs[i]
            if q.defines():
                live.discard(q.defines())
            live |= set(self.user_vars) if q.op == 'halt' else set(q.uses())

        ended = False
        for i, q in enumerate(instrs):
            ops = {a for a in (q.arg1, q.arg2) if is_name(a)} if q.op != 'call' else set()
            if q.op in BINARY_OPS:
                ry = self.fetch(q.arg1, i, ops)
                rz = self.fetch(q.arg2, i, ops, avoid={ry}, allow_imm=True)
                x = q.result
                if is_name(q.arg1) and self.reg_desc[ry] == {q.arg1} and \
                        (q.arg1 not in self.live_after[i] or q.arg1 == x):
                    rx = ry                              # y dies here: reuse its register
                else:
                    rx = self.get_reg(i, result=x, soft={ry, rz})
                self.emit(OP_INSTR[q.op], rx, ry, rz)
                self.set_result(x, rx)
            elif q.op in UNARY_INSTR:
                ry = self.fetch(q.arg1, i, ops)
                x = q.result
                if is_name(q.arg1) and self.reg_desc[ry] == {q.arg1} and \
                        (q.arg1 not in self.live_after[i] or q.arg1 == x):
                    rx = ry
                else:
                    rx = self.get_reg(i, result=x, soft={ry})
                self.emit(UNARY_INSTR[q.op], rx, ry)
                self.set_result(x, rx)
            elif q.op == '=':
                x, y = q.result, q.arg1
                if not is_name(y):
                    rx = self.get_reg(i, result=x)
                    self.emit('LD', rx, Imm(y))
                    self.set_result(x, rx)
                elif x != y:
                    ry = self.fetch(y, i, ops)
                    for r2 in self.regs:
                        self.reg_desc[r2].discard(x)
                    self.reg_desc[ry].add(x)             # no instruction: x now lives in ry
                    self.addr[x] = {ry}
            elif q.op == 'param':
                self.emit('PUSH', self.fetch(q.arg1, i, ops, allow_imm=True))
            elif q.op == 'call':
                self.emit('CALL', Lbl(q.arg1))
                rx = self.get_reg(i, result=q.result)
                self.emit('MOV', rx, RV)
                self.set_result(q.result, rx)
            elif q.op == 'print':
                self.emit('PRINT', self.fetch(q.arg1, i, ops, allow_imm=True))
            elif q.op in ('if', 'iffalse'):
                r = self.fetch(q.arg1, i, ops)
                self.store_live(live_out)
                self.emit('BNZ' if q.op == 'if' else 'BZ', r, Lbl(q.result))
                ended = True
            elif q.is_cond_jump():
                ra = self.fetch(q.arg1, i, ops)
                rb = self.fetch(q.arg2, i, ops, avoid={ra}, allow_imm=True)
                self.store_live(live_out)
                self.emit(RELOP_BRANCH[q.op[2:]], ra, rb, Lbl(q.result))
                ended = True
            elif q.op == 'goto':
                self.store_live(live_out)
                self.emit('BR', Lbl(q.result))
                ended = True
            elif q.op == 'halt':
                self.store_live(set(self.user_vars))
                self.emit('HALT')
                ended = True
            else:
                raise ValueError(f"cannot generate code for {q}")
        if not ended:
            self.store_live(live_out)


def generate_code(cfg, user_vars, temps, nregs=4):
    g = CodeGenerator(cfg, user_vars, temps, nregs)
    g.generate()
    return g
