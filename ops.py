"""
ops.py - The single definition of what every operator MEANS at run time.

The AST interpreter, the three-address-code interpreter, the constant folder in
the optimizer and the target-machine simulator all call these functions, so the
source program, the TAC, the optimized TAC and the machine code are guaranteed
to agree on semantics (C-like: int / int truncates toward zero, % takes the
sign of the dividend).
"""
import math


class EvalError(Exception):
    """A run-time error in the program being compiled (division by zero, log(0), ...)."""


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _trunc_div(a, b):
    if b == 0:
        raise EvalError("integer division by zero")
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def binop(op, a, b):
    try:
        if op == '+': return a + b
        if op == '-': return a - b
        if op == '*': return a * b
        if op == '/':
            if is_int(a) and is_int(b):
                return _trunc_div(a, b)
            if b == 0:
                raise EvalError("division by zero")
            return a / b
        if op == '%':
            if is_int(a) and is_int(b):
                return a - b * _trunc_div(a, b)
            if b == 0:
                raise EvalError("modulo by zero")
            return math.fmod(a, b)
        if op == '^':
            if is_int(a) and is_int(b):
                if b < 0:
                    if a == 0:
                        raise EvalError("zero raised to a negative power")
                    return 1 if a == 1 else (-1 if b % 2 else 1) if a == -1 else 0
                if abs(a) > 1 and b > 256:
                    raise EvalError("integer power too large")
                return a ** b
            return math.pow(a, b)
        if op == '<': return a < b
        if op == '<=': return a <= b
        if op == '>': return a > b
        if op == '>=': return a >= b
        if op == '==': return a == b
        if op == '!=': return a != b
    except (ValueError, OverflowError, ZeroDivisionError) as e:
        raise EvalError(f"{op}: {e}")
    raise ValueError(f"unknown binary operator {op}")


def unop(op, a):
    if op == 'uminus': return -a
    if op == 'not': return not a
    if op == 'inttofloat': return float(a)
    raise ValueError(f"unknown unary operator {op}")


BUILTINS = {'sin': math.sin, 'cos': math.cos, 'log': math.log, 'sqrt': math.sqrt}


def call_builtin(name, arg):
    try:
        return BUILTINS[name](arg)
    except (ValueError, OverflowError) as e:
        raise EvalError(f"{name}({arg}): {e}")


RELOPS = ('<', '<=', '>', '>=', '==', '!=')
NEGATED_RELOP = {'<': '>=', '<=': '>', '>': '<=', '>=': '<', '==': '!=', '!=': '=='}
COMMUTATIVE = ('+', '*', '==', '!=')

# token type -> operator spelling used in the IR
TOKEN_OP = {'PLUS': '+', 'MINUS': '-', 'STAR': '*', 'SLASH': '/', 'PERCENT': '%', 'CARET': '^',
            'LT': '<', 'LE': '<=', 'GT': '>', 'GE': '>=', 'EQ': '==', 'NE': '!=',
            'AND': '&&', 'OR': '||', 'NOT': '!'}


def fmt_value(v):
    """How a run-time value is printed by print() in every executor."""
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, float):
        return repr(v)
    return str(v)
