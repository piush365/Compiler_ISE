"""
interpreter.py - Reference executors used to VERIFY the compiler.

* run_ast   : executes the type-checked AST directly (the meaning of the source)
* run_quads : executes the numbered three-address code (jump targets = quad numbers)
* run_cfg   : executes a control-flow graph of basic blocks (jump targets = block labels)

Each returns (output_lines, final_values_of_user_variables). If the compiler is
correct, all stages - and the target machine in vm.py - produce identical results.
"""
from ast_nodes import Num, Bool, Var, BinOp, UnaryOp, FuncCall, Assign, Print, Block, If, While
from ops import binop, unop, call_builtin, fmt_value, TOKEN_OP, EvalError

MAX_STEPS = 200_000


ZERO = {'int': 0, 'float': 0.0, 'bool': False}


def initial_env(symtab):
    """Static storage starts zero-initialised with the variable's type: 0, 0.0 or false."""
    return {v.name: ZERO[v.type] for v in symtab.variables()}


class StepLimit(EvalError):
    pass


class _Budget:
    def __init__(self, limit):
        self.left = limit

    def tick(self):
        self.left -= 1
        if self.left < 0:
            raise StepLimit("step limit exceeded (infinite loop?)")


def run_ast(program, symtab, max_steps=MAX_STEPS):
    env = initial_env(symtab)
    out = []
    budget = _Budget(max_steps)

    def ev(n):
        if isinstance(n, (Num, Bool)):
            return n.value
        if isinstance(n, Var):
            return env.get(n.name, 0)
        if isinstance(n, BinOp):
            op = TOKEN_OP[n.op.type]
            if op == '&&':
                return ev(n.left) and ev(n.right)
            if op == '||':
                return ev(n.left) or ev(n.right)
            a, b = ev(n.left), ev(n.right)
            if n.ty == 'float' or (op in ('<', '<=', '>', '>=', '==', '!=') and 'float' in (n.left.ty, n.right.ty)):
                a, b = float(a), float(b)   # same coercions the compiler inserts
            return binop(op, a, b)
        if isinstance(n, UnaryOp):
            v = ev(n.expr)
            return unop('not' if n.op.type == 'NOT' else 'uminus', v)
        if isinstance(n, FuncCall):
            return call_builtin(n.func_name, float(ev(n.arg)))
        raise TypeError(n)

    def ex(s):
        budget.tick()
        if isinstance(s, Assign):
            v = ev(s.expr)
            if symtab.type_of(s.var_name) == 'float':
                v = float(v)
            env[s.var_name] = v
        elif isinstance(s, Print):
            out.append(fmt_value(ev(s.expr)))
        elif isinstance(s, Block):
            for x in s.stmts:
                ex(x)
        elif isinstance(s, If):
            for x in (s.then_body if ev(s.cond) else (s.else_body or [])):
                ex(x)
        elif isinstance(s, While):
            while ev(s.cond):
                budget.tick()
                for x in s.body:
                    ex(x)
        else:
            ev(s)

    for s in program:
        ex(s)
    return out, {v.name: env[v.name] for v in symtab.variables()}


def _exec_instr(q, env, out, params):
    """Execute one non-jump instruction. Returns None, or the branch decision for jumps."""
    def val(a):
        return env.get(a, 0) if isinstance(a, str) else a
    op = q.op
    if op == '=':
        env[q.result] = val(q.arg1)
    elif op in ('+', '-', '*', '/', '%', '^'):
        env[q.result] = binop(op, val(q.arg1), val(q.arg2))
    elif op in ('uminus', 'not', 'inttofloat'):
        env[q.result] = unop(op, val(q.arg1))
    elif op == 'param':
        params.append(val(q.arg1))
    elif op == 'call':
        args = params[-q.arg2:]
        del params[-q.arg2:]
        env[q.result] = call_builtin(q.arg1, *args)
    elif op == 'print':
        out.append(fmt_value(val(q.arg1)))
    elif op == 'goto':
        return True
    elif op == 'if':
        return bool(val(q.arg1))
    elif op == 'iffalse':
        return not val(q.arg1)
    elif op.startswith('if'):
        return binop(op[2:], val(q.arg1), val(q.arg2))
    else:
        raise ValueError(f"cannot execute {q}")
    return None


def run_quads(quads, symtab, max_steps=MAX_STEPS):
    env, out, params = initial_env(symtab), [], []
    budget = _Budget(max_steps)
    pc = 0
    while quads[pc].op != 'halt':
        budget.tick()
        q = quads[pc]
        taken = _exec_instr(q, env, out, params)
        pc = q.result if taken else pc + 1
    return out, {v.name: env[v.name] for v in symtab.variables()}


def run_cfg(cfg, symtab, max_steps=MAX_STEPS):
    env, out, params = initial_env(symtab), [], []
    budget = _Budget(max_steps)
    order = [b.name for b in cfg.blocks]
    bi, ii = 0, 0
    while True:
        block = cfg.blocks[bi]
        if ii >= len(block.instrs):          # fall through to the next block in layout
            bi, ii = bi + 1, 0
            continue
        q = block.instrs[ii]
        if q.op == 'halt':
            break
        budget.tick()
        taken = _exec_instr(q, env, out, params)
        if taken:
            bi, ii = order.index(q.result), 0
        else:
            ii += 1
    return out, {v.name: env[v.name] for v in symtab.variables()}
