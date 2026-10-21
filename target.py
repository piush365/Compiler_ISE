"""
target.py - Module 6: the target machine (instruction set + simulator).

A simple load/store register machine in the style of the Dragon book (section 8.2).
Registers R0..R(k-1) are allocatable; RV receives the result of a CALL.

    LD   R, x          R = memory[x]
    LD   R, #c         R = c                     (immediate constant)
    ST   x, R          memory[x] = R
    MOV  Rd, Rs        Rd = Rs
    ADD  Rd, Rs, Rt|#c Rd = Rs + Rt  (likewise SUB MUL DIV MOD POW)
    INC  R / DEC R     R = R + 1 / R - 1         (machine idiom chosen by the peephole pass)
    NEG  Rd, Rs        Rd = -Rs
    NOT  Rd, Rs        Rd = !Rs
    ITOF Rd, Rs        Rd = float(Rs)
    BR   L             goto L
    BLT  Rs, Rt|#c, L  if Rs < Rt goto L     (likewise BLE BGT BGE BEQ BNE)
    BNZ  R, L / BZ R, L   branch if R is true / false
    PUSH R|#c          push an actual parameter (call by value)
    CALL f             call built-in f: builds an activation record, result -> RV
    PRINT R|#c
    HALT

The simulator really maintains a run-time stack of activation records for CALL
(see runtime.py), so the execution statistics show stack allocation at work.
"""
from dataclasses import dataclass
from typing import Any, List
from ops import binop, unop, call_builtin, fmt_value, EvalError

ARITH = {'ADD': '+', 'SUB': '-', 'MUL': '*', 'DIV': '/', 'MOD': '%', 'POW': '^'}
BRANCH = {'BLT': '<', 'BLE': '<=', 'BGT': '>', 'BGE': '>=', 'BEQ': '==', 'BNE': '!='}
RELOP_BRANCH = {v: k for k, v in BRANCH.items()}
UNARY = {'NEG': 'uminus', 'NOT': 'not', 'ITOF': 'inttofloat'}
JUMPS = ('BR', 'BNZ', 'BZ') + tuple(BRANCH)


@dataclass(frozen=True)
class Reg:
    name: str
    def __str__(self): return self.name


@dataclass(frozen=True)
class Imm:
    value: Any
    def __str__(self): return '#' + fmt_value(self.value)


@dataclass(frozen=True)
class Mem:
    name: str
    def __str__(self): return self.name


@dataclass(frozen=True)
class Lbl:
    name: str
    def __str__(self): return self.name


@dataclass
class MInstr:
    op: str
    args: List[Any]

    def __str__(self):
        if self.op == 'LABEL':
            return f"{self.args[0]}:"
        return f"    {self.op:<5} {', '.join(str(a) for a in self.args)}".rstrip()

    def target(self):
        return self.args[-1].name if self.op in JUMPS else None


RV = Reg('RV')


class StepLimit(EvalError):
    pass


def run_machine(code: List[MInstr], initial_memory, max_steps=1_000_000):
    """
    Execute target code. `initial_memory` maps each variable to its initial
    (zero) value. Returns (output, final variable values, statistics).
    """
    labels = {ins.args[0]: i for i, ins in enumerate(code) if ins.op == 'LABEL'}
    regs, mem, out = {}, dict(initial_memory), []
    arg_stack, run_stack = [], []
    stats = {'instructions executed': 0, 'calls': 0, 'max stack depth': 0, 'loads': 0, 'stores': 0}

    def val(a):
        if isinstance(a, Imm):
            return a.value
        if isinstance(a, Reg):
            return regs.get(a.name, 0)
        raise ValueError(f"bad operand {a}")

    pc = 0
    while pc < len(code):
        ins = code[pc]
        op, a = ins.op, ins.args
        if op == 'LABEL':
            pc += 1
            continue
        stats['instructions executed'] += 1
        if stats['instructions executed'] > max_steps:
            raise StepLimit("step limit exceeded (infinite loop?)")
        nxt = pc + 1
        if op == 'LD':
            regs[a[0].name] = a[1].value if isinstance(a[1], Imm) else mem.get(a[1].name, 0)
            stats['loads'] += 1
        elif op == 'ST':
            mem[a[0].name] = val(a[1])
            stats['stores'] += 1
        elif op == 'MOV':
            regs[a[0].name] = val(a[1])
        elif op in ARITH:
            regs[a[0].name] = binop(ARITH[op], val(a[1]), val(a[2]))
        elif op == 'INC':
            regs[a[0].name] = binop('+', val(a[0]), 1)
        elif op == 'DEC':
            regs[a[0].name] = binop('-', val(a[0]), 1)
        elif op in UNARY:
            regs[a[0].name] = unop(UNARY[op], val(a[1]))
        elif op == 'BR':
            nxt = labels[a[0].name]
        elif op in BRANCH:
            if binop(BRANCH[op], val(a[0]), val(a[1])):
                nxt = labels[a[2].name]
        elif op == 'BNZ':
            if val(a[0]):
                nxt = labels[a[1].name]
        elif op == 'BZ':
            if not val(a[0]):
                nxt = labels[a[1].name]
        elif op == 'PUSH':
            arg_stack.append(val(a[0]))
        elif op == 'CALL':
            # activation record: [param | returned value | control link | return address]
            fp = len(run_stack) - 1
            record = {'param': arg_stack.pop(), 'returned value': None,
                      'control link': fp, 'return address': pc + 1}
            run_stack.append(record)
            stats['calls'] += 1
            stats['max stack depth'] = max(stats['max stack depth'], len(run_stack))
            record['returned value'] = call_builtin(a[0].name, record['param'])
            regs['RV'] = record['returned value']
            nxt = run_stack.pop()['return address']
        elif op == 'PRINT':
            out.append(fmt_value(val(a[0])))
        elif op == 'HALT':
            break
        else:
            raise ValueError(f"unknown instruction {ins}")
        pc = nxt
    return out, {v: mem[v] for v in initial_memory}, stats


def format_code(code):
    return '\n'.join(str(i) for i in code)
